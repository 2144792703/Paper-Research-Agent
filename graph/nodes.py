import re

from graph.state import SupervisorState
from tools.arxiv_tool import search_papers
from llm import invoke_llm, stream_llm

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
    paper_summaries = state.get("paper_summaries") or []
    summary = (state.get("summary") or "").strip()
    critique = (state.get("critique") or "").strip()
    previous = (state.get("next") or "").strip() or "none"
    revision_count = state.get("revision_count", 0)
    critique_times = state.get("critique_times", 3)

    # 评审意见：只在上一步是 critic 时才是当前待处理的，否则标注过期截断
    critique_display = "无"
    if critique:
        if previous == "critic":
            critique_display = critique[:200] + ("..." if len(critique) > 200 else "")
        else:
            critique_display = critique[:120] + "...(已过期)"

    ps_total = len(papers)
    ps_done = len(paper_summaries)

    message = f"""你是论文研究助手的路由决策者。只能输出 search、summarize、critic 三者之一。

当前状态：
- 研究主题：{state["topic"]}
- 筛选后论文：{len(papers)} 篇
- 单篇结构化总结：{ps_done}/{ps_total if ps_total else 0}
- 研究综述：{"已生成" if summary else "未生成"}
- 评审进度：{revision_count}/{critique_times}
- 上次决策：{previous}
  (none=初始；search=搜索→筛选→单篇总结 整条链已完成；summarize=综述刚写完；critic=刚收到评审意见)
- 评审意见：{critique_display}

决策规则（严格按优先级判断，命中即停）：
1. 上次决策是 critic → 输出 summarize。
   必须按评审意见修改综述，不要跳步去 search 或 critic。
2. 已有综述（无论上次是什么，除非规则1命中）→ 输出 critic。
   提交评审。上一步是 summarize 时必须走这条，禁止再次 summarize。
3. 论文数为 0 → 输出 search。
4. 综述未生成 + 有论文 → 输出 summarize。
5. 初始状态（none）→ 输出 search。
6. 综述为空时，绝对禁止输出 critic。必须先 summarize。

硬约束：
- 上一步是 summarize 时，绝对禁止再次输出 summarize（防死循环）。
- 同一综述周期内有论文时，禁止重复 search。

输出：只一个小写英文单词，不要其他任何内容。"""

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

    paper_summaries = state.get("paper_summaries") or []
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

    message = f"""请根据以下论文信息，写一份 Markdown 格式的研究报告：

{paper_texts}

要求：
1. 开头用 ## 研究背景 写一段现状概述
2. 中间用 ## 论文对比 放一个 Markdown 表格（列：论文/问题/方法/结果）
3. 结尾用 ## 研究空白 指出未来方向
4. 总字数 300-500 字
"""

    if state.get("critique"):
        message += f"\n\n需要根据评审意见修改：{state['critique']}"

    print("\n" + "=" * 60)
    print("📝 正在生成研究报告...")
    print("=" * 60 + "\n")

    full_text = ""

    for chunk in stream_llm(message):
        print(chunk, end="", flush=True)
        full_text += chunk

    return {'summary': full_text.lstrip()}

def critic_node(state: SupervisorState):
    logger.info("critic_node")
    """评审 summary 质量，决定通过还是打回重做"""

    history = state.get("critique_history") or []
    if history:
        prompt = f"""请评审修订后的论文总结：
主题：{state["topic"]}
当前版本：{state['summary']}

上一轮评审意见：{history[-1]}

请判断：
1. 上一次提出的问题解决了吗？
2. 还有新问题吗？

如果全部达标，只回复：通过。
如果还有问题，回复具体修改意见（1-3 条）。
"""
    else:
        # 第一次审评
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

    new_history = history + [result.strip()]

    return {
        "critique": result.strip(),
        "revision_count": state["revision_count"]+1,
        "critique_history": new_history
    }

def followup_node(state: SupervisorState):
    logger.info("followup_node")
    prompt = f"""基于以下研究主题和内容，推荐 2-3 个用户可能想进一步了解的方向：
主题：{state["topic"]}
总结：{state['summary']}

每个方向一句话，用序号列出。"""
    result = invoke_llm(prompt)
    return {"followup": result.strip()}
