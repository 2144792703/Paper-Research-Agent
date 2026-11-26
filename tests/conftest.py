"""pytest 公共 fixture：为安全测试提供编译好的 graph 实例（session 级复用）。"""

import os

import pytest

# 离线测试在导入 graph 之前补默认配置：评审机/CI 没有 .env 时也能收集用例。
# setdefault 不会覆盖开发者已有的 .env（load_dotenv 默认也不覆盖环境变量）。
os.environ.setdefault("MODEL_PROVIDER", "remote")
os.environ.setdefault("MODEL", "test-model")
os.environ.setdefault("API_KEY", "test-key")
os.environ.setdefault("CACHE_ENABLED", "0")

from graph.graph_compile import graph as _graph  # noqa: E402


@pytest.fixture(scope="session")
def graph():
    return _graph
