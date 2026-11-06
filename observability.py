"""
可观测性接入层（Langfuse）。

观测逻辑只存在于本文件：业务节点里不写任何埋点，
调用方把 CallbackHandler 通过 `graph.invoke(..., config=...)` 传进去，
LangGraph 会把 callbacks 与 metadata 向下传递给每个节点和每次 ChatOpenAI 调用。

分层关系（Langfuse 后台看到的结构）：
    Trace      一次完整研究（graph.invoke 的根 run，名字取自 langfuse_trace_name）
    Span       每个图节点（supervisor / search / select / summarize_one / ...）
    Generation 每次 LLM 调用（节点里的 ChatOpenAI.invoke / stream），token 在这一层统计
"""

import logging
from typing import Any

from config import LANGFUSE_ENABLED, LANGFUSE_PUBLIC_KEY

logger = logging.getLogger(__name__)


def trace_config(topic: str) -> dict[str, Any]:
    """构造 graph.invoke 的 config；未配置 key 或 SDK 初始化失败时返回空 dict（不上报）"""
    if not LANGFUSE_ENABLED:
        return {}

    try:
        from langfuse.langchain import CallbackHandler

        handler = CallbackHandler()
    except Exception as e:
        # 观测失败不能影响主流程：只告警，返回空 config
        logger.warning(f"[observability] Langfuse 初始化失败，本次跳过上报：{e}")
        return {}

    return {
        "callbacks": [handler],
        "metadata": {
            # langfuse_* 前缀的键会被 SDK 提取为 trace 级属性，其余作为 run metadata
            "langfuse_trace_name": f"paper-research:{topic[:60]}",
            "langfuse_tags": ["paper-research-agent"],
            "topic": topic,
        },
    }


def trace_id(config: dict[str, Any]) -> str | None:
    """取本次调用的 Langfuse trace id（未启用时返回 None），便于终端打印核对"""
    callbacks = config.get("callbacks") or []
    if not callbacks:
        return None
    return getattr(callbacks[0], "last_trace_id", None)


def flush() -> None:
    """CLI 退出前主动把缓冲的 span 发出去；服务端每次请求结束后也可调用"""
    if not LANGFUSE_ENABLED:
        return
    try:
        from langfuse import get_client

        get_client().flush()
    except Exception as e:
        logger.debug(f"[observability] Langfuse flush 忽略异常：{e}")


def public_key_hint() -> str:
    """日志里只暴露 public key 前缀，永不打印 secret key"""
    return f"{LANGFUSE_PUBLIC_KEY[:8]}..." if LANGFUSE_PUBLIC_KEY else ""
