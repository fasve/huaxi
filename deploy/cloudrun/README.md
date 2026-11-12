# 微信云托管部署指南（路线 A）

> 目标：FastAPI 后端跑在**微信云托管**，用它自带的已备案 HTTPS 域名给小程序用，
> 省掉"买服务器 + 买域名 + 等 ICP 备案"这三件事。
> 前置：小程序 AppID（体验版即可，用于控制台关联）；本地能导出 MySQL 数据。

---

## 0. 你需要准备

- 一个**小程序 AppID**（云托管按 AppID 开通环境）；
- 微信开发者工具（部署后改 `utils/config.js` 用）；
- 本地数据库的一份 dump（`travel.sql`，含 308 条 POI）；
- 大约 30–60 分钟。

**费用**：云托管按量计费，低流量一般每月几元到几十元；MySQL 最小规格也有低配档。
具体以控制台报价为准，建议先开按量、把最大实例数设成 1。

---

## 1. 开通云托管并创建环境

1. 打开 <https://cloud.weixin.qq.com/>（微信云托管），用**小程序管理员**扫码登录；
2. 选择你的小程序 → **开通云托管**；
3. 创建一个环境（例如 `prod`），地域选**上海**（离贵州近）；
4. 记下环境 ID（形如 `prod-xxxxxx`）。

---

## 2. 创建 MySQL 并导入数据

云托管控制台 → **数据库 → MySQL → 新建**：

1. 规格选最小可用档，记下：**内网地址、端口（3306）、库名、用户名、密码**；
2. 建库：库名 `travel`，字符集 `utf8mb4` / `utf8mb4_unicode_ci`；
3. 导入数据（二选一）：
   - 控制台「数据管理 / SQL 操作」里上传 `travel.sql` 执行；
   - 或用控制台的「导入」功能上传 dump 文件。

### 本地导出 dump（Windows）

```powershell
& "C:\Program Files\MySQL\MySQL Server 8.0\bin\mysqldump.exe" `
  -uroot -p --default-character-set=utf8mb4 --single-transaction `
  --set-gtid-purged=OFF travel > travel.sql
```

> 不要用 `scripts/init_db.py` 初始化生产库——它会清库并只灌回最早的 88 条种子数据。

导入后核对：

```sql
SELECT COUNT(*) FROM poi;              -- 期望 308
SELECT COUNT(*) FROM trip_mode_config; -- 4
SELECT COUNT(*) FROM preset_route;     -- ≥1
```

---

## 3. 部署服务

云托管控制台 → **服务管理 → 新建服务**：

| 项 | 填什么 |
|---|---|
| 服务名称 | `travel-api` |
| 部署方式 | **代码包上传**（推荐）或 Git 仓库 |
| 代码目录 | 仓库根目录（含 `Dockerfile` 的那层） |
| Dockerfile 路径 | `Dockerfile` |
| 监听端口 | `8000` |
| 健康检查路径 | `/api/v1/health` |
| 最小/最大实例数 | 0 / 1（省钱；有访问会自动拉起） |
| 规格 | 0.5C1G 起 |

**代码包怎么打**（在仓库根目录）：

```powershell
# 排除 .venv / node_modules / .env，避免体积和泄密
tar -czf travel-api-src.tar.gz `
  --exclude=travel-api/.venv --exclude=travel-api/logs --exclude=travel-api/.env `
  --exclude=travel-miniapp --exclude=travel-portal --exclude=travel-web `
  --exclude=.backup --exclude=design --exclude=.tmp-build `
  Dockerfile .dockerignore travel-api
```

> 没有 `tar` 就用 7-Zip 打包成 zip：只勾 `Dockerfile`、`.dockerignore`、`travel-api/`（排除 `.venv`、`logs`、`.env`）。

---

## 4. 环境变量（服务 → 版本 → 环境变量）

必填：

| 变量 | 示例 |
|---|---|
| `APP_ENV` | `prod` |
| `API_HOST` | `0.0.0.0` |
| `DB_HOST` | 云托管 MySQL 内网地址 |
| `DB_PORT` | `3306` |
| `DB_USER` / `DB_PASSWORD` | MySQL 账号密码 |
| `DB_NAME` | `travel` |
| `JWT_SECRET` | `openssl rand -hex 32` 生成 |
| `MOCK_LOGIN` | `false`（有真实 AppID/Secret 时）；没有就先 `true` 跑通 |
| `WECHAT_APPID` / `WECHAT_SECRET` | 小程序后台「开发管理 → 开发设置」 |
| `PUBLIC_API_ORIGIN` | 部署完拿到的默认域名，如 `https://travel-api-xxx.run.tcloudbase.com` |
| `CORS_ORIGINS` | 同上（PC 端要接的话再加前端域名） |
| `FEATURE_QA_CHAT` | `true`（用问答就填，另配 `LLM_API_KEY`） |

可选：`ICP_NO`、`PRIVACY_CONTACT`、`ADMIN_BOOTSTRAP_PASSWORD`（首次启动建管理员，**务必改**）。

---

## 5. 部署并验证

1. 点「部署」，等构建日志出现 `Application startup complete`；
2. 打开服务详情里的**默认域名**，访问：
   - `https://<默认域名>/api/v1/health` → `{"status":"ok",...}`
   - `https://<默认域名>/api/v1/pois?page_size=1` → `total: 308`
3. 若打不开：看「日志」里的报错，常见是数据库连不上（内网地址/账号错）或 `JWT_SECRET` 没填。

---

## 6. 小程序接入

1. 改 `travel-miniapp/utils/config.js` 顶部一行：

```js
const PROD_DOMAIN = 'travel-api-xxx.run.tcloudbase.com';  // 去掉 https://，不带路径
```

2. 微信公众平台 → 开发管理 → 开发设置 → **服务器域名**：
   - `request 合法域名`：`https://travel-api-xxx.run.tcloudbase.com`
   - `downloadFile 合法域名`：同上（POI 图片由后端 `/static` 提供）
3. 开发者工具「上传」→ 公众平台设为**体验版** → 手机扫码验证。

> 云托管的默认域名是腾讯的、已备案且自带证书，直接填进白名单即可，不用自己买域名。

---

## 7. 已知限制与后续优化

| 项 | 现状 | 建议 |
|---|---|---|
| 图片存储 | 打进镜像（62MB），重建后回到镜像内容 | 正式运营时把 `static/poi` 传到 COS，`CDN_DOMAIN` 指向 CDN |
| 管理端上传 | 上传到容器本地，重建即丢 | 同上，或让上传写 COS |
| PC 游客端 / 管理后台 | 还没部署（小程序不依赖） | 需要的话另开云托管静态站点或 OSS + CDN |
| 数据库备份 | 云托管 MySQL 自带备份策略 | 控制台确认保留天数 |
| 冷启动 | 最小实例 0 时首次访问有 1–3s 延迟 | 演示前先访问一次 health 预热 |

---

## 8. 与 preflight 的关系

云托管部署后，在容器里或本地跑：

```bash
python travel-api/scripts/preflight_release.py --strict
```

`APP_ENV / CORS_ORIGINS / 微信凭据 / 小程序 release 域名` 这些项会随环境变量与 `PROD_DOMAIN` 填好而转 PASS；
`ICP 备案号`、`小程序备案` 这类仍需要你在微信/通管局侧办理。
