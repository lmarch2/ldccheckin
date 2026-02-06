# Findings（调研结论）

- 站点：`https://store.ryanai.org/`
- 登录：Linux DO OAuth2。服务器侧无法复用本机“已登录浏览器会话”，因此需要可迁移的登录态文件。
- 签到入口：页面右上角“签到 / Checkin”按钮；**已签到时按钮不显示**。

结论：
- Playwright 登录链路容易触发 Cloudflare 人机验证，不适合服务器无人值守。
- 站点是 Next.js(App Router)，签到逻辑是 **Server Action**：
  - `checkIn` actionId：`00573f21cb6fdebcbb247b7ddbec9edcf954d96992`
  - `getCheckinStatus` actionId：`00047583cb7e0d3bd45fc537bd80dc9c6a7c04a1e8`
- 可用纯 HTTP 方式复现按钮行为：
  - `POST https://store.ryanai.org/`
  - Header：`next-action: <actionId>`，`accept: text/x-component`，`content-type: text/plain;charset=UTF-8`，并带上 Cookie
  - Body：`[]`
