import os
from dotenv import load_dotenv

load_dotenv()


def _clamp_float(value, low: float, high: float, default: float) -> float:
    """把非法或越界的浮点参数收敛到 [low, high]，解析失败时退回 default"""
    try:
        value = float(value)
    except (TypeError, ValueError):
        return default
    return max(low, min(value, high))


# ============================================================
# 模块一：模型路由
# ============================================================
# local  -> 本地 Ollama 服务
# remote -> 远程 OpenAI 兼容 API（BASE_URL 可配）
MODEL_PROVIDER = os.getenv("MODEL_PROVIDER", "remote").strip().lower()
# 缓存键的 provider 段：不同提供方即使用同一模型名也不会互相命中
PROVIDER_NAME = MODEL_PROVIDER


# ============================================================
# 模块二：远程模型（OpenAI 兼容接口）
# ============================================================
REQUEST_TIMEOUT = os.getenv('REQUEST_TIMEOUT', '600.0')
MAX_RETRIES = os.getenv('MAX_RETRIES', '2')
# 混沌测试：请求发出前按概率注入可重试异常（0 关闭；仅远程模式生效，调试时临时开启）
CHAOS_FAILURE_RATE = _clamp_float(os.getenv('CHAOS_FAILURE_RATE', '0.0'), 0.0, 1.0, 0.0)

API_KEY = os.getenv("API_KEY")


def _parse_key_pools() -> list[str]:
    """解析 key 池：API_KEY_POOLS 逗号分隔去重保序；为空时回退到单个 API_KEY

    两种用法：
        池化：API_KEY_POOLS=key1,key2,key3 -> 轮换 + 单 key 冷却 + 全局 RPM 限流
        单个：只填 API_KEY=key1            -> 池中仅 1 个 key，逻辑相同但不切换
    """
    raw = os.getenv("API_KEY_POOLS", "")
    keys = [k.strip() for k in raw.split(",") if k.strip()]
    if not keys and API_KEY:
        keys = [API_KEY]
    return list(dict.fromkeys(keys))


MODEL = os.getenv("MODEL")
BASE_URL = os.getenv("BASE_URL")
API_KEYS = _parse_key_pools()

# 仅远程模式强制要求 API key；本地模式不依赖
if MODEL_PROVIDER != "local" and not API_KEYS:
    raise RuntimeError("未配置任何 API key：请在 .env 中配置 API_KEY_POOLS 或 API_KEY")

KEY_COOLDOWN = float(os.getenv('KEY_COOLDOWN', '5'))  # 单 key 限流退避基数（秒）
RPM_LIMIT = int(os.getenv('RPM_LIMIT', '10'))         # 全局（跨 key）每分钟请求上限，0 表示关闭节流
RPM_WINDOW = 60.0                                      # 滑动窗口长度（秒）


# ============================================================
# 模块三：本地模型（Ollama）
# ============================================================
OLLAMA_HOST = os.getenv("OLLAMA_HOST", "http://127.0.0.1:11434")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "qwen2.5:7b-instruct-q5_K_M")
try:
    OLLAMA_TIMEOUT = float(os.getenv("OLLAMA_TIMEOUT", "300"))
except ValueError:
    OLLAMA_TIMEOUT = 300.0


# ============================================================
# 模块四：论文搜索与筛选参数
# ============================================================
SEARCH_MIN, SEARCH_MAX = 1, 50   # 单次搜索拉取的论文数量合法区间（arXiv 单次请求上限 2000，此处按流程承受能力收敛）
KEEP_MIN, KEEP_MAX = 1, 10       # 最终保留论文数量的合法区间


def _clamp_int(value, low: int, high: int, default: int) -> int:
    """把非法或越界的参数收敛到 [low, high]，解析失败时退回 default"""
    try:
        value = int(value)
    except (TypeError, ValueError):
        return default
    return max(low, min(value, high))


SEARCH_MAX_RESULTS = _clamp_int(os.getenv("SEARCH_MAX_RESULTS", "15"), SEARCH_MIN, SEARCH_MAX, 15)
KEEP_PAPERS = _clamp_int(os.getenv("KEEP_PAPERS", "5"), KEEP_MIN, KEEP_MAX, 5)

OLLAMA_MODEL_CHEAP = (os.getenv("OLLAMA_MODEL_CHEAP") or "").strip() or OLLAMA_MODEL
MODEL_CHEAP = (os.getenv("MODEL_CHEAP") or "").strip() or MODEL or ""
# 轻量模型是否关闭思考/推理：1=关闭（默认），0=保留；仅在远程且轻量模型与主模型不同时生效
CHEAP_MODEL_DISABLE_THINKING = _clamp_int(
    os.getenv("CHEAP_MODEL_DISABLE_THINKING", "1"), 0, 1, 1
) == 1
SUMMARY_CONCURRENCY = _clamp_int(os.getenv("SUMMARY_CONCURRENCY", "3"), 1, 8, 3)
STRONG_MODEL = OLLAMA_MODEL if MODEL_PROVIDER == "local" else MODEL
CHEAP_MODEL = OLLAMA_MODEL_CHEAP if MODEL_PROVIDER == "local" else MODEL_CHEAP


def clamp_search_count(value=None) -> int:
    """校验搜索论文数量，None 时取 .env 配置值"""
    return _clamp_int(value if value is not None else SEARCH_MAX_RESULTS, SEARCH_MIN, SEARCH_MAX, SEARCH_MAX_RESULTS)


def clamp_keep_papers(value=None) -> int:
    """校验最终保留论文数量，None 时取 .env 配置值"""
    return _clamp_int(value if value is not None else KEEP_PAPERS, KEEP_MIN, KEEP_MAX, KEEP_PAPERS)


# ============================================================
# 模块五：可观测性（Langfuse）
# ============================================================
# 两个 key 缺任一即视为未配置，观测能力降级为“不上报”，不影响主流程。
LANGFUSE_PUBLIC_KEY = (os.getenv("LANGFUSE_PUBLIC_KEY") or "").strip()
LANGFUSE_SECRET_KEY = (os.getenv("LANGFUSE_SECRET_KEY") or "").strip()
# SDK v5 优先读 LANGFUSE_BASE_URL，这里兼容旧的 LANGFUSE_HOST 写法
LANGFUSE_BASE_URL = (
    os.getenv("LANGFUSE_BASE_URL")
    or os.getenv("LANGFUSE_HOST")
    or "https://cloud.langfuse.com"
).strip()
LANGFUSE_ENABLED = bool(LANGFUSE_PUBLIC_KEY and LANGFUSE_SECRET_KEY)


# ============================================================
# 模块六：LLM 磁盘缓存与成本统计
# 社区网址：https://docs.litellm.com.cn/docs/proxy/model_cost_map
# https://github.com/BerriAI/litellm/blob/main/model_prices_and_context_window.json
# ============================================================
_BASE_DIR = os.path.dirname(os.path.abspath(__file__))


def _optional_float(name: str):
    """读取可选浮点配置，空值或非法值返回 None（表示“未设置”）"""
    raw = (os.getenv(name) or "").strip()
    if not raw:
        return None
    try:
        return float(raw)
    except ValueError:
        return None


CACHE_ENABLED = (os.getenv("CACHE_ENABLED", "1") or "").strip().lower() not in ("0", "false", "no", "off")
CACHE_DIR = os.getenv("CACHE_DIR") or os.path.join(_BASE_DIR, ".cache")
# 方案8 规约：prompt 模板/缓存格式大改，或任何影响输出的代码逻辑变更时 +1，强制旧缓存全部失效
# （缓存键只覆盖 prompt/模型/采样参数，覆盖不了代码行为变化与供应商侧模型更新）
CACHE_VERSION = (os.getenv("CACHE_VERSION") or "1").strip()

# 采样参数：参与缓存键；留空则不向 API 传参（使用服务端默认值）
LLM_TEMPERATURE = _optional_float("LLM_TEMPERATURE")
LLM_TOP_P = _optional_float("LLM_TOP_P")

# 单价表（litellm 的 model_prices_and_context_window.json），单位：美元 / token
MODEL_PRICES_PATH = os.getenv("MODEL_PRICES_PATH") or os.path.join(
    _BASE_DIR, "prices", "model_prices_and_context_window.json"
)
# 表里查不到的模型可手动给单价（美元 / 百万 token），两者都填才生效
MODEL_PRICE_INPUT_PER_1M = _optional_float("MODEL_PRICE_INPUT_PER_1M")
MODEL_PRICE_OUTPUT_PER_1M = _optional_float("MODEL_PRICE_OUTPUT_PER_1M")
# 可选：人民币展示汇率，不填则只显示美元
USD_TO_CNY = _optional_float("USD_TO_CNY")
