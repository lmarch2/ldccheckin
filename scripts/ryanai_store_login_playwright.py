#!/usr/bin/env python3
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path
from urllib.parse import urlparse

from playwright.sync_api import (
    Error as PlaywrightError,
    TimeoutError as PlaywrightTimeoutError,
    sync_playwright,
)

DEFAULT_URL = "https://store.ryanai.org/"
DEFAULT_STATE_PATH = "state/storage_state.json"

ALLOWED_DOMAIN_SUFFIX = "ryanai.org"

LOGIN_TEXT_RE = re.compile(r"(登录|log\s*in|sign\s*in)", re.IGNORECASE)


def _safe_hostname(url: str) -> str:
    try:
        return (urlparse(url).hostname or "").lower()
    except ValueError:
        return ""


def _has_visible(locator, limit: int = 10) -> bool:
    try:
        count = locator.count()
    except PlaywrightError:
        return False

    for i in range(min(count, limit)):
        item = locator.nth(i)
        try:
            if item.is_visible():
                return True
        except PlaywrightError:
            continue
    return False


def _is_probably_logged_out(page) -> bool:
    host = _safe_hostname(page.url)
    if not host:
        return False

    if host.endswith("linux.do"):
        return True

    if not host.endswith(ALLOWED_DOMAIN_SUFFIX):
        return True

    if _has_visible(page.get_by_role("link", name=LOGIN_TEXT_RE)):
        return True
    if _has_visible(page.get_by_role("button", name=LOGIN_TEXT_RE)):
        return True
    return False


def _try_chmod_600(path: Path) -> None:
    try:
        path.chmod(0o600)
    except OSError as exc:
        print(f"提示：无法设置 {path} 权限为 600：{exc}", file=sys.stderr)


def _parse_args(argv: list[str]):
    parser = argparse.ArgumentParser(description="生成 store.ryanai.org 的 Playwright 登录态(storage_state)。")
    parser.add_argument("--url", default=DEFAULT_URL, help="目标站点 URL（默认：%(default)s）")
    parser.add_argument("--state", default=DEFAULT_STATE_PATH, help="输出 storage_state.json 路径（默认：%(default)s）")
    parser.add_argument(
        "--timeout-seconds",
        type=int,
        default=120,
        help="单步超时秒数（默认：%(default)s）",
    )
    return parser.parse_args(argv)


def main(argv: list[str]) -> int:
    args = _parse_args(argv)
    if args.timeout_seconds < 5:
        print("错误：--timeout-seconds 不能小于 5", file=sys.stderr)
        return 1

    state_path = Path(args.state).expanduser()
    state_path.parent.mkdir(parents=True, exist_ok=True)
    timeout_ms = args.timeout_seconds * 1000

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=False)
        try:
            context = browser.new_context()
            try:
                page = context.new_page()
                page.set_default_timeout(timeout_ms)

                print(f"正在打开：{args.url}")
                page.goto(args.url, wait_until="domcontentloaded")

                print("请在打开的浏览器窗口中完成 Linux DO OAuth 登录。")
                print("确认你已能正常访问 store.ryanai.org（无需再跳转登录）后，回到此终端按回车继续。")
                try:
                    input()
                except KeyboardInterrupt:
                    print("\n已取消。", file=sys.stderr)
                    return 1

                page.goto(args.url, wait_until="domcontentloaded")
                page.wait_for_timeout(1000)

                if _is_probably_logged_out(page):
                    print("仍检测到未登录/跳转登录页。请确认已完成授权登录后重试。", file=sys.stderr)
                    print(f"当前 URL：{page.url}", file=sys.stderr)
                    return 2

                context.storage_state(path=str(state_path))
                _try_chmod_600(state_path)
                print(f"已保存登录态：{state_path}")
                return 0
            except PlaywrightTimeoutError as exc:
                print(f"超时：{exc}", file=sys.stderr)
                return 1
            except PlaywrightError as exc:
                print(f"Playwright 错误：{exc}", file=sys.stderr)
                return 1
            finally:
                try:
                    context.close()
                except PlaywrightError:
                    pass
        finally:
            try:
                browser.close()
            except PlaywrightError:
                pass


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))

