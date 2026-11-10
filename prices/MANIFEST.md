# litellm 模型价格表快照

- 来源：https://github.com/BerriAI/litellm/blob/main/model_prices_and_context_window.json
- 单位：美元 / token（input_cost_per_token、output_cost_per_token 等字段）
- 抓取日期：2026-11-09
- 备注：静态快照，价格随上游更新而漂移，本项目据此计算的成本一律视为估算值。
  涉及服务端缓存计价的字段名：`input_cost_per_token_cached`（OpenAI 系）、
  `cache_read_input_token_cost` / `cache_creation_input_token_cost`（Anthropic 系）。
