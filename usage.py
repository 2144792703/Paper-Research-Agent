"""
单次 run 的 token 与成本统计。

成本口径：
    成本 = Σ 每次调用 (input_tokens × 输入单价 + output_tokens × 输出单价)

单价来源（按优先级）：
    1. .env 显式覆盖 MODEL_PRICE_INPUT_PER_1M / MODEL_PRICE_OUTPUT_PER_1M（美元/百万 token）
    2. litellm 价格表 prices/model_prices_and_context_window.json（美元/token）
    3. 都查不到 -> 只报 token，不硬算钱

缓存命中的调用不计 token、不计成本，只累加命中次数。
"""

from __future__ import annotations

import json
import logging
import os
import re
import threading

from config import (
    MODEL_PRICE_INPUT_PER_1M,
    MODEL_PRICE_OUTPUT_PER_1M,
    MODEL_PRICES_PATH,
    USD_TO_CNY,
)

logger = logging.getLogger(__name__)

_lock = threading.Lock()
_by_model: dict[str, dict[str, int]] = {}
_calls = 0
_cached_calls = 0

_price_table: dict | None = None
_lower_index: dict[str, dict] | None = None


def _load_price_table() -> dict:
    """懒加载价格表；文件缺失或损坏时退化为空表（只报 token）"""
    global _price_table, _lower_index
    if _price_table is None:
        try:
            with open(MODEL_PRICES_PATH, encoding="utf-8") as f:
                raw = json.load(f)
            raw.pop("sample_spec", None)
            _price_table = raw
            _lower_index = {k.lower(): v for k, v in raw.items()}
        except Exception as e:
            logger.warning(f"[cost] 价格表加载失败，仅统计 token：{e}")
            _price_table = {}
            _lower_index = {}
    return _price_table


def _price_per_token(model: str | None):
    """返回 (输入单价, 输出单价)，单位美元/token；查不到返回 None"""
    if MODEL_PRICE_INPUT_PER_1M is not None and MODEL_PRICE_OUTPUT_PER_1M is not None:
        return MODEL_PRICE_INPUT_PER_1M / 1e6, MODEL_PRICE_OUTPUT_PER_1M / 1e6
    if not model:
        return None
    table = _load_price_table()
    if not table:
        return None

    candidates = [model]
    if "/" in model:
        candidates.append(model.split("/", 1)[1])  # openai/gpt-4o -> gpt-4o

    for name in candidates:
        entry = table.get(name) or (_lower_index or {}).get(name.lower())
        if not entry:
            continue
        in_cost = entry.get("input_cost_per_token")
        out_cost = entry.get("output_cost_per_token")
        if in_cost is not None and out_cost is not None:
            return float(in_cost), float(out_cost)
    return None


def _price_table_date() -> str | None:
    """读价格表旁 MANIFEST.md 的抓取日期（缺文件返回 None），用于标注快照新鲜度"""
    try:
        manifest = os.path.join(os.path.dirname(MODEL_PRICES_PATH), "MANIFEST.md")
        with open(manifest, encoding="utf-8") as f:
            for line in f:
                m = re.search(r"抓取日期[：:]\s*(\d{4}-\d{2}-\d{2})", line)
                if m:
                    return m.group(1)
    except Exception:
        pass
    return None


def record_usage(input_tokens: int = 0, output_tokens: int = 0, *, model: str | None = None, cached: bool = False) -> None:
    """累加一次调用的用量；cached=True 时只记命中次数（token 为 0）"""
    global _calls, _cached_calls
    with _lock:
        _calls += 1
        if cached:
            _cached_calls += 1
            return
        slot = _by_model.setdefault(model or "unknown", {"input": 0, "output": 0})
        slot["input"] += int(input_tokens or 0)
        slot["output"] += int(output_tokens or 0)


def reset() -> None:
    """每次 run 开始前清零"""
    global _calls, _cached_calls
    with _lock:
        _by_model.clear()
        _calls = 0
        _cached_calls = 0


def summary() -> dict:
    """汇总本次 run：token、调用次数、命中次数、估算成本"""
    with _lock:
        by_model = {name: dict(t) for name, t in _by_model.items()}
        calls = _calls
        cached_calls = _cached_calls

    input_total = sum(t["input"] for t in by_model.values())
    output_total = sum(t["output"] for t in by_model.values())

    cost_usd = 0.0
    unpriced: list[str] = []
    for name, t in by_model.items():
        price = _price_per_token(name)
        if price is None:
            unpriced.append(name)
            continue
        cost_usd += t["input"] * price[0] + t["output"] * price[1]

    priced = not unpriced
    return {
        "input_tokens": input_total,
        "output_tokens": output_total,
        "total_tokens": input_total + output_total,
        "calls": calls,
        "cached_calls": cached_calls,
        "models": by_model,
        "cost_usd": round(cost_usd, 8) if priced else None,
        "cost_cny": round(cost_usd * USD_TO_CNY, 6) if (priced and USD_TO_CNY) else None,
        "unpriced_models": unpriced,
        "price_table_date": _price_table_date(),
    }


def format_summary(data: dict | None = None) -> str:
    """把 summary() 排成给终端看的多行文本"""
    d = data or summary()
    lines = [
        "本次 run 用量：",
        f"  input tokens  = {d['input_tokens']}",
        f"  output tokens = {d['output_tokens']}",
        f"  total tokens  = {d['total_tokens']}",
        f"  LLM 调用次数  = {d['calls']}（缓存命中 {d['cached_calls']} 次，未发请求）",
    ]
    if d["cost_usd"] is None:
        models = "、".join(d["unpriced_models"]) or "未知模型"
        lines.append(f"  估算成本      = 单价未知（{models} 不在价格表），仅报 token")
    else:
        cost = f" 估算成本      = ${d['cost_usd']:.6f}"
        if d["cost_cny"] is not None:
            cost += f"（约 ¥{d['cost_cny']:.6f}，汇率 {USD_TO_CNY}）"
        lines.append(cost)
    if d.get("price_table_date"):
        lines.append(f"  价格表快照     = {d['price_table_date']}（litellm 静态快照，成本为估算值）")
    return "\n".join(lines)
