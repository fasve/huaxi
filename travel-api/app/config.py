"""全局配置：从 .env 读取，敏感信息不入代码。"""
from pathlib import Path

from dotenv import load_dotenv
from pydantic_settings import BaseSettings

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")


class Settings(BaseSettings):
    # 数据库
    DB_HOST: str = "127.0.0.1"
    DB_PORT: int = 3306
    DB_USER: str = "root"
    DB_PASSWORD: str = ""
    DB_NAME: str = "travel"

    # 服务
    API_HOST: str = "0.0.0.0"
    API_PORT: int = 8000

    # ---------- 微信登录（设计方案 7.5：code2session + 自签 JWT） ----------
    # AppSecret 仅存服务端 .env，严禁写入小程序 / 前端代码。
    WECHAT_APPID: str = ""
    WECHAT_SECRET: str = ""
    WECHAT_API_BASE: str = "https://api.weixin.qq.com"  # 可指向自建代理 / 联调 mock server
    WECHAT_TIMEOUT_SECONDS: float = 5.0
    WECHAT_MAX_RETRIES: int = 2       # 仅对网络错误与 errcode=-1 重试
    # 默认关闭：生产走真实 code2session。仅本地 dev 在 .env 里显式置 true。
    MOCK_LOGIN: bool = False
    # 允许 PC 端匿名游客（非微信场景），独立签发 typ=anonymous 的 JWT
    ALLOW_ANONYMOUS_GUEST: bool = True

    # ---------- JWT（python-jose；签发与校验口径见 app/services/jwt_service.py） ----------
    # 生产必须配置：openssl rand -hex 32。留空且 MOCK_LOGIN=false 时登录接口返回 503。
    JWT_SECRET: str = ""
    JWT_ALG: str = "HS256"            # 自签 JWT，当前仅支持 HS256
    JWT_EXPIRE_HOURS: int = 168      # 7 天（设计方案 7.5），配合 /auth/refresh 滑动续期
    JWT_ISSUER: str = "travel-api"
    JWT_AUDIENCE: str = "travel-client"
    JWT_LEEWAY_SECONDS: int = 30     # 允许客户端时钟小幅偏差
    # 存量平滑：us_ / admin_session 服务端会话继续校验至自然过期；
    # 旧版 `{id}.{hmac}` 自签 token 默认拒绝（已不再签发），如需过渡可显式开启。
    ALLOW_LEGACY_HMAC_TOKEN: bool = False

    # ---------- 上线合规 / 生产运行（设计方案 7.x；M0 与 M6 的机器可检部分） ----------
    # dev / staging / prod；prod 时 CORS 收紧为白名单并下发安全响应头
    APP_ENV: str = "dev"
    # 逗号分隔的完整 origin 列表（含 https://，无尾斜杠），仅 prod 生效且必填
    CORS_ORIGINS: str = ""
    # 站点规划：与 ICP 备案、证书、微信后台合法域名保持一致（供自检与运维核对）
    PUBLIC_API_ORIGIN: str = ""       # https://api.xxx.cn（request 合法域名）
    PORTAL_ORIGIN: str = ""           # https://www.xxx.cn（PC 游客端）
    ADMIN_ORIGIN: str = ""            # https://admin.xxx.cn（管理后台，不对小程序开放）
    CDN_ORIGIN: str = ""              # https://cdn.xxx.cn（downloadFile 合法域名）
    ICP_NO: str = ""                  # ICP 备案号，展示于站点页脚
    PRIVACY_CONTACT: str = ""         # 隐私指引联系邮箱

    # ---------- 可选增强开关（P1/P2，默认关闭；配置凭据后显式开启） ----------
    FEATURE_ROUTE_API: bool = False        # #9 路线分段（腾讯位置服务，未配置时走直线估算）
    FEATURE_AI_POLISH: bool = False        # T7 AI 润色与小贴士（未配置时走规则模板）
    FEATURE_SUBSCRIBE_MSG: bool = False    # T8 出行前一日订阅消息提醒
    FEATURE_GEO_LOCATE: bool = False       # 小程序精定位（一期未启用）
    FEATURE_PRESET_ROUTES: bool = True     # 预设主题路线（G7，已上线默认开）

    # 腾讯位置服务（#9 / 方案 8.1）：WebService key，仅服务端使用
    TENCENT_LBS_KEY: str = ""
    TENCENT_LBS_BASE: str = "https://apis.map.qq.com"
    TENCENT_LBS_TIMEOUT_SECONDS: float = 5.0

    # AI 润色（T7）：OpenAI 兼容 /chat/completions 接口；留空则走规则模板
    AI_POLISH_BASE_URL: str = ""
    AI_POLISH_API_KEY: str = ""
    AI_POLISH_MODEL: str = "gpt-4o-mini"
    AI_POLISH_TIMEOUT_SECONDS: float = 20.0

    # 微信订阅消息（T8）：出行前一日提醒模板
    WECHAT_TEMPLATE_TRIP_REMINDER: str = ""
    SUBSCRIBE_REMINDER_LEAD_HOURS: int = 24   # 提前小时数（默认出行前一日）
    REMINDER_SCAN_INTERVAL_MIN: int = 30      # 后台扫描周期（分钟）

    # ---------- 专属问答「问小旅」（云端 LLM；未配 Key 时降级为知识库直出） ----------
    FEATURE_QA_CHAT: bool = False      # 默认关；.env 打开并配好 LLM_* 才走模型
    LLM_BASE_URL: str = "https://api.deepseek.com/v1"
    LLM_API_KEY: str = ""
    LLM_MODEL: str = "deepseek-chat"
    LLM_THINKING: str = "auto"         # auto / on / off（部分 provider 才支持）
    LLM_TIMEOUT: int = 45
    LLM_MAX_TOKENS: int = 800
    LLM_TEMPERATURE: float = 0.3
    QA_DAILY_LIMIT: int = 300          # 登录用户每日提问上限
    QA_ANON_DAILY_LIMIT: int = 50      # 匿名（按 IP）每日提问上限
    QA_MAX_HISTORY: int = 6            # 携带最近 N 条历史消息（3 轮）
    QA_TOP_K: int = 5                  # 每次检索注入的知识卡条数
    QA_MAX_QUESTION: int = 300         # 单条提问最大字数

    # 可选：Redis 缓存（留空则使用进程内 TTL 缓存，配置后自动切换）
    REDIS_URL: str = ""

    # 管理后台：账号密码登录（会话制）
    # 仅首次初始化时用于创建默认管理员；正式部署前应改密并限制管理子域访问
    ADMIN_BOOTSTRAP_USERNAME: str = "admin"
    ADMIN_BOOTSTRAP_PASSWORD: str = "admin123"
    ADMIN_SESSION_HOURS: int = 12

    # 游客端：账号密码登录（会话制，7 天免登录）
    USER_SESSION_HOURS: int = 168

    # 高德开放平台 Web 服务 key（仅服务端使用，不下发到浏览器）
    # 用途仅限：逆地理编码 / IP 定位（地名解析）。天气数据已全部改用 Open-Meteo，无需 key。
    # 旧字段 AMAP_WEATHER_KEY 保留兼容读取，取值优先级：AMAP_KEY > AMAP_WEATHER_KEY。
    AMAP_KEY: str = ""
    AMAP_WEATHER_KEY: str = ""
    AMAP_CITY_ADCODE: str = "520111"  # 贵阳市花溪区行政区划代码

    @property
    def amap_key(self) -> str:
        """高德 Web 服务 key：优先新字段，兼容旧字段。"""
        return (self.AMAP_KEY or self.AMAP_WEATHER_KEY or "").strip()

    @property
    def wechat_configured(self) -> bool:
        """是否具备调用真实 code2session 的凭据（排除模板占位值）。"""
        appid = self.WECHAT_APPID.strip()
        secret = self.WECHAT_SECRET.strip()
        if not appid or not secret:
            return False
        placeholders = ("test_appid", "test_secret", "your_", "请", "xxx", "changeme")
        return not any(p in appid.lower() or p in secret.lower() for p in placeholders)

    @property
    def jwt_configured(self) -> bool:
        return bool(self.JWT_SECRET.strip())

    @property
    def route_api_configured(self) -> bool:
        """腾讯位置服务 key 是否可用（占位符视为未配置）。"""
        key = (self.TENCENT_LBS_KEY or "").strip()
        return bool(key) and not any(p in key.lower() for p in ("your_", "xxx", "changeme", "请"))

    @property
    def ai_polish_configured(self) -> bool:
        """AI 润色服务是否可用：需同时配置 base_url 与 api_key。"""
        base = (self.AI_POLISH_BASE_URL or "").strip()
        key = (self.AI_POLISH_API_KEY or "").strip()
        return bool(base and key)

    @property
    def subscribe_configured(self) -> bool:
        """订阅消息是否可用：需 WeChat 凭据 + 模板 ID + 开关。"""
        return bool(self.WECHAT_TEMPLATE_TRIP_REMINDER.strip()) and self.wechat_configured

    @property
    def qa_enabled(self) -> bool:
        """问答是否真正走模型：开关打开且配置了 LLM Key；否则降级为知识库直出。"""
        return bool(self.FEATURE_QA_CHAT and (self.LLM_API_KEY or "").strip())

    @property
    def is_prod(self) -> bool:
        """是否按生产模式运行：影响 CORS 白名单与安全响应头。"""
        return self.APP_ENV.strip().lower() in ("prod", "production")

    @property
    def cors_origins(self) -> list[str]:
        """生产跨域白名单；未配置返回空列表（默认拒绝跨站，安全兜底）。"""
        return [o.strip().rstrip("/") for o in self.CORS_ORIGINS.split(",") if o.strip()]

    @property
    def database_url(self) -> str:
        return (
            f"mysql+pymysql://{self.DB_USER}:{self.DB_PASSWORD}"
            f"@{self.DB_HOST}:{self.DB_PORT}/{self.DB_NAME}?charset=utf8mb4"
        )


settings = Settings()
