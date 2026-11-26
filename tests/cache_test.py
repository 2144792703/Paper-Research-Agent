"""缓存键隔离与空值处理的离线单测（不落盘、不发网络）。"""

import cache


def test_cache_key_is_provider_sensitive():
    # provider 段包含 BASE_URL 指纹，换服务地址后不能命中旧缓存
    a = cache.cache_key("同一段 prompt", provider="remote:aaaaaaaa", model="m")
    b = cache.cache_key("同一段 prompt", provider="remote:bbbbbbbb", model="m")
    assert a != b


def test_cache_key_is_model_and_prompt_sensitive():
    base = cache.cache_key("prompt", provider="remote:x", model="m1")
    assert base != cache.cache_key("prompt", provider="remote:x", model="m2")
    assert base != cache.cache_key("prompt2", provider="remote:x", model="m1")


def test_cache_key_normalizes_whitespace():
    # 统一换行并把行内空白压缩，但保留换行结构
    assert cache.cache_key("a   b\n c", provider="p", model="m") == cache.cache_key(
        "a b\nc", provider="p", model="m"
    )


class _Store:
    def __init__(self):
        self.data: dict[str, str] = {}

    def set(self, key, value):
        self.data[key] = value

    def get(self, key):
        return self.data.get(key)

    def delete(self, key):
        self.data.pop(key, None)


def test_cache_put_skips_empty(monkeypatch):
    store = _Store()
    monkeypatch.setattr(cache, "_get_cache", lambda: store)
    cache.cache_put("k", "")
    cache.cache_put("k", "   ")
    assert store.data == {}


def test_cache_put_writes_non_empty(monkeypatch):
    store = _Store()
    monkeypatch.setattr(cache, "_get_cache", lambda: store)
    cache.cache_put("k", "value")
    assert store.data["k"] == "value"


def test_cache_get_treats_blank_as_miss(monkeypatch):
    store = _Store()
    store.data["k"] = "   "
    monkeypatch.setattr(cache, "_get_cache", lambda: store)
    assert cache.cache_get("k") is None
    assert "k" not in store.data  # 历史空值被删除，避免回放空报告
