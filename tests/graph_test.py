"""图节点边界行为的离线单测（不调 LLM/arXiv）。"""

import graph.nodes as nodes


def test_supervisor_terminates_after_max_attempts(monkeypatch):
    # 达到次数上限时必须直接结束，且不能再调用模型
    def _boom(*args, **kwargs):
        raise AssertionError("不应调用路由模型")

    monkeypatch.setattr(nodes, "invoke_llm", _boom)
    out = nodes.supervisor_node({
        "topic": "graph neural network", "papers": [], "summary": "",
        "search_attempts": nodes.MAX_SEARCH_ATTEMPTS,
    })
    assert out == {"next": "end"}


def test_supervisor_prompt_has_no_64_char_rule(monkeypatch):
    captured = {}

    def _fake_invoke(message, **kwargs):
        captured["message"] = message
        return "search"

    monkeypatch.setattr(nodes, "invoke_llm", _fake_invoke)
    out = nodes.supervisor_node({"topic": "a" * 80, "papers": [], "summary": ""})
    assert out == {"next": "search"}
    assert "64" not in captured["message"]


def test_worker_search_increments_attempts(monkeypatch):
    monkeypatch.setattr(nodes, "search_papers", lambda *a, **k: [])
    out = nodes.worker_search({
        "topic": "graph neural network", "papers": [], "search_max_results": 5,
        "search_attempts": 1,
    })
    assert out["search_attempts"] == 2
    assert out["papers"] == []
