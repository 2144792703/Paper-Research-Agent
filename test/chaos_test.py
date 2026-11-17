"""混沌开关的确定性测试：不依赖真实 API，验证注入、重试恢复、耗尽降级与统计并发安全。"""

import threading
from types import SimpleNamespace

import pytest

import models.remote as remote
from graph import nodes


@pytest.fixture
def chaos_env(monkeypatch):
    """隔离远程 client 的缓存、冷却与用量统计，避免测试发真实请求或 sleep"""
    monkeypatch.setattr(remote, "CHAOS_FAILURE_RATE", 0.2)
    monkeypatch.setattr(remote, "cache_get", lambda key: None)
    monkeypatch.setattr(remote, "cache_put", lambda key, value: None)
    monkeypatch.setattr(remote, "record_usage", lambda *args, **kwargs: None)
    monkeypatch.setattr(remote, "_mark_server_err", lambda i: None)
    monkeypatch.setattr(remote, "_rate_wait", lambda: 0)
    monkeypatch.setattr(remote, "_disabled", set())
    monkeypatch.setattr(remote, "_current", 0)
    monkeypatch.setattr(remote, "_cooldown_until", [0.0] * len(remote.API_KEYS))
    monkeypatch.setattr(remote, "_fail_count", [0] * len(remote.API_KEYS))
    remote.reset_chaos_stats()
    yield
    remote.reset_chaos_stats()


def _fake_client():
    return SimpleNamespace(
        invoke=lambda prompt: SimpleNamespace(
            content="ok", usage_metadata={}, response_metadata={}
        )
    )


def test_injected_failures_are_retried_then_succeed(chaos_env, monkeypatch):
    # 前两次注入失败，第三次放行
    seq = iter([0.0, 0.0, 0.9])
    monkeypatch.setattr(remote.random, "random", lambda: next(seq))
    monkeypatch.setattr(
        remote, "_get_client", lambda i, model, no_think=False: _fake_client()
    )

    assert remote.invoke_llm("hello", model="test-model") == "ok"

    stats = remote.chaos_stats()
    assert stats["injected"] == 2
    assert stats["calls"] == 1
    assert stats["attempts"] == 3
    assert stats["retries"] == 2
    assert stats["calls_retried"] == 1


def test_exhausted_retries_raise_retryable_error(chaos_env, monkeypatch):
    monkeypatch.setattr(remote.random, "random", lambda: 0.0)
    monkeypatch.setattr(
        remote, "_get_client", lambda i, model, no_think=False: _fake_client()
    )

    with pytest.raises(remote.ChaosInjectedError):
        remote.invoke_llm("hello", model="test-model")

    stats = remote.chaos_stats()
    assert stats["injected"] == remote.MAX_ROUNDS
    assert stats["calls"] == 1
    assert stats["attempts"] == remote.MAX_ROUNDS
    assert stats["retries"] == remote.MAX_ROUNDS - 1


def test_summarize_falls_back_to_structured_summaries(monkeypatch):
    def _boom(*args, **kwargs):
        raise RuntimeError("stream failed")

    monkeypatch.setattr(nodes, "stream_llm", _boom)
    state = {
        "paper_summaries": [
            {
                "title": "Paper A",
                "url": "http://a",
                "summary": {
                    "problem": "问题A",
                    "method": "方法A",
                    "result": "结果A",
                    "limitation": "局限A",
                },
            },
            {
                "title": "Paper | B",
                "url": "http://b",
                "summary": {
                    "problem": "问题B",
                    "method": "方法B",
                    "result": "结果B",
                    "limitation": "局限B",
                },
            },
        ],
        "papers": [],
    }

    result = nodes.worker_summarize(state)

    assert result["summary"].startswith("## 研究背景")
    assert "## 论文对比" in result["summary"]
    assert "## 研究空白" in result["summary"]
    assert "降级汇总" in result["summary"]
    assert "Paper \\| B" in result["summary"]


def test_select_falls_back_to_search_order(monkeypatch):
    """筛选模型不可用时，按搜索顺序保留前 N 篇，不中断主流程"""

    def _boom(*args, **kwargs):
        raise RuntimeError("select failed")

    monkeypatch.setattr(nodes, "invoke_llm", _boom)
    papers = [
        SimpleNamespace(url=f"http://{i}", title=f"Paper {i}", summary=f"摘要 {i}")
        for i in range(3)
    ]

    result = nodes.worker_select({"topic": "graph neural network", "papers": papers, "keep_papers": 2})

    assert result["papers"] == papers[:2]


def test_supervisor_falls_back_to_deterministic_route(monkeypatch):
    """路由模型不可用时，按状态判定表回退，不中断主流程"""

    def _boom(*args, **kwargs):
        raise RuntimeError("router failed")

    monkeypatch.setattr(nodes, "invoke_llm", _boom)
    state = {"topic": "graph neural network", "papers": [], "summary": "", "next": "none"}

    assert nodes.supervisor_node(state)["next"] == "search"


def test_fallback_route_matches_state_table():
    assert nodes._fallback_route({"papers": [], "summary": "", "next": "none"}) == "search"
    assert nodes._fallback_route({"papers": [SimpleNamespace()], "summary": "", "next": "search"}) == "summarize"
    assert nodes._fallback_route({"papers": [], "summary": "已生成", "next": "summarize"}) == "critic"
    assert nodes._fallback_route({"papers": [], "summary": "已生成", "next": "critic"}) == "summarize"


def test_chaos_stats_are_thread_safe(chaos_env):
    def worker():
        for _ in range(500):
            remote._record_chaos_attempts(1)

    threads = [threading.Thread(target=worker) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    stats = remote.chaos_stats()
    assert stats["calls"] == 4000
    assert stats["attempts"] == 4000
    assert stats["retries"] == 0