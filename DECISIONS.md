# Decisions

<!--
One entry per decision, written when the decision happened, not at the end.
A decision has an alternative you rejected. "Used Python because it's popular"
is not a decision. "Fixed a bug in main.py" is a commit message.

Format:

## YYYY-MM-DD - short title

What I found.
What I changed it to.
What else I considered, and why I did not do that.
-->

## 2026-09-20 - Question format and response schema

I chose to generate exactly five multiple-choice questions for each topic. Each question contains exactly four options, an `answer_index`, and a `difficulty` value of `easy`, `medium`, or `hard`. I chose `answer_index` instead of storing the correct answer as text because the index gives a fixed relationship between the answer and the options and is straightforward to validate. I considered using short-answer questions or allowing a variable number of options, but rejected those alternatives because they would make the response structure less consistent and validation less precise.

## 2026-09-20 - JSON extraction strategy

I chose to implement an `extract_json` function that extracts the JSON object from the model response and handles both Markdown code fences and explanatory text before the JSON. I considered requiring the model to return perfectly formatted JSON and passing the response directly to `json.loads()`, but rejected that approach because a model can return valid JSON surrounded by formatting or a short preamble. Handling these cases in the application makes the parser more tolerant without changing the required response schema.

## 2026-09-20 - Refusal detection

I chose to detect explicit refusal language before attempting JSON parsing. I considered treating every unparseable prose response as `invalid_output`, but rejected that approach because the application contract distinguishes a model refusal from other unusable responses. The application therefore checks for explicit refusal phrases and reports `refused` when they are detected. The trade-off is that phrase-based detection may produce a false positive if a legitimate response contains one of the selected refusal phrases.



## 2026-10-04 - Model: gpt-oss-20b instead of llama-3.1-8b-instant

I first set LLM_MODEL=llama-3.1-8b-instant, because it is a plain instruct model and a good fit for five short questions. My first real call returned a 404 model_not_found ("does not exist or you do not have access to it"). I switched to openai/gpt-oss-20b; two real runs ("laptop" and "photosynthesis") both returned five valid questions and ok. I considered openai/gpt-oss-120b, which costs twice as much per token for a task. The cost of my choice is that gpt-oss is a reasoning model, so hidden reasoning tokens may add cost and latency. I will measure that in run_log.jsonl instead of assuming it.


## 2026-10-04 - All errors are retried the same way

I chose to retry every error up to 3 attempts in total, without trying to tell temporary failures such as a 429 from permanent ones such as the 404 I hit on llama-3.1-8b-instant. I considered not retrying permanent failures, but rejected that, because stub:error raises a generic exception that carries no signal to classify, and the lab's check expects 2 or 3 log lines for it. The cost is that a permanent error wastes about three attempts and a few seconds of backoff before it is reported.

## 2026-10-04 - Repair retry re-asks with the original prompt plus one sentence

For the one repair retry after an `invalid_output` reply, I send the original prompt with one added sentence saying the previous reply could not be used and to reply again with only the JSON object. I considered sending the unusable reply back to the model and asking it to fix that text, but rejected it because it adds input tokens to every repair, and a reply that was cut off at `max_tokens` has little worth repairing. I also considered repeating the identical prompt, but rejected it because the retry then gives the model no hint that anything went wrong. The cost is that the model does not see what was wrong with its first reply.

## 2026-10-04 - Backoff exponent is the number of the attempt about to be made

SPEC.md says the delay before attempt `n` is `(2 ** n) + random.uniform(0, 1)`. I read `n` as the attempt about to be made, so the wait before attempt 2 is 4 to 5 seconds and before attempt 3 is 8 seconds (capped). I considered using the number of the attempt that just failed, which gives 2 to 3 seconds and then 4 to 5 seconds, and rejected it because it does not match "before attempt n" in the spec. The cost is that a call that always fails takes about 13 seconds before the program gives up, which is still well inside `check.py`'s 60 second limit.

## 2026-10-04 - Latency is timed around the model call only

I wrap only `client.chat.completions.create(...)` in `Timer`, so `latency_ms` excludes JSON parsing, validation and the backoff sleep between attempts. I considered timing the whole run or each attempt including its parsing, but rejected that because the client's question about slowness is about the model, and the log line is per call. Parsing takes microseconds and a sleep is my own policy, so including either would blur what the model costs in time. The cost is that the log does not show how long a user actually waits across retries; I add the lines of one `run_id` together for that.

## 2026-10-04 - Missing, partial or zeroed usage is treated as unknown and estimated

`read_usage` uses the provider's token counts only when both are present and not both zero. If `usage` is missing, either count is `None`, or both are 0, I estimate both counts with `estimate_tokens()` and set `tokens_estimated=true`. I considered trusting zeros as measurements, but rejected it because a provider reporting zero tokens for a call that returned text is wrong, and a cost of 0.0 would then be reported as fact. I also considered estimating only the missing count, but rejected it because mixing a measured and an estimated count on one line would make `tokens_estimated` ambiguous. The cost is that an honest zero completion count is estimated instead; that is rare for this app.

## 2026-10-04 - Keep stub runs out of the log that feeds REPORT.md

I tested retries with the stubs by setting `RUN_LOG_PATH` to a temporary file, and made 25 runs against the real provider to build `run_log.jsonl` and `samples/run_log_sample.jsonl`. I considered running stub modes into the real log to reach 20 lines quickly or to show `error` retries, but rejected it because stub calls take about a millisecond and cost fake tokens, which would pull the median latency and cost per paper in `REPORT.md` away from what the real model does. The cost is that the committed sample contains no `error` line; the retry behaviour is shown by the stub checks in SPEC.md instead.
