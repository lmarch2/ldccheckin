#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen

from rich import box
from rich.console import Console
from rich.panel import Panel
from rich.prompt import Confirm, IntPrompt, Prompt
from rich.table import Table


from ldccheckin.constants import (
    DEFAULT_ACTION_CONFIG_FILE,
    DEFAULT_CRON_HOUR,
    DEFAULT_CRON_MINUTE,
    DEFAULT_USER_AGENT,
    DEFAULT_WIZARD_TIMEOUT_SECONDS,
    default_cookie_file_for_host,
)


@dataclass(frozen=True)
class ShopConfig:
    url: str
    host: str
    title: str
    description: str
    cookie_file: Path


console = Console()


def _normalize_url(raw: str) -> str:
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


def _fetch_shop_info(url: str, timeout_seconds: int) -> tuple[str, str]:
    req = Request(
        url,
        headers={
            "user-agent": DEFAULT_USER_AGENT,
            "accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        },
    )
    try:
        with urlopen(req, timeout=timeout_seconds) as resp:
            content_type = (resp.headers.get("content-type") or "").lower()
            body = resp.read().decode("utf-8", errors="replace")
    except HTTPError as exc:
        raise ValueError(f"抓取失败：HTTP {getattr(exc, 'code', 'unknown')}") from exc
    except URLError as exc:
        raise ValueError(f"抓取失败：{exc}") from exc

    if "html" not in content_type and "text" not in content_type:
        raise ValueError(f"页面内容类型异常：{content_type}")

    title_match = re.search(r"<title[^>]*>(.*?)</title>", body, flags=re.IGNORECASE | re.DOTALL)
    desc_match = re.search(
        r'<meta[^>]+name=["\']description["\'][^>]+content=["\'](.*?)["\']',
        body,
        flags=re.IGNORECASE | re.DOTALL,
    )
    title = (title_match.group(1) if title_match else "").strip()
    title = re.sub(r"\s+", " ", title)
    desc = (desc_match.group(1) if desc_match else "").strip()
    desc = re.sub(r"\s+", " ", desc)
    return title or "(未识别标题)", desc or "(未识别描述)"


def _load_action_map(path: Path) -> dict[str, dict[str, str]]:
    if not path.exists():
        return {}
    loaded = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(loaded, dict):
        return {}
    result: dict[str, dict[str, str]] = {}
    for host, value in loaded.items():
        if not isinstance(host, str) or not isinstance(value, dict):
            continue
        status_action_id = value.get("status_action_id")
        checkin_action_id = value.get("checkin_action_id")
        if isinstance(status_action_id, str) and status_action_id.strip() and isinstance(checkin_action_id, str) and checkin_action_id.strip():
            result[host.strip().lower()] = {
                "status_action_id": status_action_id.strip(),
                "checkin_action_id": checkin_action_id.strip(),
            }
    return result


def _save_action_map(path: Path, action_map: dict[str, dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(action_map, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _append_or_update_cron(
    *,
    shops: list[ShopConfig],
    python_path: str,
    repo_path: str,
    action_config_file: str,
    minute: int,
    hour: int,
) -> None:
    current = subprocess.run(["crontab", "-l"], check=False, capture_output=True, text=True)
    lines = current.stdout.splitlines() if current.returncode == 0 else []

    managed_start = "# ldccheckin-auto-signin-start"
    managed_end = "# ldccheckin-auto-signin-end"

    filtered: list[str] = []
    skipping = False
    for line in lines:
        if line.strip() == managed_start:
            skipping = True
            continue
        if line.strip() == managed_end:
            skipping = False
            continue
        if not skipping:
            filtered.append(line)

    commands: list[str] = []
    for shop in shops:
        cmd = (
            f"{python_path} scripts/checkin.py "
            f"--base-url {shop.url} "
            f"--cookie-file {shop.cookie_file} "
            f"--action-config-file {action_config_file}"
        )
        commands.append(cmd)

    chained = "; ".join(commands)
    cron_line = f"{minute} {hour} * * * cd {repo_path} && {{ {chained}; }} >> {repo_path}/logs/checkin.log 2>&1"

    filtered.extend([managed_start, cron_line, managed_end])
    content = "\n".join(filtered).strip() + "\n"
    subprocess.run(["crontab", "-"], input=content, text=True, check=True)


def _collect_urls_interactive() -> list[str]:
    console.print(Panel("[bold cyan]签到向导[/bold cyan]\n支持单个 URL 输入，或从文件批量读取 URL。", border_style="cyan"))
    mode = Prompt.ask(
        "选择 URL 来源",
        choices=["single", "file"],
        default="single",
    )

    if mode == "single":
        values = Prompt.ask("请输入店铺 URL（例如 https://oeo.cc.cd/ ）")
        return [values]

    path_text = Prompt.ask("请输入 URL 文件路径", default="state/shops.txt")
    return _read_urls_from_file(Path(path_text).expanduser())


def _prepare_shop_configs(urls: list[str], timeout_seconds: int) -> list[ShopConfig]:
    seen: set[str] = set()
    result: list[ShopConfig] = []

    for raw in urls:
        normalized = _normalize_url(raw)
        parsed = urlparse(normalized)
        host = (parsed.hostname or "").lower()
        if host in seen:
            continue
        seen.add(host)

        title, desc = _fetch_shop_info(normalized, timeout_seconds)
        result.append(
            ShopConfig(
                url=normalized,
                host=host,
                title=title,
                description=desc,
                cookie_file=Path(default_cookie_file_for_host(host)),
            )
        )
    return result


def _show_shops(shops: list[ShopConfig]) -> None:
    table = Table(title="识别到的店铺信息", box=box.ROUNDED, border_style="bright_blue")
    table.add_column("#", style="cyan", width=4)
    table.add_column("URL", style="green")
    table.add_column("标题", style="white")
    table.add_column("描述", style="magenta")
    table.add_column("Cookie 文件", style="yellow")

    for index, shop in enumerate(shops, start=1):
        table.add_row(str(index), shop.url, shop.title, shop.description, str(shop.cookie_file))

    console.print(table)


def _save_cookies(shops: list[ShopConfig]) -> None:
    for shop in shops:
        console.print(Panel(f"[bold]{shop.url}[/bold]\n请粘贴该店铺 cookie（可直接粘贴 `cookie: ...`）。", border_style="green"))
        cookie = Prompt.ask("Cookie")
        normalized = cookie.strip()
        if not normalized:
            raise ValueError(f"{shop.url} 的 cookie 为空")
        if normalized.lower().startswith("cookie:"):
            normalized = normalized.split(":", 1)[1].strip()
        if "=" not in normalized:
            raise ValueError(f"{shop.url} 的 cookie 格式无效")

        shop.cookie_file.parent.mkdir(parents=True, exist_ok=True)
        shop.cookie_file.write_text(normalized + "\n", encoding="utf-8")
        try:
            os.chmod(shop.cookie_file, 0o600)
        except OSError:
            pass


def _ensure_action_ids(shops: list[ShopConfig], action_config_file: Path) -> None:
    action_map = _load_action_map(action_config_file)

    for shop in shops:
        if shop.host in action_map:
            continue
        console.print(Panel(f"[bold yellow]{shop.url}[/bold yellow]\n未发现 actionId 配置，请输入。", border_style="yellow"))
        status_action_id = Prompt.ask("status_action_id（getCheckinStatus）")
        checkin_action_id = Prompt.ask("checkin_action_id（checkIn）")
        if not status_action_id.strip() or not checkin_action_id.strip():
            raise ValueError(f"{shop.url} 的 actionId 不能为空")
        action_map[shop.host] = {
            "status_action_id": status_action_id.strip(),
            "checkin_action_id": checkin_action_id.strip(),
        }

    _save_action_map(action_config_file, action_map)


def _install_daily_cron(shops: list[ShopConfig], action_config_file: Path) -> None:
    if not Confirm.ask("是否创建每日自动签到计划任务（crontab）？", default=True):
        return

    python_path = Prompt.ask("Python 可执行路径", default=sys.executable)
    repo_path = Prompt.ask("项目根目录", default=str(Path.cwd()))
    hour = IntPrompt.ask("每天几点执行（小时 0-23）", default=DEFAULT_CRON_HOUR)
    minute = IntPrompt.ask("分钟（0-59）", default=DEFAULT_CRON_MINUTE)

    if hour < 0 or hour > 23 or minute < 0 or minute > 59:
        raise ValueError("cron 时间范围无效")

    _append_or_update_cron(
        shops=shops,
        python_path=python_path,
        repo_path=repo_path,
        action_config_file=str(action_config_file),
        minute=minute,
        hour=hour,
    )
    console.print("[bold green]已写入 crontab 每日任务。[/bold green]")


def _parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="交互式签到向导：批量配置店铺、Cookie 与计划任务")
    parser.add_argument("--url", default="", help="单个店铺 URL")
    parser.add_argument("--url-file", default="", help="批量 URL 文件，每行一个 URL")
    parser.add_argument("--action-config-file", default=DEFAULT_ACTION_CONFIG_FILE, help="actionId 配置文件路径")
    parser.add_argument("--timeout-seconds", type=int, default=DEFAULT_WIZARD_TIMEOUT_SECONDS, help="抓取店铺信息超时秒数")
    return parser.parse_args(argv)


def main(argv: list[str]) -> int:
    args = _parse_args(argv)
    if args.timeout_seconds < 5:
        console.print("[red]错误：--timeout-seconds 不能小于 5[/red]")
        return 1

    try:
        if args.url_file:
            urls = _read_urls_from_file(Path(args.url_file).expanduser())
        elif args.url:
            urls = [args.url]
        else:
            urls = _collect_urls_interactive()

        shops = _prepare_shop_configs(urls, timeout_seconds=args.timeout_seconds)
        if not shops:
            console.print("[red]未获取到有效店铺 URL。[/red]")
            return 1

        _show_shops(shops)
        if not Confirm.ask("确认以上店铺并继续配置？", default=True):
            console.print("[yellow]已取消。[/yellow]")
            return 1

        _save_cookies(shops)
        action_config_file = Path(args.action_config_file).expanduser()
        _ensure_action_ids(shops, action_config_file)
        _install_daily_cron(shops, action_config_file)

        console.print("[bold green]配置完成。现在可直接执行签到脚本。[/bold green]")
        return 0
    except (ValueError, FileNotFoundError, URLError, OSError, subprocess.CalledProcessError) as exc:
        console.print(f"[red]错误：{exc}[/red]")
        return 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
