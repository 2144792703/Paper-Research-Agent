# v0.1 MVP — 论文研究报告 Agent

## 功能清单
- arXiv 论文检索（关键词搜索，可配置数量）
- LLM 论文筛选（保留 top N 篇，Pydantic 结构化输出）
- 单篇结构化总结（问题/方法/结果/局限）
- 综述报告生成（Markdown 格式，含对比表格，流式输出）
- Critic 反思循环（最多 2 轮，带历史对比评审）
- 追问推荐（followup 节点）
- CLI 交互（argparse 参数 + 边界钳制）
- FastAPI 服务（POST /research SSE 流式 + GET /health + Swagger UI）
- 边界保护（无效主题拦截、全局异常处理、请求超时）

## 已知限制
- Critic 要求"具体量化数据"但 arXiv 摘要不含数字，可能永远不达标
- 单线程处理（summarize_one 串行，未并发）
- 无缓存，重复查询每次都消耗 API 调用
- 未接入 Docker / 可观测性

## 技术栈
- LangGraph (Supervisor 模式)
- DeepSeek API (key 池 + 指数退避 + 401/403 永久禁用)
- FastAPI + SSE
- Pydantic v2
- arxiv / pdfplumber

## 评估结果
- 20 主题测试通过率：95%（19/20，唯一失败为 emoji 乱码被正确拦截）
- 平均耗时：28.9s/主题
