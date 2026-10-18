# Cost

Yes, each question paper has a cost, although nothing is charged on Groq's free tier, so these figures are the equivalent cost at list price. A paper needed 1.12 model calls on average (measured: 28 calls across 25 runs) and cost about $0.0004 (estimated: measured tokens times list price). 1,000 papers would therefore cost about $0.40 (estimated by multiplying; it assumes similar topics and the same failure rate). About 94% of that is output tokens: calls averaged 265 prompt tokens and 1,122 completion tokens (both measured).

Prices used: $0.075 per million input tokens and $0.30 per million output tokens, from Groq's published price list for `openai/gpt-oss-20b`. Because the free tier publishes no price of its own, I used the paid price of the same model. The extra 0.12 calls per paper are repair retries after 4 calls were cut off at the 2,000-token `max_tokens` limit (measured); the cost of those retries is included above.

# Speed

Median latency per call was 6.9 s (measured), p95 was 17.3 s (measured) and the slowest call was 17.5 s (measured). The slowest call was a first attempt that succeeded, not a retry. Of the 5 calls slower than 10 s, 2 were repair retries and 3 were first attempts, so retries are not the only cause. A tail like this is what feels slow to the client: the same call took between 1.7 s and 17.5 s.

Latency did not follow output size (correlation -0.03 between completion tokens and latency, measured), so most of the variation looks like provider-side waiting, but this log cannot prove that. A paper that needed a repair retry waits for two calls, one after the other. The logged latency covers the model call only, so backoff sleeps are not in these numbers; none happened in these real runs because no call ended in `error`.

# Method

All figures come from `run_log.jsonl` for 25 real runs on 25 different topics, 28 calls in total, against `openai/gpt-oss-20b` on 2026-10-04. Stub runs were written to a separate log and are not included. Of the 25 runs, 24 ended `ok` and 1 ended `invalid_output` after its repair retry.

Measured: status, latency (`time.perf_counter` around the model call only, not parsing or waiting) and token counts (the provider's `usage`; no line used my estimate, `tokens_estimated` is false on all 28). Computed: cost per call from the two prices, cost per paper as total cost over 25 runs, calls per paper as 28 over 25, and percentiles by nearest rank. With only 28 calls, p95 is close to the maximum. If a provider reports no usage, `estimate_tokens()` (about 4 characters per token) is used and the line is flagged; that did not happen here.
