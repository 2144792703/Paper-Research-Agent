from graph.graph_compile import graph

result = graph.invoke({
    "topic": "graph neural network",
    "papers": [],
    "summary": "",
    "next": "",
    "critique": "",
    "followup": "",

    "paper_summaries": [],

    "critique_times": 2,
    "revision_count": 0,
})

summaries = result.get("paper_summaries", [])
print(f"\n=== 总结了 {len(summaries)} 篇论文 ===")
for s in summaries:
    print(f"\n📄 {s['title'][:60]}")
    sm = s["summary"]
    print(f"  问题: {sm.get('problem', '')}")
    print(f"  方法: {sm.get('method', '')}")
    print(f"  结果: {sm.get('result', '')}")
    print(f"  局限: {sm.get('limitation', '')}")
