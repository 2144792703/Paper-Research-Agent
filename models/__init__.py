"""
模型实现包：统一对外暴露 invoke_llm / stream_llm。

路由规则由环境变量 MODEL_PROVIDER（在 config.py 中加载）决定：
    - remote：使用远程 OpenAI 兼容 API（实现见 models.remote）
    - local ：使用本地 Ollama 服务（实现见 models.local）

新增其它模型实现时：
    1. 在 models/ 下新建一个模块，暴露 invoke_llm(prompt)->str 与 stream_llm(prompt)->Iterator[str]。
    2. 在本文件的 if/elif 中增加一个分支即可，无需改动业务层与框架。
"""

from __future__ import annotations

import logging

from config import MODEL_PROVIDER

logger = logging.getLogger(__name__)

# 支持的提供方白名单，非法值直接抛错，避免静默回退到错误实现
_SUPPORTED = ("local", "remote")
if MODEL_PROVIDER not in _SUPPORTED:
    raise RuntimeError(
        f"不支持的 MODEL_PROVIDER={MODEL_PROVIDER!r}，仅支持 {_SUPPORTED}"
    )

if MODEL_PROVIDER == "local":
    from .local import invoke_llm, stream_llm
else:
    from .remote import invoke_llm, stream_llm

logger.info(f"[models] 模型提供方已切换为: {MODEL_PROVIDER}")


def _resolve_provider() -> str:
    """返回当前提供方并打印实际使用的实现模块（模块导入时已完成路由）"""
    logger.info(f"[main] 模型提供方={MODEL_PROVIDER}, 实现包=models.{MODEL_PROVIDER}")
    return MODEL_PROVIDER


__all__ = ["invoke_llm", "stream_llm", "MODEL_PROVIDER", "_resolve_provider"]
