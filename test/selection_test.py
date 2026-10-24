from graph.graph_compile import graph

topics = ["RAG retrieval", "LLM agent planning", "graph neural network"]

for topic in topics:
    result = graph.invoke({
        "topic": topic,
        "papers": [],
        "summary": "",
        "next": "",
        "followup": "",
        "critique": "",
        "critique_times": 2,
        "revision_count": 0,
    })

    papers = result.get("papers", [])
    print(f"\n=== 主题: {topic} ===")
    print(f"筛选后论文数: {len(papers)}")
    for p in papers:
        print(f"  - {p.title[:60]}")
    print(f"summary: {result.get('summary','')[:80]}")
