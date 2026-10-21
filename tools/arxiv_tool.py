import arxiv

from pydantic import BaseModel, Field
from langchain_core.tools import tool

class PaperMeta(BaseModel):
    title: str = Field(description="论文标题")
    authors: list[str] = Field(description="作者列表")
    published: str = Field(description="发布日期 YYYY-MM-DD")
    summary: str = Field(description="摘要前200字")
    url: str = Field(description="PDF链接或abs链接")

def search_papers(query: str, max_results: int = 5) -> list[PaperMeta]:
    """
    输入：搜索关键词（如 "LangGraph agent"），最多返回几篇
    输出：论文元数据列表
    """
    print("search_papers")
    search_client = arxiv.Client(
        page_size=10,
        num_retries=5,
        delay_seconds=5.0,
    )
    search = arxiv.Search(
        query = query,
        max_results = max_results,   # 返回的搜索数量
        sort_by = arxiv.SortCriterion.SubmittedDate,
    )
    papers: list[PaperMeta] = []

    try:
        for sr in search_client.results(search):
            papers.append(
                PaperMeta(
                    title=sr.title,
                    authors=[a.name for a in sr.authors],
                    published=sr.published.strftime("%Y-%m-%d"),
                    summary=sr.summary[:200],
                    url=sr.pdf_url or sr.entry_id,
                )
            )
    except arxiv.HTTPError as e:
        print(e)
    print(f'===search_papers，查到 {len(papers)} 条数据。并返回 {len(papers)} 条数据。===')
    return papers

@tool("search_papers")
def search_papers_tool(query: str, field: str = 'all', max_results: int = 5) -> list[dict]:
    """搜索 arXiv 论文
    Args:
        query: 搜索关键词
        field: 搜索字段 - all/ti(标题)/au(作者)/abs(摘要)
        max_results: 最多返回几篇
    """
    if field != "all":
        query = f"{field}:{query}"
    papers = search_papers(query, max_results)
    print(f'===search_papers_tool，查到 {len(papers)} 条数据。并返回 {len(papers)} 条数据。===')
    return [p.model_dump() for p in papers]
