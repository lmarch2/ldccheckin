# LDC Multi-Shop Check-in (Cookie + HTTP)

English | [中文](README.zh-CN.md)

Automate daily check-ins for multiple LDC shops by calling their Next.js Server Actions over HTTP.

- Beautiful interactive setup wizard (Rich TUI)
- Supports a single shop URL or bulk URLs from a file
- Fetches shop metadata, guides cookie input, and can create a daily cron job

## Features

- Detects “already checked in today” vs “needs check-in”
- Saves debug responses to `artifacts/` when parsing fails
- Supports any HTTPS shop URL (actionIds can be overridden via `state/action_ids.json`)

## Built-in Shops (Extensible)

| Shop | Default Cookie File |
| --- | --- |
| `https://store.ryanai.org/` | `state/ryanai.cookie` |
| `https://oeo.cc.cd/` | `state/oeo.cookie` |
| `https://ldc-shop.3-418.workers.dev/` | `state/ldc-shop.3-418.cookie` |
| `https://ldc.wxqq.de5.net/` | `state/ldc.wxqq.de5.net.cookie` |

You can override the cookie path with `--cookie-file`. For non built-in shops, the default is `state/<host>.cookie`.

## Requirements

- Python 3.10+
- Linux / macOS / Docker

Install dependencies:

```bash
pip install -r requirements.txt
```

## Quick Start (10 seconds)

```bash
# 1) Start the interactive wizard
python scripts/wizard.py

# 2) Follow prompts to input URL / cookie / actionId
# 3) (Optional) let the wizard create a daily cron job
```

## Interactive Wizard (Recommended)

```bash
python scripts/wizard.py
```

The wizard will:

1. Collect one URL or load URLs from a file
2. Fetch shop title/description and display them
3. Ask you to paste the cookie for each shop
4. Write/complete `state/action_ids.json`
5. Optionally create a daily `crontab` entry

### URL File Format

One URL per line, supports `#` comments:

```text
# state/shops.txt
https://oeo.cc.cd/
https://ldc-shop.3-418.workers.dev/
https://ldc.wxqq.de5.net/
```

Copy the template:

```bash
cp shops.example.txt state/shops.txt
```

Run with bulk URLs:

```bash
python scripts/wizard.py --url-file state/shops.txt
```

## Run Check-in

### 1) Prepare cookie files

After logging in via browser, extract the `cookie:` value (DevTools “Copy as cURL” is convenient) and save to files:

```bash
mkdir -p state

cat > state/ryanai.cookie <<'EOF'
<store.ryanai.org cookie>
EOF

cat > state/oeo.cookie <<'EOF'
<oeo.cc.cd cookie>
EOF

cat > state/ldc-shop.3-418.cookie <<'EOF'
<ldc-shop.3-418.workers.dev cookie>
EOF

cat > state/ldc.wxqq.de5.net.cookie <<'EOF'
<ldc.wxqq.de5.net cookie>
EOF

chmod 600 state/*.cookie
```

### 2) Run a single shop

```bash
python scripts/checkin.py
python scripts/checkin.py --base-url https://oeo.cc.cd/
python scripts/checkin.py --base-url https://ldc-shop.3-418.workers.dev/
python scripts/checkin.py --base-url https://ldc.wxqq.de5.net/
```

### 3) Run all built-in shops (Recommended)

```bash
python scripts/checkin.py --run-all
```

Legacy equivalent (manual chaining):

```bash
python scripts/checkin.py && python scripts/checkin.py --base-url https://oeo.cc.cd/ && python scripts/checkin.py --base-url https://ldc-shop.3-418.workers.dev/ && python scripts/checkin.py --base-url https://ldc.wxqq.de5.net/
```

## Scheduling (cron)

You can let the wizard create it, or do it manually.

Example: run daily at 01:00.

```bash
crontab -e

0 1 * * * cd <repo_path> && <python_path> scripts/checkin.py --run-all >> <repo_path>/logs/checkin.log 2>&1
```

Replace `<repo_path>` with your repo path and `<python_path>` with the absolute Python executable (e.g. `~/.venv/bin/python`).

## CLI Options

```bash
python scripts/checkin.py --help
python scripts/wizard.py --help
```

Common flags:

- `--base-url`: target shop URL (default `https://store.ryanai.org/`)
- `--run-all`: run all built-in shops
- `--cookie-file`: cookie file path (defaults based on host)
- `--cookie-env`: read cookie from env var (takes precedence)
- `--skip-status`: skip status query and attempt check-in directly

Wizard flags:

- `--url`: a single shop URL
- `--url-file`: bulk URL file
- `--action-config-file`: actionId config path

## Exit Codes

- `0`: success / already checked in today
- `1`: error (network, parsing, unexpected response)
- `2`: needs login / cookie expired / Cloudflare challenge

## actionId Configuration

Different shops use different Server Actions (`next-action`). Resolution order:

1. CLI `--status-action-id` + `--checkin-action-id`
2. `--action-config-file` (default `state/action_ids.json`)
3. Built-in defaults for the shops listed above

If you see `Server action not found`, capture the correct `next-action` values in browser DevTools and add them.

## Security Notes

- `state/`, `artifacts/`, and `logs/` are Git-ignored
- Never commit real cookies/tokens/debug payloads
- If a cookie leaks, log out and regenerate it immediately

## Project Layout

```text
.
├── ldccheckin/
│   ├── constants.py
│   ├── cli_checkin.py
│   └── cli_wizard.py
├── scripts/
│   ├── checkin.py
│   └── wizard.py
├── state/          # local cookies (ignored)
├── artifacts/      # debug output (ignored)
├── logs/           # runtime logs (ignored)
├── action_ids.example.json
├── shops.example.txt
├── requirements.txt
├── README.md
+└── README.zh-CN.md
```

## Disclaimer

Make sure you have authorization to access the target accounts and comply with the shop’s Terms of Service.
