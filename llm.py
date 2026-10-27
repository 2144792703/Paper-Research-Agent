import time
import logging
import httpx

from langchain_openai import ChatOpenAI
from openai import RateLimitError, AuthenticationError, PermissionDeniedError

from config import MODEL, API_KEYS, BASE_URL, REQUEST_TIMEOUT, MAX_RETRIES, KEY_COOLDOWN

logger = logging.getLogger(__name__)

MAX_ROUNDS = 4        # 完整遍历上限，耗尽后抛出最后一次限流异常
MAX_COOLDOWN = 60.0   # 单 key 冷却封顶（秒）

# ===== 池状态（模块级，跨调用持久）=====
_clients: dict[int, ChatOpenAI] = {}          # key 索引 -> 客户端缓存
_current = 0                                   # 粘性指针：上次调用成功的 key 索引
_fail_count = [0] * len(API_KEYS)              # 每个 key 的连续限流次数
_cooldown_until = [0.0] * len(API_KEYS)        # 每个 key 的解封时间戳（monotonic）
_disabled: set[int] = set()                    # 401/403 永久禁用的 key（进程内）


def _get_client(i: int) -> ChatOpenAI:
    """按 key 索引获取客户端（缓存复用）"""
    if i not in _clients:
        _clients[i] = ChatOpenAI(
            model=MODEL,
            api_key=API_KEYS[i],
            http_client=httpx.Client(trust_env=False, timeout=60.0) ,
            base_url=BASE_URL,
            timeout=float(REQUEST_TIMEOUT),
            max_retries=int(MAX_RETRIES),
        )
    return _clients[i]


def _mark_limited(i: int):
    """429：该 key 退避递增（KEY_COOLDOWN × 2^(n-1)，封顶 MAX_COOLDOWN）"""
    _fail_count[i] += 1
    delay = min(KEY_COOLDOWN * 2 ** (_fail_count[i] - 1), MAX_COOLDOWN)
    _cooldown_until[i] = time.monotonic() + delay
    logger.warning(f"key#{i} 限流，退避 {delay:.0f}s，切换下一个 key")


def _mark_success(i: int):
    """成功：粘性指针指向该 key，全部冷却与限流计数清零"""
    global _current
    _current = i
    for j in range(len(API_KEYS)):
        _fail_count[j] = 0
        _cooldown_until[j] = 0.0


def _scan_order() -> list[int]:
    """从 current 起的环形顺序，排除已禁用 key；全禁用返回空列表"""
    n = len(API_KEYS)
    return [( _current + s) % n for s in range(n) if (_current + s) % n not in _disabled]


def _next_target(order: list[int], tried: set[int]):
    """优先选已解封的 key；全冷却则等待最早解封者；无可选返回 None"""
    now = time.monotonic()
    for i in order:
        if i not in tried and _cooldown_until[i] <= now:
            return i
    remain = [i for i in order if i not in tried]
    if not remain:
        return None
    target = min(remain, key=lambda i: _cooldown_until[i])
    wait = _cooldown_until[target] - time.monotonic()
    if wait > 0:
        logger.warning(f"所有 key 冷却中，等待 key#{target} 退避，剩余 {wait:.0f}s")
        time.sleep(wait)
    return target


def invoke_llm(prompt: str) -> str:
    """调用模型；429 按 key 池轮换 + 退避，401/403 永久禁用，4 轮耗尽抛异常"""
    last_err: RateLimitError | None = None
    for _ in range(MAX_ROUNDS):
        order = _scan_order()
        if not order:
            raise RuntimeError("API key 池已无可用 key（全部鉴权失败被禁用）")
        tried: set[int] = set()
        while len(tried) < len(order):
            target = _next_target(order, tried)
            if target is None:
                break
            tried.add(target)
            try:
                content = _get_client(target).invoke(prompt).content
                _mark_success(target)
                return content
            except (AuthenticationError, PermissionDeniedError) as e:
                _disabled.add(target)
                logger.error(f"key#{target} 鉴权失败，已从池中永久禁用：{e}")
            except RateLimitError as e:
                last_err = e
                _mark_limited(target)
    raise last_err if last_err else RuntimeError("API 请求失败：重试轮次耗尽")


def stream_llm(prompt: str):
    """流式调用，yield 每个 chunk 文本；首 chunk 前限流可换 key，中途限流标记冷却后直接抛出"""
    last_err: RateLimitError | None = None
    for _ in range(MAX_ROUNDS):
        order = _scan_order()
        if not order:
            raise RuntimeError("API key 池已无可用 key（全部鉴权失败被禁用）")
        tried: set[int] = set()
        while len(tried) < len(order):
            target = _next_target(order, tried)
            if target is None:
                break
            tried.add(target)
            try:
                iterator = _get_client(target).stream(prompt)
                first = next(iterator)  # 首 chunk 前抛错可安全换 key
            except (AuthenticationError, PermissionDeniedError) as e:
                _disabled.add(target)
                logger.error(f"key#{target} 鉴权失败，已从池中永久禁用：{e}")
                continue
            except RateLimitError as e:
                last_err = e
                _mark_limited(target)
                continue
            _mark_success(target)
            yield first.content
            try:
                for chunk in iterator:
                    yield chunk.content
            except RateLimitError:
                _mark_limited(target)  # 中途限流：标记冷却，不重试（避免内容重复）
                raise
            return
    raise last_err if last_err else RuntimeError("API 请求失败：重试轮次耗尽")
