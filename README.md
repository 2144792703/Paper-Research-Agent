# 项目名称：根据研究主题使用 arXiv 工具生成相关综述报告

## 核心功能
1. 输入主题，自动搜索 arXiv 论文
2. LLM 筛选最相关论文（优先同子领域、同技术范式），逐篇结构化总结
3. 生成综述报告，critic 自动修订最多 2 轮

## 可配置参数
| 参数 | 命令行 | .env | 默认 | 取值范围 |
| --- | --- | --- | --- | --- |
| 模型提供方 | - | `MODEL_PROVIDER` | remote | remote / local |
| 远程模型 | - | `MODEL` | - | - |
| 远程 key（池化 / 单个） | - | `API_KEY_POOLS` / `API_KEY` | - | 逗号分隔多个 key |
| 轻量节点模型 | - | `MODEL_CHEAP` / `OLLAMA_MODEL_CHEAP` | 回退主模型 | - |
| 轻量模型关闭思考 | - | `CHEAP_MODEL_DISABLE_THINKING` | 1 | 0 / 1 |
| 本地模型 | - | `OLLAMA_MODEL` | qwen2.5:7b-instruct-q5_K_M | - |
| 单次搜索拉取论文数 | `--search-count` | `SEARCH_MAX_RESULTS` | 15 | 1-50 |
| 最终保留论文数 | `--papers` | `KEEP_PAPERS` | 5 | 1-10 |
| 单篇总结并发度 | - | `SUMMARY_CONCURRENCY` | 3 | 1-8 |
| 最大评审轮数 | `--max-retries` | - | 2 | - |
| 混沌失败率 | - | `CHAOS_FAILURE_RATE` | 0.0 | 0-1 |

命令行参数优先，未指定时读取 .env；越界值会自动收敛到合法区间并提示。

## 项目架构草图
```plaintext
topic → supervisor → search → select → summarize_one → summarize → critic
                          ↑                                    │
                          └──────── 未通过：按评审意见修订 ──────┘
                                                               │ 通过
                                                               ↓
                                                         followup → END
```

- `remote` / `local` 由 `MODEL_PROVIDER` 唯一路由，业务层只依赖 `llm.invoke_llm / stream_llm`。
- 远程 key 支持池化（多个 key 轮换）与单个 key 两种写法，细节见 [API_KEY_POOL.md](API_KEY_POOL.md)。
