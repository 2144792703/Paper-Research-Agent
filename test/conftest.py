"""pytest 公共 fixture：为安全测试提供编译好的 graph 实例（session 级复用）。"""

import pytest

from graph.graph_compile import graph as _graph


@pytest.fixture(scope="session")
def graph():
    return _graph
