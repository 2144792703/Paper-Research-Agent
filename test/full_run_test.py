from graph.graph_compile import graph

result = graph.invoke({
    "topic": "retrieval augmented generation",
    "papers": [],
    "summary": "",
    "next": "",
    "critique": "",
    "followup": "",
    "paper_summaries": [],
    "critique_times": 2,
    "revision_count": 0,
})

print("=" * 60)
print(f"主题【1】: {result['topic']}")
print(f"\n--- 结构化总结 ({len(result.get('paper_summaries',[]))} 篇) ---")
for s in result.get("paper_summaries", []):
    print(f"  📄 {s['title'][:50]}")
    print(f"     {s['summary'].get('problem','')[:60]}")

print(f"\n--- 研究综述 ---")
print(result['summary'])

print(f"\n--- 评审意见 ---")
print(result.get('critique', '无'))

print(f"\n--- 追问推荐 ---")
print(result.get('followup', '无'))

result1 = graph.invoke({
    "topic": "protein structure prediction",
    "papers": [],
    "summary": "",
    "next": "",
    "critique": "",
    "followup": "",
    "paper_summaries": [],
    "critique_times": 2,
    "revision_count": 0,
})

print("=" * 60)
print(f"主题【2】: {result1['topic']}")
print(f"\n--- 结构化总结 ({len(result1.get('paper_summaries',[]))} 篇) ---")
for s in result1.get("paper_summaries", []):
    print(f"  📄 {s['title'][:50]}")
    print(f"     {s['summary'].get('problem','')[:60]}")

print(f"\n--- 研究综述 ---")
print(result1['summary'])

print(f"\n--- 评审意见 ---")
print(result1.get('critique', '无'))

print(f"\n--- 追问推荐 ---")
print(result1.get('followup', '无'))

