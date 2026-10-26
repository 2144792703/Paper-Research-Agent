import os
from dotenv import load_dotenv

load_dotenv()

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
if not API_KEYS:
    raise RuntimeError("未配置任何 API key：请在 .env 中配置 API_KEY_POOLS 或 API_KEY")

KEY_COOLDOWN = float(os.getenv('KEY_COOLDOWN', '5'))  # 单 key 限流退避基数（秒）