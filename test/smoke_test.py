from logger import setup_logger
from llm import invoke_llm, stream_llm

setup_logger()

# 测试1：同步调用
print("=== 测试1: invoke_llm ===")
result = invoke_llm("用一句话解释什么是RAG")
print(result)

# 测试2：流式调用
print("\n=== 测试2: stream_llm ===")
for chunk in stream_llm("用一句话解释什么是LangGraph"):
    print(chunk, end="", flush=True)
print()

# 测试3：完整 graph 跑一次
print("\n=== 测试3: graph 冒烟 ===")
from graph.graph_compile import graph
result = graph.invoke(
    {
        "topic": "RAG retrieval",
        "papers": [],
        "summary": "",
        "next": "",
        "followup": "",
        "critique": "",
        "critique_times": 2,
        "revision_count": 0,
    }
)
print("summary:", result["summary"][:100])
print("followup:", result["followup"][:100])