import time
from graph.graph_compile import graph

# 20个测试主题
TEST_TOPICS = [
    # 5个正常主题
    "RAG retrieval",
    "transformer attention mechanism",
    "protein structure prediction",
    "object detection YOLO",
    "graph neural networks",
    # 5个生僻领域
    "quantum error correction",
    "CRISPR gene editing delivery",
    "climate model downscaling",
    "speech emotion recognition",
    "federated learning heterogeneity",
    # 5个拼写错误
    "trannsformer",
    "deep learing RAG",
    "proten structure",
    "graph neuaral network",
    "speech reccognition",
    # 5个超宽泛/刁钻
    "AI",
    "how to build everything",
    "the future",
    "",
    "🤖🤖🤖",
]


def run_one(topic: str) -> dict:
    """跑一个主题，返回结果"""
    t0 = time.time()
    try:
        result = graph.invoke({
            "topic": topic,
            "critique_times": 1,
            "keep_papers": 3,
        })
        elapsed = time.time() - t0
        summary = result.get("summary", "")

        # 通过标准：有报告且长度>=200字
        passed = len(summary) >= 200
        return {"topic": topic, "passed": passed, "elapsed": elapsed,
                "summary_len": len(summary), "error": None}
    except Exception as e:
        return {"topic": topic, "passed": False, "elapsed": time.time() - t0,
                "summary_len": 0, "error": str(e)[:200]}


if __name__ == "__main__":
    results = []
    for i, topic in enumerate(TEST_TOPICS):
        print(f"[{i + 1}/{len(TEST_TOPICS)}] 测试: {topic[:40]}")
        r = run_one(topic)
        results.append(r)
        print(f"  -> {'✅通过' if r['passed'] else '❌失败'} ({r['elapsed']:.1f}s, {r['summary_len']}字)")

    # 统计
    passed = sum(1 for r in results if r["passed"])
    total = len(results)
    avg_time = sum(r["elapsed"] for r in results) / total

    print(f"\n{'=' * 50}")
    print(f"通过率: {passed}/{total} = {passed / total * 100:.0f}%")
    print(f"平均耗时: {avg_time:.1f}s")

    # 写报告
    with open("eval_results.md", "w", encoding="utf-8") as f:
        f.write(f"# Eval 结果\n\n")
        f.write(f"通过率: {passed}/{total}\n\n")
        f.write(f"平均耗时: {avg_time:.1f}s\n\n")
        f.write("## 失败列表\n")
        for r in results:
            if not r["passed"]:
                f.write(f"- **{r['topic'][:40]}**: {r['error'] or f'报告过短({r["summary_len"]}字)'}\n")

