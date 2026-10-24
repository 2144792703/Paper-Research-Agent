from tools.arxiv_tool import search_papers, PaperMeta

# 测试 1：正常搜索
papers = search_papers("RAG retrieval", max_results=3)
assert len(papers) > 0, "应该搜索到论文了。"
assert isinstance(papers[0], PaperMeta), "应该返回 PaperMete 对象。"
assert papers[0].title, "标题不为空。"
assert papers[0].url, "URL 不为空。"
print(f"✅ 测试1通过：搜到 {len(papers)} 篇，第一篇：{papers[0].title[:50]}")

# 测试2：无结果
papers = search_papers("xyzabc123notaword", max_results=5)
assert papers == [], f"无结果应返回空列表，实际：{papers}"
print("✅ 测试2通过：无结果返回空列表")

# 测试3：max_results 边界
papers = search_papers("deep learning", max_results=3)
assert len(papers) <= 3, f"最多返回3篇，实际{len(papers)}"
print(f"✅ 测试3通过：max_results=3 实际返回 {len(papers)} 篇")

# 测试4：PaperMeta 字段完整性
p = papers[0]
assert p.title and isinstance(p.title, str)
assert p.authors and isinstance(p.authors, list)
assert p.published and isinstance(p.published, str)
assert p.summary and isinstance(p.summary, str)
assert p.url and isinstance(p.url, str)
print("✅ 测试4通过：PaperMeta 5个字段完整")