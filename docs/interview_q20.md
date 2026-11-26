# 面试高频 20 题 · 用本项目作答

> 用法：每题按「题目 → 本项目答案 → 可被追问的延伸点」准备；答案里的节点名、参数、文件与测试名都可以在仓库里直接指给面试官看。
> 原则：先给结论，再给实现位置，最后主动说边界。答不上来的题不许混进「已掌握」，统一放到文末回补清单。

## 索引

| 模块 | 题号 |
| --- | --- |
| RAG / 检索 | Q1–Q2 |
| Agent 架构 | Q3–Q5 |
| 状态与持久化 | Q6–Q7 |
| 并发与性能 | Q8–Q9 |
| 模型分级与成本 | Q10–Q12 |
| 可靠性 | Q13–Q15 |
| 安全 | Q16–Q17 |
| 工程化 | Q18–Q20 |

---

## 一、RAG / 检索

### Q1. 论文检索怎么做去重合并？

**本项目答案**
检索入口是 `tools/arxiv_tool.py::search_papers`：先 `_clean_query` 去掉控制字符、压缩空白，引号不成对时直接去掉，避免拼出非法 arXiv 查询；然后用 `arxiv.Search(sort_by=Relevance)` 按相关性排序，`page_size=15`、`num_retries=3`、`delay_seconds=5.0`。抓到异常只记类型名并返回已获取的部分结果，不向上抛。

合并发生在 `graph/nodes.py::worker_search`：先从已有 `papers` 建 `seen = {p.url for p in existing}`，再把新结果里 URL 不在池中的追加进去，返回 `merged` 和 `search_attempts + 1`。去重键用 `p.url`（`pdf_url or entry_id`），不用标题，因为同一标题可能有 v1/v2 不同版本。

**可追问**
- 为什么用 URL 而不是标题去重？→ 标题大小写/标点差异大，URL 是稳定唯一标识。
- 为什么不用集合整体去重？→ 要保留原顺序，搜索顺序本身是筛选失败时的兜底顺序。

### Q2. 筛选策略与同子领域优先怎么实现？摘要信息不足时怎么处理？

**本项目答案**
`worker_select` 先 `keep_count = min(clamp_keep_papers(...), len(papers))`，再把候选论文和截断后的摘要拼进 prompt，要求模型返回 `SelectionResult`（Pydantic：`index/subfield/reason`）。prompt 有三条约束：同子领域、同技术范式优先；候选不足时允许跨领域补足，但 `reason` 必须以「跨领域补充：」开头；组合跨领域时要在 reason 里说明。解析时丢弃越界 `index` 和重复 URL，数量不足 N 时按搜索顺序补齐；模型异常或 JSON 解析失败时直接保留前 N 篇。

摘要信息不足的处理有三层：筛选阶段 `_select_summary_limit` 用 `SELECT_SUMMARY_CHARS=600` 和 `SELECT_TOTAL_CHARS=24000` 两个预算取小，候选多时单篇会被压到 600 以下；单篇总结用完整摘要；总结 prompt 明确要求「摘要未提供的量化指标一律写原文未提供」。报告生成后再跑 `report_check.check_report`，报告里出现、但原始摘要语料里找不到的百分比/时间/倍数/小数会被列为告警。

**可追问**
- 为什么语料只用 `papers` 的原始摘要，不用 `paper_summaries`？→ 二次总结可能已经带了模型编造的数字，用它做语料等于自证清白。
- 600 和 24000 会不会把关键信息截掉？→ 会，这是成本与召回的直接取舍，已在已知限制里写明。

---

## 二、Agent 架构

### Q3. workflow vs agent 怎么取舍？你为什么选 workflow？

**本项目答案**
选 workflow（`StateGraph`），因为任务边界稳定：检索 → 筛选 → 单篇总结 → 综述 → 评审 → 追问，步骤可枚举。图里只有两处条件边：`supervisor` 的 `route` 和 `critic` 之后的 `after_critic`；其余都是固定边。更关键的是 `supervisor_node` 有确定性护栏：`summary` 非空时直接返回 `summarize` 或 `critic`，`papers` 非空且无综述时直接返回 `summarize`，只有初始状态才把状态判定表交给 cheap 模型。等于把「智能路由」压缩成「开局判一次 + 状态机兜底」。

代价是灵活性：遇到需要临时查新工具、改写检索词、多轮澄清的任务，这套图不会自己长出新路径。收益是可预测、可测试、可估算成本，48 个离线用例里大部分都在验证状态转移而不是模型输出。

**可追问**
- 什么场景你会换成 agent？→ 步骤无法预先枚举、需要动态选工具时；可以保留图作为外层，把某个节点换成 ReAct 子 agent。

### Q4. 条件边怎么路由？最大轮数与终止判断怎么做？

**本项目答案**
两处条件边都在 `graph/graph_compile.py`：`route(state)` 直接返回 `state["next"]`，映射到 `search / summarize / critic / end`；`after_critic(state)` 在评审通过（`_passed`：去掉首尾标点后等于「通过」）或 `revision_count >= critique_times` 时返回 `finish`（去 `followup`），否则回 `supervisor`。

终止有四道：`revision_count` 每次 `critic_node` 调用时 +1，`critique_times` 由 CLI `--max-retries` 传入并 clamp 到 1–5（默认 2）；`search_attempts >= MAX_SEARCH_ATTEMPTS`（默认 3）直接返回 `end`；主题判为乱码且没有论文时返回 `end`；外层 `graph.invoke` 带 `RECURSION_LIMIT=60`，LangGraph 自己会拦意外成环。

**可追问**
- 为什么评审完要回 `supervisor` 而不是直接回 `summarize`？→ 保持「所有分支都由 supervisor 决策」的结构一致性；实际回 `summarize` 是由护栏决定的，不额外调模型。
- 60 步够不够？→ 5 篇论文 2 轮评审实测 12 次 LLM 调用、图步数远小于 60。

### Q5. Agent 失控或死循环怎么兜底？

**本项目答案**
四层。第一层是确定性路由护栏（见 Q3），避免模型把 `summarize ↔ supervisor` 判成环。第二层是缓存防线：空响应不写缓存，`cache_get` 读到历史空值会删除并视为未命中，杜绝「空综述反复回放」。第三层是综述兜底：`stream_llm` 抛错或返回空串时用 `_fallback_report` 拼简版 Markdown，保证 `summary` 非空，流程能继续评审。第四层是计数与递归上限：`revision_count`、`MAX_SEARCH_ATTEMPTS`、`RECURSION_LIMIT`。

非关键路径也不拖垮主流程：单篇总结失败保留空结构，`critic` 失败按「通过」处理，`followup` 失败给占位提示。key 池全部 401/403 被禁用时抛 `RuntimeError`，CLI 捕获后只打印友好提示，不输出 traceback。

**可追问**
- 降级会不会掩盖问题？→ 会。所以终端会打印「路由模型不可用，已按状态回退」这类提示，报告层再做数字校验；代价是降级报告质量下降，需要人工复核。

---

## 三、状态与持久化

### Q6. 状态字段怎么设计？

**本项目答案**
`graph/state.py` 用 `TypedDict` 定义 `SupervisorState`，13 个字段：`topic`、`papers`、`summary`、`next`、`critique`、`followup`、`critique_history`、`paper_summaries`、`critique_times`、`revision_count`、`search_max_results`、`keep_papers`、`search_attempts`。

设计上分三类：输入参数（topic、两个篇数、轮数）、过程产物（papers 是 `list[PaperMeta]`，paper_summaries 是 `list[dict]`）、控制位（next、revision_count、search_attempts、critique_history）。选 `TypedDict` 是因为 LangGraph 节点只返回增量字典，框架按 key 合并；需要校验的结构（筛选结果、单篇总结）才用 Pydantic。

**可追问**
- 为什么 `paper_summaries` 是 dict 而不是 Pydantic？→ 它是节点内部产物，失败时要能保留空结构继续跑，用 dict 更宽容；真正对外校验的是 `_summarize_one` 里的 `PaperSummary.model_validate_json`。
- 状态会不会太大？→ 5 篇摘要量级很小；但全量摘要在 state 里传递，接持久化时要考虑存储体积。

### Q7. 多轮评审计数怎么防死循环？需要持久化时怎么接 checkpointer？

**本项目答案**
计数在 `critic_node`：每次调用返回 `revision_count + 1` 和追加后的 `critique_history`；`after_critic` 用 `revision_count >= critique_times` 作为硬终止。`critique_times` 由 `--max-retries`（clamp 1–5）或 API 的 `max_retries` 传入，默认 2。评审 prompt 还带「评审铁律：不得要求摘要中不存在的数据」，避免评审自己制造不可能完成的修改要求。

持久化目前没接，是已知限制。要接的话：`graph.compile(checkpointer=SqliteSaver.from_conn_string(...))`，调用时传 `config={"configurable": {"thread_id": run_id}}`；中断后 `graph.invoke(None, config)` 可从最后检查点恢复。当前 state 里的 `PaperMeta` 是 Pydantic 模型、其余是基础类型，序列化可行；主要改造点是服务端要维护 `thread_id`、`usage/cache` 统计按 run 隔离，以及锁语义从「进程内串行」改成「按 thread 串行」。

**可追问**
- 为什么现在不做？→ 先把单轮链路做稳；持久化会引入恢复语义、状态版本兼容和存储清理，属于下一阶段。

---

## 四、并发与性能

### Q8. 单篇总结怎么并发？结果顺序如何对齐输入？

**本项目答案**
`worker_summarize_one` 用 `ThreadPoolExecutor(max_workers=SUMMARY_CONCURRENCY)` + `executor.map(_summarize_one, papers)`。选线程池而不是 asyncio，是因为底层 `ChatOpenAI.invoke` 是同步客户端，`diskcache` 也是同步 IO；`executor.map` 天然按输入顺序返回结果，不需要额外排序。

每篇的异常在 `_summarize_one` 内部吞掉，返回带 `title/url` 的空结构，保证单篇失败不拖垮整批。并发结束后还有一致性自检：逐项比对 `p.url != s.get("url")`，不一致就 `logger.error` 打出 idx 和 URL，方便发现顺序错位。

**可追问**
- 线程池会不会打爆限流？→ 会。所以有全局 `RPM_LIMIT` 滑动窗口（默认 10 次/分钟）和 key 池退避；本地模型建议把并发降到 1–2。

### Q9. 并发度怎么配？提速前后怎么测？

**本项目答案**
`SUMMARY_CONCURRENCY` 在 `config.py` clamp 到 1–8，默认 3；本地 Ollama 建议 1–2，远程多 key 可以往上调，但要和 `RPM_LIMIT` 一起看。

测法是同一主题、同样 5 篇论文，串行版与并发版各跑一次，在 `worker_summarize_one` 里用 `perf_counter()` 记录「总结阶段耗时」并写日志，对比日志而不是掐秒表。实测总结阶段 102.19s → 29.43s，提速 3.47 倍；同轮总耗时 192.48s → 123.33s。指标只覆盖总结阶段，因为检索、综述、评审是串行不变的。

**可追问**
- 为什么不是 5 倍？→ 并发度是 3 不是 5，且单篇耗时不一致、RPM 窗口会节流，所以上限本来就不是线性。
- 这个数字可信吗？→ 是单次对照，不是压测；口径写在讲稿和 README 里，不夸大。

---

## 五、模型分级与成本

### Q10. 哪些节点用 cheap、哪些用 strong，为什么？

**本项目答案**
cheap：`supervisor`、`select`、`summarize_one`、`followup`；strong：`summarize`、`critic`。理由是高频率、短输出、结构化程度高的任务对模型能力不敏感，而综述和评审直接决定最终质量。远程模式通过 `MODEL_CHEAP` 指定，留空回退 `MODEL`；本地模式用 `OLLAMA_MODEL_CHEAP`。

还有一个细节：当 cheap 与 strong 不是同一个模型时，`_no_think` 会给 cheap 请求加 `extra_body={"chat_template_kwargs": {"enable_thinking": False}}`，避免轻量模型把输出预算花在思考上；缓存键也会加 `|no-think` 后缀，防止和思考模式互相命中。

**可追问**
- 如果便宜模型筛选质量差怎么办？→ 筛选有兜底（按搜索顺序前 N）和跨领域补齐；质量仍差就换模型或提高 cheap 档位。

### Q11. 缓存键怎么设计？空响应为什么不写缓存？

**本项目答案**
`cache.py::cache_key` 把 `CACHE_VERSION / provider / model / sampling(temperature, top_p) / 规范化 prompt` 打包成 JSON（`sort_keys=True`）后取 sha256。`normalize` 只统一换行、压缩空白，不改变语义。remote 的 `provider` 段是 `remote:<BASE_URL 的 sha256 前 8 位>`，换服务地址不会串缓存；thinking/no-think 用模型名后缀隔离。

空响应不写：`cache_put` 里 `if not value or not value.strip(): return`。读取侧 `cache_get` 如果拿到历史空值会 `store.delete(key)` 并按未命中处理。原因就是踩过的坑：模型偶发返回空串，旧版本把空值写进缓存，之后每次命中都拿到空综述，`supervisor` 反复要求重写，几乎死循环。对应单测 `tests/cache_test.py::test_cache_put_skips_empty` 和 `test_cache_get_treats_blank_as_miss`。

**可追问**
- 改了代码但没改 prompt 怎么办？→ 缓存键覆盖不到代码行为，需要手动提升 `CACHE_VERSION`，这是明确代价。

### Q12. 成本 / token 怎么统计？

**本项目答案**
`usage.py` 按模型累加：`record_usage(input_tokens, output_tokens, model=...)`，缓存命中只记 `cached_calls`，不记 token。流式在 `stream_llm` 里逐 chunk 累加 `usage_metadata`，结束后一次性 `record_usage`；这里按「端点返回增量 usage」的口径实现，换端点要重新对账。

成本单价优先级：`.env` 的 `MODEL_PRICE_INPUT_PER_1M/OUTPUT_PER_1M` 优先；否则查 `prices/model_prices_and_context_window.json`；都查不到时 `cost_usd=None`，只报 token。混合模型时支持部分计价：能算的模型算钱，不能算的列进 `unpriced_models`，`cost_partial=True`。终端还会标价格表快照日期。

**可追问**
- 为什么有些模型不估算？→ 宁可报「单价未知」，也不拿错价格算出一个看起来精确的假数字。
- 已知偏差？→ 流式中途失败时，已产出的 token 不计入统计，报告数字会偏低。

---

## 六、可靠性

### Q13. 重试只覆盖哪类异常？

**本项目答案**
`models/remote.py` 把 `InternalServerError`、`APIConnectionError`、`APITimeoutError` 归为 `_NETWORK_RETRYABLE`：固定冷却 `KEY_COOLDOWN`（默认 5s）后换 key。`RateLimitError` 单独处理：按 `KEY_COOLDOWN × 2^(n-1)` 指数退避，封顶 60s。`AuthenticationError / PermissionDeniedError` 不重试，直接从池里永久禁用。整体最多完整遍历 4 轮（`MAX_ROUNDS=4`），耗尽后抛最后一次异常。

流式还有额外约束：只有首 chunk 之前抛错才能安全换 key；开始产出后遇到限流或网络错误，只标记冷却并抛出，不重试，避免把重复内容拼进报告。SDK 层 `MAX_RETRIES` 默认 0，重试权掌握在自己的 key 池手里。

**可追问**
- 为什么不重试所有异常？→ 解析错误、鉴权错误重试没有意义；4xx 里只有 429 值得退避。

### Q14. 429 / 401 / 403 分别怎么处理？

**本项目答案**
429：`_mark_limited` 增加该 key 的连续限流次数，冷却时间指数增长；同时 `_log_rate_limit` 打印脱敏后的响应头和 body 前 200 字符，用于判断是账号、IP 还是 RPM 维度。冷却中的 key 不会被选中，`_next_target` 会挑最早解封的 key，必要时 sleep 等待。

401/403：`_disabled.add(target)`，本进程内永久跳过；如果全部 key 都被禁用，抛 `RuntimeError("API key 池已无可用 key")`。

5xx/网络错误：走 `_mark_server_err`，固定 5 秒冷却后换 key，不计入 429 的指数退避。

**可追问**
- 禁用会持久化吗？→ 不会，进程重启后重置；这是有意的，避免临时鉴权故障永久踢掉 key。

### Q15. 三层兜底各自降级成什么？

**本项目答案**
- 路由层：`_fallback_route`，有综述时按上次决策返回 `critic`/`summarize`，有论文返回 `summarize`，否则 `search`；与 supervisor prompt 的状态判定表一一对应。
- 筛选层：模型异常或 JSON 解析失败，按搜索顺序保留前 N 篇。
- 综述层：`_fallback_report` 用 `paper_summaries` 拼「研究背景 / 论文对比 / 研究空白」三段简版；没有摘要时输出「研究未能完成」提示。

非关键路径：单篇总结失败保留空结构；评审失败按「通过」处理（非关键路径不阻断）；追问失败返回占位提示。对应测试都在 `tests/chaos_test.py`，包括 `test_summarize_falls_back_to_structured_summaries`、`test_select_falls_back_to_search_order`、`test_supervisor_falls_back_to_deterministic_route`。

**可追问**
- 兜底报告和正常报告怎么区分？→ 现在有结构化质量标记：任一兜底触发会写入 `degraded=True` 和 `degraded_reasons`（如 `summarize_fallback`、`select_fallback`），CLI 打印提示，SSE `done` 事件返回同名字段；CLI/服务端都能据此判断。

### Q16. 混沌注入验证了什么？

**本项目答案**
`CHAOS_FAILURE_RATE`（0–1，默认 0，仅 remote 生效）在请求发出前按概率抛 `ChaosInjectedError`，它继承 `APITimeoutError`，所以会命中 `_NETWORK_RETRYABLE` 分支，自动走换 key、冷却、重试和三层兜底，业务节点零改动。统计项有 `injected / calls / attempts / retries / calls_retried`，终端在开关打开时打印。

验证的是「故障下流程仍能收敛」：重试能消化一部分注入，消化不了时兜底能出降级报告而不是崩掉；`tests/chaos_test.py` 用确定性方式覆盖了注入后重试成功、重试耗尽抛错、三层兜底和统计并发锁（`test_chaos_stats_are_thread_safe`）。运行证据归档在 `docs/evidence/day48-chaos-test-runs.txt`。

**可追问**
- 它不能验证什么？→ 不模拟 429 的真实响应头、不模拟鉴权失败，也不模拟流式中途断流；这些靠单测和手动验证补。

---

## 七、安全

### Q17. 提示词注入怎么防？还防不了什么？

**本项目答案**
入口统一 `security.sanitize_topic`：去掉不可见控制字符（`\x00-\x1f\x7f`）和首尾空白，长度上限 `MAX_TOPIC_LEN=100`，CLI 与 API 都拒绝超长。`flag_injection` 维护 13 条可疑短语（如「忽略以上指令」「system prompt」「api key」「base_url」），命中只打 warning 不硬拦截，理由是正常论文标题也可能包含这些词，硬杀会误伤。

出口层：`report_check` 对报告里的量化数字做语料回溯，防止模型编数据；`tests/security_injection_test.py` 用 3 条注入路径 + 1 条正常基线做 live 验证，其中间接注入是构造恶意摘要喂节点，断言报告不出现注入短语、`sk-` key 形态或白名单外域名。

防不了的：论文标题/摘要里的间接注入（模型可能照做）、越权工具调用、检索数据投毒、长上下文淹没指令。这些写在 `security.py` 的模块注释里，属于明确盲区。

**可追问**
- 为什么只告警不拦截？→ 误杀成本高于告警成本；真正的高危动作（泄 key、写文件）在系统里本来就不存在。

### Q18. key 为什么不落日志？

**本项目答案**
key 只在 `_get_client` 里传给 ChatOpenAI，不进入日志、不进入缓存键。429 需要看响应头时，`_redact_headers` 对 `authorization / api-key / api_key / token / secret / x-api` 这类键只保留前 6 位，body 截断到 200 字符。异常日志只记 `type(e).__name__`，`debug` 级别才记详情。`.env` 在 `.gitignore` 和 `.dockerignore` 里都排除；服务端 500 响应体固定为 `{"detail": "internal error"}`，不携带异常信息。

**可追问**
- 前 6 位安全吗？→ 对 `sk-xxxx` 这类前缀没有信息量；真正的风险是完整 key 和 base_url，这两类都被截断或白名单过滤。

---

## 八、工程化

### Q19. 流式输出怎么实现？SSE 怎么推阶段进度？

**本项目答案**
CLI 侧：`worker_summarize` 调 `stream_llm`，边收 chunk 边 `print(chunk, end="", flush=True)`，同时把完整文本落缓存；缓存命中时按 40 字符窗口回放，看起来仍是流式。流式中途失败会抛异常，由节点捕获后走 `_fallback_report`。

HTTP 侧：`server.py` 用 `StreamingResponse(media_type="text/event-stream")`。当前事件只有四个：请求进入时的 `progress`（`step=start, topic`）、正常结束的 `done`（报告前 2000 字、`truncated`、`status`、`degraded`、`degraded_reasons`、`trace_id`、`usage`、`report_warnings`）、超时的 `timeout`、内部异常的 `partial`。也就是说 SSE 目前只推「开始/终态」，没有把每个节点做成进度事件；要接的话可以用 `graph.stream(..., stream_mode="updates")` 把节点名映射成 `progress` 事件，但会引入背压和断线清理问题，属于下一阶段。

**可追问**
- 为什么报告只回 2000 字？→ 控制单条 SSE 消息体积，同时用 `truncated` 标记明确告知被截断。

### Q20. 全局异常与超时怎么降级？离线/live 测试怎么隔离？Docker 验证了什么？Langfuse 接在哪一层？

**本项目答案**
异常与超时：`server.py` 有全局 `@app.exception_handler(Exception)`，统一返回 500 和 `{"detail": "internal error"}`；研究任务跑在单线程 `ThreadPoolExecutor` 里，用 `asyncio.wait_for(..., timeout=SERVER_TIMEOUT)` 包住，默认 540 秒，超时发 `timeout` 事件。因为线程无法强杀，锁会等任务真正结束后再释放，期间新请求排队，这一点在 README 的已知限制里写明。

测试隔离：`pytest.ini` 配置 `testpaths=tests` 和默认 `-m "not live"`；`tests/conftest.py` 在导入 graph 前注入测试用默认配置，所以没有 `.env` 也能跑离线用例；真实链路用例统一打 `live` 标记（`security_injection_test.py` 5 个）。`scripts/` 放手动脚本，不进 pytest 收集，内部把项目根目录加入 `sys.path`。

Docker：`Dockerfile` 基于 `python:3.13-slim`，先装依赖再拷源码以利用层缓存；`useradd --uid 10001` 非 root 运行；`HEALTHCHECK` 用标准库轮询 `/health`；`docker-compose.yml` 挂载 `./.cache:/app/.cache` 复用缓存、`env_file` 读 `.env`；必须单 worker，因为 `asyncio.Lock` 和统计都是进程内状态。

Langfuse：只接在 `observability.py`，业务节点零埋点。`trace_config(topic)` 生成 `callbacks: [CallbackHandler]` 和 `langfuse_*` metadata，在 `graph.invoke(..., config=...)` 时注入；层级是 Trace（一次研究）→ Span（每个节点）→ Generation（每次真实 LLM 调用），缓存命中不产生 Generation。双 key 缺任一就返回空 dict，初始化失败也只告警。

**可追问**
- 为什么单 worker？→ 锁、usage、cache 统计都是进程内全局态，多 worker 会互相覆盖；要横向扩展得先把状态外置。

---

## 回补清单

> 已还清（D55）：Q4/Q7 的评审标点兼容已修并补回归用例；Q15 的降级质量标记已落地为 `degraded / degraded_reasons`。以下仅列仍未闭环的项。

| 题号 | 现状 | 原因 | 后续路径 |
| --- | --- | --- | --- |
| Q7 | checkpointer 只有方案，未实际接入 | 当前优先把单轮链路做稳，持久化涉及恢复语义与状态版本兼容 | 用 `SqliteSaver` + `thread_id` 跑一次中断恢复，补一个离线用例 |
| Q12 | 两个在用 Qwen 模型无单价，成本只报 token | 价格表是 litellm 静态快照，未收录这两个模型，官方计费页也未给出可直接引用的单价 | 确认计费口径后补录价格表（附来源与日期），或在 `.env` 用 `MODEL_PRICE_*_PER_1M` 覆盖 |
| Q19 | SSE 只有 start 与终态事件，无节点级进度 | `graph.stream` 的事件映射、背压与断线清理未实现 | 先做只读进度事件（不改变主链路），用 `stream_mode="updates"` 映射节点名 |
| Q9 | 提速数据是单次对照，不是压测 | 没有固定 benchmark 脚本 | 固化 5 篇固定主题的对照脚本，重复 3 次取中位数 |
