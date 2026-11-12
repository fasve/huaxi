"""FastAPI 入口：花溪区个性化旅游路线规划系统后端。

启动：python run.py（或 python -m uvicorn app.main:app --port 8000）
"""
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app.config import BASE_DIR, settings
from app.routers import (
    admin, admin_auth, admin_ext, compare, guest, preset_routes, qa, qa_admin,
    trips, user_auth, weather,
)


@asynccontextmanager
async def lifespan(_: FastAPI):
    # 幂等：确保管理员账号表存在并创建初始账号（不覆盖已改过的密码）
    from app.services.admin_auth import init_admin_auth
    from app.services.jwt_service import assert_config, init_auth_tables
    from app.services.user_auth import init_user_auth

    # G4：真实 code2session + 自签 JWT 的配置自检（不改数据库，先打印模式）
    try:
        print(f"[travel-api][AUTH] {assert_config()}")
    except Exception as exc:
        print(f"[travel-api][AUTH][ERROR] 认证配置自检失败：{exc}")
    try:
        init_admin_auth()
    except Exception as exc:  # 数据库未就绪时不阻断游客端启动
        print(f"[travel-api] 管理端账号初始化失败（请检查 MySQL）：{exc}")
    try:
        init_user_auth()
        init_auth_tables()   # user_wechat_session + token_denylist
    except Exception as exc:
        print(f"[travel-api] 游客账号表初始化失败（请检查 MySQL）：{exc}")
    # 预设主题路线（G7）：幂等建表 + trip 补列 + 贵大游学线种子，零手动迁移
    try:
        from app.services.preset_seed import ensure_preset_routes
        result = ensure_preset_routes()
        print(f"[travel-api] 预设路线就绪：{result}")
    except Exception as exc:
        print(f"[travel-api] 预设路线初始化失败（请检查 MySQL）：{exc}")
    # P1/P2 扩展表：trip_enrichment / trip_reminder / 价格分档 / 生效规则 / 同义词 / 配置版本
    try:
        from app.services.extensions_seed import ensure_extensions
        print(f"[travel-api] P1/P2 扩展表就绪：{ensure_extensions()}")
    except Exception as exc:
        print(f"[travel-api] P1/P2 扩展表初始化失败（请检查 MySQL）：{exc}")
    # T8：仅当开启 FEATURE_SUBSCRIBE_MSG 时启动提醒扫描线程（daemon）
    try:
        from app.services.notify_service import start_scheduler
        start_scheduler()
    except Exception as exc:
        print(f"[travel-api] 订阅提醒调度启动失败：{exc}")
    yield
    try:
        from app.services.notify_service import stop_scheduler
        stop_scheduler()
    except Exception:
        pass


app = FastAPI(
    title="花溪区个性化旅游路线规划系统 API",
    version="1.0.0",
    description="游客端（小程序/PC）+ 管理端接口；游客支持账号注册登录与微信静默登录，管理端使用管理员账号登录。",
    lifespan=lifespan,
)

# 跨域：dev 放开便于本地联调；prod 收紧到备案域名白名单（设计方案 7.x / README 七）
# prod 未配置 CORS_ORIGINS 时默认拒绝全部跨站请求，由 preflight_release.py 报 FAIL。
_cors_origins = settings.cors_origins if settings.is_prod else ["*"]
if settings.is_prod and not _cors_origins:
    print("[travel-api][SECURITY][WARN] APP_ENV=prod 但 CORS_ORIGINS 未配置：已拒绝所有跨站请求")
app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"] if settings.is_prod else ["*"],
    allow_headers=["Authorization", "Content-Type", "X-Requested-With"] if settings.is_prod else ["*"],
)


@app.middleware("http")
async def prod_security_headers(request, call_next):
    """生产安全响应头：HSTS（仅 HTTPS 生效）、MIME 嗅探与引用来源收敛。"""
    response = await call_next(request)
    if settings.is_prod:
        response.headers.setdefault("Strict-Transport-Security", "max-age=31536000; includeSubDomains")
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
        response.headers.setdefault("X-Frame-Options", "DENY")
    return response

app.include_router(guest.router)
app.include_router(guest.modes_router)
app.include_router(user_auth.router)  # /auth/register、/auth/login、/auth/me、/auth/logout
app.include_router(weather.router)     # /weather（Open-Meteo 实况 + 15 天预报）、/location/resolve（高德地名解析）
# compare 必须先于 trips 注册：静态路径 /trips/compare 优先于动态 /trips/{trip_id}
app.include_router(compare.router)
app.include_router(trips.router)
# #14 预设主题路线（游学线）；管理端 A7 放在 admin 组之后注册
app.include_router(preset_routes.router)
# 认证路由先注册：/admin/login 为公开接口，不受 Bearer 校验影响
app.include_router(admin_auth.router)
app.include_router(admin.router)
app.include_router(admin_ext.router)
app.include_router(preset_routes.admin_router)
# 专属问答「问小旅」：游客端 /qa，管理端 /admin/qa（未配 LLM Key 时降级知识库直出）
app.include_router(qa.router)
app.include_router(qa_admin.router)

# 静态资源：POI 图片等（/static/poi/xxx.jpg）
_static_dir = BASE_DIR / "static"
_static_dir.mkdir(parents=True, exist_ok=True)
app.mount("/static", StaticFiles(directory=str(_static_dir)), name="static")


@app.get("/")
def root():
    return dict(
        name="花溪区个性化旅游路线规划系统",
        docs="/docs",
        guest_api="/api/v1",
        admin_api="/api/v1/admin",
    )


@app.get("/api/v1/health")
def health():
    # 仅回显非敏感的运行模式，便于部署后核对环境是否切到 prod
    return dict(
        status="ok",
        env=settings.APP_ENV,
        cors="whitelist" if settings.is_prod else "dev-open",
    )
