import time
import threading
import logging
import random
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


class ChaosInjectedError(APITimeoutError):
    """混沌测试注入的超时异常（属于 _NETWORK_RETRYABLE，复用现有重试/换 key 逻辑）"""

    def __init__(self, message: str = "chaos injected timeout"):
        Exception.__init__(self, message)


from config import (
    MODEL, API_KEYS, BASE_URL, REQUEST_TIMEOUT, MAX_RETRIES, KEY_COOLDOWN, RPM_LIMIT, RPM_WINDOW,
    LLM_TEMPERATURE, LLM_TOP_P, PROVIDER_TAG, CHAOS_FAILURE_RATE,
    CHEAP_MODEL, STRONG_MODEL, CHEAP_MODEL_DISABLE_THINKING,
)
from cache import cache_get, cache_key, cache_put
from usage import record_usage

logger = logging.getLogger(__name__)

# 缓存键的 provider 段：remote 带 BASE_URL 指纹，换提供方/换地址都不会串缓存
PROVIDER = PROVIDER_TAG

MAX_ROUNDS = 4        # 完整遍历上限，耗尽后抛出最后一次限流异常
MAX_COOLDOWN = 60.0   # 单 key 冷却封顶（秒）

# ===== 池状态（模块级，跨调用持久）=====
_clients: dict[tuple[int, str, bool], ChatOpenAI] = {}
_pool_lock = threading.Lock()
_current = 0                                   # 粘性指针：上次调用成功的 key 索引
_fail_count = [0] * len(API_KEYS)              # 每个 key 的连续限流次数
_cooldown_until = [0.0] * len(API_KEYS)        # 每个 key 的解封时间戳（monotonic）
_disabled: set[int] = set()                    # 401/403 永久禁用的 key（进程内）
_req_times: deque = deque()                    # 全局请求时间戳（所有 key 共享同一限流窗口）
_last_req_ts = 0.0                             # 上一次请求的发起时间（用于最小间隔）

# ===== 混沌开关（仅调试；CHAOS_FAILURE_RATE=0 时不介入，不产生日志）=====
_chaos_stats = {
    "injected": 0,      # 注入的可重试故障次数
    "calls": 0,         # 真实请求调用次数（每次进入真实请求记 1 次；缓存命中不计）
    "attempts": 0,      # 真实请求尝试次数
    "retries": 0,       # 同一逻辑调用内的重试次数（= attempts - calls）
    "calls_retried": 0, # 发生过重试的逻辑调用次数
}
_chaos_lock = threading.Lock()


def reset_chaos_stats() -> None:
    with _chaos_lock:
        for k in _chaos_stats:
            _chaos_stats[k] = 0


def chaos_stats() -> dict:
    """返回本进程累计的混沌统计，供开/关对照记录"""
    with _chaos_lock:
        return dict(_chaos_stats)


def _maybe_inject_chaos() -> None:
    """在请求发出前按概率注入可重试超时；rate=0 时直接返回"""
    if CHAOS_FAILURE_RATE <= 0 or random.random() >= CHAOS_FAILURE_RATE:
        return
    with _chaos_lock:
        _chaos_stats["injected"] += 1
    logger.warning(f"[chaos] 注入可重试故障（rate={CHAOS_FAILURE_RATE:.2f}）")
    raise ChaosInjectedError()


def _record_chaos_attempts(attempts: int) -> None:
    """记录一次逻辑调用的尝试/重试次数（仅开关打开时统计）"""
    if CHAOS_FAILURE_RATE <= 0 or attempts <= 0:
        return
    with _chaos_lock:
        _chaos_stats["calls"] += 1
        _chaos_stats["attempts"] += attempts
        if attempts > 1:
            _chaos_stats["calls_retried"] += 1
            _chaos_stats["retries"] += attempts - 1


def _no_think(model: str) -> bool:
    """轻量模型是否需要关闭思考；与主模型相同时不处理，避免误伤强模型"""
    return bool(
        CHEAP_MODEL_DISABLE_THINKING
        and model
        and model == CHEAP_MODEL
        and CHEAP_MODEL != STRONG_MODEL
    )


def _get_client(i: int, model: str, no_think: bool = False) -> ChatOpenAI:
    """按 key 索引获取客户端（缓存复用）"""
    cache_key_ = (i, model, no_think)
    with _pool_lock:
        if cache_key_ not in _clients:
            kwargs = dict(
                model=model,
                api_key=API_KEYS[i],
                http_client=httpx.Client(trust_env=False, timeout=float(REQUEST_TIMEOUT)),
                base_url=BASE_URL,
                timeout=float(REQUEST_TIMEOUT),
                max_retries=int(MAX_RETRIES),
            )
            if LLM_TEMPERATURE is not None:
                kwargs["temperature"] = LLM_TEMPERATURE
            if LLM_TOP_P is not None:
                kwargs["top_p"] = LLM_TOP_P
            if no_think:
                # ModelScope/vLLM 兼容写法：关闭 Qwen/GLM 的思考模式
                kwargs["extra_body"] = {"chat_template_kwargs": {"enable_thinking": False}}
            _clients[cache_key_] = ChatOpenAI(**kwargs)
    return _clients[cache_key_]


def _usage_tokens(response) -> tuple[int, int]:
    """从 LangChain 响应/流式 chunk 中取 (input_tokens, output_tokens)"""
    md = getattr(response, "usage_metadata", None) or {}
    if md:
        return int(md.get("input_tokens") or 0), int(md.get("output_tokens") or 0)
    tu = (getattr(response, "response_metadata", None) or {}).get("token_usage") or {}
    return int(tu.get("prompt_tokens") or 0), int(tu.get("completion_tokens") or 0)


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


def _redact_headers(headers: dict) -> dict:
    """响应头日志脱敏：Authorization / 各类 Key 只保留键名和值的前 6 位"""
    out = {}
    for k, v in (headers or {}).items():
        lk = k.lower()
        if any(s in lk for s in ("authorization", "api-key", "api_key", "token", "secret", "x-api")):
            v = (str(v)[:6] + "...") if v else ""
        out[k] = v
    return out


def _log_rate_limit(i: int, e: Exception):
    """打印 429 的响应头与 body，用于判断限流按账号/IP/RPM/TPM 哪个维度计算"""
    resp = getattr(e, "response", None)
    if resp is None:
        logger.warning(f"key#{i} 429（无响应对象），无法读取限流头")
        return
    try:
        headers = _redact_headers(dict(resp.headers))
        body = (resp.text or "")[:200]  # 从 500 缩到 200，减少泄露面
    except Exception as read_err:
        logger.warning(f"key#{i} 429，读取响应失败（{type(read_err).__name__}）")
        return
    logger.warning(f"key#{i} 429 headers={headers} body={body}")


def _scan_order() -> list[int]:
    """从 current 起的环形顺序，排除已禁用 key；全禁用返回空列表。调用方需持有 _pool_lock"""
    n = len(API_KEYS)
    return [(_current + s) % n for s in range(n) if (_current + s) % n not in _disabled]


def _next_target(order: list[int], tried: set[int]):
    """优先选冷却已解封且全局窗口有空位的 key；否则选最早可用的 key（等待由调用方执行）"""
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
    return target


def invoke_llm(prompt: str, model: str | None = None) -> str:
    """调用模型；429/5xx 按 key 池轮换 + 退避，401/403 永久禁用，4 轮耗尽抛异常

    先查磁盘缓存：命中直接返回，不发任何网络请求，也不产生 Langfuse Generation。
    """
    active = model or MODEL
    no_think = _no_think(active)
    # 思考/非思考响应不同，缓存键需区分，避免互相命中
    key = cache_key(prompt, provider=PROVIDER, model=f"{active}|no-think" if no_think else active)
    cached = cache_get(key)
    if cached is not None:
        record_usage(model=active, cached=True)
        return cached

    last_err: Exception | None = None
    attempts = 0
    for _ in range(MAX_ROUNDS):
        with _pool_lock:
            order = _scan_order()
        if not order:
            raise RuntimeError("API key 池已无可用 key（全部鉴权失败被禁用）")
        tried: set[int] = set()
        while len(tried) < len(order):
            with _pool_lock:
                target = _next_target(order, tried)
                if target is None:
                    break
                wait = max(_cooldown_until[target] - time.monotonic(), _rate_wait())
                if wait <= 0:
                    # 选中 key、标记占用、记录请求同一临界区，避免并发下重复选中
                    tried.add(target)
                    _record_req()
            if wait > 0:
                time.sleep(wait + 0.05)
                # 睡醒后名额仍可能被其他线程抢占：标记已尝试，避免同轮反复评估
                with _pool_lock:
                    tried.add(target)
                continue
            try:
                attempts += 1
                _maybe_inject_chaos()
                response = _get_client(target, active, no_think).invoke(prompt)
                with _pool_lock:
                    _mark_success(target)
                in_tokens, out_tokens = _usage_tokens(response)
                record_usage(in_tokens, out_tokens, model=active)
                cache_put(key, response.content)
                _record_chaos_attempts(attempts)
                return response.content
            except (AuthenticationError, PermissionDeniedError) as e:
                with _pool_lock:
                    _disabled.add(target)
                logger.error(f"key#{target} 鉴权失败，已从池中永久禁用：{type(e).__name__}")
            except _NETWORK_RETRYABLE as e:
                last_err = e
                with _pool_lock:
                    _mark_server_err(target)
                logger.warning(f"key#{target} 临时网络/服务端错误（{type(e).__name__}），冷却后换下一个 key")
            except RateLimitError as e:
                last_err = e
                _log_rate_limit(target, e)
                with _pool_lock:
                    _mark_limited(target)
    _record_chaos_attempts(attempts)
    raise last_err if last_err else RuntimeError("API 请求失败：重试轮次耗尽")


def stream_llm(prompt: str, model: str | None = None):
    """流式调用，yield 每个 chunk 文本；首 chunk 前限流/5xx 可换 key，中途限流标记冷却后直接抛出

    命中磁盘缓存时按固定窗口回放完整文本，不发请求、不产生 Langfuse Generation。
    """
    active = model or MODEL
    no_think = _no_think(active)
    # 思考/非思考响应不同，缓存键需区分，避免互相命中
    key = cache_key(prompt, provider=PROVIDER, model=f"{active}|no-think" if no_think else active)
    cached = cache_get(key)
    if cached is not None:
        record_usage(model=active, cached=True)
        for i in range(0, len(cached), 40):
            yield cached[i:i + 40]
        return

    last_err: Exception | None = None
    attempts = 0
    for _ in range(MAX_ROUNDS):
        with _pool_lock:
            order = _scan_order()
        if not order:
            raise RuntimeError("API key 池已无可用 key（全部鉴权失败被禁用）")
        tried: set[int] = set()
        while len(tried) < len(order):
            with _pool_lock:
                target = _next_target(order, tried)
                if target is None:
                    break
                wait = max(_cooldown_until[target] - time.monotonic(), _rate_wait())
                if wait <= 0:
                    # 选中 key、标记占用、记录请求同一临界区，避免并发下重复选中
                    tried.add(target)
                    _record_req()
            if wait > 0:
                time.sleep(wait + 0.05)
                # 睡醒后名额仍可能被其他线程抢占：标记已尝试，避免同轮反复评估
                with _pool_lock:
                    tried.add(target)
                continue
            try:
                attempts += 1
                _maybe_inject_chaos()
                iterator = _get_client(target, active, no_think).stream(prompt)
                first = next(iterator)  # 首 chunk 前抛错可安全换 key
            except (AuthenticationError, PermissionDeniedError) as e:
                with _pool_lock:
                    _disabled.add(target)
                logger.error(f"key#{target} 鉴权失败，已从池中永久禁用：{type(e).__name__}")
                continue
            except _NETWORK_RETRYABLE as e:
                last_err = e
                with _pool_lock:
                    _mark_server_err(target)
                logger.warning(f"key#{target} 临时网络/服务端错误（{type(e).__name__}），冷却后换下一个 key")
                continue
            except RateLimitError as e:
                last_err = e
                _log_rate_limit(target, e)
                with _pool_lock:
                    _mark_limited(target)
                continue
            with _pool_lock:
                _mark_success(target)
            # 流式边收边发；结束后把完整文本落缓存，下次直接回放（不再请求 API）
            # 注意：此处按“端点每个 chunk 返回增量 usage”累加；若换的端点改为返回累计值需重新对账
            total_in = total_out = 0
            parts: list[str] = []
            in_t, out_t = _usage_tokens(first)
            total_in += in_t
            total_out += out_t
            parts.append(first.content)
            yield first.content
            try:
                for chunk in iterator:
                    in_t, out_t = _usage_tokens(chunk)
                    total_in += in_t
                    total_out += out_t
                    parts.append(chunk.content)
                    yield chunk.content
            except (RateLimitError, *_NETWORK_RETRYABLE) as e:
                # 中途限流/网络/服务端故障：标记冷却，不重试（避免内容重复）
                if isinstance(e, RateLimitError):
                    with _pool_lock:
                        _mark_limited(target)
                else:
                    with _pool_lock:
                        _mark_server_err(target)
                _record_chaos_attempts(attempts)
                raise
            record_usage(total_in, total_out, model=active)
            cache_put(key, "".join(parts))
            _record_chaos_attempts(attempts)
            return
    _record_chaos_attempts(attempts)
    raise last_err if last_err else RuntimeError("API 请求失败：重试轮次耗尽")
