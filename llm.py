"""
模型调用统一入口（路由层）。

业务层始终通过 `from llm import invoke_llm, stream_llm` 调用，
本文件根据 MODEL_PROVIDER 把调用路由到 models.local 或 models.remote，
切换模型实现无需改动任何业务代码。
"""

from models import invoke_llm, stream_llm, MODEL_PROVIDER

__all__ = ["invoke_llm", "stream_llm", "MODEL_PROVIDER"]
