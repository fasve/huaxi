"""LLM 客户端：OpenAI 兼容 Chat Completions（云端 API / 本机 Ollama 通用）。

设计要点（对应设计方案 8.2「可选增强、故障不阻断主链路」）：

- 只负责「发请求 + 流式解析 + 错误归一」，不掺业务；prompt 组装在 `qa_service`；
- 统一 OpenAI 兼容协议：DeepSeek / 通义千问 / 智谱 / 本机 Ollama 只换 `.env` 里
  `LLM_BASE_URL` / `LLM_API_KEY` / `LLM_MODEL` 三项，业务代码零改动；
- `trust_env=False`：绕过系统 HTTP_PROXY（本机代理配置错误会让请求走错代理而 TLS 失败）；
- 瞬时错误（连接重置 / 超时 / 5xx）自动重试 1 次，降低偶发降级率；鉴权/限流/格式错误不重试；
- 所有失败归一为 `LlmError(code)`，由上层决定降级；**绝不把 API Key 写进日志/异常文本**。
"""
from __future__ import annotations

import json
import logging
import time
from collections.abc import Iterator

import httpx

from app.config import settings

log = logging.getLogger("travel.llm")

# 可重试的归一化错误码（瞬时故障；auth/rate_limit/bad_response/not_configured 不重试）
_RETRYABLE = ("timeout", "unavailable")


class LlmError(RuntimeError):
    """LLM 调用异常。

    code 取值：not_configured / timeout / auth / rate_limit / unavailable / bad_response
    """

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


def mask_key(value: str) -> str:
    """掩码显示：只保留尾 4 位。"""
    v = (value or "").strip()
    if not v:
        return ""
    if len(v) <= 4:
        return "*" * len(v)
    return "*" * (len(v) - 4) + v[-4:]


def configured() -> bool:
    """问答模块是否可用：FEATURE_QA_CHAT 打开且已配置 Key。"""
    return bool(settings.qa_enabled)


def thinking_supported() -> bool:
    """当前 provider 是否支持 `thinking` 参数（仅 DeepSeek 官方接口）。"""
    return "deepseek.com" in (settings.LLM_BASE_URL or "").lower()


def _thinking_payload() -> dict:
    """按 LLM_THINKING 生成思考模式参数（chat / stream 两条链路共用）。

    - on   -> {"thinking": {"type": "enabled"}}：开启思考（更慢更费 token，且忽略 temperature）
    - off  -> {"thinking": {"type": "disabled"}}：强制关闭
    - auto -> DeepSeek 官方接口默认关闭（短问答更快更省），其他 provider 不下发
    非 DeepSeek provider 一律不带该字段，避免 400。
    """
    if not thinking_supported():
        return {}
    mode = (settings.LLM_THINKING or "auto").strip().lower()
    if mode == "on":
        return {"thinking": {"type": "enabled"}}
    if mode == "off":
        return {"thinking": {"type": "disabled"}}
    return {"thinking": {"type": "disabled"}}  # auto：站内问答都是短回答，默认关思考


def _endpoint() -> str:
    return f"{settings.LLM_BASE_URL.rstrip('/')}/chat/completions"


def _headers() -> dict[str, str]:
    headers = {"Content-Type": "application/json"}
    key = (settings.LLM_API_KEY or "").strip()
    if key:
        headers["Authorization"] = f"Bearer {key}"
    return headers


def _timeout(override: float | None = None) -> httpx.Timeout:
    """连接/读取超时：每次调用实时读取配置（管理端改配置即生效）。"""
    read = float(override) if override else max(5, int(settings.LLM_TIMEOUT or 45))
    return httpx.Timeout(read, connect=10.0, write=10.0, pool=5.0)


def _payload(
    messages: list[dict],
    *,
    stream: bool,
    model: str | None = None,
    temperature: float | None = None,
    max_tokens: int | None = None,
) -> dict:
    payload = {
        "model": model or settings.LLM_MODEL,
        "messages": messages,
        "stream": stream,
        "temperature": settings.LLM_TEMPERATURE if temperature is None else temperature,
        "max_tokens": settings.LLM_MAX_TOKENS if max_tokens is None else max_tokens,
    }
    payload.update(_thinking_payload())
    return payload


def _raise_for_status(resp: httpx.Response) -> None:
    """HTTP 状态码 → 归一化错误码（不泄漏响应中的敏感信息）。"""
    if resp.status_code == 200:
        return
    if resp.status_code in (401, 403):
        raise LlmError("auth", "大模型鉴权失败（请检查 API Key）")
    if resp.status_code == 429:
        raise LlmError("rate_limit", "大模型调用频率超限")
    if resp.status_code >= 500:
        raise LlmError("unavailable", f"大模型服务异常（HTTP {resp.status_code}）")
    raise LlmError("bad_response", f"大模型请求失败（HTTP {resp.status_code}）")


def _chat_once(
    messages: list[dict],
    *,
    model: str | None,
    temperature: float | None,
    max_tokens: int | None,
    timeout: float | None,
) -> dict:
    payload = _payload(
        messages, stream=False, model=model,
        temperature=temperature, max_tokens=max_tokens,
    )
    try:
        with httpx.Client(timeout=_timeout(timeout), trust_env=False) as client:
            resp = client.post(_endpoint(), headers=_headers(), json=payload)
    except httpx.TimeoutException as exc:
        raise LlmError("timeout", "大模型响应超时") from exc
    except httpx.HTTPError as exc:
        raise LlmError("unavailable", "大模型服务连接失败") from exc

    _raise_for_status(resp)
    try:
        data = resp.json()
        answer = (data["choices"][0]["message"]["content"] or "").strip()
    except (KeyError, IndexError, TypeError, ValueError) as exc:
        raise LlmError("bad_response", "大模型返回格式异常") from exc
    if not answer:
        raise LlmError("bad_response", "大模型返回空内容")
    return {"answer": answer, "usage": data.get("usage") or {}}


def chat(
    messages: list[dict],
    *,
    model: str | None = None,
    temperature: float | None = None,
    max_tokens: int | None = None,
    timeout: float | None = None,
    force: bool = False,
) -> dict:
    """非流式调用，返回 {answer, usage}；失败抛 LlmError。

    force=True 时跳过「功能开关」检查（仅管理端测试连通性用，只要有 Key 就发请求）。
    timeout 可选：单次调用覆盖全局 LLM_TIMEOUT（如意图解析用更短的服务端超时）。
    瞬时故障（超时/连接失败/5xx）自动重试 1 次。
    """
    if not force and not configured():
        raise LlmError("not_configured", "问答服务未启用")
    if force and not (settings.LLM_API_KEY or "").strip():
        raise LlmError("not_configured", "尚未配置大模型 API Key")

    for attempt in (1, 2):
        try:
            return _chat_once(
                messages, model=model, temperature=temperature,
                max_tokens=max_tokens, timeout=timeout,
            )
        except LlmError as exc:
            if attempt == 1 and exc.code in _RETRYABLE:
                log.warning("[llm] chat %s，0.5s 后重试一次：%s", exc.code, exc.message)
                time.sleep(0.5)
                continue
            raise
    raise LlmError("unavailable", "大模型服务连接失败")  # pragma: no cover


def _iter_stream(payload: dict, timeout: float | None) -> Iterator[str]:
    """单次流式请求：解析 SSE，逐段 yield 文本增量。"""
    with httpx.Client(timeout=_timeout(timeout), trust_env=False) as client:
        with client.stream("POST", _endpoint(), headers=_headers(), json=payload) as resp:
            _raise_for_status(resp)
            for line in resp.iter_lines():
                line = (line or "").strip()
                if not line or line.startswith(":"):
                    continue
                if not line.startswith("data:"):
                    continue
                data = line[5:].strip()
                if data == "[DONE]":
                    break
                try:
                    chunk = json.loads(data)
                except ValueError:
                    continue
                choices = chunk.get("choices") or []
                if not choices:
                    continue
                delta = (choices[0].get("delta") or {}).get("content")
                if delta:
                    yield delta


def stream_chat(
    messages: list[dict],
    *,
    model: str | None = None,
    temperature: float | None = None,
    max_tokens: int | None = None,
    timeout: float | None = None,
) -> Iterator[str]:
    """流式调用：逐段 yield 文本增量；失败抛 LlmError。

    仅当「还没吐出任何内容」时对瞬时故障重试 1 次；已输出部分则直接报错，避免前端拼接错乱。
    """
    if not configured():
        raise LlmError("not_configured", "问答服务未启用")

    payload = _payload(
        messages, stream=True, model=model,
        temperature=temperature, max_tokens=max_tokens,
    )
    for attempt in (1, 2):
        produced = False
        try:
            for delta in _iter_stream(payload, timeout):
                produced = True
                yield delta
        except LlmError as exc:
            if attempt == 1 and not produced and exc.code in _RETRYABLE:
                log.warning("[llm] stream %s，0.5s 后重试一次：%s", exc.code, exc.message)
                time.sleep(0.5)
                continue
            raise
        except httpx.TimeoutException as exc:
            if attempt == 1 and not produced:
                log.warning("[llm] stream 超时，0.5s 后重试一次")
                time.sleep(0.5)
                continue
            raise LlmError("timeout", "大模型响应超时") from exc
        except httpx.HTTPError as exc:
            if attempt == 1 and not produced:
                log.warning("[llm] stream 连接失败，0.5s 后重试一次")
                time.sleep(0.5)
                continue
            raise LlmError("unavailable", "大模型服务连接失败") from exc

        if not produced:
            if attempt == 1:
                log.warning("[llm] stream 未返回内容，0.5s 后重试一次")
                time.sleep(0.5)
                continue
            raise LlmError("bad_response", "大模型未返回任何内容")
        return
