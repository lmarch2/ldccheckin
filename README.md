# LDC 多店自动签到（Cookie + HTTP）

基于 Python 标准库，通过 HTTP 调用站点的 Next.js Server Action 完成签到。

- 无需浏览器自动化
- 无需第三方 Python 依赖
- 支持多站点按域名自动匹配 Cookie 文件

## 功能特性

- 自动判断“今日已签到”与“需要签到”
- 失败时输出可读错误并保留调试响应到 `artifacts/`
- 仅允许白名单站点，避免误发 Cookie 到未知域名

## 支持站点

| 站点 | 默认 Cookie 文件 |
| --- | --- |
| `https://store.ryanai.org/` | `state/ryanai.cookie` |
| `https://oeo.cc.cd/` | `state/oeo.cookie` |
| `https://ldc-shop.3-418.workers.dev/` | `state/ldc-shop.3-418.cookie` |

可通过 `--cookie-file` 覆盖默认路径。

## 环境要求

- Python 3.10+
- Linux / macOS / Docker 均可

## 快速开始

### 1) 准备 Cookie 文件

为每个站点在浏览器登录后导出 Cookie（推荐从 DevTools `Copy as cURL` 提取 `cookie:` 值）：

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

chmod 600 state/*.cookie
```

### 2) 单站执行

```bash
python scripts/ryanai_store_checkin.py
python scripts/ryanai_store_checkin.py --base-url https://oeo.cc.cd/
python scripts/ryanai_store_checkin.py --base-url https://ldc-shop.3-418.workers.dev/
```

### 3) 一次执行全部站点

```bash
python scripts/ryanai_store_checkin.py && \
python scripts/ryanai_store_checkin.py --base-url https://oeo.cc.cd/ && \
python scripts/ryanai_store_checkin.py --base-url https://ldc-shop.3-418.workers.dev/
```

## 定时执行（cron）

示例：每天 01:00 依次签到 3 个站点。

```bash
crontab -e

0 1 * * * cd <repo_path> && { \
<python_path> scripts/ryanai_store_checkin.py; \
<python_path> scripts/ryanai_store_checkin.py --base-url https://oeo.cc.cd/; \
<python_path> scripts/ryanai_store_checkin.py --base-url https://ldc-shop.3-418.workers.dev/; \
} >> <repo_path>/logs/checkin.log 2>&1
```

将 `<repo_path>` 替换为仓库实际路径，将 `<python_path>` 替换为解释器绝对路径（例如 `~/.venv/bin/python`）。

## CLI 参数

```bash
python scripts/ryanai_store_checkin.py --help
```

常用参数：

- `--base-url`：目标站点（默认 `https://store.ryanai.org/`）
- `--cookie-file`：Cookie 文件路径（默认按域名自动匹配）
- `--cookie-env`：从环境变量读取 Cookie（优先于文件）
- `--skip-status`：跳过状态查询，直接尝试签到

## 退出码

- `0`：签到成功，或今日已签到
- `1`：网络异常 / 响应解析失败 / 其他错误
- `2`：未登录 / Cookie 失效 / 遇到人机验证

## 多站点 actionId 配置

不同站点的 Next.js Server Action `next-action` 通常不同。

脚本优先级如下：

1. 命令行显式传入 `--status-action-id` + `--checkin-action-id`
2. 读取 `--action-config-file`（默认 `state/action_ids.json`）
3. 使用内置默认（已内置本文档列出的 3 个站点）

当看到 `Server action not found` 时，请为对应站点补充配置，例如：

```json
{
  "oeo.cc.cd": {
    "status_action_id": "<getCheckinStatus next-action>",
    "checkin_action_id": "<checkIn next-action>"
  },
  "ldc-shop.3-418.workers.dev": {
    "status_action_id": "<getCheckinStatus next-action>",
    "checkin_action_id": "<checkIn next-action>"
  }
}
```

你也可以直接复制模板：

```bash
cp action_ids.example.json state/action_ids.json
```

抓取方式：在浏览器 DevTools 的 `Network` 面板中，找到签到相关请求头里的 `next-action`。

## 安全与开源注意事项

- `state/`、`artifacts/`、`logs/` 已在 `.gitignore` 中忽略
- 不要提交任何真实 Cookie、会话令牌或调试响应
- 如 Cookie 泄露，请立即在对应站点退出登录并重新登录生成新 Cookie

## 项目结构

```text
.
├── scripts/
│   └── ryanai_store_checkin.py
├── state/          # 本地 Cookie（已忽略）
├── artifacts/      # 调试输出（已忽略）
├── logs/           # 运行日志（已忽略）
├── requirements.txt
└── README.md
```

## 免责声明

请确保你对目标站点账号拥有合法访问权限，并遵守目标站点服务条款。
