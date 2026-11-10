"""
本地 Ollama 模型实现。

对外接口与 models.remote 完全一致：
    invoke_llm(prompt: str) -> str
    stream_llm(prompt: str) -> Iterator[str]

模型固定指向 Ollama 中的 qwen2.5:7b-instruct-q5_K_M（可通过 OLLAMA_MODEL 覆盖）。
仅使用标准库，不引入额外依赖。
"""

from __future__ import annotations

import json
import logging
import urllib.error
import urllib.request
from typing import Iterator

from config import OLLAMA_HOST, OLLAMA_MODEL, OLLAMA_TIMEOUT
from cache import cache_get, cache_key, cache_put
from usage import record_usage

logger = logging.getLogger(__name__)


def _api_url() -> str:
    return OLLAMA_HOST.rstrip("/") + "/api/generate"


def _post(payload: dict):
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        _api_url(),
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        return urllib.request.urlopen(req, timeout=OLLAMA_TIMEOUT)
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")[:500]
        if e.code == 404:
            raise RuntimeError(
                f"Ollama 接口 404：请确认 `ollama serve` 已运行且模型 {OLLAMA_MODEL!r} 已 pull。url={_api_url()} body={body}"
            )
        raise RuntimeError(f"Ollama HTTP {e.code}：{body}")
    except urllib.error.URLError as e:
        raise RuntimeError(f"Ollama 连接失败：{e}（地址 {OLLAMA_HOST}）")


def _generate(prompt: str, stream: bool):
    payload = {"model": OLLAMA_MODEL, "prompt": prompt, "stream": stream}
    resp = _post(payload)

    if not stream:
        raw = resp.read().decode("utf-8", errors="replace")
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            raise RuntimeError(f"Ollama 返回非 JSON：{raw[:500]}")
        text = data.get("response")
        if text is None:
            raise RuntimeError(f"Ollama 响应缺少 response 字段：{raw[:500]}")
        return text, int(data.get("prompt_eval_count") or 0), int(data.get("eval_count") or 0)

    def _iter():
        in_tokens = out_tokens = 0
        for line in resp:
            if not line:
                continue
            try:
                chunk = json.loads(line.decode("utf-8", errors="replace"))
            except json.JSONDecodeError:
                continue
            in_tokens = int(chunk.get("prompt_eval_count") or in_tokens)
            out_tokens = int(chunk.get("eval_count") or out_tokens)
            piece = chunk.get("response")
            if piece:
                yield piece
            if chunk.get("done"):
                break
        record_usage(in_tokens, out_tokens, model=OLLAMA_MODEL)

    return _iter()


def invoke_llm(prompt: str) -> str:
    """与 llm.invoke_llm 同签名：输入 prompt，返回完整文本；命中磁盘缓存则不发请求"""
    key = cache_key(prompt, provider="local", model=OLLAMA_MODEL)
    cached = cache_get(key)
    if cached is not None:
        record_usage(model=OLLAMA_MODEL, cached=True)
        return cached

    text, in_tokens, out_tokens = _generate(prompt, stream=False)
    record_usage(in_tokens, out_tokens, model=OLLAMA_MODEL)
    cache_put(key, text)
    return text


def stream_llm(prompt: str) -> Iterator[str]:
    """与 llm.stream_llm 同签名：逐块 yield 文本；命中缓存时回放，不发请求"""
    key = cache_key(prompt, provider="local", model=OLLAMA_MODEL)
    cached = cache_get(key)
    if cached is not None:
        record_usage(model=OLLAMA_MODEL, cached=True)
        for i in range(0, len(cached), 40):
            yield cached[i:i + 40]
        return

    parts: list[str] = []
    for piece in _generate(prompt, stream=True):
        parts.append(piece)
        yield piece
    cache_put(key, "".join(parts))
