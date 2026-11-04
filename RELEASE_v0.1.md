# v0.1 MVP — 论文研究报告 Agent

## 核心功能
- arXiv 论文检索（关键词搜索，数量可配置）
- LLM 论文筛选（保留 top N 篇最相关）
- 单篇结构化总结（问题/方法/结果/局限）
- 综述报告生成（Markdown 格式，含对比表格）
- Critic 反思循环（最多 2 轮，带历史对比）
- CLI 交互（argparse 参数 + 阶段进度提示）
- FastAPI 服务（POST /research SSE 流式 + GET /health）
- 边界保护（无效主题拦截、参数钳制、全局异常处理、180s 超时）

## 评估结果
- 20 主题通过率：19/20 = 95%
- 平均耗时：28.9s/主题
- 无效输入（emoji/乱码）正确拦截

## 已知限制
- Critic 要求"具体量化数据"但 arXiv 摘要不含数字，可能永远不达标（数据源头问题）
- summarize_one 串行处理，未并发
- 无缓存，重复查询每次都消耗 API 调用
- PDF 解析工具已写但未接入主流程

## 技术栈
- LangGraph（Supervisor 模式 + 条件边）
- DeepSeek API（key 池 + 指数退避 + 401/403 永久禁用）
- FastAPI + SSE StreamingResponse
- Pydantic v2 结构化输出
- arxiv 官方库

## 项目结构
- main.py：CLI 入口
- server.py：FastAPI 服务
- eval.py：20 主题评估脚本
- graph/：state + nodes + graph_compile
- models/：local(Ollama) / remote(API) provider 抽象
- tools/：arxiv_tool + pdf_tool
- config.py + .env：配置
