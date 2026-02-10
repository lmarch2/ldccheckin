#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from urllib.parse import urlparse

from ldccheckin.action_id_discovery import ActionIdDiscoveryError, discover_action_ids
from ldccheckin.cli_checkin import (
    _load_cookie,
    _read_action_map,
    _resolve_cookie_file,
    _safe_hostname,
    _validate_base_url,
)
from ldccheckin.constants import (
    DEFAULT_ACTION_CONFIG_FILE,
    DEFAULT_ALL_SHOP_URLS,
    DEFAULT_BASE_URL,
    DEFAULT_COOKIE_ENV,
    DEFAULT_COOKIE_FILE,
    DEFAULT_TIMEOUT_SECONDS,
    DEFAULT_USER_AGENT,
)


class ExitCodes:
    OK = 0
    ERROR = 1


def _normalize_base_url(raw: str) -> str:
    text = raw.strip()
    if not text:
        raise ValueError("URL 不能为空")
    if not text.startswith(("http://", "https://")):
        text = f"https://{text}"
    parsed = urlparse(text)
    if parsed.scheme != "https":
        raise ValueError("仅支持 https:// URL")
    host = (parsed.hostname or "").strip().lower()
    if not host:
        raise ValueError("URL 缺少主机名")
    return f"https://{host}/"


def _read_urls_from_file(path: Path) -> list[str]:
    if not path.exists():
        raise FileNotFoundError(str(path))
    urls: list[str] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        row = line.strip()
        if not row or row.startswith("#"):
            continue
        urls.append(row)
    return urls


def _save_action_map(path: Path, action_map: dict[str, dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(action_map, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="自动抓取各站点 next-action（actionId）并写入配置文件。")
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL, help="目标站点 URL（默认：%(default)s）")
    parser.add_argument("--run-all", action="store_true", help="按内置店铺列表依次抓取全部小店")
    parser.add_argument("--url-file", default="", help="从文件读取 URL（每行一个，可写 host 或 URL）")
    parser.add_argument("--cookie", default="", help="Cookie 字符串（不推荐：会进入 shell history）")
    parser.add_argument("--cookie-env", default=DEFAULT_COOKIE_ENV, help="读取 Cookie 的环境变量名（默认：%(default)s）")
    parser.add_argument("--cookie-file", default=DEFAULT_COOKIE_FILE, help="读取 Cookie 的文件路径（默认：按域名自动映射）")
    parser.add_argument(
        "--action-config-file",
        default=DEFAULT_ACTION_CONFIG_FILE,
        help="按域名保存 actionId 的 JSON 文件（默认：%(default)s）",
    )
    parser.add_argument("--timeout-seconds", type=int, default=DEFAULT_TIMEOUT_SECONDS, help="请求超时秒数（默认：%(default)s）")
    parser.add_argument("--user-agent", default=DEFAULT_USER_AGENT, help="自定义 User-Agent（默认：Chrome/Linux）")
    parser.add_argument("--max-js-files", type=int, default=30, help="最多扫描多少个静态 JS 文件（默认：%(default)s）")
    parser.add_argument("--max-candidates-test", type=int, default=200, help="最多测试多少个 actionId 候选（默认：%(default)s）")
    return parser.parse_args(argv)


def _iter_targets(args: argparse.Namespace) -> list[str]:
    if args.run_all:
        return list(DEFAULT_ALL_SHOP_URLS)
    if args.url_file.strip():
        urls = _read_urls_from_file(Path(args.url_file).expanduser())
        return [_normalize_base_url(u) for u in urls]
    return [_normalize_base_url(args.base_url)]


def main(argv: list[str]) -> int:
    args = _parse_args(argv)
    if args.timeout_seconds < 5:
        print("错误：--timeout-seconds 不能小于 5", file=sys.stderr)
        return ExitCodes.ERROR

    targets = _iter_targets(args)
    if len(targets) > 1:
        if args.cookie.strip():
            print("提示：多站点模式会按域名读取 Cookie 文件，已忽略 --cookie。", file=sys.stderr)
        args.cookie = ""
        if args.cookie_file.strip():
            print("提示：多站点模式会按域名自动映射 Cookie 文件，已忽略 --cookie-file。", file=sys.stderr)
        args.cookie_file = ""

    action_config_file = Path(args.action_config_file).expanduser()
    try:
        action_map = _read_action_map(action_config_file)
    except ValueError as exc:
        print(f"错误：{exc}", file=sys.stderr)
        return ExitCodes.ERROR

    updated_hosts: list[str] = []
    failed_urls: list[str] = []

    for base_url in targets:
        print(f"\n=== {base_url} ===")

        try:
            _validate_base_url(base_url)
        except ValueError as exc:
            print(f"错误：{exc}", file=sys.stderr)
            failed_urls.append(base_url)
            continue

        host = _safe_hostname(base_url)
        if not host:
            print("错误：无法从 base_url 解析主机名", file=sys.stderr)
            failed_urls.append(base_url)
            continue

        cookie = ""
        cookie_file_path: Path | None = None
        try:
            cookie_file_path = _resolve_cookie_file(base_url, args.cookie_file)
            cookie = _load_cookie(args.cookie, args.cookie_env, cookie_file_path)
        except FileNotFoundError:
            if cookie_file_path is not None:
                print(f"提示：未找到 Cookie 文件：{cookie_file_path}（将尽量无 Cookie 抓取）", file=sys.stderr)
            else:
                print("提示：未找到 Cookie 文件（将尽量无 Cookie 抓取）", file=sys.stderr)
            cookie = ""
        except ValueError as exc:
            print(f"提示：Cookie 无效：{exc}（将尽量无 Cookie 抓取）", file=sys.stderr)
            cookie = ""
        except OSError as exc:
            print(f"提示：读取 Cookie 失败：{exc}（将尽量无 Cookie 抓取）", file=sys.stderr)
            cookie = ""

        try:
            discovered = discover_action_ids(
                base_url=base_url,
                cookie=cookie,
                timeout_seconds=args.timeout_seconds,
                user_agent=args.user_agent,
                max_js_files=max(1, int(args.max_js_files)),
                max_candidates_test=max(1, int(args.max_candidates_test)),
            )
        except ActionIdDiscoveryError as exc:
            print(f"抓取失败：{exc}", file=sys.stderr)
            failed_urls.append(base_url)
            continue

        action_map[host] = {
            "status_action_id": discovered.status_action_id,
            "checkin_action_id": discovered.checkin_action_id,
        }
        updated_hosts.append(host)

        print("已识别 actionId：")
        print(f"  status_action_id : {discovered.status_action_id}")
        print(f"  checkin_action_id: {discovered.checkin_action_id}")
        print(f"  （测试候选 {discovered.candidates_tested} 个，扫描 JS {discovered.js_files_scanned} 个）")

        if discovered.used_cookie_for_checkin_probe:
            print("提示：本次识别为获取 checkin_action_id 使用了 Cookie 探测，可能会触发一次签到。", file=sys.stderr)
        elif discovered.used_cookie_for_status_probe:
            print("提示：本次识别为获取 status_action_id 使用了 Cookie 探测。", file=sys.stderr)

    if updated_hosts:
        _save_action_map(action_config_file, action_map)
        print(f"\n已写入：{action_config_file}")

    print("\n=== 汇总 ===")
    print(f"成功 {len(updated_hosts)} 个，失败 {len(failed_urls)} 个。")

    if failed_urls:
        print("执行失败：" + "、".join(failed_urls), file=sys.stderr)
        return ExitCodes.ERROR

    return ExitCodes.OK


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
