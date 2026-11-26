# D55 缓冲日：查漏补缺记录

> 目标：把前面欠下的非阻断项清掉或明确归档，不带病进总复盘。
> 结论：阻断性拖欠为 0；不能当天闭环的项全部进 P2 清单并注明原因。

## 一、今日还清

| 项 | 处理 | 验证 |
| --- | --- | --- |
| 评审「通过」精确匹配导致多跑一轮（D53 回补 Q4/Q7） | `after_critic` 改为 `_passed()`：去掉首尾中英文标点后比较「通过」 | `tests/graph_test.py::test_after_critic_accepts_trailing_punctuation` |
| 兜底降级缺少显式质量标记（D53 回补 Q15） | `SupervisorState` 新增 `degraded / degraded_reasons`；路由、筛选、单篇总结、综述、评审兜底都会写标记（同因去重、跨节点累加）；CLI 打印质量标记，SSE `done` 事件返回同名字段 | `tests/chaos_test.py` 三处断言 + `tests/server_test.py` 的 `degraded: false` 断言 + `tests/graph_test.py::test_degrade_reasons_accumulate_and_dedupe` |
| 混沌注入与真实 5xx 冷却是否拆分（P2 决策） | 决策：不拆分。混沌开关仅调试、默认关闭，拆分只增加配置面，不改善生产可靠性；README 设计决策行同步为「已决策不拆分」 | README「设计决策与踩坑」 |
| 文档间数字不一致 | 离线用例统一为 48、live 为 5；节点名、参数、3.47 倍口径在 README / 两份讲稿 / 题库之间逐条对齐 | 见下表 |
| 离线与 live 说明不一致 | `pytest.ini`（`testpaths=tests`、默认 `-m "not live"`）、README 测试节、`scripts/` 说明三者一致；5 个 live 用例均在 `tests/security_injection_test.py` | `python -m pytest --collect-only`；`-m live` 收集 5 个 |
| 历史注释过期 | 删除 `tests/security_injection_test.py` 里「supervisor 会把 >64 字符判 invalid」的旧说明 | 该规则已不存在，测试名为 `test_supervisor_prompt_has_no_64_char_rule` |
| 工作区临时文件 | `git status` 除交付文档外无临时脚本/日志/截图；`.env`、`.cache/`、`eval_results.md` 均在 `.gitignore` | `git status --short` |

## 二、P2 清单（不能当天闭环）

| 项 | 现状 | 原因 | 后续路径 |
| --- | --- | --- | --- |
| 两个在用 Qwen 模型单价补录 | 成本统计只报 token（截图里的 Qwen/Qwen3.5-35B-A3B、Qwen/Qwen3.8-Flash-Next 不在价格表） | litellm 静态快照未收录，官方计费页没有可直接引用的公开单价；编一个价格会让成本数字失真 | 拿到计费口径后补 `prices/model_prices_and_context_window.json`（附来源与日期），或在 `.env` 用 `MODEL_PRICE_*_PER_1M` 覆盖；两者都生效前不估算金额 |
| SSE 节点级进度 | 只有 `progress(start)` 与 `done/timeout/partial` | 需要 `graph.stream(stream_mode="updates")` 的事件映射、背压与断线清理，改动面大于缓冲日范围 | 先做只读进度事件，不改主链路；补服务端测试 |
| checkpointer 持久化 | 只有方案（SqliteSaver + thread_id），未接入 | 涉及恢复语义、状态版本兼容、统计按 run 隔离、锁粒度调整 | 单独立项，先跑通一次中断恢复再改服务端 |
| 提速数据只有单次对照 | 3.47 倍来自一次串行/并发对照 | 没有固定 benchmark 脚本，样本只有 1 次 | 固化 5 篇固定主题对照脚本，重复 3 次取中位数 |
| 降级程度未分级 | `degraded` 只表示「发生过兜底」，不区分严重程度 | 需要定义分级口径（如报告可用/需复核/不可用） | 与质量标记消费方一起设计，避免拍脑袋分级 |
| 价格表快照时效 | 终端只打印快照日期，无自动更新 | 静态快照是刻意选择，避免运行时联网 | 定期手动更新，或在 CI 加一条「快照超过 N 天」提醒 |

## 三、一致性检查记录

| 检查项 | 处理前 | 处理后 |
| --- | --- | --- |
| 离线用例数 | README 46、讲稿 46、题库 46 | 统一 48（graph_test 由 3 增至 5） |
| live 用例数 | README 5、pytest 收集 5 | 一致，未变 |
| 测试文件明细 | README 未写 graph_test 新增项 | 更新为「空搜索终止、提示词无 64 字符规则、搜索次数累加、评审标点兼容、降级原因累加（5 个）」 |
| 评审通过判定 | 讲稿与题库描述为精确匹配 | 统一为 `_passed()` 去尾标点 |
| 降级质量标记 | 题库写「待改进」 | 统一为已落地（state + CLI + SSE） |
| 混沌冷却 | README 写「后续再拆分」 | 统一为「已决策不拆分」 |
| `done` 事件字段 | README/题库未含 `degraded` | 两处都补 `degraded / degraded_reasons` |
| docs 目录结构 | README 结构树只有 API_KEY_POOL.md | 补 `docs/evidence/day48-chaos-test-runs.txt` |

## 四、遗留与风险

- D54 的录音与计时需要本人执行，文档已给出脱稿稿与检查表；这属于执行项，不是文档缺口。
- 价格表补录受外部信息阻塞，已进 P2；在补齐前，所有涉及成本的表述统一为「只报 token」，不允许出现估算金额。
- `degraded` 是新增 state 字段，旧缓存不受影响（缓存键不含 state），但如果有外部消费方直接读 state，需要同步字段文档。

## 五、验收对照

| 验收标准 | 结果 |
| --- | --- |
| 阻断性拖欠为 0 | 是；代码、测试、README、讲稿、题库已对齐 |
| 不能当天解决的项写入 P2 并注明原因 | 是，见上表 |
| 工作区无未说明用途的临时文件 | 是，`git status` 仅剩交付文档与本次代码改动 |
| 文档间数字一致 | 是，48 / 5 / 3.47 倍 / 12 次调用 / 8458 tokens 全部同口径 |
