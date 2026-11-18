"""pytest 公共 fixture：为安全测试提供编译好的 graph 实例（session 级复用）。"""

import pytest

from graph.graph_compile import graph as _graph

# 脚本式验收文件（模块顶层直接跑真实链路），不参与 pytest 收集
collect_ignore = [
    "full_run_test.py",
    "smoke_test.py",
    "selection_test.py",
    "summary_test.py",
    "tools_test.py",
    "run_security_test.py",
]


@pytest.fixture(scope="session")
def graph():
    return _graph
