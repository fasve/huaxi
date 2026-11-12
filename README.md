# 花溪区个性化旅游路线规划系统 - 运行说明

基于《花溪区个性化旅游路线规划系统设计方案》实现：
**FastAPI 后端 + 微信小程序 + PC 游客端 + Vue3 管理后台**，数据库为本机 MySQL 8.0.26。

## 一、系统组成与端口

| 端 | 目录 | 地址 | 技术栈 | 面向 |
|---|---|---|---|---|
| 后端 API | `travel-api/` | `localhost:8000` | Python FastAPI + SQLAlchemy | 全部前端 |
| 管理后台 | `travel-web/` | `localhost:5173` | Vue3 + Element Plus | 运营人员（**账号密码登录**） |
| **PC 游客端** | `travel-portal/` | **`localhost:5174`** | Vue3 + Vite（无 UI 库，手写样式） | 游客（PC/平板，账号登录 / 游客模式） |
| 小程序游客端 | `travel-miniapp/` | 微信开发者工具 | 原生 WXML/WXSS | 游客（手机，账号登录 / 游客模式） |

> 数据库：本机 MySQL 8.0.26，库名 `travel`，连接配置在 `travel-api/.env`。
> 四端共用同一套 `/api/v1/*` 接口，改任一前端的数据，其余端即时可见。

## 二、启动顺序（后端必须最先）

```bash
# ① 后端：8000
cd travel-api
python run.py

# ② 管理后台：5173
cd travel-web
npm run dev

# ③ PC 游客端：5174
cd travel-portal
npm run dev
```

首次运行前各执行一次：

```bash
cd travel-api  && python scripts/init_db.py   # 建库 + 80 条种子数据（只需一次）
cd travel-web  && npm install                 # 首次
cd travel-portal && npm install               # 首次
```

- 接口文档：<http://localhost:8000/docs>（Swagger UI）
- 健康检查：<http://localhost:8000/api/v1/health> → `{"status":"ok"}`
- **管理后台初始账号：`admin` / `admin123`**（后端首次启动时自动创建，密码以 PBKDF2 哈希存库）
- **游客账号**：后端启动时幂等创建 `user_account` / `user_session` 表，无需额外脚本；在 PC 端或小程序注册即可，管理端账号与之完全独立

### 后端 Python 环境（2026-11-11 重建，务必看）

虚拟环境 `travel-api/.venv` 现为 **CPython 3.11.4**（系统解释器 `C:\Python\python.exe`）。此前那套 3.13 环境已损坏：`pyvenv.cfg` 的基座指向 `.workbuddy\binaries\python\versions\3.13.12`，该基座在项目目录下无法被 venv 启动器拉起，报 `did not find executable at '...python.exe'` 并退出码 **103**。

装依赖优先用锁文件（版本精确、无需回溯）：

```powershell
cd travel-api
uv pip install -r requirements.lock.txt -i https://pypi.tuna.tsinghua.edu.cn/simple
# 没有 uv 时：
.venv\Scripts\python.exe -m pip install -r requirements.lock.txt -i https://pypi.tuna.tsinghua.edu.cn/simple
```

两条**必须遵守**的约束：

1. **`requirements*.txt` 只能写 ASCII**。pip 在 Windows 用系统编码（本机 GBK）读该文件，中文注释会直接抛
   `UnicodeDecodeError: 'gbk' codec can't decode byte ...`。原来 `python-jose` 那行的中文注释就是这么把安装搞崩的。
2. **`requirements.txt` 的 `>=` 在弱网/老 pip 上会长时间回溯**（实测 5 分钟以上无输出），所以日常重装用 `requirements.lock.txt`；
   两份文件都要能覆盖代码真实 import 的三方包（`requests` / `Pillow` / `qrcode` / `redis` 之前漏登记，已补）。

重建后可自检：

```powershell
.venv\Scripts\python.exe -c "import fastapi,uvicorn,sqlalchemy,pymysql,numpy,jose,requests,PIL,qrcode;print('ok')"
```

> 旧的 3.13 环境已改名为 `travel-api/.venv.broken` 留档，确认无碍后可直接删除。

### 在 PyCharm 里运行后端

项目已内置虚拟环境 `travel-api/.venv` 和运行配置：

1. PyCharm 打开 **`my-travel` 根目录**（不是 travel-api）
2. `File → Settings → Python Interpreter → Add Interpreter → Add Local Interpreter → Existing`
   选择 `travel-api\.venv\Scripts\python.exe`
3. 运行配置选 **`Travel API (FastAPI)`** → 绿色三角；或右键 `travel-api/run.py` → `Run 'run'`

> **2026-11-11 之后**：`.venv` 已从 3.13 重建为 **3.11.4**。PyCharm 若仍显示旧的 3.13 解释器，`Settings → Python Interpreter` 里重新选一次同一个路径即可（解释器路径没变，只是版本变了）。

> **注意**：若 8000 端口已被命令行实例占用，PyCharm 会报 `WinError 10048`。
> 先停掉命令行那个实例，再在 PyCharm 里运行；二选一即可，不要同时跑两个。
>
> 改后端代码后**必须重启**（`run.py` 默认不开热重载）。需要自动重启：
> `set RELOAD=1 && python run.py`（cmd）或 `$env:RELOAD=1; python run.py`（PowerShell）。

## 三、PC 游客端（travel-portal）

打开 <http://localhost:5174>：浏览资源、生成行程、四模式对比**无需登录**；「保存行程」和「我的行程」需要登录（也可选游客模式）。

| 页面 | 路径 | 功能 |
|---|---|---|
| 首页 | `/` | 四模式介绍与选择、系统能力说明、高分资源精选 |
| 发现花溪 | `/explore` | 四类资源浏览、关键字/评分/价格/标签筛选、详情弹窗、分页 |
| 定制行程 | `/plan` | 模式/天数(1-7)/预算/人群/偏好 → 生成行程 |
| 行程详情 | `/trip/:id` | 时间轴、每日「换一批」、槽位「更换」候选、保存、**打印为 PDF**、**导出 txt 行程单** |
| 模式对比 | `/compare` | 同一组需求一次算出四模式并排对比（花费/节奏/免费点占比/住宿/每日路线），**不落库** |
| 我的行程 | `/my` | 登录引导 / 游客体验、已保存行程列表、打开、删除 |
| **登录 / 注册** | `/login` | 账号密码登录、注册（注册后自动登录）、游客模式入口 |

### 游客登录 / 注册攻略（PC + 小程序通用）

1. **注册**：右上角「登录 / 注册」→ 切到「注册」→ 填用户名（必填）、昵称/手机号（选填）、密码 + 确认密码 → 提交后**自动登录**，头部显示昵称。
2. **登录**：切到「登录」，用**用户名或手机号 + 密码**登录；未登录点「保存行程」会自动跳到登录页，登录后回到原行程。
3. **跨端**：小程序「我的 → 登录 / 注册」用**同一个账号**登录，即可看到 PC 端保存的行程（两端共用 `travel` 库与 `user` 主体）。
4. **退出**：PC 头部「退出」/ 小程序「我的 → 退出登录」；JWT 的 `jti` 进入撤销名单**立即失效**，旧 token 再请求会返回 401。
5. **游客模式**：PC 端使用**匿名 JWT**（`typ=anonymous`，按设备稳定建档）；小程序端使用 **`wx.login` 静默登录**（`typ=wechat`，服务端 code2session 换 openid）。都不需要注册，行程不与账号绑定，换设备不会同步。
6. **小程序入口**：微信开发者工具 → 「我的」tab → 「登录 / 注册」；行程详情页未登录点保存会弹出登录引导。

| 项 | 规则 |
|---|---|
| 用户名 | 2~32 位中英文、数字、下划线，**唯一** |
| 手机号 | 选填，11 位数字，唯一，可用于登录；返回时脱敏 |
| 密码 | 6~64 位，PBKDF2-HMAC-SHA256 + 随机盐存哈希，**不存明文** |
| 登录态 | **标准 JWT（python-jose / HS256）**，默认 **7 天**（`JWT_EXPIRE_HOURS`），`Authorization: Bearer <token>`；`/auth/refresh` 滑动续期，退出登录按 `jti` 撤销 |
| 数据表 | `user_account`（登录凭据）+ `user_wechat_session`（session_key，仅服务端）+ `token_denylist`（撤销名单）；行程仍归属 `user`，表由后端启动时幂等创建 |
| 兼容性 | 存量 `us_` / `admin_session` 会话继续校验至自然过期（**不再签发**）；旧 `{id}.{hmac}` 自签串默认拒绝，可用 `ALLOW_LEGACY_HMAC_TOKEN` 临时放开 |

首页嵌入天气卡片（数据源 Open-Meteo，免密钥）；「发现花溪」与「行程详情」嵌入高德地图组件（打印时自动隐藏）。两者默认按**浏览器实时定位**展示你所在位置的天气与「我的位置」蓝点，可一键切回花溪，配置与降级链路见第九节。

打印说明：行程页点「打印 / 存为 PDF」，浏览器打印对话框里目标选「另存为 PDF」；打印样式已隐藏导航、按钮与页脚。

## 四、管理后台（travel-web）

打开 <http://localhost:5173>，用**管理员账号 + 密码**登录。左侧共 7 个模块：

| 模块 | 功能 |
|---|---|
| **数据概览** | 资源总数/上架率/行程数/用户数 KPI、资源分类与模式分布、近 7 日趋势（SVG）、预算区间分布、热门 POI Top8 |
| **资源管理** | 四类 POI 增删改查、上下架、筛选、CSV/Excel 导入、CSV 导出 |
| **行程管理** | 所有生成记录（含匿名草稿）列表、模式/状态筛选、详情时间轴、删除 |
| **标签字典** | 14 个偏好标签 CRUD、关联资源数分布、删除时自动解除关联 |
| **模式配置** | 9 维权重滑杆调整（保存自动归一化至 1.00）、硬约束展示、配置版本号 |
| **用户管理** | 游客列表（注册账号显示账号名）、openid 脱敏、行程数、启用/禁用 |
| **系统设置** | 健康检查、清缓存、**在线编辑算法硬约束**、**修改管理员密码**、跳转 API 文档与游客端 |

> 顶部右侧显示当前登录管理员，并有「游客端 ↗」快捷入口与「退出登录」。

### 账号与密码

| 项 | 说明 |
|---|---|
| 初始账号 | `admin` / `admin123`（**仅限本地演示，首次登录后请立即修改**） |
| 存储方式 | `admin_user` 表；PBKDF2-HMAC-SHA256（20 万次迭代 + 随机盐），**不存明文** |
| 登录态 | **标准 JWT（HS256，`typ=admin`）**，默认 **12 小时**（`ADMIN_SESSION_HOURS`）；与游客端 JWT 类型隔离 |
| 请求头 | 登录后所有管理端请求自动带 `Authorization: Bearer <token>` |
| 修改密码 | 管理后台「系统设置 → 账号安全」，或命令行 `python scripts/reset_admin_password.py 新密码 [用户名]` |
| 忘记密码 | 运行上面的重置脚本（同时吊销该账号全部会话），再用新密码登录 |
| 改密影响 | 改密后 JWT 里的 `pv`（口令哈希派生）失配，该账号**所有已登录 token 立即失效**，需重新登录 |
| 存量兼容 | `admin_session` 表仅保留兼容旧 token（12 小时内自然淘汰），**不再签发** |
| 初始化口径 | 后端启动时幂等建表；**仅当账号表为空**才创建默认账号，不会覆盖已改过的密码 |

> 旧版固定令牌 `X-Admin-Token` 已移除，带该请求头会被返回 401。
> 初始账号密码由 `travel-api/app/config.py` 的 `ADMIN_BOOTSTRAP_*` 提供，可在 `.env` 覆盖。

## 五、后端接口清单（新增部分）

| 接口 | 用途 |
|---|---|
| `POST /api/v1/auth/register` · `POST /auth/login` | **游客注册 / 登录**，返回 7 天 JWT（公开接口） |
| `GET /api/v1/auth/me` · `POST /auth/logout` · `POST /auth/refresh` | 当前游客身份（含 `is_guest`）/ 撤销 JWT / 滑动续期 |
| `POST /api/v1/auth/wechat/login` | **微信静默登录**：`wx.login` 的 code → 服务端 code2session → JWT（详见第十四章） |
| `POST /api/v1/auth/anonymous` | PC 匿名游客登录：按设备稳定建档，签发 `typ=anonymous` JWT |
| `POST /api/v1/admin/login` | **管理员账号密码登录**，返回 12 小时 `typ=admin` JWT（公开接口） |
| `GET /api/v1/admin/me` · `POST /admin/logout` · `POST /admin/password` | 当前账号 / 退出登录 / 修改密码 |
| `GET /api/v1/admin/stats/overview` | Dashboard 聚合统计 |
| `GET /api/v1/admin/trips` · `GET /{id}` · `DELETE /{id}` | 行程管理 |
| `GET/POST/PUT/DELETE /api/v1/admin/tags` | 标签字典 CRUD |
| `GET /api/v1/admin/users` · `PATCH /{id}/status` | 用户管理 |
| `GET /api/v1/admin/system/health` · `POST /system/cache/clear` | 系统运维 |
| `PUT /api/v1/admin/mode-configs/{mode}` | 模式配置**部分更新**（weights / hard_rules / description 可单独传） |
| `POST /api/v1/trips/compare` | 四模式对比（不落库，避免污染统计） |
| `POST /api/v1/location/resolve` | **实时位置解析**（高德）：body 带 `lng/lat` 走逆地理拿 adcode 与区县；不带坐标走 IP 城市级定位（坐标不进 URL） |
| `GET /api/v1/weather?lng=&lat=&days=15` | **实况 + 未来 15 天预报**（Open-Meteo 免密钥公开 API 代理），按 WGS-84 坐标查询；不传坐标时用花溪区中心 |
| `GET /api/v1/weather/forecast?lng=&lat=&days=15` | **仅未来 15 天逐日预报**（同上数据源），`items[]` 含日期/星期/昼夜天气/高低温/降水概率 |
| `GET /api/v1/weight-metadata` | **个性化权重元数据**：8 个权重维度、7 套偏好模板、3 种晚间偏好、各模式滑块初值 |
| `POST /api/v1/trips/preview` | **权重预览**（不落库）：按新权重重排候选点位，返回排名、分数与"与默认的差异" |
| `POST /api/v1/trips/{trip_id}/reweight` | **按权重重排既有行程**：沿用天数/预算/偏好，行程 ID 不变 |

其余 P0 接口（POI 列表/详情、行程生成、重排、替换、模式说明）保持不变。
**浏览、生成、对比不需要登录**；保存行程、我的行程、删除行程需 `Authorization: Bearer <JWT>`，账号 / 微信 / 匿名游客 / 管理端四种 JWT 由同一个 `jwt_service` 校验，类型互相隔离。

## 六、验收要点

| 指标 | 结果 |
|---|---|
| 四类资源 ≥80 条种子数据 | ✅ 80 条（景点 22 / 美食 26 / 住宿 16 / 休闲 16） |
| 四模式行程生成 | ✅ 权重打分 → 贪心装箱 → 最近邻 + 2-opt，四模式特征可辨 |
| 预算硬约束 | ✅ 四模式零预算违规（含弹性上限校验） |
| 行程调整 | ✅ 单日重排 / 槽位替换 / 候选推荐 |
| 分级松弛提示 | ✅ relax_log 返回并在小程序、PC 端、管理端展示 |
| 多端数据一致 | ✅ 管理端下架 POI → 小程序与 PC 端即时不再出现 |
| 性能 | ✅ 7 天行程生成 <10ms（指标 P95 <800ms） |
| 管理端登录 | ✅ 账号密码校验、错误密码 401、JWT `typ=admin` 隔离、退出/改密后旧 JWT 立即失效 |
| 游客注册登录 | ✅ 注册 / 手机号登录 / 重名 400 / 错误密码 401 / 退出后 JWT 撤销 / 滑动续期 |
| **G4 微信登录 + JWT** | ✅ `scripts/verify_auth_jwt.py` **76/76 通过**；真实 code2session 成功与 40029/40163/45011/-1/网络异常全覆盖；JWT 篡改/过期/iss/aud/nbf/越权全拒绝；session_key 仅存服务端；HTTP 端到端 26 项通过（详见第十四章） |
| 天气与地图组件 | ✅ 天气全程走 Open-Meteo（免密钥，实况 + 15 天同一接口）、地图走高德 JS API 2.0 底图、PC 首页/资源页/行程页接入、`npm run build` 通过 |
| 实时位置 | ✅ 逆地理（北京→110101 / 花溪→520111）、IP 定位（贵阳市 520100）、非法坐标 422、不传坐标默认花溪，联调通过 |
| 天气接口 | ✅ 一次请求返回实况 + 15 天预报共 18 项联调全通过：字段完整（天气/温度/体感/湿度/中文风向/风级/云量/is_day）、预报 15 条含降水概率、温度区间合理、不传坐标默认花溪、非法坐标 422 |
| 15 天预报 | ✅ Open-Meteo 免密钥代理，15 条逐日数据字段完整（日期/星期/昼夜天气/高低温/降水概率），16 天上限与 days 越界 422 校验通过；服务不可用时明确提示「天气服务暂不可用」，**绝不回落到虚构数据** |
| 天气 UI | ✅ 自绘 SVG 图标（7 类天气）+ 按天气切换的渐变主视觉 + 白天/夜间/降水概览块 + 15 天横向滚动日卡与相对温度条，Edge 无头截图逐轮核对无错位 |
| 坐标口径 | ✅ 天气用 WGS-84、地图用 GCJ-02，两套坐标在 `location.ts` 并存；IP 定位返回的高德坐标会反算回 WGS-84 |
| 构建 | ✅ travel-web / travel-portal 均 `npm run build` 通过 |
| 个性化权重 | ✅ 8 维滑块 + 7 套预设 + 3 种晚间偏好；权重归一化和为 1；不同权重给出不同选点排序；`is_personalized` 标记准确（未调整时等价模式默认）；按权重重排行程 ID 不变；30/30 项验证脚本通过 |
| 节奏微调 | ✅ 每日点数上限 2~6、游玩时长上限 3~12、晚间偏好三选一均生效；只改本次 rules 副本不污染模式配置；提前收工模式下晚餐仍被排入（回归项） |
| 多端一致性 | ✅ PC 游客端 `/personalize` 与小程序 `pages/personalize/personalize` 共用同一套接口与归一化口径 |

## 七、dev / prod 差异与风险提示

**当前全部为 dev 配置，不可直接上线：**

| 项 | dev（现在） | prod 必须处理 |
|---|---|---|
| 游客登录 | 账号注册登录（PBKDF2 哈希）+ **标准 JWT（7 天）**；微信 code2session 代码已就绪，本地 `MOCK_LOGIN=true` 走 dev mock；PC 用匿名 JWT | **填入真实 `WECHAT_APPID/SECRET` 并把 `MOCK_LOGIN` 改为 false**（代码默认已是 false）；增加失败限流、密码找回与操作审计 |
| 管理端鉴权 | 账号密码 + PBKDF2 哈希 + **12h `typ=admin` JWT** | 增加角色权限、登录失败限流/验证码、操作审计、管理子域与游客端隔离 |
| JWT 密钥 | 本地 `.env` 固定开发密钥 | `openssl rand -hex 32` 重新生成 `JWT_SECRET`，轮换后旧 token 全部失效 |
| 初始密码 | `admin123` 写在配置默认值里 | **必须改密**并删除默认口令；改用环境变量注入首账号 |
| CORS | dev 仍为 `allow_origins=["*"]` | **代码已就绪**：`APP_ENV=prod` 时自动收紧为 `CORS_ORIGINS` 白名单并下发 HSTS 等安全头，只需注入配置（见第十五章） |
| HTTP | 明文 `http://127.0.0.1` | **模板已就绪**：`deploy/nginx/travel.conf.example` 提供四站点 HTTPS / 80 跳转 / 反代 / `/docs` 关闭；仍须申请证书并部署 |
| 备案 / 类目 / 合法域名 / 隐私指引 / 提审 | 全部 dev / 未办理 | **流程清单与端内实现已就绪**：见 `上线合规与提审手册.md` 与 `deploy/release-checklist.json`，平台侧 18 项待企业主体办理 |
| 缓存 | 进程内 TTL 缓存 | 切 Redis（接口已抽象，改一行配置） |
| 数据库 | 本机 root 账号、密码在 `.env` | 独立最小权限账号，`.env` 不入库不入仓库 |
| 前端代理 | vite `server.proxy` | 构建 `dist/` 后由 Nginx 托管，API 走 `/api` 反代 |
| 高德密钥 | 本地 `.env` / `.env.local` 占位符，未配置自动降级 | Web服务 key 只留服务端（仅做地名解析）；地图 key 配 Referer 白名单、安全密钥走服务端代理，并接入配额监控 |
| 天气数据源 | Open-Meteo 公开 API，免密钥，服务端代理 | 国内生产建议改用和风天气等国内服务商（需申请 key，接口结构已按易替换设计），或对 Open-Meteo 出网做白名单与缓存加固；注意其数值预报与国内实况口径存在差异 |

**部署步骤（prod 概要）**：`npm run build` 产出两个 `dist/` → Nginx 分别用不同 server_name 或 location 托管 → `/api` 反代到 uvicorn/gunicorn → 后端用环境变量注入 DB 与管理员凭据 → 开启 HTTPS 与访问日志。

**已知边界**：
- PC 端已接入高德地图 JS API 2.0 合规底图（见第九节）；行程仍以时间轴为主，地图为辅助分布示意，演示坐标为近似值。
- `travel-api/.env` 含数据库密码，已加入 `.gitignore`，不要提交。
- 游客端 PC 打印样式针对 Chrome/Edge 验证；打印前建议用「打印预览」确认分页。

## 八、常见问题

| 现象 | 原因 / 处理 |
|---|---|
| `WinError 10048` 端口被占用 | 8000 已有实例（PyCharm 或命令行），停掉其中一个 |
| 启动即退出、退出码 **103**，报 `did not find executable at '<...>\python.exe'` | 虚拟环境的**基座解释器**没了：`.venv\pyvenv.cfg` 的 `home` 指向已被删除/挪走的 Python（本项目原指向 `.workbuddy` 的 3.13）。用系统 3.11 重建：删掉 `.venv` → `uv venv .venv --python C:\Python\python.exe` → `uv pip install -r requirements.lock.txt` |
| `pip install -r requirements.txt` 报 `UnicodeDecodeError: 'gbk' codec can't decode` | 该文件里有非 ASCII 字符（中文注释）。pip 用系统编码读依赖文件，改成英文注释或加 `-X utf8` |
| `pip install` 长时间无输出、CPU 打满 | `>=` 约束在弱网/老 pip 上回溯爆炸。改用 `requirements.lock.txt`（精确版本）或 `uv pip install` |
| **手机扫预览码报「网络异常，请确认后端已启动」** | 手机上 `127.0.0.1` 是手机自己。后端要以 `API_HOST=0.0.0.0` 启动（`run.py` 会打印 `手机/真机调试 → http://<内网IP>:8000/api/v1`），小程序 `utils/config.js` 的 `LAN_HOST` 要是电脑当前内网 IP，手机与电脑同一 Wi-Fi。详见下方「真机 / 预览联调」 |
| 手机连不上但电脑用内网 IP 能打开 | Windows 防火墙拦了 python 入站；或路由器开了 AP 隔离（访客 Wi-Fi 常见）；或手机开了代理/VPN |

### 真机 / 预览联调（2026-11-11）

模拟器里 `127.0.0.1` 能通，但**手机上的 `127.0.0.1` 指手机自己**，所以真机必须走电脑的局域网 IP：

1. 后端以 `API_HOST=0.0.0.0` 启动（`.env` 已配），启动日志会打印可用地址，例如
   `[travel-api] 手机/真机调试 → http://192.168.31.116:8000/api/v1`。
2. 小程序 `utils/config.js` 里把 `LAN_HOST` 改成同一个 IP（模拟器会自动用 `127.0.0.1`，真机自动用 `LAN_HOST`，无需手动切换）。
3. 手机与电脑连**同一 Wi-Fi**；从手机浏览器先访问 `http://<内网IP>:8000/api/v1/health`，能出 `{"status":"ok"}` 再扫码。
4. 重新点「预览」生成新二维码（旧码 25 分钟就过期）。手机上打开后：右上角 `···` → **开发调试** → **打开调试**（否则 http + IP 会被域名校验拦掉），退出重进。
5. 仍不行就改用「**真机调试**」，它走开发者工具的代理，不受局域网与域名限制。

> `run.py` 曾在 `host` 上写过反向判断（`API_HOST=0.0.0.0` 时强制 `127.0.0.1`），导致只监听本机、手机必然连不上，已于 2026-11-11 修正。
> 内网 IP 变了（DHCP 重新分配）只需改 `LAN_HOST` 一行；`wx.request` 失败提示现在会带上实际请求地址，方便一眼定位。
| 前端「无法连接后端服务」 | 后端未启动；或改了后端代码没重启 |
| 注册提示「该用户名已被注册」 | 用户名唯一，换一个即可；已有账号请切到「登录」 |
| 保存行程跳到登录页 | 设计如此：保存 / 我的行程需登录，登录后自动回到原行程；也可选游客模式 |
| 退出登录后行程「不见了」 | 行程仍在库中，用同一账号重新登录即可；游客模式的行程属于 mock 身份，换账号看不到 |
| 小程序看不到 PC 端行程 | 两端需用同一个注册账号登录（游客模式不跨端同步） |
| 登录提示「账号或密码错误」 | 管理员核对 `admin` / 初始密码；游客核对注册时的用户名或手机号 |
| 登录后又跳回登录页 / 接口 401 | 会话过期（12h）、在别处改过密码，或后端重启后旧 token 失效 → 重新登录 |
| 忘记管理员密码 | `cd travel-api && python scripts/reset_admin_password.py 新密码` |
| 管理端请求返回 401 | 只支持 `Authorization: Bearer <token>`；旧版 `X-Admin-Token` 已作废 |
| `127.0.0.1:5173` 访问 502 | 本机 HTTP 代理干扰；**用 `localhost:5173`**（vite 监听 IPv6 `[::1]`） |
| 小程序请求失败 | 开发者工具需勾选「详情 → 本地设置 → 不校验合法域名」；`utils/api.js` 的 `BASE` 需指向后端地址 |
| 模式配置保存报「权重和必须为 1.0」 | 前端已自动归一化；若手动调 API，需保证 9 维静态权重和 = 1.0 |
| 想恢复初始数据 | 重跑 `python scripts/init_db.py`（**会清空已有行程**；管理员账号表也会重建为默认口令） |
| 换一批结果相同 | 重排用随机种子；需复现某次行程请记录请求中的 `seed` |

## 九、天气与地图（Open-Meteo 天气 + 腾讯地图底图 / 高德仅服务端地名解析）

> **2026-11 迁移说明**：PC 端底图与路线规划已从高德换成**腾讯位置服务**——
> `src/components/TMap.vue`（腾讯 GL JS API）+ `src/components/qqmap.ts`（加载器与 `direction/v1` JSONP 路线）。
> 配置见 `travel-portal/.env.example`：`VITE_QQMAP_JS_KEY`（底图）、`VITE_QQMAP_WS_KEY`（路线，可不填复用前者）。
> 老组件 `src/components/AmapMap.vue` 已不再被引用，保留仅作参考。
> 服务端 `/location/resolve` 仍走高德 Web 服务 key（只做坐标↔地名，key 不下发前端）；小程序 `<map>` 本身就是腾讯引擎。
> 下文凡是「高德底图 / AmapMap」的表述，底图部分以本条为准。


PC 游客端新增两个可复用组件 + 一个全局定位模块。**天气数据全部来自 Open-Meteo**（免密钥公开 API），**高德只负责地名解析与地图底图**，两者都按用户实时位置展示，不写死花溪区：

| 组件 | 文件 | 出现位置 | 数据来源 |
|---|---|---|---|
| `useLocation` | `travel-portal/src/location.ts` | 全局单例，被天气卡片与地图共享 | 浏览器 `geolocation` → 服务端逆地理 / IP 定位 → 花溪默认 |
| `WeatherIcon` | `travel-portal/src/components/WeatherIcon.vue` | 天气卡片 | 内联 SVG 自绘（晴/多云/阴/雨/雷/雪/雾），按天气文案自动分类，夜间晴天显示月亮 |
| `WeatherCard` | `travel-portal/src/components/WeatherCard.vue` | 首页「出行前，先看实时天气」、行程详情页紧凑天气条 | `GET /api/v1/weather?lng=&lat=`（Open-Meteo，一次请求返回**实况 + 15 天预报**） |
| `AmapMap` | `travel-portal/src/components/AmapMap.vue` | 发现花溪（当前页资源分布）、行程详情（按天连线） | 高德地图 JS API 2.0 官方底图 + 蓝色「我的位置」圆点 |

### 天气卡片设计

- **渐变主视觉**：顶部按天气类型自动切换渐变（晴=暖橙、阴=灰蓝、雨=深蓝、雷=紫、雪=青蓝、雾=灰），带装饰圆与毛玻璃质感；
- **左中右三段式**：大号温度 + 天气描述 + 实况图标（自绘 SVG），右侧「白天 / 夜间 / 降水概率」概览块，底部湿度、风力、云量、距花溪距离胶囊；
- **15 天横向滚动日卡**：每列含周几/日期、天气图标、天气文案、降水概率徽标、最高/最低温，以及一条**在 15 天整体温区内的相对高度温度条**（一眼看出哪天最热）；鼠标滚轮可横向滑动；
- **行程页紧凑模式**：只展示前 6 天，卡片更矮，避免行程页过长。

### 数据源分工

| 数据 | 来源 | 是否需要 key |
|---|---|---|
| 实时实况（温度、体感、湿度、风、云量、降水） | **Open-Meteo** `current` 接口 | ❌ 免密钥 |
| 未来 15 天逐日预报（最高/最低温、白天/夜间天气、降水概率） | **Open-Meteo** `daily` + `hourly` 接口 | ❌ 免密钥 |
| 定位 / 逆地理 / IP 定位（把坐标翻译成区县地名） | 高德 Web 服务 API | ✅ 需要 Web服务 key |
| 地图底图与点位渲染 | 高德地图 JS API 2.0 | ✅ 需要 Web端 (JS API) key |

> **为什么天气不用高德**：高德天气 API 只提供「今天 + 3 天」共 4 天，且需要单独申请 Web 服务 key；Open-Meteo 一次请求即可同时给出实况与 16 天逐日数据，无需注册与密钥，因此作为**唯一的天气数据源**。服务端代理 + 30 分钟缓存，前端不直接访问外部服务；接口不可用时界面明确提示「天气服务暂不可用」，**不会用虚构数据填补**。
>
> **坐标系差异（重要）**：Open-Meteo 使用 **WGS-84**，高德使用 **GCJ-02**。因此 `location.ts` 同时保存两套坐标——`wgsLng/wgsLat`（天气查询用）与 `lng/lat`（地图与逆地理用），IP 定位返回的高德坐标会反算回 WGS-84。

### 配置攻略（密钥不写入代码与仓库）

**天气不需要任何 key**，只要本机能访问 `api.open-meteo.com` 即可。代码和示例文件里只保留显式占位符 `请在高德开放平台申请自己的 key 并替换此占位符`，请把自行申请的 key 填入本地配置文件（均已 gitignore）。

1. 打开高德开放平台 <https://console.amap.com/dev/key/app> → 创建应用 → 添加 Key。
   - **Web服务 Key**：用于服务端逆地理编码与 IP 定位（只影响地名解析，不影响天气）。
   - **地图 Key**：服务平台选「**Web端 (JS API)**」；2021-12-02 之后创建的 Key 会同时生成**安全密钥 securityJsCode**，两个都要用。
2. 在 Key 设置中配置 **Referer 域名白名单**（本地调试填 `localhost` / `127.0.0.1`，上线填备案域名），避免 key 被他人盗用。
3. 填 Web服务 key：编辑 `travel-api/.env` → 把 `AMAP_KEY=` 的占位符替换为 Web服务 key → **重启后端**。`AMAP_CITY_ADCODE=520111` 是定位失败时的默认区县（花溪区）。
4. 填地图 key：编辑 `travel-portal/.env.local`（没有就从 `.env.example` 复制）→ 替换 `VITE_AMAP_JS_KEY` 与 `VITE_AMAP_SECURITY_CODE` 两个占位符 → **重启 `npm run dev`**（Vite 的 env 在启动时注入，改动后必须重启）。
5. 刷新首页 / 发现花溪 / 行程详情页，即可看到实时实况、未来 15 天预报与地图点位。

> 未配置或填错时不会白屏：天气卡片显示「天气服务暂不可用」+ 原因提示，地图卡片显示「地图尚未启用」；其余功能不受影响。

### 实时位置（默认行为）

| 层级 | 行为 |
|---|---|
| ① 浏览器精定位 | 页面首次用到天气/地图时请求浏览器定位授权（`localhost` / HTTPS 下可用），拿到 **WGS-84** 坐标，同时保留 GCJ-02 副本；经 `POST /api/v1/location/resolve` 逆地理得到所在区县 `adcode`；授权后以 `watchPosition` 持续跟随，位移超过 100m 才更新 |
| ② IP 城市级定位 | 用户拒绝授权、浏览器不支持或超时（8s）时，由服务端调用高德 IP 定位拿到城市级坐标与 adcode（GCJ-02，反算成 WGS-84 用于天气），界面标注「IP 城市级定位」 |
| ③ 花溪区默认 | 前两级都失败时回到花溪区（adcode 520111），保证天气与地图仍可用 |

- **天气按实时位置查**：`GET /api/v1/weather?lng=<WGS-84 经度>&lat=<WGS-84 纬度>&days=15`，一次返回 `live`（实况）与 `casts`（15 天逐日预报）；不传坐标时默认花溪区中心。人在外地时首页会提示「距花溪约 X km」。
- **只取预报**：`GET /api/v1/weather/forecast?lng=&lat=&days=15` 返回 `items[]`，含日期、星期、白天/夜间天气、最高/最低温、降水概率。
- **地图显示我的位置**：蓝色圆点 + 精度圈，点击可看地名与距花溪距离；「看景点」= 适配景点视野，「定位到我」= 跳到我的位置；用户距花溪 60km 内时两者会一起纳入初始视野。
- **随时切换**：天气卡片与地图卡片都有「重新定位」「切回花溪」，切回后停止定位跟随；刷新页面后本机会话内复用上次位置（30 分钟有效）。
- **隐私**：精确坐标只存在当前浏览器的 `sessionStorage`，坐标放在 POST 请求体里（不出现在 URL / 访问日志），后端只做一次逆地理后即丢弃，不写数据库、不关联账号、不记录详细门牌地址。

### 安全与合规

| 项 | 说明 |
|---|---|
| 天气服务 | Open-Meteo 免密钥公开 API，服务端代理 + 30 分钟 TTL 缓存；前端拿不到外部地址与调用细节 |
| 底图来源 | 仅高德地图 JS API 2.0 官方底图，未叠加任何第三方或境外瓦片；地图自带版权与审图号信息不可隐藏 |
| 地图 key | JS API 规范要求前端加载脚本，因此会出现在页面中，**必须配 Referer 白名单**；`npm run build` 会把环境变量内联进 `dist/assets/*.js`，`dist/` 已 gitignore，但**不要把带 key 的构建产物公开分发**；生产环境建议按高德官方文档由 Nginx/服务端代理转发安全密钥（`_AMapSecurityConfig.serviceHost`），避免明文暴露 |
| Web服务 key | 只在 `travel-api` 服务端使用（`.env` 已被 gitignore），仅用于逆地理 / IP 定位 |
| 坐标系 | 天气用 **WGS-84**，地图与逆地理用 **GCJ-02**，两套坐标在 `location.ts` 内并存并按用途取用；当前 80 条演示资源坐标为花溪区近似值，仅作分布示意，接入真实业务数据须统一到 GCJ-02 |
| 数据范围 | 只展示系统自有 POI 与用户自己的行程，不采集、不存储、不公开他人位置数据；个人坐标仅留在本机会话 |
| 接口 | `POST /api/v1/location/resolve`（有坐标→逆地理，无坐标→IP 定位，坐标在 body）、`GET /api/v1/weather?lng=&lat=&days=15`（实况 + 15 天预报）、`GET /api/v1/weather/forecast?lng=&lat=&days=15`（仅预报）；`configured=false` / `available=false` / `error` 时组件降级展示 |
| 缓存 | 逆地理按 4 位小数网格、天气按 0.01° 网格、15 天预报按 0.01° 网格、IP 定位按进程，均 30 分钟 TTL，减少外部调用消耗 |

### 相关排查

| 现象 | 处理 |
|---|---|
| 天气卡片显示「天气服务暂不可用」 | Open-Meteo 不可达：检查后端出网（`curl https://api.open-meteo.com/v1/forecast?latitude=26.4&longitude=106.6&current=temperature_2m`），或接口参数变动 |
| 天气位置偏差几百米 | 正常：Open-Meteo 用 WGS-84，若误传 GCJ-02 坐标会偏移约 500 米；确认前端传的是 `wgsLng/wgsLat` |
| 地图显示「加载失败」/ 白屏 | 检查能否访问 `webapi.amap.com`、key 是否为「Web端 (JS API)」、Referer 白名单是否含 `localhost` |
| 地图报 `INVALID_USER_SCODE` | 2021-12-02 后申请的 key 必须同时配置 `VITE_AMAP_SECURITY_CODE`（安全密钥） |
| 位置只显示「贵阳市」没有区县级 | 浏览器拒绝定位授权，退化为 IP 城市级定位；在地址栏站点权限里允许「位置」后点「重新定位」 |
| 点位明显偏移 | 种子坐标为近似值 / 未转换坐标系；接入真实数据时统一为 GCJ-02 |

| 15 天预报条显示「暂无预报数据」 | 后端未启动或 `/api/v1/weather` 返回 `error`，可先直接访问该接口看返回的 `error` 字段 |
| 一直显示「IP 城市级定位」 | 浏览器定位被拒绝或系统定位服务不可用；在浏览器地址栏左侧站点权限里把「位置」改为允许，再点「重新定位」。必须用 `localhost` 访问（安全上下文），不要用 `127.0.0.1` |
| 蓝点没出现在地图里 | 确认已给浏览器定位授权、地图 key 已配置；点「定位到我」可手动把地图中心移到当前位置 |
| 想看花溪当地天气 / 视野 | 点「切回花溪」，会停止跟随并按花溪区坐标重新查询天气与视野 |

## 十、图片资源系统（多源合规抓图 + 管理端上传）

> **2026-11-11 图片口径（两次调整后的最终版）**
> 1. **停用**：Wikimedia / Openverse / Pixabay / Pexels 等联网抓图、外部直链本地化、自动生成占位图；
> 2. **允许两类来源**：`upload`（管理员在管理端本地上传，含批量采集脚本走同一接口）、
>    `legacy_local`（`static/poi/` 里的历史存量文件，经认领脚本挂回原 POI，**授权未核实**）；
> 3. 落地：`app/services/image_policy.py` 在序列化层统一过滤，`poi.images` 与 `poi.image_meta`
>    只有上面两类来源会返回给游客端（行程/游学线路同样生效）；管理端抓图/直链/补图接口一律 **410**。
>
> 存量认领：`scripts/adopt_local_legacy_images.py` 把库里仍指向磁盘现存文件的图恢复为
> `legacy_local`，并如实写入「来源未记录，商用前需替换为已授权素材」。当前结果：
> **177 张图 / 63 个 POI 达到 ≥2 张**；10 个 POI 无图（8 个游学点 + 2 家酒店，后者原本只有占位 SVG，已丢弃）。
> 体检：`python scripts/check_poi_images.py --expect 2 --strict`。
>
> 新增图片请走管理端上传，或 `scripts/collect_poi_images.py`（需要 PEXELS_API_KEY / UNSPLASH_ACCESS_KEY，
> 免费商用授权，逐张记录作者与协议）。

### 10.1 数据现状

全库 **80 条资源（景点 22 / 美食 26 / 住宿 16 / 休闲 16）已 100% 配图**：

| 项 | 数量 |
|---|---|
| 已配图资源 | 80 / 80 |
| 本地图片文件总数 | 190 张（`travel-api/static/poi/`） |
| 平均每条资源图片数 | 2.4 张，首张为封面 |
| 已登记授权元信息 | 80 / 80（`poi.image_meta`） |

### 10.2 图片源：合规优先的 Provider 链

图片抓取抽象为可插拔的 `ImageProvider`，按**合规性从高到低自动降级**：

| 优先级 | Provider | 授权 | 需要 key | 说明 |
|---|---|---|---|---|
| 1 | **Wikimedia Commons** | CC / 公有领域 | 否 | 维基共享资源官方 API |
| 2 | **Openverse** | CC / 公有领域 | 否 | 开放许可图片聚合 API |
| 3 | **Pixabay** | Pixabay License（可商用） | 是 | 官方 API，免费 key |
| 4 | **Pexels** | Pexels License（可商用） | 是 | 官方 API，免费 key |
| 5 | 本地占位图 | 本地生成 | 否 | 前 4 个都不可用时的兜底，保证不出现裂图 |
| — | ~~Web 图片搜索~~ | 未知 | 否 | **默认关闭**，见 10.3 |

每个 Provider 返回统一的 `ImageAsset`，携带 `source / author / license / license_url`，
落库到 `poi.image_meta`（与 `images` 同序对应）——**每一张对外展示的图都能追溯到来源与授权**。

### 10.3 robots 协议合规（本系统硬约束）

抓取前一律经过 `app/services/robots.py` 的 `RobotsGate` 判定，命中 Disallow 直接拒绝、不发请求。

**UA 诚实声明**：不再伪装成 Chrome 浏览器，改用
`TravelPortalBot/1.0 (+http://localhost:8000; contact=<邮箱>)`。
站点方能识别并直接联系，也拿得到应有的速率豁免。

**判定分两档**（按图片使用权来源区分）：

| 档位 | 适用场景 | robots 不可读（403/超时）时 |
|---|---|---|
| 严格档 | 搜索结果页、管理员手动指定的直链 | **禁止** |
| 宽松档 | 官方图库 CDN 直链（授权协议已覆盖） | 放行（robots 无有效约束） |

**为什么 Web 搜索兜底默认关闭**：核查目标站 robots.txt 后确认，
`cn.bing.com` 明确 `Disallow: /images/search?` —— 抓取搜索结果页属于不被允许的机器抓取。
该 Provider 即使被显式开启（`IMAGE_ALLOW_WEB_SEARCH=true`），
**也会先做 robots 判定**，命中禁止即返回空，不会绕过协议。

> 注：robots 判定必须基于**带 query 的实际请求 URL**。
> Bing 的规则是 `Disallow: /images/search?`，不带 query 的 `/images/search` 不匹配该规则，
> 但真实请求一定带 `?q=...` —— 用无 query 的 URL 判定会误判为「允许」。

### 10.4 管理端功能

**系统设置 → 图片来源与授权**：展示各源的可用性、授权类型与不可用原因；
可在此直接填写 Pixabay / Pexels 的 API Key（写入服务端 `.env`，**不下发浏览器**，只回传掩码尾号）。

**资源管理 → 新增 / 编辑资源** 弹窗的图片区块：

| 能力 | 操作 | 说明 |
|---|---|---|
| **联网抓取实景图** | 点按钮 | 按「名称 + 地域 + 类别」检索，自动降级到可用源 |
| **上传本地图片** | 选文件 | jpg/jpeg/png/webp/gif/bmp/svg，≤8MB |
| **添加图片直链** | 粘贴 URL | 后端下载并本地化；**严格档 robots 校验**，被禁则明确报错 |
| **设为封面 / 前移 / 后移 / 删除** | 悬停缩略图 | 首张即封面；`images` 与 `image_meta` 同步移动 |
| **来源角标 + 悬停详情** | 悬停角标 | 显示来源 / 作者 / 授权 |

### 10.5 前端展示位置

| 端 | 位置 | 表现 |
|---|---|---|
| PC 游客端 | 首页「花溪精选」 | 16:9 封面图 + 悬停放大 |
| PC 游客端 | 发现花溪列表 | 封面图 + 类别角标 + 悬停缩放 |
| PC 游客端 | 资源详情弹层 | 多图画廊网格 |
| PC 游客端 | 行程时间轴 | 每个行程点右侧 72×54 缩略图 |
| PC 游客端 | 槽位替换候选 | 每个候选左侧缩略图 |
| 管理端 | 资源管理表格 / 编辑弹窗 | 缩略图 + 图片数量 + 来源角标 |
| 管理端 | 系统设置 | 图片源可用性表 + API Key 配置 |
| 微信小程序 | 首页「花溪精选」 | 120×90 缩略图（无图时显示名称首字渐变块） |

### 10.6 相关接口

| 接口 | 用途 |
|---|---|
| `GET /static/poi/{file}` | 静态图片访问（`app/main.py` 挂载 `/static`） |
| `POST /api/v1/admin/pois/images/upload` | 上传本地图片，返回地址 + 授权元信息 |
| `GET /api/v1/admin/pois/images/fetch?name=&sub_type=&category=&count=` | 联网抓图（自动降级到可用源） |
| `POST /api/v1/admin/pois/images/localize?url=` | 外部直链本地化（严格档 robots 校验） |
| `POST /api/v1/admin/pois/{id}/images/fetch?count=` | 对已存在资源联网补图 |
| `GET /api/v1/admin/pois/images/providers` | 各源可用性、授权类型、API Key 配置状态 |
| `POST /api/v1/admin/pois/images/keys` | 配置 API Key（写入 `.env`，不回传明文） |
| `GET /api/v1/admin/system/health` | `images` 段：已配图数 / 授权登记数 / 文件数 / 各源状态 |

### 10.7 脚本

```bash
cd travel-api
.venv/Scripts/python.exe scripts/fetch_images.py                # 只补没有图的资源
.venv/Scripts/python.exe scripts/fetch_images.py --force        # 全部重抓（换图）
.venv/Scripts/python.exe scripts/fetch_images.py --only 1,2,7   # 只抓指定 id
.venv/Scripts/python.exe scripts/fetch_images.py --count 5      # 每条存 5 张
.venv/Scripts/python.exe scripts/backfill_image_meta.py        # 回填存量图片的授权元信息
.venv/Scripts/python.exe scripts/migrate_image_meta.py         # 幂等迁移：poi.image_meta 列
```

### 10.8 部署注意

- **启用合规图片源**：在管理端「系统设置 → 图片来源与授权」填入 Pixabay 或 Pexels 的免费 key
  （[Pixabay](https://pixabay.com/api/docs/) / [Pexels](https://www.pexels.com/api/)），即时生效、无需重启。
  若部署环境可直连外网，Wikimedia 与 Openverse 无需 key 即可用。
- `travel-api/static/poi/` 是运行时资源目录，已加入 `.gitignore`；
  换机器部署时需重跑 `scripts/fetch_images.py`，或直接拷整个 `static/` 目录。
- 生产环境建议改为对象存储（OSS/COS）+ CDN，避免把图片放在应用进程内。
- 存量图片的授权状态标记为「历史抓取 · 未知授权」，**商用前请用合规图库重抓替换**。
- 游客端与管理端 dev server 已配置 `/static` 代理到 8000 端口；生产构建走同源相对路径。

---

## 十一、个性化权重（按权重调整路线）

### 11.1 功能定位

在四种模式之上增加一层**用户可控的个性化**：模式决定"默认口味"（硬约束 + 默认权重），
个性化让用户直接拖动 8 个评分维度的滑块，决定"我更在乎什么"，并可微调节奏。
调整只改变**选点优先级**，预算硬约束、时间窗、槽位不重复等规则始终生效。

- **PC 游客端**：`/personalize`（导航栏「个性化」）
- **小程序**：`pages/personalize/personalize`（需求页与行程页均有入口）
- 入口互通：`/plan`（基础定制）→ `/personalize`；行程详情页「按权重调整路线 →」→ `/personalize?trip=xxx`

### 11.2 8 个权重维度

| 维度 | key | 含义 | 拉高后的效果 |
|---|---|---|---|
| 品质口碑 | `quality` | 评分、点评与体验质量 | 只挑评价好的地方，行程更稳 |
| 人气热度 | `popularity` | 网络热度与话题性 | 玩法热门热闹，避开冷门 |
| 地标打卡 | `landmark` | 必去地标与出片点位 | 青岩古镇这类地标优先入程 |
| 性价比 | `cost_efficiency` | 单位花费换来的满意度 | 优先免费、高性价比点位 |
| 预算贴合 | `budget_fit` | 花费与剩余预算的匹配度 | 更贴着每日预算花 |
| 时间效率 | `time_density` | 单位时间获得的体验密度 | 少排长线景点，多排短平快 |
| 舒适休憩 | `rest_comfort` | 可坐可歇、室内、温泉类体验 | 偏泡汤、亲水公园、慢节奏 |
| 本地风土 | `local_flavor` | 老字号、黔菜、非遗与在地体验 | 更偏在地美食与民俗 |

维度定义与 `trip_mode_config.weights` 的键完全一致，因此引擎 `scoring.score_poi` 无需改动即可生效。

### 11.3 权重归一化口径

1. 前端滑块给出 **0~100 的关注度**（8 维各自独立）；
2. 后端 `normalize_weights()` 过滤非法键与负值，按总和归一化为**和为 1** 的权重向量；
3. 全 0 / 未传 / 仅传部分维度 → 回落到该模式的默认权重（**完全等价于未个性化**）；
4. `is_custom()` 比对归一化结果与模式默认，偏差 > 0.005 才标记 `is_personalized=true`；
5. 画像百分比用**最大余数法**分配，保证合计精确为 100。

### 11.4 节奏微调

除权重外可调三项，同样只改本次生成的 `hard_rules` 副本，不污染数据库里的模式配置：

| 项 | 范围 | 作用 |
|---|---|---|
| `daily_poi_max` | 2~6 个 | 每日游玩点数量上限 |
| `play_hours_max` | 3~12 小时 | 每日游玩时长上限 |
| `evening` | `relax` / `night_scene` / `fine_dining` | 晚间偏好：早点休息(21:30 收工) / 夜游打卡(夜市灯光, 21:30) / 观景晚宴(晚餐 18:30 起, 90 分钟) |

晚间偏好通过 `evening_slot` 驱动引擎的晚间策略分支（`none` / `rest` / `dine_night` / `landmark_night`）。
为保证下午景点不挤占晚餐窗口，引擎引入**绝对时钟 + 槽位截止时刻**（上午止于午餐窗口、下午止于晚餐窗口、晚间止于收工时刻）。

### 11.5 偏好模板（预设）

7 套一键模板：均衡默认 / 省钱优先 / 品质优先 / 打卡刷屏 / 深度在地 / 亲子悠闲 / 效率拉满。

### 11.6 新增接口

| 接口 | 用途 |
|---|---|
| `GET /api/v1/weight-metadata` | 权重维度、预设模板、晚间偏好、各模式滑块初值（前端滑块由该接口驱动） |
| `POST /api/v1/trips/preview` | **权重预览**（不落库）：按新权重重排候选点位，返回排名、分数与"与默认的差异" |
| `POST /api/v1/trips/{trip_id}/reweight` | **按权重重排既有行程**：沿用天数/预算/偏好，行程 ID 不变（历史链接不失效） |

行程生成接口 `POST /api/v1/trips/generate` 新增两个可选字段：

```json
{
  "days": 2, "budget": 1500, "mode": "checkin",
  "weights": { "quality": 12, "popularity": 32, "landmark": 34, "cost_efficiency": 6,
               "budget_fit": 6, "time_density": 8, "rest_comfort": 1, "local_flavor": 1 },
  "pace": { "daily_poi_max": 4, "play_hours_max": 9, "evening": "night_scene" }
}
```

行程响应新增 `custom_weights` / `weight_profile` / `is_personalized` / `pace_config` 四个字段。

### 11.7 数据持久化

`trip` 表新增两列（幂等迁移脚本）：

```bash
cd travel-api
.venv/Scripts/python.exe scripts/migrate_trip_personalization.py
```

| 列 | 类型 | 含义 |
|---|---|---|
| `custom_weights` | JSON | 本次行程实际使用的权重向量（0~1，和为 1）；空 = 沿用模式默认 |
| `pace_config` | JSON | 节奏微调（点数上限 / 游玩小时 / 晚间偏好） |

行程的"换一批"重排（`/rebalance`）会继续沿用其权重与节奏，保证口径一致。

### 11.8 验证脚本

```bash
cd travel-api
.venv/Scripts/python.exe scripts/verify_personalization.py   # 30 项检查
.venv/Scripts/python.exe scripts/smoke_test.py               # 四模式回归
```

覆盖：归一化口径（和为 1 / 非法键 / 全 0 回落 / 空输入等价默认）、节奏改写不污染原 rules、
晚间偏好映射、预览接口、生成与重排的持久化、不同权重给出不同选点排序、
提前收工模式下晚餐仍被排入（回归项）、三种晚间偏好均能生成完整日程。

---

## 十二、路线规划（精确到出行方式）

参考高德地图导航，把「点位直线连线」升级为「真实道路路线 + 分步转向提示」。

### 12.1 出行方式

地图卡片顶部新增方式切换：**🚗 驾车 / 🚌 公交 / 🚶 步行 / 🚲 骑行**。切换即时按该方式重新规划全部路段；
结果按 `mode:起点:终点` 缓存，重复切换不重复请求。

### 12.2 实现要点

- 客户端调用高德 JS API 2.0 路径规划插件（`AMap.Driving` / `Transfer` / `Walking` / `Riding`，
  见 `src/components/amap.ts` 的 `loadRoutePlugins()`）。
- 每天点位按行程顺序串联（**酒店作为当天出发点**），相邻点位之间计算一段路线；
  真实道路路径**按天着色**绘制，路段中点标注「距离 · 耗时」小标签。
- 公交模式解析 `Transfer` 的 `plans[0].segments`：步行段给出转向提示，乘车段给出线路名与上下车站。
- 底部「路线详情」面板按天分组列出每段（出发 → 到达、距离 · 耗时、公交费用），可展开查看分步转向 / 换乘提示。
- 行程时间轴每段之间插入交通提示（如「🚗 2.6km · 12分」），让文字行程也「精确到出行方式」。

### 12.3 健壮性

- 高德不可达（配额 / 网络 / 无结果）时**自动降级**：用球面距离 + 各方式平均速度估算，并标注「估算」，绝不白屏或报错。
- 切换出行方式、换一批重排、重新定制后，地图与时间轴交通提示随行程数据自动刷新。

### 12.4 涉及改动

- `src/components/amap.ts`：新增 `TravelMode` / `TRAVEL_MODES` / `RouteStep` / `RouteLeg` / `RouteLegSummary` 类型与 `loadRoutePlugins()`。
- `src/components/AmapMap.vue`：新增 `route` / `travelMode` props 与 `routes` 事件；路线规划、绘制、详情面板、方式切换、降级兜底。
- `src/views/Trip.vue`：地图改用 `route` 模式（含酒店为出发点），接收 `@routes` 在每日时间轴插入交通提示；`api.ts` 的 `Trip.hotel` 补充经纬度字段。

---

## 十三、预设主题路线 · 贵州大学校园游学线（G7 / T9 / A7）

对应设计方案 5.8、11.4、接口 #14 / #15、里程碑 M4。**不是另写一套行程引擎**，而是把专家编排好的站点序列当高权重保底项注入现有四阶段流水线，复用全部约束校验与展示逻辑。

### 13.1 页面与入口

| 端 | 位置 | 能力 |
|---|---|---|
| PC 游客端 | `/study`（导航「游学路线」）；首页新增游学 banner | 日期选择、逐站讲解、研学任务卡、拍照提示、入校预约、date_gate 结论、四模式适配口径、信息来源与待核字段、**一键成程** |
| PC 行程详情 | `/trip/:id` | 游学行程横幅 + 时间轴内嵌逐站讲解/任务卡；保底站锁定，不提供「更换」 |
| 微信小程序 | `pages/study/study`（首页入口） | 同上（日期 picker、加段开关、模式/天数/预算、一键成程） |
| 管理后台 | `/preset-routes`（左侧「预设路线」） | A7：站点编排查看、日期闸门预览、季节性启停、政策周更校验登记、待核来源高亮 |

### 13.2 数据模型

新增两张表 + `trip` 两列，**服务启动时幂等自动建表/补列**（`app/main.py` lifespan → `ensure_preset_routes()`），无需手动迁移；也可手动执行 `scripts/seed_preset_routes.py [--force]`。

| 表/列 | 关键字段 |
|---|---|
| `preset_route` | code、title、theme、target_group、duration_hours、season_window、enabled、version、summary、reservation_note、transit_note、mode_tips、sources、policy_checked_at |
| `preset_route_stop` | route_id、seq、poi_id、stay_min、walk_in_min、narration_title/text、task_card、photo_tip、must_visit、date_gate(JSON)、fallback_poi_id、degrade_text、degrade_stay_min、slot、is_addon |
| `trip.preset_route_code` / `trip.visit_date` | 标识本次行程注入的线路与出行日期 |
| `poi.category=study` | 8 个游学点 + `poi_ext_study` 扩展（org / reservation_channel / visit_policy / season_window / study_theme） |

> **设计取舍**：方案 3.2 写「study 装箱时按 scenic 入池」，实现中改为**不进普通候选池，仅作为预设路线的保底站注入**。否则校园站点会污染四模式的自由选点结果；游学点在装箱时仍映射为 `scenic` 类别以复用打分与预算逻辑。

### 13.3 date_gate 日期感知闸门（核心）

`app/planner/preset_routes.py` 为纯函数层（不依赖 DB / Web 框架，可离线单测）。四类闸门在**生成时自动处理而非报错**：

| 类型 | 判定 | 不满足时 |
|---|---|---|
| `weekday_only` | 非周末 + 非法定节假日 + 非寒暑假（1/2/7/8 月） | 校史馆降级为馆外展板讲解，停留 60→20 分钟，讲解文案替换，relax_log 提示 |
| `season_window` | 樱花 03-15 ~ 04-05（支持跨年窗口） | 替换为「贤正湖畔常绿绿道」，任务卡改为常绿树种辨识 |
| `reservation_required` | 恒命中 | 不阻断行程，强制追加「出行前完成 iGZU 访客预约」任务卡与预约渠道 |
| `open_hours` | 恒通过 | 给出建议到站时刻（如校史馆 08:30） |

节假日口径只内置**公历固定节日**（元旦 / 劳动节 / 国庆核心假日）+ 周末 + 寒暑假近似；春节、清明、端午、中秋按农历逐年变动，**不硬编码**，由 A7 后台按当年国务院通知维护 `EXTRA_HOLIDAYS`。这是刻意的诚实口径，避免用编造日期误判。

### 13.4 接口

| 方法 + 路径 | 用途 |
|---|---|
| `GET /api/v1/preset-routes?theme=&target_group=&visit_date=` | 线路列表 + 日期概览（工作日/周末/花期/室内场馆可用性） |
| `GET /api/v1/preset-routes/{code}?visit_date=&include_addon=` | 逐站讲解、任务卡、date_gate 结论、线路级预约与降级汇总（**纯展示，零算法开销**） |
| `POST /api/v1/trips/generate` | 新增 `preset_route_code` / `visit_date` / `include_addon` 三个可选入参 → 半天游学 + 半天按 mode 自由补全 |
| `GET /api/v1/admin/preset-routes` · `GET /{code}` · `PATCH /{code}` | A7 管理端（需管理员 Bearer token） |

响应新增 `preset_route`（线路详情）、`visit_date` 与每个 `TripItem.preset`（逐站讲解/任务卡/gate 结论）。线路详情同时存入 `trip.pace_config.preset_route`，因此**重新打开行程、按权重重排、单日换一批**都能恢复游学动线，不会静默丢失。

### 13.5 注入与拼接机制

1. `resolve_for_generation()` 按 date_gate 解析出有效站点 → `InjectedStop`（含映射为 scenic 的 `PlannerPoi`）。
2. `generate_trip(..., preset_stops=...)` 在第 1 天按 `seq` 预占 morning / afternoon 槽；保底站**不占模式的 POI 名额**（`max_count` 相应放宽），剩余槽位继续走正常贪心装箱 → 拼接能力。
3. `SlotItem` 新增 `preset_seq / locked / travel_override_min / preset_meta`：
   - 校内衔接用预置 `walk_in_min` 实测值，**不走 Haversine / 外部路径 API**（5.8 第 5 条）；
   - `locked` 项免于 Stage4 的 2-opt 重排、`_recalc_times` 的时间窗置空、以及全局预算降级的移除候选；
   - 上午放不下的站点顺延到午餐后，仍保持 seq 顺序。
4. date_gate 降级/替换/预约结论写入 `relax_log`，并把线路主题与预约说明写进行程说明卡。

### 13.6 验证

```bash
cd travel-api
.venv/Scripts/python.exe scripts/verify_preset_routes.py   # 54 项检查
.venv/Scripts/python.exe scripts/seed_preset_routes.py --force  # 改文案后强制重建线路
```

覆盖：四类闸门（工作日 / 周末 / 寒暑假 / 国庆 / 花期 / 错季 / 跨年窗口 / 预约 / 开放时段）、纯展示接口、一键成程保底注入与 seq 顺序、拼接能力、全天深度版加段、重新读取 / 按权重重排 / 单日重排不丢动线、A7 启停、不带线路时的普通生成对照。

实测（2026-11-11 工作日，leisure / days=1 / ¥800）：第 1 天 9 个槽位中 **5 个游学保底站 + 4 个自由生成点**，seq 严格递增；错季樱花自动替换为常绿绿道；周末出访校史馆自动降级为 20 分钟馆外讲解。

### 13.7 风险与上线前必办（⚠️）

| 项 | 状态 | 处理 |
|---|---|---|
| 校园通行开放时段（工作日 8:00–17:30 / 周末 9:00–17:00） | 第三方攻略**单源待校验** | 上线前与贵大保卫部门正面核实，同步 `sources` 与 `transit_note` |
| 校园内 8 个站点坐标 | 演示近似值（GCJ-02 口径待统一） | 接入真实业务数据前统一到 GCJ-02 |
| 入校预约政策（iGZU 访客预约） | 官方知识库口径 | A7 每周核验并「标记周更校验」；政策变动时整体降级为「预约指引 + 外观游览」或停用线路 |
| 法定节假日完整日期 | 仅内置公历固定节日 | 按当年国务院放假通知维护 `EXTRA_HOLIDAYS` |
| 文保建筑 | 仅外观参观 | 任务卡已写明禁止攀爬进入 |

**常见坑**：① 改了线路文案/站点后必须跑 `--force` 重建种子（`seed_if_empty` 默认跳过已有线路）；② 后端改代码后要重启（当前 `run.py` 不开热重载）；③ 生成时不要同时传 `preset_route_code` 到已停用线路（接口会 404）；④ 游学行程的保底站不允许手动「更换」，如需调整请回游学页改日期后重新一键成程。

---

## 十四、G4：微信真实 code2session + 标准 JWT（P0 上线阻塞项改造）

对照设计方案 7.5「登录与身份体系」与技术选型表「微信 code2session + 自签 JWT（python-jose）」，把原来的 mock 身份 + `{user_id}.{hmac}` 简化串 + 服务端会话表整体替换。

### 14.1 改造前 / 后

| 项 | 改造前 | 改造后 |
|---|---|---|
| 微信身份 | `MOCK_LOGIN=true` 用 code 派生 `mock_xxx` openid | 服务端调用 `sns/jscode2session`，用真实 openid / unionid 建档；mock 仅本地 dev **显式**开启 |
| 登录态 | `{user_id}.{hmac}` 自签串 + `user_session` / `admin_session` 随机会话 | **RFC 7519 标准 JWT**（`python-jose` HS256），`Authorization: Bearer` |
| 有效期 | 无限期（HMAC 串）/ 7 天 / 12 小时 | 游客 7 天（滑动续期）、管理端 12 小时 |
| 撤销 | 删会话行 | `jti` 写入 `token_denylist`，退出 / 续期后旧 token 立即 401 |
| session_key | 未留存 | 仅落 `user_wechat_session` 表，**不下发前端、不进 JWT** |
| 前端 code | 固定假 code（`portal_mock_code` / `miniapp_mock_code`） | 小程序 `wx.login()` 真 code；PC 走独立匿名登录，不再冒充微信 |

### 14.2 配置（`travel-api/.env`）

| 变量 | 本地 dev | 生产必须 |
|---|---|---|
| `WECHAT_APPID` / `WECHAT_SECRET` | `test_appid` / `test_secret`（占位） | 微信公众平台真实值，**仅存服务端** |
| `MOCK_LOGIN` | `true`（本地显式开启） | `false` —— 代码默认值已经是 false |
| `JWT_SECRET` | 本机固定随机值 | `openssl rand -hex 32` 重新生成；留空且非 mock 时登录返回 503 |
| `JWT_ALG` / `JWT_EXPIRE_HOURS` | `HS256` / `168` | 同左；`JWT_ISSUER=travel-api`、`JWT_AUDIENCE=travel-client` |
| `WECHAT_API_BASE` / `WECHAT_TIMEOUT_SECONDS` / `WECHAT_MAX_RETRIES` | 官方地址 / 5 / 2 | 可按内网代理调整 |
| `ALLOW_ANONYMOUS_GUEST` | `true` | PC 游客模式开关（与微信无关） |
| `ALLOW_LEGACY_HMAC_TOKEN` | `false` | 保持 false；仅存量 token 过渡期临时放开 |

启动时会打印认证模式自检，管理端「系统设置 → 登录鉴权」也可查看 `auth_mode / jwt_alg / jwt_secret / wechat_credentials`（不含任何密钥）。

### 14.3 登录链路

```
小程序启动 → storage 有有效 JWT? → 是：直接进入（剩余 <24h 自动 /auth/refresh）
                                → 否：wx.login() 取一次性 code
                                      → POST /auth/wechat/login {code, device_id}
                                      → 服务端 code2session(appid+secret+code)
                                      → upsert user（openid/unionid）
                                      → session_key 只留服务端
                                      → 签发 7 天 JWT（sub=userId, openid=...）
请求 401 → utils/api.js 自动重走静默登录 → 重放原请求（账号登录用户不会被覆盖）
PC 游客 → POST /auth/anonymous {device_id} → typ=anonymous JWT（按设备稳定建档）
```

### 14.4 JWT 与安全口径

claims：`sub / typ / openid / role / iat / nbf / exp / iss / aud / jti / pv`。校验签名 + exp + nbf + iss + aud + typ 白名单（30s 时钟容差）。

- **类型隔离**：游客接口只接受 `wechat / anonymous / account`，管理接口只接受 `admin`；互换一律 403。
- **改密即失效**：账号 / 管理员 JWT 带 `pv`（口令哈希派生），改密后历史 token 全部自动拒绝。
- **撤销**：`token_denylist` 按 `jti` 记录，过期自动清理；`POST /auth/logout`、`/auth/refresh` 均撤销旧 token。
- **敏感信息**：AppSecret、JWT_SECRET、session_key 全部只在服务端；接口响应与 JWT claims 都不含 session_key。
- **错误码**：40029 / 40163 → 401，45011 → 429，40013 / 40125 / 未知 → 502，`-1` 与网络异常自动重试，未配置凭据 → 503（不发起外网请求）。

### 14.5 四种登录方式统一口径

| 方式 | 端点 | `typ` | 有效期 |
|---|---|---|---|
| 微信静默登录（小程序） | `POST /auth/wechat/login` | `wechat` | 7 天 |
| PC 匿名游客 | `POST /auth/anonymous` | `anonymous` | 7 天 |
| 账号密码（PC + 小程序） | `POST /auth/register`、`/auth/login` | `account` | 7 天 |
| 管理后台 | `POST /admin/login` | `admin` | 12 小时 |

存量平滑：`us_` / `admin_session` 旧会话继续校验至自然过期（**不再签发**）；旧 `{id}.{hmac}` 串默认拒绝，前端 401 拦截器会自动重登。

### 14.6 验证

```bash
cd travel-api
.venv/Scripts/python.exe scripts/verify_auth_jwt.py   # 76 项检查
```

覆盖：标准 JWT 结构与篡改 / 过期 / iss / aud / nbf 拒绝、jti 撤销与滑动续期、真实 code2session 成功与全部错误码及重试、session_key 服务端留存、四种登录方式、类型隔离、改密失效、存量兼容、接口契约。

另做真实 HTTP 端到端实测（26 项全通过）：登录 → `/auth/me` → 续期 → 旧 token 401 → 登出 401、匿名游客身份稳定、带 JWT 生成并保存行程、管理端 JWT 越权 403、篡改签名 / 旧 HMAC / 无 token 均 401。`travel-portal`、`travel-web` 构建与小程序 JS/JSON 语法校验均通过。

### 14.7 上线前必办（⚠️）

1. 微信公众平台取得真实 AppID / AppSecret，写入服务端 `.env`，`MOCK_LOGIN=false`。
2. 重新生成 `JWT_SECRET`（不要用仓库/文档里的任何示例值），并确认 `.env` 已加入 `.gitignore`。
3. 小程序 `utils/config.js` 的 `trial / release` 域名换成备案 HTTPS 域名，并在公众平台登记 request / downloadFile 合法域名；`wx.login` 需真实 AppID。域名已按环境自动切换，`utils/api.js` 不再硬编码本机地址。
4. 在微信后台发布《小程序用户隐私保护指引》（端内页面、首次同意弹窗与撤回入口已实现），按 `deploy/nginx/travel.conf.example` 部署 HTTPS，并注入 `CORS_ORIGINS` 收紧跨域。
5. 备案 / 类目 / 合法域名 / 提审等流程按 `上线合规与提审手册.md` 执行，逐项更新 `deploy/release-checklist.json`；提审前跑 `preflight_release.py --strict` 作发布门禁。
6. 存量旧 HMAC token 会被拒绝属预期；如需零感知过渡，可临时把 `ALLOW_LEGACY_HMAC_TOKEN=true`，7 天后关闭。

**常见坑**：① `python-jose` 的 `leeway` 要放在 `options` 里，不是 `decode()` 关键字参数（PyJWT 才有这个参数）；② 真实 code 只有 5 分钟且一次性，重试只对 `errcode=-1` / 网络错误做；③ 生产漏配 `JWT_SECRET` 会直接 503，启动日志有 ERROR 提示；④ dev mock 下小程序传 `device_id` 保证游客身份稳定，生产 code2session 会忽略它。

---

## 十五、上线合规与提审（P0 · 7.x · M0 / M6）

> 完整操作手册见根目录 `上线合规与提审手册.md`；状态跟踪见 `deploy/release-checklist.json`。

### 15.1 边界说明

备案、类目、证书、合法域名登记、提审发布都需要企业主体与平台审核，**代码侧无法代办**。本次把工程内能提前完成的全部做完并机器可检，把外部流程整理成 18 项带责任人、验收口径、阻塞标记的可跟踪清单。**M0 / M6 里程碑仍未完成**：按方案 10.2 的验收口径，需要「备案已受理」与「审核通过并全量」这两个外部结果。

### 15.2 已落地的工程产物

| 类别 | 位置 | 内容 |
|---|---|---|
| 小程序域名 | `travel-miniapp/utils/config.js` + `utils/api.js` | dev / trial / release 三环境按 `envVersion` 自动切换，移除硬编码 `127.0.0.1` |
| 隐私闭环 | `travel-miniapp/pages/privacy/*`、`app.js`、`pages/mine/*` | 隐私保护指引 + 服务条款双文档页、首次启动版本化同意弹窗、查看与撤回入口、微信侧 `getPrivacySetting` 兼容（失败不阻断） |
| PC 端 | `travel-portal/public/privacy.html`、`src/App.vue`、`travel-web/src/App.vue` | 隐私指引静态页（构建后为 `/privacy.html`）、页脚备案号占位、跨端入口改 `VITE_*` 变量 |
| 后端 | `travel-api/app/config.py`、`app/main.py` | `APP_ENV / CORS_ORIGINS / *_ORIGIN / ICP_NO / PRIVACY_CONTACT`；prod 收紧 CORS 白名单 + HSTS 等安全头；`/health` 回显 `env` 与 `cors` |
| 部署 | `deploy/nginx/travel.conf.example`、`deploy/env/*`、`deploy/legal-domains.md` | 四站点 HTTPS / 80 跳转 / API 反代 / `/docs` 关闭 / 管理接口子域隔离、生产 env 与 Vite 变量模板、合法域名登记表 |
| 门禁 | `travel-api/scripts/preflight_release.py`、`deploy/release-checklist.json` | 40 项自动检查 + 18 项人工清单，`--strict` 可作发布门禁 |

### 15.3 隐私与类目口径

一期定位「旅游 - 旅游信息查询 / 工具类」，全端文案不得出现预订 / 下单 / 购买 / 代订等交易表述（自检已扫描 54 个前端源文件，0 命中）。当前版本不调用 `wx.getLocation`、不收集精确位置；二期启用前需更新隐私指引并单独弹窗授权，拒绝回落默认花溪区且不阻断主流程。后台公示、小程序页、PC 页三处文案需一致，版本 `2026.11.1`。

### 15.4 自检与发布门禁

```bash
python travel-api/scripts/preflight_release.py                              # 检查本地 dev .env
python travel-api/scripts/preflight_release.py --env deploy/env/.env.prod.example
python travel-api/scripts/preflight_release.py --env /srv/travel/.env --strict
python travel-api/scripts/preflight_release.py --json                       # CI 可读
```

脚本不连数据库、不发网络请求、不打印密钥。当前本地结果：`PASS 19 / FAIL 16 / WARN 5；人工 done 0 / 待办 18（阻塞 13）`，结论「不具备提审条件」——反映的是平台侧流程未办理，而非工程缺失。

### 15.5 里程碑状态

| 里程碑 | 工程侧 | 平台侧 | 下一步 |
|---|---|---|---|
| M0 合规启动 | 已就绪（材料清单、文案扫描、域名 / 证书 / 隐私模板与代码） | 0/8，备案未受理 | 立即并行发起注册、认证、类目确认与备案（周期 1~2 月） |
| M6 提审上线 | 已就绪（HTTPS 模板、prod 配置、隐私闭环、走查 / 压测 / 提审材料模板、门禁） | 0/10，未提审未全量 | 备案生效后按手册第 3、5 节执行 |

只有拿到平台凭证才把 `release-checklist.json` 对应项改为 `done` 并填 `evidence`。

---

## 十六、小程序端与 PC 游客端功能对齐（2026-11-11）

以 `travel-portal`（PC 游客端）为基准，把小程序从"能跑通主链路"补齐到"与 PC 端同能力"。**没有改动后端一行代码**——差的都是前端能力。

### 16.1 能力对照

| 能力 | PC 端 | 小程序（改造前） | 小程序（现在） |
|---|---|---|---|
| 资源浏览 | `/explore`：分类 / 关键字 / 评分 / 价格档 / 标签 / 分页 / 地图分布 / 详情画廊 | ❌ 只有首页 6 条精选 | ✅ `pages/explore` 全量对齐，另加中文标签与「加载更多」 |
| 四模式对比 | `/compare`：并排指标 + 差异总结 + 采用某模式 | ❌ 无入口 | ✅ `pages/compare` 四列改四卡 + 同一套 4 条差异总结 |
| 模式开销预估 | Plan 页 `ModeConfigurator`：住宿/餐饮/交通/晚间/点数/节奏 + 整体开销 + 预算贴合 | ❌ 只能填天数预算 | ✅ 定制页第 5 段，`utils/cost.js` 同一套口径，另把 `cost_prefs` 真正回传后端 |
| 个性化 | 8 维滑块 + 7 模板 + 预览 + 天数/预算可调 | ⚠️ 滑块与预览齐全，但生成写死「2 天 / ¥1200」 | ✅ 接住定制页带入的天数与预算，生成载荷带 `weights` + `pace` |
| 天气 | 首页卡片 + 行程页紧凑条 | ❌ 无 | ✅ 首页实况 + 15 天横向滚动；行程页 3 天紧凑条（默认花溪坐标，一期不采集精确定位） |
| 游学线 | 行程页横幅 + 逐站讲解 + 任务卡 | ⚠️ 只有独立游学页，成程后讲解丢失 | ✅ 行程页横幅（闸门结论 / 降级标记）+ 每站可展开讲解 / 任务卡 / 拍照提示 / 预约提示 |
| 路线地图 | 高德 JS API 真实道路、四种出行方式 | ❌ 无 | ⚠️ 原生 `map` 按天着色连线（示意，不是真实道路）；通勤时长仍走 `/route-segments` |
| 导出 | 导出 txt / 打印 PDF | ❌ 无 | ✅ 「复制行程单文本」进剪贴板（含讲解与任务卡） |
| 行程时间轴 | 缩略图 + 交通提示 | ⚠️ 无图 | ✅ 缩略图 + 每日通勤 + 游学锁定标记 |
| 我的行程 | 卡片含创建时间 / 预算 / 花费 | ⚠️ 只有模式与花费 | ✅ 创建时间 + 预算 / 花费 / 使用率 + 空态引导 |
| 导航栏 | 6 个路由 | 2 个 tab | 4 个 tab：首页 / 发现 / 定制 / 我的 |

### 16.2 新增页面

| 页面 | 文件 | 关键实现 |
|---|---|---|
| 发现花溪 | `pages/explore/*` | 先取 `GET /tags` 再拉列表（标签显示中文）；`onReachBottom` 触底加载；单页 12 条；「地图」浮层展示当前已加载点位的 markers；详情用 swiper 画廊 + 6 项元信息 + `wx.openLocation` 导航 |
| 四模式对比 | `pages/compare/*` | `POST /trips/compare`（不落库）；`Math.round` 等运算全部预置在 JS（WXML 不支持 `Math.*`）；从定制页带 `days/budget/party/prefs` 进入即自动出结果 |

### 16.3 tabBar 传参约定

`wx.switchTab` 不能带 query，因此「首页模式卡」「对比页采用某模式」统一走 `getApp().globalData`：

```
pendingMode: 'premium'                       // 只切模式
pendingPlan: { days, budget, partyType, prefs }  // 连带条件
→ switchTab('/pages/request/request')
→ request.onShow() 消费并立刻清空（避免下次进入被旧值覆盖）
```

### 16.4 顺手修掉的两个真问题

1. **偏好 code 与后端标签对不上（会导致生成质量塌陷）**
   改造前小程序硬编码的偏好是 `culture / food / parent_child`，而库里的标签是 `heritage / food_street / family`。
   `stage1_candidates` 的逻辑是：`pref` 非空时，景点/休闲点若与偏好标签**完全无交集**就剔除。也就是说用户一勾"历史文化"，候选池会被筛到只剩地标 Top20，只能靠分级松弛救回来。
   现在偏好标签全部来自 `GET /tags`（14 个标准 code），不会再对不上。
2. **标签在界面上显示成英文 code**
   `GET /pois` 的 `tags` 返回的是 code（`heritage`），PC 端 Explore 直接把它当文本渲染。小程序侧统一用 `/tags` 字典翻成中文；PC 端这个问题**尚未修改**（见 16.6）。

### 16.5 自检脚本（本机无微信开发者工具时的兜底）

```bash
cd travel-miniapp

# 静态检查：JSON 可解析 / JS 语法 / 页面四件套 / tabBar 注册 /
#          WXML 标签闭合 / 事件处理函数存在性 / WXML 禁用表达式 / 跳转 url 已注册
node tools/check.js

# 行为模拟：用内存 storage + 真实 HTTP 伪造 wx.*，直接跑页面 js 与事件处理函数，
#          断言 data 与跳转结果（需后端 8000 在跑）
node tools/sim.js
```

当前结果：`check.js` 全部通过（14 js / 14 json / 10 wxml / 10 页面）；`sim.js` 六组场景全通过（首页、发现、对比、定制、行程、个性化，含游学成程后的讲解展开 / 地图连线 / 行程单复制 / 锁定站不可替换）。

### 16.6 仍未做 / 待办

| 项 | 说明 |
|---|---|
| 微信开发者工具视觉走查 | 本机未安装开发者工具，真机与模拟器的样式、`map` 组件表现需人工看一眼 |
| 真实道路路线 | 小程序 `map` 只能画连线；要真实道路需后端接路径规划 API 并下发 polyline（PC 端走的是高德 JS 插件，小程序用不了） |
| 订阅消息 | `utils/config.js` 的 `TRIP_REMINDER_TEMPLATE_ID` 仍为空占位，需在公众平台申请模板后填入 |
| PC 端标签 code 显示 | `travel-portal/src/views/Explore.vue` 详情里把 `tags` 当中文直接渲染，建议与小程序统一成 `/tags` 字典 |
| 微信真实登录 | 仍依赖 `WECHAT_APPID/SECRET` 与 `MOCK_LOGIN=false`（对应 M6-03），本机 dev 走 mock |

### 16.7 对合规口径的影响

新增页面只涉及**资源浏览、模式对比、天气、地图底图**，没有引入交易、支付、定位采集：

- `preflight_release.py` 的类目文案扫描仍为 **PASS，0 命中**（扫描文件数由 54 增至 62）；
- 位置口径不变：**不调用 `wx.getLocation`**，天气按花溪区默认坐标查询；
- 隐私指引早已列明第三方为「高德地图 / Open-Meteo」，无需改文案即可覆盖新页面。

---

## 十七、小程序 UI 设计系统（2026-11-11）

完整规范见 [`小程序UI设计规范.md`](小程序UI设计规范.md)，视觉稿见 `design/`。

### 17.1 视觉基调

**黔中山水**：青绿主色（花溪河水）+ 纸白底 + 一点暖橙（只给价格与提醒）。卡片靠 1rpx 描边与极浅投影分层，不堆重阴影。

| 资产 | 值 |
|---|---|
| 主色 | `#2F7D5C`（压深 `#1F6B4F` / 提亮 `#6FB79A` / 淡底 `#EAF4EF`） |
| 强调色 | `#D97734`（只用于价格、评分、里程提醒，一屏 ≤3 处） |
| 中性 | ink `#14211C` / body `#3D4A44` / muted `#8A9A93` / line `#E6EDE9` / bg `#F4F7F5` |
| 字号 | 六档：48 / 38 / 32 / 28 / 24 / 20 rpx；数字统一 `tabular-nums` |
| 圆角 | 4 / 12 / 20 / 28rpx + 胶囊 |
| 阴影 | 三档：card / raise / sheet（外加主按钮的 brand 阴影） |

### 17.2 落地方式

- `travel-miniapp/app.wxss` 改为**令牌 + 组件库**：`page{}` 里定义全部 CSS 变量，下面提供 `.card` `.btn-primary/ghost/soft` `.chip` `.tag` `.badge` `.sheet` `.empty` `.skeleton` `.tl-*` 等通用类；页面 WXSS 只写本页独有版式，不再各自重定义按钮与胶囊。
- 六个主要页面重排版式：首页（头图 + 压图数据条 + 天气 + 模式 + 精选横滑）、发现（吸顶筛选 + 双列卡）、定制（五段式 + **底部常驻结算条**）、行程（总览 + 游学横幅 + 地图 + 吸顶 Day 胶囊 + 时间轴）、对比（**四张小卡切换 + 单卡详情**，替代四列长卡）、我的（渐变身份卡 + 行程进度条）。
- **tabBar 图标**：`tools/make_tab_icons.py` 用 Pillow 生成 81×81 线性图标（常态 `#8A9A93` / 选中 `#2F7D5C`），`app.json` 已引用，`packOptions.ignore` 已把 `tools/` 排除出包。

### 17.3 视觉稿

| 图 | 内容 | 源文件 |
|---|---|---|
| `design/ui-screens.png` | 六屏总览（首页 / 发现 / 定制 / 行程 / 对比 / 我的） | `design/ui-preview.html` |
| `design/ui-kit.png` | 令牌与组件板（色板 / 字阶 / 按钮 / 胶囊 / 徽标 / 卡片 / 时间轴 / 空态 / 弹层 / 图标） | `design/ui-kit.html` |

两张图都是无头 Edge 渲染同一套令牌得到的（1rpx = 0.5px），改 WXSS 后重跑一次命令即可同步，命令见规范第 7 节。

### 17.4 验收

- `node tools/check.js`：14 js / 14 json / 10 wxml / 10 页面全通过；本轮新增三项静态校验——**WXSS 花括号平衡**、**`var(--x)` 变量必须有定义**、**WXML 里用到的 class 必须有对应样式**（后者当场揪出个性化页两个空壳容器 `.pz-pace` / `.pz-pv-list`，已补）
- `node tools/sim.js`：六组场景全通过，新增断言覆盖「对比页小卡切换只换详情不重算」「行程页 Day 胶囊触发滚动定位」「每日预算字段存在」
- `preflight_release.py`：仍为 `PASS 19 / FAIL 16 / WARN 5`，文案红线 0 命中

### 17.5 微信开发者工具走查（2026-11-11，基础库 3.4.10 / iPhone 12·13 Pro）

本机装的开发者工具在 `E:\微信web开发者工具`。接入方式与踩到的坑：

| 步骤 | 做法 |
|---|---|
| 开服务端口 | CLI 首次调用会报 `IDE service port disabled`；设置项藏在 `%LOCALAPPDATA%\微信开发者工具\User Data\<hash>\WeappLocalData\localstorage_*.json` 的 `security.enableServicePort`，改 `true` 后 IDE 会把 `.ide-status` 写回 `On`（CLI 只认这个文件） |
| 有效 AppID | `project.config.json` 里的 `touristappid` 会被新版工具拒（`不存在此 AppID`）。改为在 **`project.private.config.json`（已 gitignore）**里写登录账号的**小程序测试号** `wxe346e853c41e8a70`，不动仓库里的占位值；拿到正式 AppID 后只改这一个文件 |
| 自动化截图 | `cli auto --project ... --auto-port 9420` + `miniprogram-automator`；脚本 [`travel-miniapp/tools/devtools-shots.js`](travel-miniapp/tools/devtools-shots.js)，产物在 [`design/devtools/`](design/devtools/)（10 张，379×819） |

**走查抓到 5 个静态检查发现不了的问题，均已修复**：

1. **`scroll-view` 高度爆炸**：`scroll-x` 上加 `enable-flex` / `display:flex` 后，容器高度被算成 6420px（标签行 8959px），发现页列表被整体挤出视口。改回 `white-space:nowrap` + inline-block 经典写法，涉及天气条、精选、分类、标签、日切换、模式小卡 6 处。
2. **两列网格因 1px 换行**：`calc(50% - 7rpx)` 在 332px 容器里算出 162.5px，取整后 163×2+7 = 333 > 332，定制页 4 张模式卡竖排。改为 `calc((100% - 16rpx) / 2)` 落在整数上。
3. **对比页第 4 张小卡被切**：`.mcard` 没写 `box-sizing: border-box`，padding 把 82px 撑成 104px。补 border-box 并收窄到 172rpx，4 张正好一行。
4. **行程页首屏被地图吃掉半屏**：地图改为默认收起、点标题行展开，首屏只留一行入口 + D1/D2 切换。
5. **Day 胶囊跳转后被吸顶条压住标题**：`pageScrollTo` 的 `offsetTop` 由 -20 改为 -56，吸顶条同时改白底 + 细阴影。

走查另确认：无 JS 异常、无 console 报错；首页、发现、定制、对比、行程、我的六页的真实渲染与设计稿一致（真实照片、真实天气、真实行程数据）。**真机（iOS/Android）上的 emoji 与 `backdrop-filter` 仍建议人工一眼确认。**




## 十八、行程编辑与待计划篮子（2026-11-12，整合自 `my-travel(2)` 分支）

从另一条分支（AI 对话版）挑选了**不依赖大模型、可独立落地**的行程编辑能力并入主线。

### 18.1 后端新增接口（`app/routers/trips.py` + `app/services/trip_edit.py`）

| 方法 | 路径 | 说明 |
|---|---|---|
| POST | `/api/v1/trips/{id}/items/add` | 把收藏 / 待计划点位排入指定天，重算时间轴与费用 |
| DELETE | `/api/v1/trips/{id}/items/{item_id}` | 删除行程项并重算当天时间轴 |
| POST | `/api/v1/trips/{id}/items/{item_id}/move` | 移到另一天（可指定插入位置） |
| POST | `/api/v1/trips/{id}/items/{item_id}/copy` | 复制到另一天 |
| POST | `/api/v1/trips/{id}/items/{item_id}/replace` | 替换为另一个点位 |
| GET | `/api/v1/trips/{id}/diagnose` | 行程判官：密度 / 折返 / 开放时间 / 重复 / 预算体检 |
| POST | `/api/v1/trips/{id}/optimize` | 同日点位重排（2-opt / 全排列）减少通勤 |
| POST | `/api/v1/trips/{id}/redistribute` | 按地理区域把点位重新分配到各天（KMeans + 均衡） |

配套改动：

- `trip_item.transport_mode` 新列（`VARCHAR(16)`），记录该点与前一点之间的出行方式；老库需执行
  `ALTER TABLE trip_item ADD COLUMN transport_mode VARCHAR(16) NULL`（已在本地库执行）。
- `Trip` 详情的 items 增加 `id` 字段，前端编辑动作依赖它。
- `trip_service` 补 `date_meta()` 与 `PLAY_CATEGORIES` 两个纯函数，供 `trip_edit` 复用。

### 18.2 待计划篮子（PC 游客端）

- `travel-portal/src/basket.ts`：localStorage 持久化（最多 30 条）。
- 发现页卡片右下角「＋待计划」加入篮子（重复加入会提示）。
- 行程页顶部出现「待计划 N」卡片：可选第几天 → 「一键排入」→ 调 `items/add` 后刷新行程。

自测脚本：`python scripts/smoke_trip_edit.py`（生成 → 加/移/复制/替换/删 → 判官 → 优化 → 跨天重排，全部 200）。

## 十九、专属问答「问小旅」与对话式行程闭环（2026-11-12，整合自 `my-travel(2)` 分支）

从 `my-travel(2)` 分支整合的第二个能力层：**问答（检索增强）+ 对话里改行程 + 攻略解析 + 判官/优化**。
默认**不依赖大模型也能跑**：未配置 `LLM_API_KEY` 时自动降级为「知识库直出」，回答标注
`degraded=true / aigc=false`，引用卡片照常返回。

### 19.1 新增数据表（已建）

| 表 | 用途 |
|---|---|
| `qa_knowledge` | FAQ / 运营贴士 / 政策口径（后台可增删改，保存即失效缓存） |
| `qa_conversation` | 会话（匿名可用；登录后归档到账号） |
| `qa_message` | 消息（含引用来源 `refs`、`aigc`、`degraded`、`latency_ms`，便于审计） |

### 19.2 接口

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/api/v1/qa/status` | 开关 / 模型 / Key 掩码（不回明文） |
| GET | `/api/v1/qa/suggestions` | 首屏推荐问题 |
| POST | `/api/v1/qa/chat` | SSE 流式（`meta` → `delta`* → `done`） |
| POST | `/api/v1/qa/chat/sync` | 非流式（小程序 / 简单集成） |
| GET/DELETE | `/api/v1/qa/conversations[/{id}]` | 会话列表 / 详情 / 删除 |
| POST | `/api/v1/qa/judge` | 行程判官（复用 `trip_edit.diagnose`，过程写入会话） |
| POST | `/api/v1/trips/{id}/chat-edit` | 一句话改行程（换交通 / 改出发时间 / 增删 / 移动 / 重排） |
| POST | `/api/v1/trips/parse-guide` | 粘贴攻略文本 → 匹配 POI → 生成行程（不抓外链） |
| GET/POST/PUT/DELETE | `/api/v1/admin/qa/knowledge` | 知识库 CRUD |
| GET/DELETE | `/api/v1/admin/qa/conversations[/{id}]`、`/stats` | 对话审计 + 运营统计 |
| GET/PUT | `/api/v1/admin/qa/config`、`/config/test` | 模型配置（热生效，Key 只回掩码） |

### 19.3 配置（`.env`）

```
FEATURE_QA_CHAT=true          # 开关；关掉则 /qa/* 返回 503
LLM_API_KEY=                  # 留空 → 知识库直出（degraded）
LLM_BASE_URL=https://api.deepseek.com/v1
LLM_MODEL=deepseek-chat
```

`LLM_*` 走 OpenAI 兼容协议，换通义/智谱/本地 Ollama 只改这三项，代码不用动。

### 19.4 前端

- PC 游客端：顶部导航新增「问小旅」`/chat`（`Chat.vue`），支持流式回答、引用卡片、
  历史会话、AIGC 标识、降级提示、对话内行程卡 / 判官卡 / 智能解析。
- 管理后台：新增「问答管理」`/qa`（`QaManage.vue`），三个页签——知识库、对话审计、模型配置。
- 小程序端已接入同款页面：`pages/chat/chat`（见 §20），接口与 PC 完全一致。

### 19.5 自测

```bash
python scripts/smoke_qa.py               # 15 项：状态/推荐/降级问答/知识库 CRUD 生效/判官
python scripts/smoke_trip_edit.py        # 8 个编辑接口全 200
python scripts/smoke_chat_closed_loop.py # chat-edit 改交通/出发时间 + parse-guide 生成行程
```

无 Key 时的实测：问答 `degraded=true / aigc=false`、引用 5 条；`parse-guide` 能从一段攻略里
匹配出 5 个 POI 并合并成 2 天行程（本地子串扫描兜底，不编造未匹配地点）。


## 二十、小程序「问小旅」与 POI 扩容到 300+（2026-11-12）

### 20.1 小程序问答页

| 文件 | 说明 |
|---|---|
| `pages/chat/chat.js` | 状态 / 推荐问题 / 同步问答 / 历史会话 / 新对话 |
| `pages/chat/chat.wxml` | 气泡列表、引用卡片、AIGC 与降级标识、建议 chips、历史 sheet |
| `pages/chat/chat.wxss` | 复用 `app.wxss` 设计变量，含安全区适配 |
| `app.json` | 注册 `pages/chat/chat`；入口在首页 hero 的「问小旅」按钮 |

交互要点：

- 使用 `POST /qa/chat/sync`（小程序不必处理 SSE），带 `conversation_id` 续聊；
- 回答下方按 `refs` 渲染 POI / FAQ / MODE 引用卡片（POI 可点开）；
- `aigc=true` 显示「AI 生成」，`degraded=true` 显示「知识库摘录」并 toast 提示；
- 未登录点「历史」会提示先登录；登录后列出会话并可回看。

验证：`node tools/check.js`（11 页全过）、`node tools/sim.js`（新增问小旅场景，
校验状态、推荐问题、降级标记、引用卡片、会话 id）、开发者工具真机渲染截图
`design/devtools/16-chat-intro.png` / `17-chat-answer.png`。

### 20.2 POI 扩容（88 → 308）

脚本：`scripts/import_amap_pois.py`（高德 WebService，GCJ-02 无需转换）

```bash
python scripts/import_amap_pois.py --dry-run   # 抓取 + 导出 CSV/报告，不写库
python scripts/import_amap_pois.py --apply     # 去重后写库
```

结果：新增 **220 条**，库内总数 **308**（92 景点 / 106 美食 / 46 住宿 / 56 休闲 / 8 游学）。
产出物在 `scripts/amap_export/`：

- `amap_pois_extended.csv`：完整抓取结果（含 open_time / ext / tags）
- `amap_pois_review.csv`：需人工核对的 114 条（门票、住宿价、营业时间缺失等）
- `amap_pois_report.json`：数量、地理分布、去重明细

写库前已备份原表：`scripts/backup_poi_before_import.json`（88 条全字段）。

### 20.3 封面补齐

新 POI 没有实拍图，用 `scripts/fill_cover_images.py` 生成 8 套无版权分类封面
（nature / mountain / heritage / night / campus / food / hotel / leisure，抽象 SVG，
不含任何素材）：补了 **230 条**（220 新 + 10 条原先空图），已有实景图的 78 条跳过。

图片策略相应放开第三类来源 `generated-cover`（`app/services/image_policy.py`），
元信息如实写 `source_name=分类主题封面（程序生成）`、`license=程序生成·无版权素材`、
`note=抽象分类图形，非实景照片`。**这不是实景照片**，需要在正式上线前用管理员上传替换。

配齐度（`python scripts/check_poi_images.py --expect 1`）：

```
POI 总数 308，配齐度 308/308（100%）
已配图引用 407 张 | 磁盘文件 185 个
```

### 20.4 回归

扩容后既有的算法与游学链路全部复跑通过：`smoke_test` 全过、`verify_preset_routes`
**54/54**、`verify_personalization` **30/30**、`smoke_qa` **15/15**、`smoke_trip_edit` 8 接口全 200，
小程序 `check.js` / `sim.js` 全过。


## 二十一、小程序端两处修复（2026-11-12）

### 21.1 分类封面 SVG → PNG（真机/开发者工具都裂图）

**问题**：扩容时 `fill_cover_images.py` 生成的是 SVG 封面，PC 浏览器能显示，
但小程序 `<image>` 对网络 SVG 支持不稳定，230 个 POI 的封面在开发者工具里全是裂图。

**修复**：

- 新增 `tools/make_cover_png.py`：用 Pillow 直接绘制 8 套 1200×675 PNG 封面
  （渐变底 + 太阳/山/建筑/碗/帐篷等抽象图形，无任何版权素材），不依赖浏览器栅格化；
- 数据侧把 230 条 `covers/*.svg` 引用切成 `covers/*.png`，meta 补一句「PNG 版，小程序可渲染」；
- 原 SVG 保留（便于二次调色），实际引用只走 PNG。

### 21.2 原生 tabBar 图标不显示 → 改自定义 tabBar

**问题**：`app.json` 的 `tabBar.iconPath` 指向 `assets/tabbar/*.png`，文件合法（81×81 PNG）、
被 `cli preview` 正常打进包（231.6 KB），但开发者工具模拟器里四个图标全是裂图；
同一个文件用页面里的 `<image>` 却能正常显示。清编译缓存、换文件名、改绝对路径、
`packOptions.include`、开关 `ignoreDevUnusedFiles` / `useStaticServer` 均无效。

**修复**：改用官方自定义 tabBar（`app.json` 里 `tabBar.custom = true`）：

| 文件 | 说明 |
|---|---|
| `custom-tab-bar/index.js` | 4 个 tab 的数据与 `wx.switchTab` 跳转 |
| `custom-tab-bar/index.wxml` | `<image>` + 文案，选中态换 `-on` 图标 |
| `custom-tab-bar/index.wxss` | 固定底部、`env(safe-area-inset-bottom)`、选中色 `#2f7d5c` |
| 4 个 tab 页 `onShow` | `getTabBar().setData({ selected: n })` 同步选中态 |
| `app.wxss` | 新增 `.page.has-tabbar`，底部多留 100rpx 避免内容被遮住 |

验证：首页 / 发现 / 我的三页截图，图标与选中态均正常；`tools/check.js`（16 js / 12 wxml）、
`tools/sim.js`（7 个场景）全过。


### 21.3 真机连不上后端（网络异常）

**症状**：手机预览/真机调试时首页显示「0 本地资源点」，弹「网络异常，请确认后端已启动（请求 http://127.0.0.1:8000）」。
**原因**（两层叠加）：

1. `utils/config.js` 用 `platform === 'devtools'` 判断环境，而**「真机调试」下 platform 也是 devtools**，
   于是手机端拼出了 `127.0.0.1`——那是手机自己，必然连不上；
2. 电脑当时只有一条 PPPoE「宽带连接」（10.9.87.230），**WLAN 是断开的**，手机与电脑不在同一网段，
   即便填对 IP 也访问不到。

**已做的代码修复**：

- `isDevtools()` 改为 `platform === 'devtools' && (brand 为空或 devtools)`——真机调试的 brand 是手机品牌，会走局域网；
- `LAN_HOST` 更新为当前电脑 IP；
- 新增运行时覆盖：`utils/config.js` 读本地存储 `travel_api_host`，优先级高于默认值；
- 「我的 → 合规与帮助 → 后端地址（调试）」可直接改，重启小程序生效，换 Wi-Fi 不用改代码；
- 请求失败 toast 里带出实际请求的 host，便于定位。

**真机联调正确姿势**（缺一不可）：

1. 手机与电脑在**同一网段**（推荐：手机开热点 → 电脑连热点；或电脑连手机所在的同一个 Wi-Fi）；
2. 电脑上 `ipconfig` 看该网卡的 IPv4，例如 `192.168.43.5`；
3. 手机浏览器先验证：打开 `http://<该IP>:8000/api/v1/health` 能看到 JSON 才算通；
4. 微信开发者工具「真机调试 / 预览」时勾选**「不校验合法域名、web-view、TLS 及 HTTPS 证书」**；
5. Windows 防火墙放行 `C:\python\python.exe`（已有一条 Inbound Allow 规则）；
6. 小程序里「我的 → 后端地址（调试）」填 `http://<该IP>:8000`，重启小程序。

> 注意：PPPoE 拨号得到的公网/运营商地址（如 10.9.x.x）通常无法被手机访问，不能当联调地址用。