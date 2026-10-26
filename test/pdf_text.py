from tools.arxiv_tool import search_papers
from tools.pdf_tool import extract_pdf_text

# 搜一篇论文，拿它的 pdf_url
papers = search_papers("RAG retrieval", max_results=1)
pdf_url = papers[0].url
print(f"测试PDF: {pdf_url}")

text = extract_pdf_text(pdf_url, max_chars=2000)
print(f"提取文本长度: {len(text)}")
print(f"前500字:\n{text[:500]}")
print(f"\n后200字:\n{text[-200:]}")

# 验收
assert len(text) > 100, "文本太短，可能解析失败"
assert "abstract" in text.lower() or "Abstract" in text or "引言" in text, "应该包含正文内容"
print("✅ PDF解析测试通过")
