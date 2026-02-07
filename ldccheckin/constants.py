from __future__ import annotations

DEFAULT_BASE_URL = "https://store.ryanai.org/"
DEFAULT_COOKIE_ENV = "LDC_COOKIE"
DEFAULT_COOKIE_FILE = ""
DEFAULT_ACTION_CONFIG_FILE = "state/action_ids.json"
DEFAULT_TIMEOUT_SECONDS = 30
DEFAULT_WIZARD_TIMEOUT_SECONDS = 20
DEFAULT_ARTIFACTS_DIR = "artifacts"
DEFAULT_CRON_HOUR = 1
DEFAULT_CRON_MINUTE = 0
DEFAULT_USER_AGENT = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"

DEFAULT_CHECKIN_ACTION_ID = "00573f21cb6fdebcbb247b7ddbec9edcf954d96992"
DEFAULT_STATUS_ACTION_ID = "00047583cb7e0d3bd45fc537bd80dc9c6a7c04a1e8"

DEFAULT_ACTION_IDS_BY_HOST = {
    "store.ryanai.org": {
        "status_action_id": DEFAULT_STATUS_ACTION_ID,
        "checkin_action_id": DEFAULT_CHECKIN_ACTION_ID,
    },
    "oeo.cc.cd": {
        "status_action_id": "0020b40a07230b826fc09ad75e17528ec60fb3a27d",
        "checkin_action_id": "0035d168722cee2c38c16bc8067f36a10067ee30ba",
    },
    "ldc-shop.3-418.workers.dev": {
        "status_action_id": "00ec8c9facbe1fdceb7685cd71a8bfeb02d4fdede7",
        "checkin_action_id": "009d7dd2852e6e10b697787cba9a82d33cc5041694",
    },
    "ldc.wxqq.de5.net": {
        "status_action_id": "00e4e8841f678dbf8b88c158c6d22ca296ab0c3e4f",
        "checkin_action_id": "00d85e3a8ba71bd3e0a3bd837fba3976cc965525c9",
    },
}

DEFAULT_COOKIE_FILE_BY_HOST = {
    "store.ryanai.org": "state/ryanai.cookie",
    "oeo.cc.cd": "state/oeo.cookie",
    "ldc-shop.3-418.workers.dev": "state/ldc-shop.3-418.cookie",
    "ldc.wxqq.de5.net": "state/ldc.wxqq.de5.net.cookie",
}

DEFAULT_ALL_SHOP_URLS = tuple(f"https://{host}/" for host in DEFAULT_COOKIE_FILE_BY_HOST)


def default_cookie_file_for_host(host: str) -> str:
    mapped = DEFAULT_COOKIE_FILE_BY_HOST.get(host)
    if mapped:
        return mapped
    return f"state/{host}.cookie"
