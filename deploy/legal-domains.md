# 域名规划与微信「合法域名」登记表（设计方案 7.4 / 7.10）

> 上线前把 `example.cn` 全部替换为真实域名。**三处必须完全一致**：ICP 备案信息、SSL 证书 SAN、微信公众平台后台登记值。
> 微信后台路径：「开发管理 → 开发设置 → 服务器域名」；**每月可修改次数有限**（示例口径 5 次），域名一次定规划，避免联调期反复改动。

## 一、三环境域名规划

| 用途 | dev（开发版，本机） | staging（体验版） | prod（正式版） |
|---|---|---|---|
| 游客 API | `http://127.0.0.1:8000/api/v1` | `https://api-staging.example.cn/api/v1` | `https://api.example.cn/api/v1` |
| 图片静态域 | `http://127.0.0.1:8000` | `https://api-staging.example.cn` | `https://cdn.example.cn` |
| PC 游客端 | `http://localhost:5174` | `https://www-staging.example.cn` | `https://www.example.cn` |
| 管理后台 | `http://localhost:5173` | `https://admin-staging.example.cn` | `https://admin.example.cn` |

小程序端按 `wx.getAccountInfoSync().miniProgram.envVersion` 自动切换（`travel-miniapp/utils/config.js`）：
`develop → dev`、`trial → staging`、`release → prod`。dev 需在开发者工具勾选「不校验合法域名」；**提审版本必须是 release 且不含任何 localhost / IP / 占位域名**。

## 二、微信后台「服务器域名」登记清单

| 类别 | 登记值（prod） | 用途 | 备注 |
|---|---|---|---|
| request 合法域名 | `https://api.example.cn` | 全部 `/api/v1` 接口、JWT 登录、行程生成 | 只填域名，不带端口与路径 |
| downloadFile 合法域名 | `https://cdn.example.cn` | POI 图片下载展示 | 若 staging 与 prod 共用，需一并登记 staging 域 |
| uploadFile 合法域名 | 不配置 | 一期无用户上传（管理端在 PC 后台上传） | 保持为空，减少审核问询 |
| socket 合法域名 | 不配置 | 一期无 WebSocket | 保持为空 |
| udp / tcp | 不配置 | 一期无 | 保持为空 |
| 业务域名（web-view） | 不配置 | 一期无 web-view 组件 | 若后续嵌入 H5 需单独备案并上传校验文件 |

> 小程序 `wx.request` 不受浏览器 CORS 约束，但仍必须在后台登记 request 合法域名；PC 端走同源 `/api` 反代，靠后端 `CORS_ORIGINS` 白名单控制。

## 三、硬性条件（逐条核对）

- [ ] 服务器在中国内地，域名已完成 **ICP 备案**（`api / www / admin / cdn` 全部覆盖），备案号展示在站点页脚。
- [ ] **小程序备案**已通过（2023-09 起强制，M0 一票否决项）。
- [ ] 每个域名均已签发匹配的 SSL 证书，TLS 1.2+，证书配置自动续期（`certbot renew` 定时 + 到期告警）。
- [ ] 全链路 HTTPS：无 `http://` 资源、无混合内容；`http` 仅保留 80 端口跳转。
- [ ] 后端 `.env` 的 `PUBLIC_API_ORIGIN / PORTAL_ORIGIN / ADMIN_ORIGIN / CDN_ORIGIN / CORS_ORIGINS` 与上表一致。
- [ ] 小程序 `utils/config.js` 的 `trial / release` 域名与上表一致，且不含 `example.cn`、`127.0.0.1`、`localhost`。
- [ ] 管理端接口 `/api/v1/admin/` 仅在 admin 子域可达（Nginx 模板已在 api 子域 return 404）。
- [ ] 生产关闭 `/docs`、`/redoc`、`/openapi.json`（Nginx 模板已处理）。
- [ ] 证书、域名、备案、合法域名四项变更需同步评估，避免单侧改动导致小程序请求失败。

## 四、常见失败症状

| 症状 | 常见原因 |
|---|---|
| 真机 `request:fail url not in domain list` | 域名未登记 / 登记值与代码不一致 / 带端口或路径 / 证书链不完整 |
| 图片不显示 | `downloadFile` 域未登记，或图片仍是相对路径未拼绝对地址 |
| 体验版可用、正式版不可用 | `config.js` 的 release 域名仍是占位值 |
| iOS 正常、Android 失败（或反之） | 证书链不完整 / 不支持 TLS 1.2 / SNI 配置问题 |
