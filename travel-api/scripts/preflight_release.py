#!/usr/bin/env python3
"""上线前自检：M0 / M6 的机器可检项 + 人工流程清单汇总（设计方案 7.x / 7.10）。

用法：
  python travel-api/scripts/preflight_release.py
  python travel-api/scripts/preflight_release.py --env deploy/env/.env.prod.example
  python travel-api/scripts/preflight_release.py --env /srv/travel/.env --strict
  python travel-api/scripts/preflight_release.py --json

退出码：默认 0（仅报告）；--strict 时存在 FAIL 或阻塞待办返回 1，可接 CI / 发布门禁。
不依赖第三方库，仅使用标准库；不连接数据库、不发送网络请求、不打印密钥内容。
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:  # 非交互环境或旧解释器
    pass

ROOT = Path(__file__).resolve().parents[2]
API = ROOT / "travel-api"
MINI = ROOT / "travel-miniapp"
PORTAL = ROOT / "travel-portal"
WEB = ROOT / "travel-web"
DEPLOY = ROOT / "deploy"
CHECKLIST = DEPLOY / "release-checklist.json"

PLACEHOLDER = re.compile(
    r"(example\.|test_|your_|change_me|changeme|请|xxx|localhost|127\.0\.0\.1|touristappid)",
    re.I,
)
BANNED_WORDS = ("预订", "下单", "购买", "代订")
NEGATIONS = (
    "不提供", "不含", "不涉及", "不得", "不用于", "禁止", "不收集", "不做",
    "避免", "红线", "禁用", "无交易", "不启用",
)


def read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return ""


def read_env(path: Path) -> dict[str, str]:
    data: dict[str, str] = {}
    for line in read_text(path).splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        data[key.strip()] = value.strip().strip('"').strip("'")
    return data


def is_placeholder(value: str) -> bool:
    return not value or bool(PLACEHOLDER.search(value))


def https_ok(value: str) -> bool:
    return value.startswith("https://") and not is_placeholder(value)


def add(rows: list[dict], name: str, ok: bool, detail: str = "", severity: str = "FAIL") -> None:
    rows.append({
        "name": name,
        "level": "PASS" if ok else severity,
        "ok": bool(ok),
        "detail": detail,
    })


def frontend_files() -> list[Path]:
    files: list[Path] = []
    for pattern in ("*.js", "*.wxml"):
        files.extend(MINI.rglob(pattern))
    for base in (PORTAL / "src", WEB / "src"):
        for pattern in ("*.vue", "*.ts"):
            files.extend(base.rglob(pattern))
    return files


def auto_checks(env_path: Path) -> list[dict]:
    rows: list[dict] = []
    env = read_env(env_path)

    add(rows, "环境文件可读", env_path.exists(), str(env_path))
    add(rows, "APP_ENV=prod", env.get("APP_ENV", "").lower() in ("prod", "production"),
        "当前=%s" % (env.get("APP_ENV") or "未设置"))
    add(rows, "MOCK_LOGIN=false（真实 code2session）",
        env.get("MOCK_LOGIN", "").lower() == "false", env.get("MOCK_LOGIN") or "未设置")
    add(rows, "微信 AppID 已替换占位值",
        bool(env.get("WECHAT_APPID")) and not is_placeholder(env["WECHAT_APPID"]))
    add(rows, "微信 AppSecret 已替换占位值",
        bool(env.get("WECHAT_SECRET")) and not is_placeholder(env["WECHAT_SECRET"]))
    add(rows, "JWT_SECRET 已轮换（≥32 位且非模板值）",
        len(env.get("JWT_SECRET", "")) >= 32 and not is_placeholder(env.get("JWT_SECRET", "")))
    dev_secret = read_env(API / ".env").get("JWT_SECRET", "")
    add(rows, "JWT_SECRET 未沿用本地开发密钥",
        not (dev_secret and env.get("JWT_SECRET") == dev_secret), "", "WARN")
    add(rows, "ALLOW_LEGACY_HMAC_TOKEN=false",
        env.get("ALLOW_LEGACY_HMAC_TOKEN", "").lower() == "false")
    add(rows, "FEATURE_* 增强开关保持关闭",
        env.get("FEATURE_ROUTE_API", "").lower() == "false"
        and env.get("FEATURE_AI_POLISH", "").lower() == "false")

    origins = [o.strip() for o in env.get("CORS_ORIGINS", "").split(",") if o.strip()]
    add(rows, "CORS_ORIGINS 为非占位的 HTTPS 白名单",
        bool(origins) and all(https_ok(o) for o in origins),
        "%d 项" % len(origins))
    for key in ("PUBLIC_API_ORIGIN", "PORTAL_ORIGIN", "ADMIN_ORIGIN", "CDN_ORIGIN"):
        add(rows, "%s 已规划为 HTTPS 站点" % key, https_ok(env.get(key, "")),
            env.get(key, "") or "未设置")
    add(rows, "ICP 备案号已填写", bool(env.get("ICP_NO")) and "00000000" not in env["ICP_NO"],
        env.get("ICP_NO", "") or "未设置")
    add(rows, "隐私联系邮箱已替换", bool(env.get("PRIVACY_CONTACT"))
        and "@example." not in env.get("PRIVACY_CONTACT", ""))
    add(rows, "数据库使用非 root 最小权限账号",
        bool(env.get("DB_USER")) and env.get("DB_USER") != "root", env.get("DB_USER", "") or "未设置")
    add(rows, "管理端默认口令已修改",
        bool(env.get("ADMIN_BOOTSTRAP_PASSWORD"))
        and env.get("ADMIN_BOOTSTRAP_PASSWORD") not in ("admin123",)
        and not is_placeholder(env.get("ADMIN_BOOTSTRAP_PASSWORD", "")))
    add(rows, ".env 已被 .gitignore 忽略", ".env" in read_text(ROOT / ".gitignore"))

    secret = env.get("WECHAT_SECRET", "")
    if secret and not is_placeholder(secret):
        leaked = [str(f.relative_to(ROOT)) for f in frontend_files() if secret in read_text(f)]
        add(rows, "AppSecret 未泄漏到前端代码", not leaked, "; ".join(leaked[:3]))
    else:
        add(rows, "AppSecret 未泄漏到前端代码（占位环境跳过比对）", False,
            "填入真实 secret 后会重新扫描", "WARN")

    # ---- 小程序：域名 / 隐私页 / AppID ----
    cfg = read_text(MINI / "utils" / "config.js")
    add(rows, "小程序域名按 develop/trial/release 自动切换", "detectEnv" in cfg and "DOMAINS" in cfg)
    for stage in ("trial", "release"):
        block = re.search(r"%s:\s*\{(.*?)\}" % stage, cfg, re.S)
        urls = re.findall(r"https?://[^\s'\"]+", block.group(1)) if block else []
        add(rows, "小程序 %s 域名为 HTTPS 且无占位" % stage,
            bool(urls) and all(https_ok(u) for u in urls), "; ".join(urls) or "未找到")

    try:
        app_json = json.loads(read_text(MINI / "app.json"))
        pages = app_json.get("pages", [])
    except Exception:
        pages = []
    add(rows, "app.json 已注册隐私指引页", "pages/privacy/privacy" in pages)
    privacy_files = ["privacy.js", "privacy.json", "privacy.wxml", "privacy.wxss"]
    add(rows, "隐私指引四件套齐全",
        all((MINI / "pages" / "privacy" / f).exists() for f in privacy_files))
    add(rows, "首次启动同意弹窗已实现",
        "ensurePrivacyConsent" in read_text(MINI / "app.js"))
    add(rows, "「我的」页可查看指引并撤回同意",
        "withdrawConsent" in read_text(MINI / "pages" / "mine" / "mine.js"))
    try:
        appid = json.loads(read_text(MINI / "project.config.json")).get("appid", "")
    except Exception:
        appid = ""
    add(rows, "project.config.json 已填入真实 AppID",
        bool(appid) and appid != "touristappid" and not is_placeholder(appid), appid)

    # ---- PC / 管理端 ----
    add(rows, "PC 隐私指引静态页已提供",
        (PORTAL / "public" / "privacy.html").exists()
        and "隐私保护指引" in read_text(PORTAL / "public" / "privacy.html"))
    portal_app = read_text(PORTAL / "src" / "App.vue")
    web_app = read_text(WEB / "src" / "App.vue")
    # dev fallback 允许保留 localhost，但生产值必须来自 VITE_* 且模板用动态绑定
    add(rows, "PC 端管理入口改为可配置域名",
        "VITE_ADMIN_URL" in portal_app and ':href="adminUrl"' in portal_app)
    add(rows, "管理端游客入口改为可配置域名",
        "VITE_PORTAL_URL" in web_app and ':href="portalUrl"' in web_app)
    add(rows, "PC 页脚含隐私指引入口与备案占位",
        "/privacy.html" in portal_app and "VITE_ICP_NO" in portal_app)

    # ---- 类目文案红线（方案 7.2：一期不得出现交易类表述）----
    hits: list[str] = []
    for f in frontend_files():
        if f.name in ("privacy.js", "privacy.wxml"):
            continue
        for lineno, line in enumerate(read_text(f).splitlines(), 1):
            s = line.strip()
            if not any(w in s for w in BANNED_WORDS):
                continue
            if any(n in s for n in NEGATIONS) or s.startswith(("//", "*", "<!--", "#")):
                continue
            hits.append("%s:%d %s" % (f.relative_to(ROOT), lineno, s[:70]))
    add(rows, "类目文案红线（无交易类表述）", not hits,
        "; ".join(hits[:3]) or "已扫描 %d 个前端源文件" % len(frontend_files()))

    # ---- 部署文件 ----
    nginx_tpl = DEPLOY / "nginx" / "travel.conf.example"
    add(rows, "Nginx HTTPS 模板就绪",
        nginx_tpl.exists() and "ssl_protocols" in read_text(nginx_tpl))
    nginx_real = DEPLOY / "nginx" / "travel.conf"
    if nginx_real.exists():
        add(rows, "生产 Nginx 配置已替换占位域名",
            "example.cn" not in read_text(nginx_real))
    else:
        add(rows, "生产 Nginx 配置已落地", False,
            "尚未从 travel.conf.example 复制为 travel.conf", "WARN")
    add(rows, "合法域名登记表已提供", (DEPLOY / "legal-domains.md").exists())

    for project, key in (("travel-portal", "VITE_ADMIN_URL"), ("travel-web", "VITE_PORTAL_URL")):
        p = ROOT / project / ".env.production"
        if not p.exists():
            add(rows, "%s 构建变量已配置" % project, False,
                "缺少 .env.production（见 deploy/env/.env.production.example）", "WARN")
        else:
            value = read_env(p).get(key, "")
            add(rows, "%s %s 指向 HTTPS 站点" % (project, key), https_ok(value), value)

    # ---- 工程侧已落地项（恒定核对，防止后续改动回退）----
    backend = read_text(API / "app" / "main.py")
    add(rows, "后端 prod CORS 白名单与安全头已实现",
        "settings.is_prod" in backend and "Strict-Transport-Security" in backend)
    add(rows, "后端 /health 回显运行模式", "env=settings.APP_ENV" in backend)
    return rows


def manual_items(phase: str | None) -> tuple[list[dict], str]:
    if not CHECKLIST.exists():
        return [], "缺少 %s" % CHECKLIST
    try:
        data = json.loads(read_text(CHECKLIST))
    except Exception as exc:
        return [], "解析失败：%s" % exc
    items = data.get("items", [])
    if phase:
        items = [i for i in items if i.get("phase") == phase]
    return items, data.get("note", "")


def main() -> int:
    parser = argparse.ArgumentParser(description="花溪旅行上线前自检（M0 / M6）")
    parser.add_argument("--env", default=str(API / ".env"), help="待检查的环境文件路径")
    parser.add_argument("--phase", choices=["M0", "M6"], help="只显示某个里程碑的人工项")
    parser.add_argument("--strict", action="store_true", help="存在 FAIL 或阻塞待办时返回退出码 1")
    parser.add_argument("--json", action="store_true", help="以 JSON 输出，便于 CI 消费")
    args = parser.parse_args()

    env_path = Path(args.env)
    if not env_path.is_absolute():
        env_path = ROOT / env_path
    rows = auto_checks(env_path)
    items, note = manual_items(args.phase)

    passed = sum(1 for r in rows if r["level"] == "PASS")
    failed = sum(1 for r in rows if r["level"] == "FAIL")
    warned = sum(1 for r in rows if r["level"] == "WARN")
    done = sum(1 for i in items if i.get("status") == "done")
    pending = [i for i in items if i.get("status") not in ("done", "na")]
    blocking = [i for i in pending if i.get("blocking")]

    if args.json:
        print(json.dumps({
            "env_file": str(env_path), "auto": rows, "manual": items,
            "summary": {"pass": passed, "fail": failed, "warn": warned,
                        "manual_done": done, "manual_pending": len(pending),
                        "blocking_pending": len(blocking)},
        }, ensure_ascii=False, indent=2))
    else:
        print("=" * 66)
        print("花溪旅行 · 上线前自检（M0 合规启动 / M6 提审上线）")
        print("环境文件：%s" % env_path)
        print("=" * 66)
        print("\n[一] 自动检查（代码与配置）")
        for r in rows:
            tail = (" — " + r["detail"]) if r["detail"] else ""
            print("  [%s] %s%s" % (r["level"], r["name"], tail))
        print("\n[二] 人工流程清单（deploy/release-checklist.json）")
        print("  说明：%s" % note[:120])
        for i in items:
            flag = i.get("status", "todo").upper()
            mark = "!" if i.get("blocking") and flag not in ("DONE", "NA") else " "
            print("  %s[%s] %s %s · %s" % (
                mark, flag, i.get("id"), i.get("item"), i.get("owner", "")))
            if i.get("evidence"):
                print("       凭证：%s" % i["evidence"])
        print("\n" + "-" * 66)
        print("汇总：自动 PASS %d / FAIL %d / WARN %d；人工 done %d，待办 %d（其中阻塞 %d）"
              % (passed, failed, warned, done, len(pending), len(blocking)))
        if failed or blocking:
            print("结论：当前仍为 dev 状态，不具备提审条件；按 FAIL 与阻塞项逐条办理。")
            print("      代码侧可交付物已就绪，待企业主体在平台侧完成备案 / 类目 / 域名 / 提审。")
        else:
            print("结论：自动检查全绿且无阻塞待办，可按 7.10 流程提交审核。")

    if args.strict and (failed or blocking):
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
