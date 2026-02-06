#!/usr/bin/env python3
from __future__ import annotations

import argparse
import re
import sys
import time
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse

from playwright.sync_api import (
    Error as PlaywrightError,
    TimeoutError as PlaywrightTimeoutError,
    sync_playwright,
)

DEFAULT_URL = "https://store.ryanai.org/"
DEFAULT_STATE_PATH = "state/storage_state.json"
DEFAULT_TIMEOUT_SECONDS = 30
DEFAULT_ARTIFACTS_DIR = "artifacts"

ALLOWED_DOMAIN_SUFFIX = "ryanai.org"

CHECKIN_TEXT_RE = re.compile(r"(签到|check\s*in)", re.IGNORECASE)
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


def _detect_not_logged_in(page) -> bool:
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


def _pick_visible(locator, limit: int = 10):
    try:
        count = locator.count()
    except PlaywrightError:
        return None

    for i in range(min(count, limit)):
        item = locator.nth(i)
        try:
            if item.is_visible():
                return item
        except PlaywrightError:
            continue
    return None


def _find_checkin_target(page, timeout_ms: int):
    checkin_wait_ms = min(timeout_ms, 8000)
    end = time.monotonic() + (checkin_wait_ms / 1000.0)

    candidates = [
        page.locator("a,button,[role=button]").filter(has_text=CHECKIN_TEXT_RE),
        page.get_by_role("button", name=CHECKIN_TEXT_RE),
        page.get_by_role("link", name=CHECKIN_TEXT_RE),
        page.get_by_text(CHECKIN_TEXT_RE),
    ]

    while time.monotonic() < end:
        for locator in candidates:
            target = _pick_visible(locator)
            if target is not None:
                return target
        time.sleep(0.25)

    for locator in candidates:
        target = _pick_visible(locator)
        if target is not None:
            return target
    return None


def _write_artifacts(artifacts_dir: Path, prefix: str, page) -> None:
    artifacts_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    base = artifacts_dir / f"{prefix}_{ts}"

    try:
        base.with_suffix(".url.txt").write_text(f"{page.url}\n", encoding="utf-8")
    except OSError as exc:
        print(f"提示：无法写入 URL 调试文件：{exc}", file=sys.stderr)

    try:
        base.with_suffix(".html").write_text(page.content(), encoding="utf-8")
    except (OSError, PlaywrightError) as exc:
        print(f"提示：无法写入 HTML 调试文件：{exc}", file=sys.stderr)

    try:
        page.screenshot(path=str(base.with_suffix(".png")), full_page=True)
    except (OSError, PlaywrightError) as exc:
        print(f"提示：无法写入截图：{exc}", file=sys.stderr)


def _parse_args(argv: list[str]):
    parser = argparse.ArgumentParser(description="store.ryanai.org 自动签到（Playwright 旧方案）。")
    parser.add_argument("--url", default=DEFAULT_URL, help="目标站点 URL（默认：%(default)s）")
    parser.add_argument("--state", default=DEFAULT_STATE_PATH, help="storage_state.json 路径（默认：%(default)s）")
    parser.add_argument(
        "--timeout-seconds",
        type=int,
        default=DEFAULT_TIMEOUT_SECONDS,
        help="超时秒数（默认：%(default)s）",
    )
    parser.add_argument(
        "--artifacts-dir",
        default=DEFAULT_ARTIFACTS_DIR,
        help="调试产物目录（默认：%(default)s）",
    )
    parser.add_argument(
        "--headed",
        action="store_true",
        help="调试用：开启有界面浏览器（默认无头）",
    )
    parser.add_argument(
        "--slowmo-ms",
        type=int,
        default=0,
        help="调试用：每步延迟毫秒（默认：0）",
    )
    return parser.parse_args(argv)


def main(argv: list[str]) -> int:
    args = _parse_args(argv)
    if args.timeout_seconds < 5:
        print("错误：--timeout-seconds 不能小于 5", file=sys.stderr)
        return 1
    if args.slowmo_ms < 0:
        print("错误：--slowmo-ms 不能为负数", file=sys.stderr)
        return 1

    state_path = Path(args.state).expanduser()
    if not state_path.exists():
        print(f"未找到登录态文件：{state_path}", file=sys.stderr)
        print("请先运行 scripts/ryanai_store_login_playwright.py 生成 storage_state.json，并拷贝到服务器。", file=sys.stderr)
        return 2

    artifacts_dir = Path(args.artifacts_dir).expanduser()
    timeout_ms = args.timeout_seconds * 1000

    page = None
    with sync_playwright() as pw:
        browser = pw.chromium.launch(
            headless=(not args.headed),
            slow_mo=args.slowmo_ms if args.slowmo_ms else 0,
        )
        try:
            context = browser.new_context(storage_state=str(state_path))
            try:
                page = context.new_page()
                page.set_default_timeout(timeout_ms)

                page.goto(args.url, wait_until="domcontentloaded")
                page.wait_for_timeout(1000)
                try:
                    page.wait_for_load_state("networkidle", timeout=5000)
                except PlaywrightTimeoutError:
                    pass

                if _detect_not_logged_in(page):
                    _write_artifacts(artifacts_dir, "not_logged_in", page)
                    print("未登录或登录态已失效，需要重新导出 storage_state.json。", file=sys.stderr)
                    print(f"当前 URL：{page.url}", file=sys.stderr)
                    return 2

                target = _find_checkin_target(page, timeout_ms=timeout_ms)
                if target is None:
                    print("未发现签到按钮：可能已签到（按钮已隐藏）。")
                    return 0

                try:
                    target.scroll_into_view_if_needed()
                except PlaywrightError:
                    pass

                target.click()
                try:
                    page.wait_for_load_state("networkidle", timeout=5000)
                except PlaywrightTimeoutError:
                    pass

                print("已点击签到按钮。")
                return 0
            except PlaywrightTimeoutError as exc:
                if page is not None:
                    _write_artifacts(artifacts_dir, "timeout", page)
                print(f"超时：{exc}", file=sys.stderr)
                return 1
            except PlaywrightError as exc:
                if page is not None:
                    _write_artifacts(artifacts_dir, "playwright_error", page)
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

