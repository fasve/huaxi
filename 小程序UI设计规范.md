# 花溪旅行 · 微信小程序 UI 设计规范

> 版本 1.0 ｜ 适用端：微信小程序游客端（`travel-miniapp/`）｜ 落地文件：`travel-miniapp/app.wxss`
> 视觉稿：[六屏总览](design/ui-screens.png) ｜ [组件与令牌板](design/ui-kit.png) ｜ 可编辑源：[design/ui-preview.html](design/ui-preview.html)、[design/ui-kit.html](design/ui-kit.html)

---

## 1. 设计目标

这个产品解决的是「信息过载、行程难排」，用户在小程序里要做的动作只有三个：**看选什么**、**填几个条件**、**看排出来什么**。所以界面只需服务三件事：

| 原则 | 具体做法 | 反面（改版前） |
|---|---|---|
| 一眼看到重点 | 每屏只有一个视觉重心：首页是头图 + 模式卡，发现是卡片图，定制是底部结算条 | 每屏都是白卡片 + 灰文字，层级靠字号硬撑 |
| 少即是准 | 数字（价格、评分、预算使用率）用同一套等宽数字对齐，其余文字只留三档灰 | 字号从 19rpx 到 76rpx 散落十几档 |
| 决策有依据 | 模式卡直接给「2 天 ≈ ¥980」，定制页底部常驻开销与预算贴合度 | 选模式时看不到钱，生成后才发现超预算 |

**视觉基调：黔中山水**——主色取花溪河与喀斯特山林的青绿，纸白作底，暖橙只给价格/评分/提醒。不用深色块压屏，不堆重阴影，靠留白与细描边分层。

---

## 2. 设计令牌

全部以 CSS 变量定义在 `app.wxss` 的 `page{}` 里，页面样式只引用变量，**不写死色值**。

### 2.1 颜色

| 变量 | 值 | 用途 |
|---|---|---|
| `--brand` | `#2F7D5C` | 主色：主按钮、选中态、链接 |
| `--brand-deep` | `#1F6B4F` | 主色压深：导航栏、头图起点、价格数字 |
| `--brand-mid` | `#6FB79A` | 主色提亮：渐变终点、进度条 |
| `--brand-tint` | `#EAF4EF` | 主色淡底：选中胶囊、emoji 底托、图标圈 |
| `--brand-tint-2` | `#F4FAF7` | 更淡的底：卡片渐变、信息条 |
| `--accent` | `#D97734` | 暖橙：价格、评分、里程提醒 |
| `--accent-tint` | `#FDF1E7` | 暖橙淡底：评分徽标 |
| `--ink` | `#14211C` | 标题/主数字（不是纯黑） |
| `--body` | `#3D4A44` | 正文 |
| `--muted` | `#8A9A93` | 辅助说明 |
| `--faint` | `#B7C2BD` | 占位、禁用、脚注 |
| `--line` | `#E6EDE9` | 卡片描边 |
| `--line-soft` | `#F0F4F2` | 分割线 |
| `--bg` | `#F4F7F5` | 页面底色 |
| 语义色 | `--ok` `#2E9E63` / `--warn` `#C77D1E` / `--danger` `#C6473A` / `--info` `#3E7CB1` | 预算内 / 需预约 / 超预算 / 定位来源 |

用色纪律：**暖橙在一屏内不超过 3 处**；主色不做大面积背景（除头图与身份卡）；正文禁止用纯黑 `#000`。

### 2.2 字号

六档，够用就不再加：

| 类名 | 字号 | 字重 | 用途 |
|---|---|---|---|
| `t-h1` | 48rpx | 700 | 页面主标题（头图、登录页） |
| `t-h2` | 38rpx | 700 | 区块大标题 |
| `t-h3` | 32rpx | 700 | 卡片标题、步骤标题 |
| `t-h4` | 28rpx | 600 | 小节标题、行标题 |
| `t-body` | 28rpx | 400 | 正文 |
| `t-sm` / `t-xs` | 24rpx / 20rpx | 400 | 辅助、脚注 |

数字（价格、评分、预算、天数）统一 `t-num`：`font-variant-numeric: tabular-nums` + 700 字重，避免加减时宽度跳动。

### 2.3 间距与圆角

- 栅格：**4rpx 基准**，只用 8 / 16 / 24 / 32 / 40 / 48；页面左右边距固定 `24rpx`（`--gutter`）。
- 圆角四档 + 胶囊：`4rpx`（小标签）/ `12rpx`（胶囊输入、缩略图）/ `20rpx`（卡片）/ `28rpx`（底部弹层、身份卡）/ `999rpx`（按钮、chip）。
- 卡片内边距 `32rpx`；卡片间距 `24rpx`；区块标题上文距 `32rpx`、下文距 `16rpx`。

### 2.4 阴影

只三档，都很浅，用来表达层级而不是装饰：

| 变量 | 值 | 用途 |
|---|---|---|
| `--sh-card` | `0 2rpx 10rpx rgba(20,33,28,.05)` | 常规卡片 |
| `--sh-raise` | `0 10rpx 30rpx rgba(20,33,28,.12)` | 压住头图的数据条、浮层 |
| `--sh-sheet` | `0 -10rpx 36rpx rgba(16,28,22,.14)` | 底部弹层 |
| `--sh-brand` | `0 8rpx 20rpx rgba(47,125,92,.24)` | 主按钮（唯一带颜色的阴影） |

---

## 3. 组件规范

| 组件 | 类名 | 结构 | 尺寸与状态 |
|---|---|---|---|
| 卡片 | `.card` / `.card-tint` / `.card-flat` | 白底 + 1rpx 描边 + 圆角 20rpx | 内边距 32rpx；`.card-press` 提供按下缩放 0.985 |
| 区块标题 | `.sec-head` + `.sec-title` + `.sec-sub` + `.sec-more` | 标题左侧 6rpx 竖杠（渐变），副标题小一号灰 | 标题 34rpx/700；右侧「查看全部 ›」为 24rpx 主色 |
| 主按钮 | `.btn .btn-primary` | 135° 主色渐变 + brand 阴影 | 高 88rpx，胶囊；`.btn-sm` 64rpx；按下 scale .985 |
| 次级按钮 | `.btn-ghost` | 白底 + 1rpx 主色描边 | 与主按钮同高；一屏最多 2 个并列 |
| 轻按钮 | `.btn-soft` | 主色淡底 + 深主色字 | 用于「按权重个性化」这类可选动作 |
| 筛选胶囊 | `.chip` / `.chip.on` / `.chip-sm` | 高 60rpx 胶囊 | 选中：淡底 + 主色描边 + 600 字重 |
| 只读标签 | `.tag` / `.tag-brand` / `.tag-accent` / `.tag-line` | 高 40rpx，圆角 8rpx | 分类用 brand，评分用 accent，次要信息用 line |
| 状态徽标 | `.badge` + 4 种语义色 | 高 36rpx 胶囊 | 预算内/需预约/超预算/模式默认 |
| 价格 | `.price` | 暖橙 700 + 等宽数字 | 与 `.rating`（`★ 4.7`）同字号 |
| 缩略图 | `.thumb` / `.thumb-ph` | 圆角 12rpx，无图时渐变色块 + 首字 | 列表 108×82rpx，卡片图 4:3 |
| 底部弹层 | `.mask` + `.sheet` + `.sheet-grab` | 抓手 + 标题行（含圆形关闭钮）+ 内容区 | 上滑 240ms `cubic-bezier(.22,.61,.36,1)`；最大高 88vh |
| 空态 | `.empty` + `.empty-icon` + `.empty-title` + `.empty-text` | 圆形淡底图标 + 一句话 + 下一步 | 必须给「下一步动作」，不能只写"暂无数据" |
| 骨架屏 | `.skeleton` | 1.4s 渐变扫光 | 首屏与列表加载用，替代白屏 |
| 时间轴 | `.tl-row` / `.tl-time` / `.tl-rail` / `.tl-card` | 左侧时间（含时长）+ 中间圆点竖线 + 右侧卡片 | 圆点用当日主题色；末项不画竖线 |
| 数字进度条 | `.bar` / `.bar-fill` | 高 14rpx 胶囊 | 颜色随状态：`ok` / `warn` / `danger` |

**按钮层级规则**：一屏只能有一个 `.btn-primary`；同一行最多两个按钮；`btn-ghost` 与 `btn-soft` 不并排混用。

---

## 4. 页面版式

### 4.1 首页
头图（渐变 + 品牌标 + 双 CTA）→ **数据条压在头图上**（负 margin 68rpx，制造层次）→ 天气卡（大温度 + 15 天横滑）→ 模式 2×2 卡 → 精选横滑卡（320×200rpx 图）→ 脚注。
要点：头图只放品牌、主张、两个动作；数据条是全页唯一带 `--sh-raise` 的元素。

### 4.2 发现花溪
吸顶筛选区（搜索 + 分类下划线 + 4 个筛选胶囊 + 标签横滑）→ 结果计数行 → 双列卡片（图 236rpx 高，左上分类、右下评分）→ 触底加载。
要点：筛选项用**下划线**而不是胶囊表达分类，胶囊只用于具体条件，两者不混。

### 4.3 定制行程
五段式：① 模式（2×2 带 ✓）② 天数（胶囊直选 1–7）与预算（大号输入 + 快捷值）③ 人群 ④ 偏好 ⑤ 开销微调（折叠）+ 开销明细面板；**底部常驻结算条**（左：开销数字；中：预算进度条；右：生成按钮）。
要点：生成动作永远在拇指可达区；结算条与明细面板用同一套 `fit` 语义色。

### 4.4 行程详情
总览（模式 + 天数 + 花费 + 预算条）→ 游学横幅 → 天气条 → 路线地图（按天着色）→ 权重画像 → 松弛提示 → 小贴士 → **吸顶 Day 胶囊**（多日时点击滚动定位）→ 每日时间轴（讲解可展开）。
要点：时间轴是主视觉，缩略图只做 108×82rpx 辅助；锁定站用「锁定」而非「换」。

### 4.5 四模式对比
条件卡 → 差异总结（4 条编号结论）→ **四张模式小卡横排**（选中放大描边）→ 选中模式的详情卡 → 采用按钮。
要点：手机上四列真表读不动，所以拆成「小卡选 + 单卡看」。

### 4.6 我的
渐变身份卡（头像 + 账号 + 退出）→ 我的行程列表（模式 emoji + 状态徽标 + 时间 + 预算/花费 + 进度条）→ 合规与帮助 → 页脚免责说明。

---

## 5. 动效

| 场景 | 时长 / 曲线 |
|---|---|
| 按钮按下 | 140ms，scale .985 + 透明度 .92 |
| 卡片按下 | 160ms，scale .985 + 阴影收一档 |
| 底部弹层 | 240ms `cubic-bezier(.22,.61,.36,1)` 上滑，遮罩 180ms 淡入 |
| 进度条变化 | 250ms ease |
| 骨架扫光 | 1.4s 循环 |

禁止：整页转场动画、长于 300ms 的列表入场、循环脉冲（除骨架屏）。

---

## 6. 一致性与可用性红线

1. **点击区不小于 88×88rpx**（`.chip` 60rpx 高时，上下留足 padding 或用 `catchtap` 扩大热区）。
2. **正文对比度**：`--body` on white ≥ 7:1；`--muted` 只用于 ≥24rpx 的辅助文字，不用在关键信息。
3. **数字必须等宽**（`t-num`），金额前面带 `¥`，免费写「免费」而不是「¥0」。
4. **不用纯黑、不用纯白描边**（`#000` / `#fff` 边框在深色模式下会突兀）。
5. **不堆 emoji 当图标**：tabBar 用生成的 PNG 线性图标；页面内 emoji 只用于「模式」与「槽位」这两类需要亲切感的场景，且固定在 40rpx 的淡底方块里。
6. **空态必须给下一步**（按钮或可点文字），错误态必须说人话（「天气服务暂不可用，可下拉刷新重试」）。
7. **不隐藏系统能力**：返回、下拉刷新、分享、长按保存都保留原生行为。

---

## 7. 落地映射

| 设计资产 | 代码位置 |
|---|---|
| 令牌（色/字/间距/圆角/阴影） | [`travel-miniapp/app.wxss`](travel-miniapp/app.wxss) 的 `page{}` |
| 通用组件样式 | 同上（`.card` `.btn-*` `.chip` `.tag` `.badge` `.sheet` `.empty` `.skeleton`） |
| 页面级版式 | `pages/` 下各页面的 `.wxss`（只写本页独有：头图、筛选、时间轴、结算条等） |
| tabBar 图标 | [`travel-miniapp/assets/tabbar/`](travel-miniapp/assets/tabbar/)，由 [`tools/make_tab_icons.py`](travel-miniapp/tools/make_tab_icons.py) 生成 |
| 视觉稿 | [`design/ui-preview.html`](design/ui-preview.html) / [`design/ui-kit.html`](design/ui-kit.html) |

重新出图（本机 Edge 无头截图，1rpx = 0.5px）：

```powershell
$edge = "C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"
& $edge --headless=new --disable-gpu --hide-scrollbars --force-device-scale-factor=1.35 `
  "--screenshot=design/ui-screens.png" "--window-size=1300,2080" `
  "file:///C:/Users/A1DFN/Desktop/my-travel/design/ui-preview.html"
```

改主题色的正确姿势：只改 `app.wxss` 里的 `--brand*` / `--accent`，页面不跟着改；改圆角只改 `--r-*`。

---

## 8. 交付自检清单

- [x] 令牌集中定义，页面 WXSS 中无硬编码主题色（例外：头图 / 身份卡的渐变色值，作为品牌资产固定）
- [x] 六屏版式与视觉稿一致（页边距 24rpx、卡片圆角 20rpx、主按钮 88rpx）
- [x] tabBar 四枚图标两态齐备，`app.json` 已引用，`tools` 目录已排除出包
- [x] 空态 / 骨架屏 / 弹层 / 时间轴四类易漏组件都有统一样式
- [x] `node tools/check.js` 与 `node tools/sim.js` 全通过（结构、事件绑定、页面行为无回归）
- [x] **微信开发者工具真机渲染走查**（见第 9 节）：10 张真实截图、2 个渲染 bug 已修

## 9. 开发者工具走查记录

环境：微信开发者工具（`E:\微信web开发者工具`）、基础库 3.4.10、模拟器 iPhone 12/13 (Pro) 390×844、后端 `travel-api` 本地运行。
方式：`cli auto --auto-port 9420` + `miniprogram-automator` 驱动页面、截图并断言 `page.data()`；脚本见 [`travel-miniapp/tools/devtools-shots.js`](travel-miniapp/tools/devtools-shots.js)，截图在 [`design/devtools/`](design/devtools/)。

### 9.1 走查抓到的真实问题（静态检查发现不了的）

| # | 现象 | 根因 | 修复 |
|---|---|---|---|
| 1 | 发现页只剩搜索框和分类，列表整体消失 | `<scroll-view scroll-x enable-flex>` 加 `display:flex` 后，横向滚动容器的高度被算成 **6420px**（标签行 8959px），把后面的列表挤出视口 | 去掉 `enable-flex` 与容器的 `display:flex`，改回 `white-space:nowrap` + 子元素 inline-block 的经典写法；影响 5 个横向容器（天气条、精选、分类、标签、日切换、模式小卡） |
| 2 | 定制页 4 张模式卡竖着排成 1 列 | `width: calc(50% - 7rpx)` + `gap: 14rpx`：容器 332px 下算出 162.5px，四舍五入成 163×2 + 7 = **333 > 332**，多出 1px 就换行 | 改成 `width: calc((100% - 16rpx) / 2)`（gap 也统一 16rpx），让结果落在整数上；对比页小卡同样补 `box-sizing: border-box` 并收窄到 172rpx，4 张正好一行 |
| 3 | 行程页首屏被地图占掉大半屏 | 地图卡片固定展开 420rpx | 改为默认收起，点标题行展开（`mapOpen`），首屏只留一行入口 + D1/D2 切换 |
| 4 | 点 Day 胶囊后，目标那天的卡片标题被吸顶条压住 | `pageScrollTo` 的 `offsetTop: -20` 不够覆盖 44px 的吸顶条 | 改为 `-56`，并给吸顶条加白色底与细阴影 |
| 5 | 游学横幅的闸门提示堆到 4 行，把地图推得很远 | 直接渲染全部 `gate_notes` | 只显示前 2 条，其余折叠为「还有 N 条提示，见下方逐站讲解」 |

### 9.2 走查确认正常的部分

- 首页：头图渐变、压在头图上的数据条、天气卡 15 天横滑、模式卡 2×2、tabBar 图标两态
- 发现：吸顶筛选、分类下划线、标签横滑、双列卡片真实照片、评分/价格角标
- 定制：五段式表单、天数胶囊、预算输入、底部结算条（¥860 / 预算内 · 65%）
- 对比：差异总结、四张模式小卡一行放得下、选中态描边
- 行程：总览预算条、游学横幅、天气条、收起态地图、权重画像条形、时间轴（缩略图 + 时间 + 换）、Day 切换、逐站讲解展开、操作区
- 无 JS 异常、无 console 报错（`mp.on('exception')` 全程为空）

### 9.3 复现命令

```powershell
# 1) 打开项目（服务端口需在 设置 → 安全设置 打开）
& "E:\微信web开发者工具\cli.bat" open --project "C:\Users\A1DFN\Desktop\my-travel\travel-miniapp"
# 2) 启动自动化端口
& "E:\微信web开发者工具\cli.bat" auto --project "C:\Users\A1DFN\Desktop\my-travel\travel-miniapp" --auto-port 9420
# 3) 逐页截图（需先 npm i miniprogram-automator 到临时目录）
$env:MINIPROGRAM_AUTOMATOR_PATH="$env:TEMP\wxauto\node_modules\miniprogram-automator"
node travel-miniapp/tools/devtools-shots.js
```

### 已知待补

| 项 | 说明 |
|---|---|
| 游学 / 登录 / 隐私三页 | 仍在用旧调色板（`#2f7d5c`、`#7c8a84`、16~20rpx 圆角），与新令牌接近但未归一；它们继承 `app.wxss` 的 `.card` 与 `.btn-primary`，不会破版，建议下一轮统一 |
| 分享海报 canvas | 海报是独立绘制层，沿用旧的品牌色值，与页面配色一致但不受令牌控制 |
| 暗色模式 | 未支持；`app.json` 未声明 `darkmode`，如要做需补 `theme.json` 与两套变量 |
| 真机 | 开发者工具模拟器已走查；iOS/Android 真机上的 `backdrop-filter`、emoji 渲染仍需一眼确认 |
