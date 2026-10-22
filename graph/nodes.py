from graph.state import SupervisorState
from tools.arxiv_tool import search_papers
from llm import invoke_llm

from logger import logger

def supervisor_node(state: SupervisorState):
    logger.info(f"supervisor_node")
    if not state.get("topic") or not state["topic"].strip():
        topic = input("请输入研究主题：\n")
        if not topic:
            print("未输入研究主题，默认为 Graph。")
            topic = "Graph"
        return {"topic": topic, "next": "search"}

    papers = state.get("papers") or []
    summary = (state.get("summary") or "").strip()
    critique = (state.get("critique") or "").strip()
    previous = (state.get("next") or "").strip() or "无（流程刚开始）"
    revision_count = state.get("revision_count", 0)
    critique_times = state.get("critique_times", 3)

    message = f"""你是论文研究助手的路由节点，负责决定下一步执行哪个节点。
只从 search、summarize、critic 中选择一个，不要输出其他任何内容。

当前状态：
- 研究主题：{state["topic"]}
- 已检索论文数：{len(papers)}
- 是否已有研究综述：{"是" if summary else "否"}
- 上一步执行的节点：{previous}
- 最近一次评审意见：{critique or "无"}
- 已修改次数：{revision_count}/{critique_times}

判断规则（从上往下，命中即停）：
1. 上一步是 search：输出 summarize（即使没检索到论文也进入总结，避免重复搜索）。
2. 已检索论文数为 0：输出 search。
3. 上一步是 critic：输出 summarize（按评审意见修改综述）。
4. 上一步是 summarize：输出 critic（提交评审）。
5. 还没有研究综述：输出 summarize。
6. 其他情况：输出 critic。

输出要求：只输出一个小写英文单词，不要标点、解释、换行或代码块。"""

    responses = invoke_llm(message)
    next_step = responses.strip().lower()
    if next_step not in {"search", "summarize", "critic"}:
        next_step = "critic" if summary else "search"
    return {'next': next_step}

def worker_search(state: SupervisorState):
    logger.info("worker_search")
    return {'papers': search_papers(state['topic'])}

def worker_summarize(state: SupervisorState):
    logger.info("worker_summarize")
    paper_texts = "\n".join([
        f"- {p.title}: {p.summary[:150]}" for p in state["papers"]
    ])
    message = f"请根据以下论文写一段200字的研究综述：\n{paper_texts}"
    if state.get("critique"):
        message += f"\n\n需要根据审评意见{state['critique']}进行精炼汇总。"
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