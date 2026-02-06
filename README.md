# store.ryanai.org 自动签到（服务器定时，Python）

通过“**Cookie + HTTP**”方式调用站点的 Next.js Server Action，实现服务器每日自动签到（不启动浏览器，不走 Playwright）：

- **已签到**：脚本会检测到 `checkedIn=true`，直接返回成功
- **未签到**：脚本会调用 `checkIn`，成功后返回成功

## 安全说明（非常重要）

`state/store.cookie` 等同于你的登录会话凭证（包含 `__Secure-authjs.session-token` 等）。请当作密码处理：

- **不要提交到 Git**
- 建议 `chmod 600 state/store.cookie`
- 不要发到不可信环境/群聊

> 如果 Cookie 曾经泄露/分享过，建议你尽快在站点里退出并重新登录以刷新会话。

## 环境要求

- Python **3.10+**
- Ubuntu 或 Docker（无需额外系统依赖）

## 安装

HTTP 方案不需要 pip 依赖（`requirements.txt` 为空）。

如果你想用 venv：

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

如果你用 conda（你要求的方式）：

```bash
source ~/miniconda3/etc/profile.d/conda.sh
conda activate ldccheckin
python --version
```

## 第一次使用：导出 Cookie（手动一次）

推荐方式（能拿到 HttpOnly cookie）：

1. 用浏览器打开 `https://store.ryanai.org/`，确保已登录
2. 打开 DevTools → `Network`
3. 刷新页面，随便点一个到 `store.ryanai.org` 的请求
4. 右键该请求 → `Copy` → `Copy as cURL`
5. 从 cURL 里找到 `-H 'cookie: ...'`（或 `-H 'Cookie: ...'`），把 `cookie:` 后面的内容保存到服务器文件：

```bash
mkdir -p state
cat > state/store.cookie <<'EOF'
<把 cookie: 后面的整段内容粘贴到这里>
EOF
chmod 600 state/store.cookie
```

## 单次执行（手动跑一次确认）

```bash
python scripts/ryanai_store_checkin.py --cookie-file state/store.cookie
echo $?
```

## 定时（cron，每天 01:00）

示例（请把路径改成你的真实路径；cron 的时间取决于服务器时区）：

```bash
mkdir -p /opt/ldccheckin/logs
crontab -e

# 每天 01:00 执行一次
0 1 * * * cd /opt/ldccheckin && /opt/ldccheckin/.venv/bin/python scripts/ryanai_store_checkin.py --cookie-file state/store.cookie >> /opt/ldccheckin/logs/checkin.log 2>&1
```

如果你用 conda env（更推荐用 env 的 python 绝对路径，而不是在 cron 里 activate）：

```bash
# 先找到 conda env python 路径
python -c 'import sys; print(sys.executable)'

# 把上面输出替换到 crontab 里，例如：
0 1 * * * cd /opt/ldccheckin && /path/to/conda/envs/ldccheckin/bin/python scripts/ryanai_store_checkin.py --cookie-file state/store.cookie >> /opt/ldccheckin/logs/checkin.log 2>&1
```

## 退出码

- `0`：成功（已签到 / 或签到成功）
- `2`：未登录 / Cookie 失效 / 遇到 Cloudflare 人机验证（需要更新 Cookie，尤其是 `cf_clearance`）
- `1`：其它错误（网络/站点异常/响应解析失败）

## 调试产物

发生错误时，会在 `artifacts/` 下保存调试响应（不包含 Cookie）：

- `*.meta.json`：状态码、content-type
- `*.resp.txt`：原始响应内容（便于定位是否被 Cloudflare 拦截等）

## Playwright 旧方案（不推荐）

由于 Playwright 登录链路可能触发 Cloudflare 人机验证，旧脚本仅保留备查：

- `scripts/ryanai_store_checkin_playwright.py`
- `scripts/ryanai_store_login_playwright.py`

如需使用，请安装 `requirements-playwright.txt` 并自行处理浏览器依赖。
