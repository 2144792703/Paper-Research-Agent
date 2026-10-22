import time, logging

from langchain.agents import create_agent
from langchain_openai import ChatOpenAI
from openai import RateLimitError

from config import MODEL, API_KEY, BASE_URL, REQUEST_TIMEOUT, MAX_RETRIES
from tools.arxiv_tool import search_papers_tool

logger = logging.getLogger(__name__)

def get_client() -> ChatOpenAI:
    """创建 LLM 客户端（单例）"""
    return ChatOpenAI(
                model=MODEL,
                api_key=API_KEY,
                base_url=BASE_URL,
                timeout=float(REQUEST_TIMEOUT),
                max_retries=int(MAX_RETRIES),
            )

client = get_client()

# agent = create_agent(
#     model=client,
#     tools=[search_papers_tool],
# )

def invoke_llm(prompt: str, max_retries: int = 4):
    """调用模型；遇到 429 限流时按 5/10/20 秒指数退避重试。"""
    for attempt in range(max_retries):
        try:
            return client.invoke(prompt).content
        except RateLimitError:
            delay = 5 * 2 ** attempt
            logger.warning(f"API限流，{delay}秒后重试 ({attempt+1}/{max_retries})")
            time.sleep(delay)
    return client.invoke(prompt).content

def stream_llm(prompt: str):
    """流式调用，yield 每个 chunk 文本"""
    for chunk in client.stream(prompt):
        yield chunk.content
