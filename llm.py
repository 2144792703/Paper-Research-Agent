import time

from langchain.agents import create_agent
from langchain_openai import ChatOpenAI
from openai import RateLimitError

from config import MODEL, API_KEY, BASE_URL, REQUEST_TIMEOUT, MAX_RETRIES
from tools.arxiv_tool import search_papers_tool

client = ChatOpenAI(
    model=MODEL,
    api_key=API_KEY,
    base_url=BASE_URL,
    timeout=float(REQUEST_TIMEOUT),
    max_retries=int(MAX_RETRIES),
)

agent = create_agent(
    model=client,
    tools=[search_papers_tool],
)

def invoke_llm(prompt: str, max_retries: int = 4):
    """调用模型；遇到 429 限流时按 5/10/20 秒指数退避重试。"""
    for attempt in range(max_retries):
        try:
            return client.invoke(prompt)
        except RateLimitError:
            delay = 5 * 2 ** attempt
            print(f"触发 API 限流，{delay} 秒后重试（{attempt + 1}/{max_retries}）")
            time.sleep(delay)
    return client.invoke(prompt)