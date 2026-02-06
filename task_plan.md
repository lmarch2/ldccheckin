# 任务计划：store.ryanai.org 自动签到（HTTP + Cookie）

## 目标

- Ubuntu/Docker 服务器上 **每天 01:00** 定时执行一次签到
- 未签到：调用 `checkIn` Server Action 完成签到
- 已签到：`getCheckinStatus` 返回 `checkedIn=true`，直接视为成功
- Cookie 失效/未登录/遇到 Cloudflare 人机验证时：返回退出码 `2`

## 非目标

- 不做常驻进程（由 cron/systemd 定时触发）

## 方案

- Python（stdlib）直接发起 HTTP 请求调用 Next.js Server Action
- 服务器保存 `state/store.cookie`（从浏览器导出 Cookie）
- 服务器每天定时运行 `scripts/ryanai_store_checkin.py`：
  - 先调用 `getCheckinStatus`
  - 未签到则调用 `checkIn`

## 交付文件

- `scripts/ryanai_store_checkin.py`
- `requirements.txt`
- `.gitignore`
- `README.md`

## 验证

1. 服务器：准备 `state/store.cookie`
2. 服务器：运行签到脚本一次，观察退出码与输出
3. cron：添加 `0 1 * * *` 定时任务并检查日志
