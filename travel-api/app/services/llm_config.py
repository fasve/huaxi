"""大模型运行时配置（问答管理端「模型配置」用）。

设计要点：
- **热生效**：管理端保存后直接改 `settings` 对象属性，`llm_client` 每次调用实时读取，
  不需要重启后端；
- **可持久化**：同时写回 `travel-api/.env`，重启后仍生效；
- **密钥安全**：`api_key` 只存服务端 `.env`，接口只回掩码；传入空值或掩码值时保持原值不变；
- 校验集中在 `update()`，非法值抛 `ValueError`，由路由层转成 400。
"""
from __future__ import annotations

from app.config import settings
from app.services import llm_client
from app.services import provider_keys

# 对外字段 → (settings 属性名, .env 变量名, 类型)
_FIELDS: dict[str, tuple[str, str, type]] = {
    "enabled": ("FEATURE_QA_CHAT", "FEATURE_QA_CHAT", bool),
    "base_url": ("LLM_BASE_URL", "LLM_BASE_URL", str),
    "model": ("LLM_MODEL", "LLM_MODEL", str),
    "thinking": ("LLM_THINKING", "LLM_THINKING", str),
    "api_key": ("LLM_API_KEY", "LLM_API_KEY", str),
    "timeout": ("LLM_TIMEOUT", "LLM_TIMEOUT", int),
    "max_tokens": ("LLM_MAX_TOKENS", "LLM_MAX_TOKENS", int),
    "temperature": ("LLM_TEMPERATURE", "LLM_TEMPERATURE", float),
    "daily_limit": ("QA_DAILY_LIMIT", "QA_DAILY_LIMIT", int),
    "anon_daily_limit": ("QA_ANON_DAILY_LIMIT", "QA_ANON_DAILY_LIMIT", int),
}

_SECRET_FIELDS = {"api_key"}


def _mask(value: str) -> str:
    return llm_client.mask_key(value)


def snapshot() -> dict:
    """当前配置（api_key 只回掩码）。"""
    key = (settings.LLM_API_KEY or "").strip()
    return dict(
        enabled=bool(settings.FEATURE_QA_CHAT),
        configured=bool(settings.qa_enabled),
        base_url=settings.LLM_BASE_URL,
        model=settings.LLM_MODEL,
        # 思考模式：auto / on / off（三档都只在 DeepSeek 官方接口下发）
        thinking=str(settings.LLM_THINKING or "auto"),
        # 当前 Base URL 是否真正支持 thinking 参数；false 时管理端可提示"该 provider 已忽略"
        thinking_effective=llm_client.thinking_supported(),
        api_key_masked=_mask(key),
        api_key_configured=bool(key),
        timeout=int(settings.LLM_TIMEOUT),
        max_tokens=int(settings.LLM_MAX_TOKENS),
        temperature=float(settings.LLM_TEMPERATURE),
        daily_limit=int(settings.QA_DAILY_LIMIT),
        anon_daily_limit=int(settings.QA_ANON_DAILY_LIMIT),
        # 前端提示用
        effective_model=f"{settings.LLM_BASE_URL.rstrip('/')} · {settings.LLM_MODEL}",
    )


def _coerce(name: str, value, typ: type):
    """把 JSON 值安全转换成目标类型；失败抛 ValueError。"""
    if typ is bool:
        if isinstance(value, bool):
            return value
        if isinstance(value, (int, float)):
            return bool(value)
        if isinstance(value, str):
            return value.strip().lower() in ("1", "true", "yes", "on")
        raise ValueError(f"{name} 需要布尔值")
    if typ is int:
        try:
            n = int(value)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"{name} 需要整数") from exc
        return n
    if typ is float:
        try:
            return float(value)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"{name} 需要数字") from exc
    return str(value).strip()


def _validate(name: str, value):
    """业务校验（返回清洗后的值）。"""
    # .env 以换行分隔变量：值里出现 \r/\n 会被拆成多行，等于可注入任意环境变量
    if isinstance(value, str) and any(ch in value for ch in "\r\n"):
        raise ValueError(f"{name} 不能包含换行符")
    if name == "base_url":
        if not value.startswith(("http://", "https://")):
            raise ValueError("base_url 必须以 http:// 或 https:// 开头")
        return value.rstrip("/")
    if name == "model":
        if not value or len(value) > 100:
            raise ValueError("model 不能为空且不超过 100 字符")
        return value
    if name == "thinking":
        mode = str(value).strip().lower()
        if mode not in ("auto", "on", "off"):
            raise ValueError("thinking 只允许 auto / on / off")
        return mode
    if name == "api_key":
        return value.strip()
    if name == "timeout":
        if not (5 <= value <= 300):
            raise ValueError("timeout 需在 5~300 秒之间")
        return value
    if name == "max_tokens":
        if not (64 <= value <= 8192):
            raise ValueError("max_tokens 需在 64~8192 之间")
        return value
    if name == "temperature":
        if not (0.0 <= value <= 2.0):
            raise ValueError("temperature 需在 0~2 之间")
        return round(value, 2)
    if name in ("daily_limit", "anon_daily_limit"):
        if not (0 <= value <= 100000):
            raise ValueError("每日提问上限需在 0~100000 之间")
        return value
    return value


def update(payload: dict) -> dict:
    """保存配置：校验 → 写回 .env → 热更新 settings → 返回最新快照。"""
    updates: dict[str, object] = {}
    for name, raw in (payload or {}).items():
        if name not in _FIELDS or raw is None:
            continue
        _, _, typ = _FIELDS[name]
        # 密钥：空值 / 掩码值表示「保持原样」
        if name in _SECRET_FIELDS:
            text = str(raw).strip()
            if not text or "*" in text:
                continue
            updates[name] = _validate(name, text)
            continue
        updates[name] = _validate(name, _coerce(name, raw, typ))

    if not updates:
        return snapshot()

    # 1) 写回 .env（持久化）
    for name, value in updates.items():
        _, env_name, _ = _FIELDS[name]
        provider_keys.write_env_value(env_name, str(value).lower() if isinstance(value, bool) else str(value))

    # 2) 热更新进程内配置（llm_client 每次调用实时读取，无需重启）
    for name, value in updates.items():
        attr, _, _ = _FIELDS[name]
        setattr(settings, attr, value)

    return snapshot()
