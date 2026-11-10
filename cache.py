"""
LLM 磁盘缓存（diskcache）。

键 = sha256(CACHE_VERSION + provider + model + 采样参数 + 规范化 prompt)
    - messages / prompt 顺序敏感，不做排序；只统一换行、压缩多余空白。
    - CACHE_VERSION 在 prompt 模板/缓存格式大改，或任何影响输出的代码逻辑变更时 +1，
      强制旧缓存失效（改 prompt 文字会自动换键，但代码逻辑变化不会）。
    - 换模型或改 temperature / top_p 都会改变键，互不命中。

只缓存完整文本（非流式）；流式输出见 models.* 中的说明。
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import threading

from diskcache import Cache

from config import (
    CACHE_DIR,
    CACHE_ENABLED,
    CACHE_VERSION,
    LLM_TEMPERATURE,
    LLM_TOP_P,
)

logger = logging.getLogger(__name__)

_lock = threading.Lock()
_cache: Cache | None = None
_stats = {"hit": 0, "miss": 0}


def _get_cache() -> Cache | None:
    """懒加载缓存目录；CACHE_ENABLED=0 时返回 None（全部视为未命中）"""
    global _cache
    if not CACHE_ENABLED:
        return None
    if _cache is None:
        with _lock:
            if _cache is None:
                os.makedirs(CACHE_DIR, exist_ok=True)
                _cache = Cache(CACHE_DIR)
    return _cache


def normalize(prompt: str) -> str:
    """只做无害规范化：统一换行符、行内空白压缩、去掉首尾空白"""
    text = prompt.replace("\r\n", "\n").replace("\r", "\n")
    return "\n".join(" ".join(line.split()) for line in text.split("\n")).strip()


def cache_key(prompt: str, *, provider: str, model: str) -> str:
    """生成缓存键（hex），采样参数与模型都参与哈希"""
    payload = {
        "version": CACHE_VERSION,
        "provider": provider,
        "model": model,
        "sampling": {"temperature": LLM_TEMPERATURE, "top_p": LLM_TOP_P},
        "prompt": normalize(prompt),
    }
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def cache_get(key: str) -> str | None:
    """命中返回缓存文本，未命中返回 None；同时打印并累计 hit / miss"""
    store = _get_cache()
    value = store.get(key) if store is not None else None
    if value is None:
        with _lock:
            _stats["miss"] += 1
        print("   🌐 cache miss（调用 API）")
        logger.info(f"[cache] miss key={key[:12]}")
        return None
    with _lock:
        _stats["hit"] += 1
    print("   ⚡ cache hit（复用本地结果，不发请求）")
    logger.info(f"[cache] hit key={key[:12]}")
    return value


def cache_put(key: str, value: str) -> None:
    """写入缓存；失败只告警，不影响主流程"""
    store = _get_cache()
    if store is None:
        return
    try:
        store.set(key, value)
    except Exception as e:
        logger.warning(f"[cache] 写入失败，忽略：{e}")


def stats() -> dict[str, int]:
    """本次进程的命中统计"""
    with _lock:
        return dict(_stats)


def reset_stats() -> None:
    with _lock:
        _stats["hit"] = 0
        _stats["miss"] = 0
