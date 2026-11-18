# 第 7 周复盘（D43–D48）

- 复盘日期：2026-11-18（计划 Day49）
- 范围：Docker / Langfuse / 缓存与成本 / 输入校验 / 注入安全 / 并发 / 混沌与兜底
- 回归命令：`python -m pytest` → **19 passed, 5 deselected in 0.08s**

## 一、本周改动清单

| 日期 | commit | 类型 | 核心改动 | 验证证据 |
| --- | --- | --- | --- | --- |
| D43 | `911124d` | 工程 | Dockerfile、docker-compose、.dockerignore | 容器从零跑通 |
| D44 | `1c074ad` | 可观测 | Langfuse 接入，调用链与 token 统计 | 双 key 配齐才启用，缺一自动跳过 |
| D45 | `6748d05` | 性能/成本 | diskcache 磁盘缓存、单次 run token/成本统计、价格表 | cache hit/miss 与成本输出 |
| D45 | `36c6cb7` | 修复 | 数字校验扩展、成本部分计价 | report_check 12 用例 |
| D46 | `d3c57bf` | 安全 | 输入清洗与注入检测、注入测试用例 | 5 个 live 用例（手动执行） |
| D47 | `5e0c027` | 性能 | 单篇总结并发化、模型分级 | 总结阶段提速 3.47 倍 |
| D48 | `a5b6402` | 稳定性 | 混沌开关、重试/换 key、路由/筛选/综述三层兜底、统计锁 | 开/关对照 + 7 个混沌单测 |
| D49 | 本次 | 清理 | 日志收敛、pytest 收集范围、周复盘 | 19 passed；3 主题实跑观察 |

## 二、遗留项结论

| 遗留项 | 结论 | 理由与证据 |
| --- | --- | --- |
| cache.py 写盘失败日志 | 已修 | warning 只留异常类型 + key 前缀，完整消息降 debug |
| usage.py 价格表加载失败日志 | 已修 | warning 只留异常类型 + 文件名 + 80 字符消息，完整消息降 debug |
| cheap 档坏 JSON（#9） | 继续观察 | `CHAOS=0` 复跑 2 主题，约 12 次结构化调用，坏 JSON=0；3 主题混沌跑也无解析失败 |
| output.txt 是否入库 | 有意保留 | 作为每日功能测试输出与版本证据，按 run 追加统计块 |
| cloudflare provider | 有意保留 | 与魔塔同属 `remote` OpenAI 兼容端点，不是独立 provider 分支 |
| 全量 pytest 混入脚本 | 已修 | `pytest.ini` + `collect_ignore` 隔离脚本，live 用例默认排除 |
| 非综述节点失败兜底 | 已修 | supervisor 确定性路由、select 顺序保留、critic/followup 降级 |

## 三、回归与观察记录

### 3.1 离线全量回归

- `python -m pytest`：19 passed，5 deselected。
- 收集范围：`test/report_check_test.py` 12 个 + `test/chaos_test.py` 7 个。
- 脚本式验收（`full_run_test.py`、`tools_test.py` 等）不参与 pytest 收集，继续用 `python test/xxx.py` 手动执行。

### 3.2 cheap 档坏 JSON 观察（CHAOS=0）

| 主题 | 筛选 | 单篇总结 | 总结耗时 | 坏 JSON | API 异常 |
| --- | --- | --- | --- | --- | --- |
| graph neural network | 5/15 | 5 篇 | 2.74s | 0 | 0 |
| retrieval augmented generation | 5/15 | 5 篇 | 2.77s | 0 | 0 |

结论：本轮无坏 JSON，先标注“继续观察”；若后续复现，保留主题与原始输出，再在解析层加 JSON 提取修复。

### 3.3 混沌附加观察（.env 当前 CHAOS_FAILURE_RATE=0.2）

| 主题 | 注入 | 请求尝试 | 重试 | 是否出报告 |
| --- | --- | --- | --- | --- |
| graph neural network | 6 | 17 | 5 | 是（1 次单篇总结注入耗尽，保留空结构后仍出报告） |
| retrieval augmented generation | 3 | 14 | 2 | 是 |
| LLM agent planning | 3 | 14 | 2 | 是 |

## 四、踩坑与解法

1. **空响应 + 空缓存导致死循环**：空值不写缓存、不读缓存；supervisor 加确定性护栏；综述失败用单篇结构化摘要兜底。
2. **ModelScope 429 `code 1305`**：模型侧过载，不是代码错误；可换 `MODEL_CHEAP`、换提供方或等待；单 key 下 `MAX_ROUNDS=4` 会被注入与冷却耗尽。
3. **混沌注入复用 5s 冷却**：单 key 下两次注入即可耗尽一轮重试，属于已知取舍（P2 再拆）。
4. **重试统计口径**：`retries` 不能简单等于 `attempts - 1`，需按逻辑调用累计，并加锁保证并发安全。
5. **Langfuse 启用条件**：`PUBLIC_KEY` 与 `SECRET_KEY` 缺任一即关闭，无需额外开关。
6. **pytest 收集范围**：`*_test.py` 脚本会在收集阶段跑真实链路，必须用 `collect_ignore` 隔离，live 用例用 marker 排除。
7. **Windows 清缓存**：不要手删 `.cache/cache.db`，用 `main.py --clear-cache`（内部 `Cache.clear()`）避免文件锁。

## 五、疑问清单（D50+ 处理）

- 价格表缺 `Qwen/Qwen3.8-Flash-Next`、`Qwen/Qwen3.5-35B-A3B`，成本只能报 token；D50 决定补录价格还是改用显式单价。
- 本地 `.env` 仍是 `CHAOS_FAILURE_RATE=0.2`，提交演示前确认恢复 `0.0`。
- 混沌注入与真实 5xx 共用 5s 冷却，是否拆分（P2）。
- 非综述节点兜底只保证不中断，质量可能下降（如 select 退化为顺序保留），是否需要显式降级标记。
