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

from ldccheckin.constants import (
    DEFAULT_ACTION_CONFIG_FILE,
    DEFAULT_ACTION_IDS_BY_HOST,
    DEFAULT_ALL_SHOP_URLS,
    DEFAULT_ARTIFACTS_DIR,
    DEFAULT_BASE_URL,
    DEFAULT_COOKIE_ENV,
    DEFAULT_COOKIE_FILE,
    DEFAULT_TIMEOUT_SECONDS,
    DEFAULT_USER_AGENT,
    default_cookie_file_for_host,
)

COOKIE_PREFIX_RE = re.compile(r"^\s*cookie\s*[:=]\s*", re.IGNORECASE)

CLOUDFLARE_HINT_RE = re.compile(
    r"(Verify you are human|Just a moment|cf-browser-verification|cf-challenge)",
    re.IGNORECASE,
)
SERVER_ACTION_NOT_FOUND_RE = re.compile(r"server action not found", re.IGNORECASE)


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
    if not host:
        raise ValueError("base_url host is empty")


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


def _resolve_cookie_file(base_url: str, cookie_file: str) -> Path:
    raw = cookie_file.strip()
    if raw:
        return Path(raw).expanduser()

    host = _safe_hostname(base_url)
    if not host:
        raise ValueError("无法从 base_url 解析主机名，请通过 --cookie-file 指定")
    return Path(default_cookie_file_for_host(host)).expanduser()


def _read_action_map(action_config_file: Path) -> dict[str, dict[str, str]]:
    if not action_config_file.exists():
        return {}

    try:
        loaded = json.loads(action_config_file.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"action 配置文件 JSON 格式错误：{exc}") from exc

    if not isinstance(loaded, dict):
        raise ValueError("action 配置文件格式错误：根节点必须是对象")

    result: dict[str, dict[str, str]] = {}
    for host, raw in loaded.items():
        if not isinstance(host, str) or not isinstance(raw, dict):
            continue

        status_action_id = raw.get("status_action_id")
        checkin_action_id = raw.get("checkin_action_id")
        if isinstance(status_action_id, str) and status_action_id.strip() and isinstance(checkin_action_id, str) and checkin_action_id.strip():
            result[host.strip().lower()] = {
                "status_action_id": status_action_id.strip(),
                "checkin_action_id": checkin_action_id.strip(),
            }
    return result


def _resolve_action_ids(
    *,
    base_url: str,
    status_action_id: str,
    checkin_action_id: str,
    action_config_file: Path,
) -> tuple[str, str]:
    raw_status = status_action_id.strip()
    raw_checkin = checkin_action_id.strip()

    if raw_status and raw_checkin:
        return raw_status, raw_checkin

    if raw_status or raw_checkin:
        raise ValueError("--status-action-id 和 --checkin-action-id 必须同时提供")

    host = _safe_hostname(base_url)

    action_map = _read_action_map(action_config_file)
    mapped = action_map.get(host)
    if mapped is not None:
        return mapped["status_action_id"], mapped["checkin_action_id"]

    built_in = DEFAULT_ACTION_IDS_BY_HOST.get(host)
    if built_in is not None:
        return built_in["status_action_id"], built_in["checkin_action_id"]

    raise ValueError(
        f"未配置 {host} 的 actionId。请通过 --status-action-id/--checkin-action-id 参数，"
        f"或在 {action_config_file} 中配置。"
    )


def _is_server_action_not_found(resp: ActionResponse) -> bool:
    return resp.status == 404 and bool(SERVER_ACTION_NOT_FOUND_RE.search(resp.body))


def _print_action_config_hint(*, host: str, action_config_file: Path) -> None:
    example = (
        "{\n"
        f"  \"{host}\": {{\n"
        "    \"status_action_id\": \"<getCheckinStatus next-action>\",\n"
        "    \"checkin_action_id\": \"<checkIn next-action>\"\n"
        "  }\n"
        "}"
    )
    print("检测到 Server action not found：当前站点 actionId 不匹配。", file=sys.stderr)
    print("请在浏览器 Network 中抓取 next-action 后配置以下文件：", file=sys.stderr)
    print(f"  {action_config_file}", file=sys.stderr)
    print("示例：", file=sys.stderr)
    print(example, file=sys.stderr)


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
    parser = argparse.ArgumentParser(description="多店自动签到（HTTP Server Action 方案）。")
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL, help="目标站点 URL（默认：%(default)s）")
    parser.add_argument("--run-all", action="store_true", help="按内置店铺列表依次签到全部小店")
    parser.add_argument("--cookie", default="", help="Cookie 字符串（不推荐：会进入 shell history）")
    parser.add_argument("--cookie-env", default=DEFAULT_COOKIE_ENV, help="读取 Cookie 的环境变量名（默认：%(default)s）")
    parser.add_argument(
        "--cookie-file",
        default=DEFAULT_COOKIE_FILE,
        help="读取 Cookie 的文件路径（默认：按域名自动映射）",
    )
    parser.add_argument(
        "--action-config-file",
        default=DEFAULT_ACTION_CONFIG_FILE,
        help="按域名读取 actionId 的 JSON 文件（默认：%(default)s）",
    )
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
    parser.add_argument("--status-action-id", default="", help="getCheckinStatus actionId（与 --checkin-action-id 配对使用）")
    parser.add_argument("--checkin-action-id", default="", help="checkIn actionId（与 --status-action-id 配对使用）")
    parser.add_argument(
        "--skip-status",
        action="store_true",
        help="跳过 getCheckinStatus，直接尝试 checkIn",
    )
    parser.add_argument(
        "--user-agent",
        default=DEFAULT_USER_AGENT,
        help="自定义 User-Agent（默认：Chrome/Linux）",
    )
    return parser.parse_args(argv)


def _run_single_target(
    args: argparse.Namespace,
    *,
    base_url: str,
    cookie_file: str,
    status_action_id: str,
    checkin_action_id: str,
) -> int:
    try:
        _validate_base_url(base_url)
    except ValueError as exc:
        print(f"错误：{exc}", file=sys.stderr)
        return ExitCodes.ERROR

    host = _safe_hostname(base_url)

    try:
        resolved_cookie_file = _resolve_cookie_file(base_url, cookie_file)
    except ValueError as exc:
        print(f"错误：{exc}", file=sys.stderr)
        return ExitCodes.ERROR

    action_config_file = Path(args.action_config_file).expanduser()
    try:
        resolved_status_action_id, resolved_checkin_action_id = _resolve_action_ids(
            base_url=base_url,
            status_action_id=status_action_id,
            checkin_action_id=checkin_action_id,
            action_config_file=action_config_file,
        )
    except ValueError as exc:
        print(f"错误：{exc}", file=sys.stderr)
        return ExitCodes.ERROR

    try:
        cookie = _load_cookie(args.cookie, args.cookie_env, resolved_cookie_file)
    except FileNotFoundError:
        print(f"未找到 Cookie 文件：{resolved_cookie_file}", file=sys.stderr)
        print(f"请把浏览器里 {host or base_url} 的 Cookie 粘贴到该文件（注意权限 chmod 600）。", file=sys.stderr)
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
                base_url=base_url,
                action_id=resolved_status_action_id,
                cookie=cookie,
                timeout_seconds=args.timeout_seconds,
                user_agent=args.user_agent,
            )
        except URLError as exc:
            print(f"网络错误：{exc}", file=sys.stderr)
            return ExitCodes.ERROR

        if _is_server_action_not_found(status_resp):
            _write_artifact(artifacts_dir, "status_action_not_found", status_resp)
            _print_action_config_hint(host=host or base_url, action_config_file=action_config_file)
            return ExitCodes.ERROR

        status_obj = _extract_first_dict_with_key(status_resp.body, "checkedIn")
        if status_obj is not None and status_obj.get("checkedIn") is True:
            print("今日已签到。")
            return ExitCodes.OK

    try:
        checkin_resp = _post_action(
            base_url=base_url,
            action_id=resolved_checkin_action_id,
            cookie=cookie,
            timeout_seconds=args.timeout_seconds,
            user_agent=args.user_agent,
        )
    except URLError as exc:
        print(f"网络错误：{exc}", file=sys.stderr)
        return ExitCodes.ERROR

    if _is_server_action_not_found(checkin_resp):
        _write_artifact(artifacts_dir, "checkin_action_not_found", checkin_resp)
        _print_action_config_hint(host=host or base_url, action_config_file=action_config_file)
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


def main(argv: list[str]) -> int:
    args = _parse_args(argv)
    if args.timeout_seconds < 5:
        print("错误：--timeout-seconds 不能小于 5", file=sys.stderr)
        return ExitCodes.ERROR

    if not args.run_all:
        return _run_single_target(
            args,
            base_url=args.base_url,
            cookie_file=args.cookie_file,
            status_action_id=args.status_action_id,
            checkin_action_id=args.checkin_action_id,
        )

    if args.cookie.strip():
        print("提示：--run-all 模式会按域名读取 Cookie 文件，已忽略 --cookie。", file=sys.stderr)
    args.cookie = ""
    if args.cookie_file.strip():
        print("提示：--run-all 模式会按域名自动映射 Cookie 文件，已忽略 --cookie-file。", file=sys.stderr)
    if args.status_action_id.strip() or args.checkin_action_id.strip():
        print("提示：--run-all 模式会按域名读取 actionId，已忽略 --status-action-id/--checkin-action-id。", file=sys.stderr)

    results: list[tuple[str, int]] = []
    for base_url in DEFAULT_ALL_SHOP_URLS:
        print(f"\n=== {base_url} ===")
        exit_code = _run_single_target(
            args,
            base_url=base_url,
            cookie_file="",
            status_action_id="",
            checkin_action_id="",
        )
        results.append((base_url, exit_code))

    ok_count = sum(1 for _, code in results if code == ExitCodes.OK)
    needs_login_urls = [url for url, code in results if code == ExitCodes.NEEDS_LOGIN]
    error_urls = [url for url, code in results if code == ExitCodes.ERROR]

    print("\n=== 汇总 ===")
    print(f"成功 {ok_count} 个，需更新 Cookie {len(needs_login_urls)} 个，失败 {len(error_urls)} 个。")

    if needs_login_urls:
        print("需更新 Cookie：" + "、".join(needs_login_urls), file=sys.stderr)
    if error_urls:
        print("执行失败：" + "、".join(error_urls), file=sys.stderr)
        return ExitCodes.ERROR
    if needs_login_urls:
        return ExitCodes.NEEDS_LOGIN
    return ExitCodes.OK


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
