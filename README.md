# 项目名称：根据研究主题使用 arXiv 工具生成相关综述报告

## 核心功能
1. 输入主题，自动搜索 arXiv 论文
2. LLM 删选最相关的论文， 逐篇结果化总结
3. 生成综述报告，critic 自动修订最多 2 轮

## 可配置参数
| 参数 | 命令行 | .env | 默认 | 取值范围 |
| --- | --- | --- | --- | --- |
| 单次搜索拉取论文数 | `--search-count` | `SEARCH_MAX_RESULTS` | 15 | 1-50 |
| 最终保留论文数 | `--papers` | `KEEP_PAPERS` | 5 | 1-10 |
| 最大评审轮数 | `--max-retries` | - | 2 | - |

命令行参数优先，未指定时读取 .env；越界值会自动收敛到合法区间并提示。

## 项目架构草图
```plaintext
topic → search → select → summarize → report → critic → followup → END
```
