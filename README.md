# 项目名称：根据研究主题使用 arXiv 工具生成相关综述报告

## 核心功能
1. 输入主题，自动搜索 arXiv 论文
2. LLM 删选最相关的 3-5 篇， 逐篇结果化总结
3. 生成综述报告，critic 自动修订最多 2 轮

## 项目架构草图
```plaintext
topic → search → select → summarize → report → critic → followup → END
```
