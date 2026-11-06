import os
from dotenv import load_dotenv

load_dotenv()


# ============================================================
# 模块一：模型路由
# ============================================================
# local  -> 本地 Ollama 服务
# remote -> 远程 OpenAI 兼容 API
MODEL_PROVIDER = os.getenv("MODEL_PROVIDER", "remote").strip().lower()


# ============================================================
# 模块二：远程模型（OpenAI 兼容接口）
# ============================================================
MODEL = os.getenv("MODEL")
API_KEY = os.getenv("API_KEY")
BASE_URL = os.getenv("BASE_URL")

REQUEST_TIMEOUT = os.getenv('REQUEST_TIMEOUT', '600.0')
MAX_RETRIES = os.getenv('MAX_RETRIES', '2')


def _parse_key_pools() -> list[str]:
    """解析 API_KEY_POOLS（逗号分隔），去重保序；为空时回退到单个 API_KEY"""
    raw = os.getenv("API_KEY_POOLS", "")
    keys = [k.strip() for k in raw.split(",") if k.strip()]
    if not keys and API_KEY:
        keys = [API_KEY]
    return list(dict.fromkeys(keys))


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
