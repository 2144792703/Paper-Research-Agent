"""
入口输入校验与注入可疑短语标记（CLI 与 API 两端共用）。

职责边界：
    - sanitize_topic：只做 strip + 不可见控制符清理，不截断、不改写语义。
    - flag_injection：返回命中的可疑短语列表，仅用于打 warning 标记，不硬拦截
      （硬拦截容易误杀正常论文标题，是否阻断由调用方/人工复核决定）。
    - 长度校验不在这里做：CLI 与 API 统一为「超长拒绝」，具体报错形式由调用方实现。

注意：本模块只覆盖直接注入的入口侧标记；间接注入（恶意指令藏在论文标题/摘要里）、
越权工具调用、检索数据投毒、长上下文淹没指令等不在当前防线内，属已知盲区。
"""

from __future__ import annotations

import re

# 主题长度上限：CLI 与 API 两端一致，超长一律拒绝（不再静默截断）
MAX_TOPIC_LEN = 100

# 不可见控制符：NUL 到 US、DEL；换行/回车/制表符等一律剔除，避免夹带不可见指令
_CONTROL_CHARS = re.compile(r"[\x00-\x1f\x7f]")

# 直接注入常见短语（小写比较）。只标记不拦截。
TOPIC_INJECTION_FLAGS: tuple[str, ...] = (
    "ignore all previous instructions",
    "ignore previous instructions",
    "忽略以上指令",
    "忽略所有指令",
    "忽略之前的指令",
    "system prompt",
    "系统提示词",
    "reveal your",
    "输出你的",
    "print your",
    "api key",
    "api_key",
    "base_url",
)


def sanitize_topic(topic: str | None) -> str:
    """strip 首尾空白并剔除不可见控制字符；None/空串返回空串。"""
    if not topic:
        return ""
    return _CONTROL_CHARS.sub("", str(topic)).strip()


def flag_injection(topic: str) -> list[str]:
    """返回主题中命中的注入可疑短语（保序去重）；未命中返回空列表。"""
    low = (topic or "").lower()
    hits: list[str] = []
    for flag in TOPIC_INJECTION_FLAGS:
        if flag in low and flag not in hits:
            hits.append(flag)
    return hits
