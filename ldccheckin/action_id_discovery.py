from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass
from urllib.error import HTTPError, URLError
from urllib.parse import urljoin
from urllib.request import Request, urlopen

from ldccheckin.cli_checkin import (
    CLOUDFLARE_HINT_RE,
    _extract_first_dict_with_key,
    _is_server_action_not_found,
    _post_action,
)

_ACTION_ID_RE = re.compile(r"\b[0-9a-f]{42}\b", re.IGNORECASE)
_NEXT_STATIC_JS_RE = re.compile(r"/_next/static/[^\"'\s<>]+\.js(?:\?[^\"'\s<>]+)?", re.IGNORECASE)

_NEXT_ACTION_KV_RE = re.compile(r"[\"']next-action[\"']\s*:\s*[\"']([0-9a-f]{42})[\"']", re.IGNORECASE)
_NEXT_ACTION_SET_RE = re.compile(
    r"set\(\s*[\"']next-action[\"']\s*,\s*[\"']([0-9a-f]{42})[\"']\s*\)",
    re.IGNORECASE,
)


class ActionIdDiscoveryError(RuntimeError):
    pass


@dataclass(frozen=True)
class DiscoveredActionIds:
    status_action_id: str
    checkin_action_id: str
    candidates_tested: int
    js_files_scanned: int
    used_cookie_for_status_probe: bool
    used_cookie_for_checkin_probe: bool


def _read_limited(resp, max_bytes: int) -> bytes:
    chunks: list[bytes] = []
    remaining = max_bytes
    while remaining > 0:
        data = resp.read(min(65536, remaining))
        if not data:
            break
        chunks.append(data)
        remaining -= len(data)
    return b"".join(chunks)


def _fetch_text(
    url: str,
    *,
    timeout_seconds: int,
    user_agent: str,
    accept: str,
    cookie: str = "",
    max_bytes: int = 6_000_000,
) -> str:
    headers = {
        "user-agent": user_agent,
        "accept": accept,
    }
    if cookie.strip():
        headers["cookie"] = cookie
    req = Request(url, headers=headers, method="GET")
    try:
        with urlopen(req, timeout=timeout_seconds) as resp:
            body_bytes = _read_limited(resp, max_bytes)
    except HTTPError as exc:
        try:
            body_bytes = _read_limited(exc, max_bytes)
        except Exception:
            body_bytes = b""
        status = getattr(exc, "code", "unknown")
        raise ActionIdDiscoveryError(f"HTTP {status}：{url}") from exc
    except URLError as exc:
        raise ActionIdDiscoveryError(f"网络错误：{exc} {url}") from exc

    return body_bytes.decode("utf-8", errors="replace")


def _extract_next_static_js_urls(base_url: str, html: str) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for match in _NEXT_STATIC_JS_RE.finditer(html):
        path = match.group(0)
        if path in seen:
            continue
        seen.add(path)
        result.append(urljoin(base_url, path))
    return result


def _extract_action_id_candidates_from_js(js_text: str) -> tuple[Counter[str], Counter[str]]:
    strong: Counter[str] = Counter()
    for match in _NEXT_ACTION_KV_RE.finditer(js_text):
        strong[match.group(1).lower()] += 1
    for match in _NEXT_ACTION_SET_RE.finditer(js_text):
        strong[match.group(1).lower()] += 1

    weak: Counter[str] = Counter()
    for match in _ACTION_ID_RE.finditer(js_text):
        weak[match.group(0).lower()] += 1

    return strong, weak


def _classify_action_body(body: str) -> set[str]:
    kinds: set[str] = set()

    status_obj = _extract_first_dict_with_key(body, "checkedIn")
    if status_obj is not None and isinstance(status_obj.get("checkedIn"), bool):
        kinds.add("status")

    checkin_obj = _extract_first_dict_with_key(body, "success")
    if checkin_obj is not None and isinstance(checkin_obj.get("success"), bool):
        if "points" in checkin_obj or "error" in checkin_obj:
            kinds.add("checkin")

    return kinds


def _probe_candidates(
    *,
    base_url: str,
    candidates: list[str],
    cookie: str,
    timeout_seconds: int,
    user_agent: str,
    tested_action_ids: set[str],
    want_status: bool,
    want_checkin: bool,
    skip_action_ids: set[str],
    max_tests: int,
) -> tuple[str, str, int]:
    status_action_id = ""
    checkin_action_id = ""
    tested = 0

    for action_id in candidates:
        if tested >= max_tests:
            break
        if action_id in tested_action_ids or action_id in skip_action_ids:
            continue

        tested_action_ids.add(action_id)
        tested += 1

        resp = _post_action(
            base_url=base_url,
            action_id=action_id,
            cookie=cookie,
            timeout_seconds=timeout_seconds,
            user_agent=user_agent,
        )
        if _is_server_action_not_found(resp):
            continue

        kinds = _classify_action_body(resp.body)
        if want_status and not status_action_id and "status" in kinds:
            status_action_id = action_id
        if want_checkin and not checkin_action_id and "checkin" in kinds:
            checkin_action_id = action_id

        if (not want_status or status_action_id) and (not want_checkin or checkin_action_id):
            break

    return status_action_id, checkin_action_id, tested


def discover_action_ids(
    *,
    base_url: str,
    cookie: str,
    timeout_seconds: int,
    user_agent: str,
    max_js_files: int = 30,
    max_js_bytes: int = 6_000_000,
    max_candidates_test: int = 200,
    max_cookie_probe_tests: int = 50,
) -> DiscoveredActionIds:
    html = _fetch_text(
        base_url,
        timeout_seconds=timeout_seconds,
        user_agent=user_agent,
        accept="text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        max_bytes=2_000_000,
    )
    if CLOUDFLARE_HINT_RE.search(html):
        raise ActionIdDiscoveryError("遇到 Cloudflare 人机验证页面（请先更新 Cookie / cf_clearance）。")

    js_urls = _extract_next_static_js_urls(base_url, html)
    if not js_urls:
        raise ActionIdDiscoveryError("未在页面中找到 /_next/static/*.js，无法抓取 actionId。")

    strong_all: Counter[str] = Counter()
    weak_all: Counter[str] = Counter()
    js_scanned = 0
    for js_url in js_urls[:max_js_files]:
        try:
            js_text = _fetch_text(
                js_url,
                timeout_seconds=timeout_seconds,
                user_agent=user_agent,
                accept="*/*",
                max_bytes=max_js_bytes,
            )
        except ActionIdDiscoveryError:
            continue
        js_scanned += 1
        strong, weak = _extract_action_id_candidates_from_js(js_text)
        strong_all.update(strong)
        weak_all.update(weak)

    candidates: list[str] = [action_id for action_id, _ in strong_all.most_common()]
    for action_id, _ in weak_all.most_common():
        if action_id not in strong_all:
            candidates.append(action_id)

    if not candidates:
        raise ActionIdDiscoveryError("未从静态 JS 中提取到任何 42 位 actionId 候选。")

    tested_action_ids: set[str] = set()
    tests_left = max_candidates_test

    used_cookie_for_status_probe = False
    used_cookie_for_checkin_probe = False

    status_action_id, checkin_action_id, tested = _probe_candidates(
        base_url=base_url,
        candidates=candidates,
        cookie="",
        timeout_seconds=timeout_seconds,
        user_agent=user_agent,
        tested_action_ids=tested_action_ids,
        want_status=True,
        want_checkin=True,
        skip_action_ids=set(),
        max_tests=tests_left,
    )
    tests_left -= tested

    if not status_action_id and cookie.strip() and tests_left > 0:
        status_only_tests = min(tests_left, max_cookie_probe_tests)
        status_action_id_2, _, tested_2 = _probe_candidates(
            base_url=base_url,
            candidates=candidates,
            cookie=cookie,
            timeout_seconds=timeout_seconds,
            user_agent=user_agent,
            tested_action_ids=tested_action_ids,
            want_status=True,
            want_checkin=False,
            skip_action_ids={checkin_action_id} if checkin_action_id else set(),
            max_tests=status_only_tests,
        )
        if status_action_id_2:
            status_action_id = status_action_id_2
        if tested_2 > 0:
            used_cookie_for_status_probe = True
        tests_left -= tested_2

    if not checkin_action_id and cookie.strip() and tests_left > 0:
        checkin_only_tests = min(tests_left, max_cookie_probe_tests)
        _, checkin_action_id_2, tested_3 = _probe_candidates(
            base_url=base_url,
            candidates=candidates,
            cookie=cookie,
            timeout_seconds=timeout_seconds,
            user_agent=user_agent,
            tested_action_ids=tested_action_ids,
            want_status=False,
            want_checkin=True,
            skip_action_ids=set(),
            max_tests=checkin_only_tests,
        )
        if checkin_action_id_2:
            checkin_action_id = checkin_action_id_2
        if tested_3 > 0:
            used_cookie_for_checkin_probe = True
        tests_left -= tested_3

    missing: list[str] = []
    if not status_action_id:
        missing.append("status_action_id")
    if not checkin_action_id:
        missing.append("checkin_action_id")
    if missing:
        tested_total = len(tested_action_ids)
        raise ActionIdDiscoveryError(f"自动抓取不完整，缺少：{', '.join(missing)}（已测试 {tested_total} 个候选）。")

    return DiscoveredActionIds(
        status_action_id=status_action_id,
        checkin_action_id=checkin_action_id,
        candidates_tested=len(tested_action_ids),
        js_files_scanned=js_scanned,
        used_cookie_for_status_probe=used_cookie_for_status_probe,
        used_cookie_for_checkin_probe=used_cookie_for_checkin_probe,
    )
