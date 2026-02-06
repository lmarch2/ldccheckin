#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen

DEFAULT_BASE_URL = "https://store.ryanai.org/"
DEFAULT_COOKIE_ENV = "LDC_COOKIE"
DEFAULT_COOKIE_FILE = "state/store.cookie"
DEFAULT_TIMEOUT_SECONDS = 30
DEFAULT_ARTIFACTS_DIR = "artifacts"

DEFAULT_CHECKIN_ACTION_ID = "00573f21cb6fdebcbb247b7ddbec9edcf954d96992"
DEFAULT_STATUS_ACTION_ID = "00047583cb7e0d3bd45fc537bd80dc9c6a7c04a1e8"

ALLOWED_DOMAIN_SUFFIX = "ryanai.org"

COOKIE_PREFIX_RE = re.compile(r"^\s*cookie\s*[:=]\s*", re.IGNORECASE)

CLOUDFLARE_HINT_RE = re.compile(
    r"(Verify you are human|Just a moment|cf-browser-verification|cf-challenge)",
    re.IGNORECASE,
)


class ExitCodes:
    OK = 0
    ERROR = 1
    NEEDS_LOGIN = 2


@dataclass(frozen=True)
class ActionResponse:
    url: str
    status: int
    content_type: str
    body: str


def _safe_hostname(url: str) -> str:
    try:
        return (urlparse(url).hostname or "").lower()
    except ValueError:
        return ""


def _validate_base_url(base_url: str) -> None:
    parsed = urlparse(base_url)
    if parsed.scheme != "https":
        raise ValueError("base_url must start with https://")

    host = (parsed.hostname or "").lower()
    if not host or not host.endswith(ALLOWED_DOMAIN_SUFFIX):
        raise ValueError(f"base_url host must end with {ALLOWED_DOMAIN_SUFFIX}")


def _normalize_cookie(raw_cookie: str) -> str:
    cookie = raw_cookie.strip()
    cookie = COOKIE_PREFIX_RE.sub("", cookie, count=1).strip()
    cookie = cookie.strip("\"'")
    cookie = cookie.replace("\r", "").replace("\n", "; ").strip()
    if not cookie or "=" not in cookie:
        raise ValueError("cookie looks empty or invalid")
    return cookie


def _load_cookie(cookie: str | None, cookie_env: str, cookie_file: Path) -> str:
    if cookie:
        return _normalize_cookie(cookie)

    env_value = os.environ.get(cookie_env, "").strip()
    if env_value:
        return _normalize_cookie(env_value)

    if not cookie_file.exists():
        raise FileNotFoundError(str(cookie_file))
    return _normalize_cookie(cookie_file.read_text(encoding="utf-8"))


def _write_artifact(artifacts_dir: Path, prefix: str, resp: ActionResponse) -> None:
    artifacts_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    base = artifacts_dir / f"{prefix}_{ts}"
    meta = {
        "url": resp.url,
        "status": resp.status,
        "content_type": resp.content_type,
    }

    try:
        base.with_suffix(".meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    except OSError:
        pass

    try:
        base.with_suffix(".resp.txt").write_text(resp.body, encoding="utf-8")
    except OSError:
        pass


def _post_action(
    *,
    base_url: str,
    action_id: str,
    cookie: str,
    timeout_seconds: int,
    user_agent: str,
) -> ActionResponse:
    data = b"[]"
    headers = {
        "accept": "text/x-component",
        "content-type": "text/plain;charset=UTF-8",
        "next-action": action_id,
        "cookie": cookie,
        "origin": base_url.rstrip("/"),
        "referer": base_url,
        "user-agent": user_agent,
    }
    req = Request(base_url, data=data, headers=headers, method="POST")

    try:
        with urlopen(req, timeout=timeout_seconds) as resp:
            content_type = (resp.headers.get("content-type") or "").strip()
            body = resp.read().decode("utf-8", errors="replace")
            return ActionResponse(url=base_url, status=int(resp.status), content_type=content_type, body=body)
    except HTTPError as exc:
        content_type = (exc.headers.get("content-type") or "").strip() if exc.headers else ""
        try:
            body = exc.read().decode("utf-8", errors="replace")
        except Exception:
            body = ""
        return ActionResponse(url=base_url, status=int(getattr(exc, "code", 0) or 0), content_type=content_type, body=body)


def _extract_first_dict_with_key(body: str, key: str) -> dict[str, Any] | None:
    for line in body.splitlines():
        if ":" not in line:
            continue
        _, payload = line.split(":", 1)
        payload = payload.strip()
        if not payload.startswith("{") or not payload.endswith("}"):
            continue
        try:
            obj = json.loads(payload)
        except json.JSONDecodeError:
            continue
        if isinstance(obj, dict) and key in obj:
            return obj
    return None


def _parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="store.ryanai.org 自动签到（HTTP Server Action 方案）。")
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL, help="目标站点 URL（默认：%(default)s）")
    parser.add_argument("--cookie", default="", help="Cookie 字符串（不推荐：会进入 shell history）")
    parser.add_argument("--cookie-env", default=DEFAULT_COOKIE_ENV, help="读取 Cookie 的环境变量名（默认：%(default)s）")
    parser.add_argument("--cookie-file", default=DEFAULT_COOKIE_FILE, help="读取 Cookie 的文件路径（默认：%(default)s）")
    parser.add_argument(
        "--timeout-seconds",
        type=int,
        default=DEFAULT_TIMEOUT_SECONDS,
        help="请求超时秒数（默认：%(default)s）",
    )
    parser.add_argument(
        "--artifacts-dir",
        default=DEFAULT_ARTIFACTS_DIR,
        help="失败时保存调试响应的目录（默认：%(default)s）",
    )
    parser.add_argument("--status-action-id", default=DEFAULT_STATUS_ACTION_ID, help="getCheckinStatus actionId")
    parser.add_argument("--checkin-action-id", default=DEFAULT_CHECKIN_ACTION_ID, help="checkIn actionId")
    parser.add_argument(
        "--skip-status",
        action="store_true",
        help="跳过 getCheckinStatus，直接尝试 checkIn",
    )
    parser.add_argument(
        "--user-agent",
        default="Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
        help="自定义 User-Agent（默认：Chrome/Linux）",
    )
    return parser.parse_args(argv)


def main(argv: list[str]) -> int:
    args = _parse_args(argv)
    if args.timeout_seconds < 5:
        print("错误：--timeout-seconds 不能小于 5", file=sys.stderr)
        return ExitCodes.ERROR

    try:
        _validate_base_url(args.base_url)
    except ValueError as exc:
        print(f"错误：{exc}", file=sys.stderr)
        return ExitCodes.ERROR

    host = _safe_hostname(args.base_url)
    if host and not host.endswith(ALLOWED_DOMAIN_SUFFIX):
        print("错误：拒绝向非 ryanai.org 域名发送 Cookie。", file=sys.stderr)
        return ExitCodes.ERROR

    try:
        cookie = _load_cookie(args.cookie, args.cookie_env, Path(args.cookie_file).expanduser())
    except FileNotFoundError:
        print(f"未找到 Cookie 文件：{args.cookie_file}", file=sys.stderr)
        print("请把浏览器里 store.ryanai.org 的 Cookie 粘贴到该文件（注意权限 chmod 600）。", file=sys.stderr)
        return ExitCodes.NEEDS_LOGIN
    except ValueError as exc:
        print(f"Cookie 无效：{exc}", file=sys.stderr)
        return ExitCodes.NEEDS_LOGIN
    except OSError as exc:
        print(f"读取 Cookie 失败：{exc}", file=sys.stderr)
        return ExitCodes.ERROR

    artifacts_dir = Path(args.artifacts_dir).expanduser()

    if not args.skip_status:
        try:
            status_resp = _post_action(
                base_url=args.base_url,
                action_id=args.status_action_id,
                cookie=cookie,
                timeout_seconds=args.timeout_seconds,
                user_agent=args.user_agent,
            )
        except URLError as exc:
            print(f"网络错误：{exc}", file=sys.stderr)
            return ExitCodes.ERROR

        status_obj = _extract_first_dict_with_key(status_resp.body, "checkedIn")
        if status_obj is not None and status_obj.get("checkedIn") is True:
            print("今日已签到。")
            return ExitCodes.OK

    try:
        checkin_resp = _post_action(
            base_url=args.base_url,
            action_id=args.checkin_action_id,
            cookie=cookie,
            timeout_seconds=args.timeout_seconds,
            user_agent=args.user_agent,
        )
    except URLError as exc:
        print(f"网络错误：{exc}", file=sys.stderr)
        return ExitCodes.ERROR

    if CLOUDFLARE_HINT_RE.search(checkin_resp.body):
        _write_artifact(artifacts_dir, "cloudflare_challenge", checkin_resp)
        print("遇到 Cloudflare 人机验证页面（需要更新 Cookie / cf_clearance）。", file=sys.stderr)
        return ExitCodes.NEEDS_LOGIN

    result = _extract_first_dict_with_key(checkin_resp.body, "success")
    if result is None:
        _write_artifact(artifacts_dir, "unexpected_response", checkin_resp)
        print("返回内容无法解析（已保存 artifacts/ 调试响应）。", file=sys.stderr)
        return ExitCodes.ERROR

    if result.get("success") is True:
        points = result.get("points")
        if isinstance(points, int) and points > 0:
            print(f"签到成功：+{points} 积分。")
        else:
            print("签到成功。")
        return ExitCodes.OK

    error = result.get("error")
    if error == "Already checked in today":
        print("今日已签到。")
        return ExitCodes.OK
    if error == "Not logged in":
        print("未登录或 Cookie 已失效，需要更新 Cookie。", file=sys.stderr)
        return ExitCodes.NEEDS_LOGIN

    _write_artifact(artifacts_dir, "checkin_failed", checkin_resp)
    if isinstance(error, str) and error.strip():
        print(f"签到失败：{error}", file=sys.stderr)
    else:
        print("签到失败：未知错误（已保存 artifacts/ 调试响应）。", file=sys.stderr)
    return ExitCodes.ERROR


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
