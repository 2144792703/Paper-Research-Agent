"""HTTP 入口的离线测试：参数校验、timeout/done 事件、截断标记。

不访问真实 LLM/arXiv：需要执行图时用假 graph 替换。
"""

import asyncio
import time

from fastapi.testclient import TestClient

import server


def _client() -> TestClient:
    return TestClient(server.app)


def test_health_ok():
    resp = _client().get("/health")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"


def test_max_retries_out_of_range_rejected():
    client = _client()
    assert client.post("/research", json={"topic": "gnn", "max_retries": 0}).status_code == 422
    assert client.post("/research", json={"topic": "gnn", "max_retries": 6}).status_code == 422


def test_search_count_out_of_range_rejected():
    client = _client()
    assert client.post("/research", json={"topic": "gnn", "search_count": 0}).status_code == 422
    assert client.post("/research", json={"topic": "gnn", "search_count": 51}).status_code == 422


def test_topic_too_long_rejected():
    assert _client().post("/research", json={"topic": "a" * 101}).status_code == 422


def _isolate(monkeypatch, fake_graph, timeout=None):
    monkeypatch.setattr(server, "graph", fake_graph)
    monkeypatch.setattr(server, "_run_lock", asyncio.Lock())
    monkeypatch.setattr(server, "trace_config", lambda topic: {})
    monkeypatch.setattr(server, "trace_id", lambda cfg: None)
    monkeypatch.setattr(server, "flush", lambda: None)
    if timeout is not None:
        monkeypatch.setattr(server, "SERVER_TIMEOUT", timeout)


def test_timeout_event(monkeypatch):
    class _SlowGraph:
        def invoke(self, *args, **kwargs):
            time.sleep(0.3)
            return {"summary": "x", "next": "critic", "papers": []}

    _isolate(monkeypatch, _SlowGraph(), timeout=0.05)
    resp = _client().post("/research", json={"topic": "gnn"})
    assert resp.status_code == 200
    assert "event: timeout" in resp.text
    time.sleep(0.4)  # 等后台线程结束，避免跨测试污染


def test_done_event_marks_truncated(monkeypatch):
    class _FakeGraph:
        def invoke(self, *args, **kwargs):
            return {"summary": "x" * 2100, "next": "critic", "papers": []}

    _isolate(monkeypatch, _FakeGraph())
    resp = _client().post("/research", json={"topic": "gnn"})
    assert "event: done" in resp.text
    assert '"truncated": true' in resp.text
    assert '"status": "ok"' in resp.text
    assert '"degraded": false' in resp.text


def test_done_event_marks_aborted(monkeypatch):
    class _AbortedGraph:
        def invoke(self, *args, **kwargs):
            return {"summary": "", "next": "end", "papers": []}

    _isolate(monkeypatch, _AbortedGraph())
    resp = _client().post("/research", json={"topic": "gnn"})
    assert '"status": "aborted"' in resp.text
