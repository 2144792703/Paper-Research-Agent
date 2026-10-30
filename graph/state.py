from typing import TypedDict

class SupervisorState(TypedDict):
    """
    topic 研究主题或搜索关键词，用于指导论文搜索和总结
    papers 论文数据池，存储搜索到的所有论文信息（如标题、作者、摘要等）
    summary 研究综述，由大模型根据 papers 生成的内容
    next 路由指令，Supervisor 节点决定下一步走向哪个节点的标识
    critique 评审意见，Critic 节点的评审结果（通过或具体修改建议）
    followup 推荐出与 topic 和 summary 的内容
    critique_history 审评历史
    paper_summaries 对每篇论文做结构化总结
    critique_times 最大重试次数，防止程序陷入无限死循环
    revision_count 当前已重试次数，每次完成评审后加 1
    """
    topic: str
    papers: list[dict]
    summary: str
    next: str
    critique: str
    followup: str
    critique_history: list[dict]
    paper_summaries: list[dict]
    critique_times: int
    revision_count: int