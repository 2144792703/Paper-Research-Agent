import re

from graph.state import SupervisorState
from tools.arxiv_tool import search_papers
from llm import invoke_llm

from pydantic import BaseModel, Field

from logger import logger

class SelectedPaper(BaseModel):
    """选中的一篇论文"""
    index: int = Field(description="候选论文的序号，对应列表中的 [i]")
    reason: str = Field(description="为什么这篇与主题相关，一句话")

class SelectionResult(BaseModel):
    """LLM 筛选结果"""
    selected: list[SelectedPaper] = Field(description="选中的论文，3-5篇")

class PaperSummary(BaseModel):
    """单篇论文的结构化总结"""
    problem: str = Field(description="用一句话总结这篇论文要解决什么问题")
    method: str = Field(description="用一句话总结这篇论文用什么方法/模型")
    result: str = Field(description="用一句话总结这篇论文的实验结果或者主要发现")
    limitation: str = Field(description="用一句话总结该论文的局限性或者未来方向")

def supervisor_node(state: SupervisorState):
    logger.info("supervisor_node")
    if not state.get("topic") or not state["topic"].strip():
        topic = input("请输入研究主题：\n")
        if not topic:
            print("未输入研究主题，默认为 Graph。")
            topic = "Graph"
        return {"topic": topic, "next": "search"}

    papers = state.get("papers") or []
    summary = (state.get("summary") or "").strip()
    critique = (state.get("critique") or "").strip()
    previous = (state.get("next") or "").strip() or "none"

    message = f"""你是论文研究助手的路由节点，根据当前进度决定下一步进入哪个节点。
只能输出 search、summarize、critic 三者之一。

当前进度：
- 研究主题：{state["topic"]}
- 已检索并筛选后的论文数：{len(papers)}
- 是否已有研究综述：{"yes" if summary else "no"}
- 上一步进入的节点：{previous}（none=流程刚开始；search=刚完成“搜索+筛选”；summarize=刚写完综述；critic=刚收到评审意见）
- 最近一次评审意见：{critique or "无"}

决策规则（严格按顺序判断，命中即停，不要自行调整顺序）：
1. 上一步是 search → 输出 summarize。
   搜索和筛选刚结束，必须先写综述；即使论文数为 0 也进入 summarize，禁止立刻再次 search。
2. 上一步是 critic → 输出 summarize。
   评审未通过时才会回到这里，必须按最近评审意见重写综述，不要重复搜索或再次提交评审。
3. 论文数为 0 → 输出 search。
   还没有论文，只能先检索。
4. 是否已有综述 = no → 输出 summarize。
   有论文但还没写综述。
5. 其余情况 → 输出 critic。
   综述刚修改完成，提交评审。

硬约束：
- 论文数大于 0 时，禁止输出 search：同一主题重复搜索不会带来新论文。

输出：只输出一个小写英文单词（search / summarize / critic），不要标点、引号、解释、换行或代码块。"""

    responses = invoke_llm(message)
    next_step = responses.strip().lower()
    if next_step not in {"search", "summarize", "critic"}:
        logger.warning(f"路由输出不合法：{responses!r}，默认走 search")
        next_step = "search"
    return {'next': next_step}

def worker_search(state: SupervisorState):
    logger.info("worker_search")
    new_papers = search_papers(state['topic'], max_results=15)
    existing = state.get("papers") or []
    seen = {p.url for p in existing}
    merged = existing + [p for p in new_papers if p.url not in seen]
    return {'papers': merged}

def worker_select(state: SupervisorState):
    """从搜索结果中筛选最相关的论文"""
    logger.info("worker_select")
    papers = state.get("papers") or []
    if not papers:
        return {"papers": []}
    
    paper_list = "\n".join([
        f"[{i}] 标题：{p.title}\n      摘要：{p.summary[:150]}"
        for i, p in enumerate(papers)
    ])

    prompt = f"""研究主题：{state['topic']}

以下是搜索到的 {len(papers)} 篇论文，请选出与主题最相关的 3-5 篇。
用序号说明选择理由。

{paper_list}

请以 JSON 返回，格式为：
{{"selected": [{{"index": 0, "reason": "这篇论文与主题的关系"}}]}}

index 必须是上面列表中的序号。只返回 JSON，不要代码块或额外说明。"""

    result = invoke_llm(prompt)
    result = re.sub(r"^\s*```(?:json)?\s*", "", result)
    result = re.sub(r"\s*```\s*$", "", result)

    try:
        parsed = SelectionResult.model_validate_json(result)
        selected_papers = []
        seen = set()
        for item in parsed.selected:
            if not 0 <= item.index < len(papers):
                continue
            paper = papers[item.index]
            if paper.url in seen:
                continue
            seen.add(paper.url)
            selected_papers.append(paper)
        if not selected_papers:
            logger.warning("筛选结果为空或序号无效，保留全部论文")
            return {"papers": papers}
        logger.info(f"筛选后保留 {len(selected_papers)} / {len(papers)} 篇")
        return {'papers': selected_papers}
    except Exception as e:
        logger.warning(f"筛选解析失败，保留全部论文：{e}")
        return {"papers": papers}

def worker_summarize_one(state: SupervisorState):
    """对每篇论文做结构化总结"""
    logger.info("worker_summarize_one")
    paper = state.get("papers") or []
    summaries = []

    for p in paper:
        prompt = f"""请阅读以下论文信息，提取结构化总结。

标题：{p.title}
摘要：{p.summary}

请以 JSON 返回：
{{"problem": "...", "method": "...", "result": "...", "limitation": "..."}}

每个字段一句话，不要超过50字。只返回 JSON。"""

        result = invoke_llm(prompt)
        # 去 markdown 代码
        result = re.sub(r"^\s*```(?:json)?\s*", "", result)
        result = re.sub(r"\s*```\s*$", "", result)

        try:
            parsed = PaperSummary.model_validate_json(result)
            summaries.append({
                "title": p.title,
                "url": p.url,
                "summary": parsed.model_dump(),
            })
            logger.info(f"已总结：{p.title[:50]}")
        except Exception as e:
            logger.warning(f"总结解析失败，跳过：{e}")
            summaries.append({
                "title": p.title,
                "url": p.url,
                "summary": {"problem": "", "method": "", "result": "", "limitation": ""}
            })
            
    return {"paper_summaries": summaries}

def worker_summarize(state: SupervisorState):
    logger.info("worker_summarize")

    paper_summaries = state.get("paper_summarizes") or []
    papers = state.get("papers") or []

    if paper_summaries:
        # 用结构化总结 拼 综述输出
        paper_texts = "\n".join([
            f"- {s['title']}: "
            f"- {s['url']}"
            f"问题={s['summary'].get('problem','')}; "
            f"方法={s['summary'].get('method','')}; "
            f"结果={s['summary'].get('result','')}"
            f"局限={s['summary'].get('limitation','')}"
            for s in paper_summaries
        ])
    else:
        # 使用原始摘要
        paper_texts = "\n".join([
            f"- {p.title}: {p.summary[:150]}" for p in papers
        ])

    message = f"""请根据以下论文总结，写一段 300 字的研究综述：
{paper_texts}

要求：
1. 开头一句话概括研究现状
2. 中间对比个篇论文的方法和贡献
3. 结尾指出研究空白或者未来方向
"""

    if state.get("critique"):
        message += f"\n\n需要根据评审意见修改：{state['critique']}"
        
    responses = invoke_llm(message)
    return {'summary': responses.strip()}

def critic_node(state: SupervisorState):
    logger.info("critic_node")
    """评审 summary 质量，决定通过还是打回重做"""
    prompt = f"""请评审以下论文总结的质量：
    主题：{state['topic']}
    总结：{state['summary']}

    评审标准：
    1. 是否覆盖了论文的核心发现？
    2. 是否有具体数据/结论？
    3. 是否只是泛泛而谈？

    如果质量达标，只回复：通过。
    如果不达标，回复具体修改意见（1-2条）。"""
    result = invoke_llm(prompt)
    return {"critique": result.strip(), "revision_count": state["revision_count"]+1}

def followup_node(state: SupervisorState):
    logger.info("followup_node")
    prompt = f"""基于以下研究主题和内容，推荐 2-3 个用户可能想进一步了解的方向：
主题：{state["topic"]}
总结：{state['summary']}

每个方向一句话，用序号列出。"""
    result = invoke_llm(prompt)
    return {"followup": result.strip()}