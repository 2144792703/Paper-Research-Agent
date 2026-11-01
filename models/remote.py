import time
import logging
import httpx

from collections import deque

from langchain_openai import ChatOpenAI
from openai import (
    RateLimitError,
    AuthenticationError,
    PermissionDeniedError,
    InternalServerError,
    APIConnectionError,
    APITimeoutError,
)

# 可轮换的"临时故障"异常集合：固定短暂冷却 + 换下一个 key，不计入限流退避
_NETWORK_RETRYABLE = (InternalServerError, APIConnectionError, APITimeoutError)

from config import MODEL, API_KEYS, BASE_URL, REQUEST_TIMEOUT, MAX_RETRIES, KEY_COOLDOWN, RPM_LIMIT, RPM_WINDOW

logger = logging.getLogger(__name__)

MAX_ROUNDS = 4        # 完整遍历上限，耗尽后抛出最后一次限流异常
MAX_COOLDOWN = 60.0   # 单 key 冷却封顶（秒）

# ===== 池状态（模块级，跨调用持久）=====
_clients: dict[int, ChatOpenAI] = {}          # key 索引 -> 客户端缓存
_current = 0                                   # 粘性指针：上次调用成功的 key 索引
_fail_count = [0] * len(API_KEYS)              # 每个 key 的连续限流次数
_cooldown_until = [0.0] * len(API_KEYS)        # 每个 key 的解封时间戳（monotonic）
_disabled: set[int] = set()                    # 401/403 永久禁用的 key（进程内）
_req_times: deque = deque()                    # 全局请求时间戳（三个 key 共享同一限流窗口）
_last_req_ts = 0.0                             # 上一次请求的发起时间（用于最小间隔）


def _get_client(i: int) -> ChatOpenAI:
    """按 key 索引获取客户端（缓存复用）"""
    if i not in _clients:
        _clients[i] = ChatOpenAI(
            model=MODEL,
            api_key=API_KEYS[i],
            http_client=httpx.Client(trust_env=False, timeout=120.0) ,
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


def _mark_server_err(i: int):
    """5xx 服务端错误：短暂冷却（固定 5s），换下一个 key，不计入限流退避"""
    _cooldown_until[i] = time.monotonic() + KEY_COOLDOWN
    logger.warning(f"key#{i} 服务端错误(5xx)，短暂冷却 {KEY_COOLDOWN:.0f}s，切换下一个 key")


def _mark_success(i: int):
    """成功：粘性指针指向该 key，全部冷却与限流计数清零"""
    global _current
    _current = i
    for j in range(len(API_KEYS)):
        _fail_count[j] = 0
        _cooldown_until[j] = 0.0


def _rate_wait() -> float:
    """全局滑动窗口 + 最小间隔：返回还需等待的秒数（0 表示可立即请求）"""
    if RPM_LIMIT <= 0:
        return 0.0
    now = time.monotonic()
    while _req_times and now - _req_times[0] >= RPM_WINDOW:
        _req_times.popleft()
    wait = 0.0
    if len(_req_times) >= RPM_LIMIT:
        wait = RPM_WINDOW - (now - _req_times[0])
    min_interval = RPM_WINDOW / RPM_LIMIT
    if now - _last_req_ts < min_interval:
        wait = max(wait, min_interval - (now - _last_req_ts))
    return max(wait, 0.0)


def _record_req():
    """记录一次真实请求的发起时间"""
    global _last_req_ts
    _last_req_ts = time.monotonic()
    _req_times.append(_last_req_ts)


def _log_rate_limit(i: int, e: Exception):
    """打印 429 的响应头与 body，用于判断限流按账号/IP/RPM/TPM 哪个维度计算"""
    resp = getattr(e, "response", None)
    if resp is None:
        logger.warning(f"key#{i} 429（无响应对象），无法读取限流头")
        return
    try:
        headers = dict(resp.headers)
        body = resp.text[:500]
    except Exception as read_err:
        logger.warning(f"key#{i} 429，读取响应失败：{read_err}")
        return
    logger.warning(f"key#{i} 429 headers={headers} body={body}")


def _scan_order() -> list[int]:
    """从 current 起的环形顺序，排除已禁用 key；全禁用返回空列表"""
    n = len(API_KEYS)
    return [( _current + s) % n for s in range(n) if (_current + s) % n not in _disabled]


def _next_target(order: list[int], tried: set[int]):
    """优先选冷却已解封且全局窗口有空位的 key；否则等待最早可用的那个"""
    now = time.monotonic()
    for i in order:
        if i not in tried and _cooldown_until[i] <= now and _rate_wait() <= 0:
            return i
    remain = [i for i in order if i not in tried]
    if not remain:
        return None

    def _delay(i: int) -> float:
        return max(_cooldown_until[i] - time.monotonic(), _rate_wait())

    target = min(remain, key=_delay)
    wait = _delay(target)
    if wait > 0:
        logger.warning(f"key#{target} 需等待 {wait:.0f}s（限流冷却或全局 RPM 窗口已满），暂停后重试")
        time.sleep(wait + 0.05)
    return target


def invoke_llm(prompt: str) -> str:
    """调用模型；429/5xx 按 key 池轮换 + 退避，401/403 永久禁用，4 轮耗尽抛异常"""
    last_err: Exception | None = None
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
            _record_req()
            try:
                content = _get_client(target).invoke(prompt).content
                _mark_success(target)
                return content
            except (AuthenticationError, PermissionDeniedError) as e:
                _disabled.add(target)
                logger.error(f"key#{target} 鉴权失败，已从池中永久禁用：{e}")
            except _NETWORK_RETRYABLE as e:
                last_err = e
                _mark_server_err(target)
                logger.warning(f"key#{target} 临时网络/服务端错误（{type(e).__name__}），冷却后换下一个 key")
            except RateLimitError as e:
                last_err = e
                _log_rate_limit(target, e)
                _mark_limited(target)
    raise last_err if last_err else RuntimeError("API 请求失败：重试轮次耗尽")


def stream_llm(prompt: str):
    """流式调用，yield 每个 chunk 文本；首 chunk 前限流/5xx 可换 key，中途限流标记冷却后直接抛出"""
    last_err: Exception | None = None
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
            _record_req()
            try:
                iterator = _get_client(target).stream(prompt)
                first = next(iterator)  # 首 chunk 前抛错可安全换 key
            except (AuthenticationError, PermissionDeniedError) as e:
                _disabled.add(target)
                logger.error(f"key#{target} 鉴权失败，已从池中永久禁用：{e}")
                continue
            except _NETWORK_RETRYABLE as e:
                last_err = e
                _mark_server_err(target)
                logger.warning(f"key#{target} 临时网络/服务端错误（{type(e).__name__}），冷却后换下一个 key")
                continue
            except RateLimitError as e:
                last_err = e
                _log_rate_limit(target, e)
                _mark_limited(target)
                continue
            _mark_success(target)
            yield first.content
            try:
                for chunk in iterator:
                    yield chunk.content
            except (RateLimitError, *_NETWORK_RETRYABLE) as e:
                # 中途限流/网络/服务端故障：标记冷却，不重试（避免内容重复）
                if isinstance(e, RateLimitError):
                    _mark_limited(target)
                else:
                    _mark_server_err(target)
                raise
            return
    raise last_err if last_err else RuntimeError("API 请求失败：重试轮次耗尽")
