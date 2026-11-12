"""图片源 API Key 运行时配置。

图片源（Pixabay / Pexels）需要免费 API key。这些 key：
- 可在管理端「系统设置 → 图片源」里直接填写，无需改代码、无需重启；
- 持久化在 travel-api/.env 中（该文件已被 .gitignore 忽略，不会入库）；
- 读取时优先用进程环境变量，其次用本模块的运行时缓存，最后读 .env。

安全提醒：key 只写服务端 .env，**绝不下发到浏览器**，管理端接口只回传
「是否已配置」和掩码后的尾号，不回传明文。
"""
from __future__ import annotations

import os
import re
from pathlib import Path

from app.config import BASE_DIR

ENV_FILE = Path(BASE_DIR) / ".env"

# 支持在管理端配置的 key 名称 → 环境变量名
_KEY_FIELDS = {
    "pixabay": "PIXABAY_API_KEY",
    "pexels": "PEXELS_API_KEY",
}

# 进程内运行时缓存（管理端设置后立即生效）
_runtime: dict[str, str] = {}


def _read_env_file() -> dict[str, str]:
    """解析 .env 为 dict（只取 KEY=value 形式）。"""
    out: dict[str, str] = {}
    if not ENV_FILE.exists():
        return out
    for raw in ENV_FILE.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, _, v = line.partition("=")
        out[k.strip()] = v.strip()
    return out


def get_key(name: str) -> str:
    """取某个源的 API key：运行时缓存 > 进程环境变量 > .env。"""
    env_name = _KEY_FIELDS.get(name)
    if not env_name:
        return ""
    if name in _runtime:
        return _runtime[name]
    val = os.getenv(env_name, "").strip()
    if val:
        return val
    return _read_env_file().get(env_name, "").strip()


def set_key(name: str, value: str) -> None:
    """设置 key：写入运行时缓存 + 持久化到 .env。"""
    env_name = _KEY_FIELDS.get(name)
    if not env_name:
        raise KeyError(f"未知的图片源：{name}")
    value = (value or "").strip()
    _runtime[name] = value
    _write_env(env_name, value)


def clear_key(name: str) -> None:
    set_key(name, "")


def _write_env(env_name: str, value: str) -> None:
    """把 key 写回 .env，保留其余内容与注释。"""
    ENV_FILE.parent.mkdir(parents=True, exist_ok=True)
    lines = ENV_FILE.read_text(encoding="utf-8").splitlines() if ENV_FILE.exists() else []
    pattern = re.compile(rf"^\s*{re.escape(env_name)}\s*=")
    replaced = False
    out: list[str] = []
    for line in lines:
        if pattern.match(line):
            out.append(f"{env_name}={value}")
            replaced = True
        else:
            out.append(line)
    if not replaced:
        if out and out[-1].strip():
            out.append("")
        out.append(f"{env_name}={value}")
    ENV_FILE.write_text("\n".join(out) + "\n", encoding="utf-8")


def mask(value: str) -> str:
    """掩码显示：只保留尾 4 位。"""
    v = (value or "").strip()
    if not v:
        return ""
    if len(v) <= 4:
        return "*" * len(v)
    return "*" * (len(v) - 4) + v[-4:]


def status() -> list[dict]:
    """各源的 key 配置状态（不回传明文）。"""
    out = []
    for name, env_name in _KEY_FIELDS.items():
        val = get_key(name)
        out.append(dict(
            name=name, env_name=env_name, configured=bool(val),
            masked=mask(val),
        ))
    return out
