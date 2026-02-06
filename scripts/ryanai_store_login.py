#!/usr/bin/env python3
from __future__ import annotations

import sys


def main() -> int:
    print("该项目已切换为“Cookie + HTTP(Server Action)”方式签到。", file=sys.stderr)
    print("Playwright 方案已保留为旧脚本：scripts/ryanai_store_login_playwright.py", file=sys.stderr)
    print("请按 README.md 导出 store.ryanai.org 的 Cookie 到 state/store.cookie。", file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
