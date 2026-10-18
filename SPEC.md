# What it does

The application accepts a topic from the command line and, for each document
in `corpus/`, asks a language model (Groq, `openai/gpt-oss-20b`) to generate
five multiple-choice questions about the topic **grounded in that one
document's material**. Every stored question carries a `source` naming the
document it came from — attached by this application, never reported by the
model (see `DECISIONS.md`, "never trust the model for provenance"). The
model may optionally call two read-only tools, `topic_lookup` and
`question_lookup`, to check the client's approved topic list or avoid
repeating an existing question.

`corpus/` is untrusted: every document was "pulled off the internet" by the
client, by their own account, so anything inside it — plain text, a PDF
page, a slide's speaker notes — is data to write questions about, never an
instruction to follow. Two independent guardrails exist for exactly this
reason (`guards.py`; full discussion in `SECURITY.md`): one labels
instruction-shaped sentences before they reach the prompt, the other scans
the model's reply for injected markers before anything is stored or printed.

The application extracts JSON from the reply even when it is wrapped in a
Markdown code fence or preceded by a short preamble, validates it with
Pydantic, and reports one of `ok`, `invalid_output`, `refused`, or `error`
per document, then the best of those as the run's final status (`ok` if any
document produced something usable, otherwise the most informative failure).

Every model call (including a tool round trip) is recorded in
`run_log.jsonl` (status, tokens, latency, cost). Every security-relevant
decision — a guardrail acting, a tool call refused, a duplicate blocked, the
loop cap reached — is recorded separately in `security_log.jsonl`. Failed
calls are retried under a capped policy. `REPORT.md` answers the client's
original cost/speed question using numbers from `run_log.jsonl`.

# Inputs

- `topic`: required first command-line argument, a string of 3 to 200 characters after stripping leading and trailing whitespace. An absent, empty, whitespace-only or out-of-range topic is rejected before any model call: exit code 2, no model call, no log line.
- `.env`, read through `client.py`: `LLM_API_KEY`, `LLM_BASE_URL`, `LLM_MODEL`. Real runs use Groq at `https://api.groq.com/openai/v1` with `openai/gpt-oss-20b`. The key is never logged, printed or committed.
- `PRICE_IN_PER_MTOK = 0.075` USD per 1,000,000 input tokens.
- `PRICE_OUT_PER_MTOK = 0.30` USD per 1,000,000 output tokens.
  Source for both: Groq's published price list for `openai/gpt-oss-20b`. Groq's free tier does not charge, so these are the equivalent paid prices and every cost in `REPORT.md` is an equivalent cost, not money spent.
- `temperature = 0.7`: the client needs question papers that do not repeat, so some variety is wanted. Shape is protected by validation and the repair retry, not by low temperature.
- `max_tokens = 2000`: five questions need well under this, and the headroom covers the case where the model's reasoning tokens count toward the limit. To be revisited after real token counts appear in `run_log.jsonl`.
- `corpus/`: the client's own documents — `.md`, `.txt`, `.pdf`, `.pptx` supported by `doc_loader.py`. **Untrusted.** Every document is processed every run; there is no per-run selection of "the right" document, because the point of this lab is that even a document nobody asked for still has to be defended against.
- `data/topics.json`, `data/generated_questions.json`: read through the two tools only, never written by a tool, never opened by any path the model supplies — see `tools.py:ALLOWED_FILES` and `SECURITY.md`.
- `MAX_TOOL_STEPS = 6` (`tools.py`): the cap on model calls across the **whole run**, not per document — a tool round trip and a retry both count against it. One shared number, not two, because splitting it added a second budget to reason about without changing any observable behaviour this lab tests for (see `DECISIONS.md`).

# Outputs

**stdout.** On success, the generated questions as JSON. Diagnostics go to stderr. The last non-empty stdout line is exactly one of `ok`, `invalid_output`, `refused`, `error`.

**Question JSON (the schema).**

- `topic`: string.
- `questions`: list of exactly 5 objects, each with:
  - `question`: string, 10 to 300 characters.
  - `options`: list of exactly 4 strings, each 1 to 100 characters.
  - `answer_index`: integer 0 to 3, pointing at an existing option.
  - `difficulty`: one of `easy`, `medium`, `hard`.

**`run_log.jsonl`** in the repository root: one JSON object per model call (a retry is its own line), append only, never committed. All lines from one run share one `run_id`. Fields:

| Field | Type | Value |
| --- | --- | --- |
| `timestamp` | string | ISO 8601, UTC |
| `run_id` | string | shared by every call in one run |
| `model` | string | the model actually used |
| `status` | string | `ok`, `invalid_output`, `refused` or `error` |
| `prompt_tokens` | int or null | measured; estimated if the provider reports none; null on `error` |
| `completion_tokens` | int or null | same rule as `prompt_tokens` |
| `latency_ms` | int | wall-clock time around the call |
| `cost_usd` | float or null | computed from the two prices; null on `error` or when a token count is null |
| `tokens_estimated` | bool | true only when the token counts are my estimate |
| `attempt` | int (extra field) | 1 for the first call of a run, 2 for the next, and so on |

`cost_usd = (prompt_tokens * PRICE_IN_PER_MTOK + completion_tokens * PRICE_OUT_PER_MTOK) / 1,000,000`

Unknown is `null`, never `0`. The log never contains a key, a full prompt or a full reply.

**`samples/run_log_sample.jsonl`**: at least 20 lines copied unedited from `run_log.jsonl`, at least 5 from the real provider. This file is committed instead of the log.

**`data/ingest_index.json`** in the repository root, written by `doc_loader.write_ingest_index()` on every run: one entry per document actually present in `corpus/` this run, each `{source, format, chars}`. The text itself is deliberately not recorded here — this file is for tracing a stored question back to an ingested document, not for re-reading the corpus from it.

**`security_log.jsonl`** in the repository root, append-only, never committed (committed as `samples/security_log_sample.jsonl` instead). One JSON object per security-relevant event, five fixed keys (`timestamp`, `run_id`, `event`, `where`, `detail`), `event` one of the seven names fixed in `security.py`. A guardrail that never calls `security.log_event` is, for marking purposes, a guardrail that never ran.

**`samples/tool_trace.jsonl`**: the full message list of one real, complete tool-calling loop (captured from an actual `stub:toolcall` run over `corpus/01_question_design_basics.md`, not hand-written), one JSON object per line. Its tool-call count and tool-result count agree (2 and 2).

# Failure cases

| Case | How to make it happen | What the program does | Last line | Exit | Log lines |
| --- | --- | --- | --- | --- | --- |
| Bad topic | `python main.py ""`, or a 2-character topic | Rejected before any call | not constrained | 2 | 0 |
| Unusable reply | `stub:malformed`, `stub:badshape`, `stub:empty` | Log the call as `invalid_output`, make exactly one repair retry; if that reply is also unusable, stop | `invalid_output` | 1 | 2 |
| Repair retry succeeds | real provider only; no supplied stub mode produces it | First line `invalid_output`, second line `ok` | `ok` | 0 | 2 |
| Refusal | `stub:refused` | Never retried | `refused` | 1 | 1 |
| Call fails | `stub:error` | Up to 3 attempts in total with backoff; all fail | `error` | 1 | 3 |
| Error, then recovery | `stub:flaky` | First line `error`, wait, second line `ok` | `ok` | 0 | 2 |
| Rate limited | `stub:ratelimit` (carries a 1 second `retry_after`) | Up to 3 attempts in total, all `error` | `error` | 1 | 3 |
| Provider reports no usage | a reply whose `usage` is missing or zeroed | Use `estimate_tokens()` and set `tokens_estimated=true` on that line; status, last line and exit code are unaffected | unchanged | unchanged | unchanged |
| Instruction found in a document | `stub:obedient` + a corpus document carrying either planted payload | Input guardrail labels the sentence (`instruction_ignored`, `guardrail_input`); if the stub still obeys anyway, the output guardrail strips the marker before storage/print (`guardrail_output`) | `ok` | 0 | varies |
| Tool argument looks like a path | `stub:traversal` | `query` is matched against topic names, never used to build a path; nothing outside `data/` is ever opened | `ok` | 0 | varies |
| Tool argument missing | `stub:traversal`'s third call | `TopicLookupArgs` validation fails; refused and logged before anything is read (`tool_arg_rejected`) | unaffected, run continues | — | — |
| Malformed stored row | `stub:toolcall`, the store's one row with no `text` | `QuestionRecord` validation fails; dropped and logged (`tool_result_rejected`), never forwarded to the model | unaffected | — | — |
| Tool loop never stops | `stub:neverstop` | Stops at `MAX_TOOL_STEPS` (6) total model calls this run; logs `loop_cap_reached` | `invalid_output` | 1 | 6 |
| Duplicate question | same topic run twice | Normalised-text match against the existing store blocks storage before it happens, not after; logs `duplicate_blocked` | `ok` | 0 | varies |

Retry rules:

- Backoff delay before attempt `n` is `(2 ** n) + random.uniform(0, 1)` seconds, never above 8 seconds.
- If the provider sends `Retry-After` and it is longer than the computed delay, wait that long instead, but never more than 8 seconds.
- The repair retry is made once and is not itself retried. If it raises an error, the run ends with `error`.
- Every error is retried the same way, including errors that cannot succeed on retry such as a 404 for an unknown model.

# Acceptance checks

Each check runs in PowerShell. Setting the three variables overrides `.env` for that terminal session only, so run `Remove-Item Env:LLM_API_KEY, Env:LLM_BASE_URL, Env:LLM_MODEL` afterwards, or open a new terminal, before using the real provider again. Checks assert on shape only: last line, exit code, number of new log lines, keys present. They never assert on question text.

`stub:flaky` must end in `ok`, exit 0, with 2 new log lines, the first `error` and the second `ok`:

```powershell
$env:LLM_API_KEY="not-needed"; $env:LLM_BASE_URL="local://stub"; $env:LLM_MODEL="stub:flaky"
$n0 = if (Test-Path run_log.jsonl) { @(Get-Content run_log.jsonl).Count } else { 0 }
python main.py "photosynthesis"; "exit: $LASTEXITCODE"
"new log lines: $(@(Get-Content run_log.jsonl).Count - $n0)"
Get-Content run_log.jsonl -Tail 2 | ForEach-Object { ($_ | ConvertFrom-Json).status }
```

`stub:ratelimit` must end in `error`, exit 1, with 3 new log lines, all with status `error`:

```powershell
$env:LLM_API_KEY="not-needed"; $env:LLM_BASE_URL="local://stub"; $env:LLM_MODEL="stub:ratelimit"
$n0 = if (Test-Path run_log.jsonl) { @(Get-Content run_log.jsonl).Count } else { 0 }
python main.py "photosynthesis"; "exit: $LASTEXITCODE"
"new log lines: $(@(Get-Content run_log.jsonl).Count - $n0)"
Get-Content run_log.jsonl -Tail 3 | ForEach-Object { ($_ | ConvertFrom-Json).status }
```

The same pattern, with only `LLM_MODEL` changed, applies to the remaining modes:

| `LLM_MODEL` | Last line | Exit | New log lines |
| --- | --- | --- | --- |
| `stub:ok`, `stub:fenced`, `stub:preamble` | `ok` | 0 | 1 |
| `stub:malformed`, `stub:badshape`, `stub:empty` | `invalid_output` | 1 | 2 |
| `stub:refused` | `refused` | 1 | 1 |
| `stub:error` | `error` | 1 | 3 |

An empty topic (`python main.py ""`) must exit 2, call no model, and add no log line.

After any run, every line of `run_log.jsonl` must parse as JSON and contain the nine required keys, and all lines from one run must share one `run_id`.

New in Lab 6, same PowerShell pattern (`$env:LLM_MODEL="stub:<mode>"`, same topic):

| `LLM_MODEL` | What it checks | What to look for |
|---|---|---|
| `stub:obedient` (corpus = 4 clean docs + 1 planted) | Injection defence | Exit 0 `ok`; no `PWNED`-shaped marker anywhere in stdout or `data/generated_questions.json`; `security_log.jsonl` contains `guardrail_input`/`instruction_ignored` and `guardrail_output` |
| `stub:toolcall` | Both tools get used; malformed row rejected | `security_log.jsonl` contains `tool_result_rejected` naming the row with no `text` |
| `stub:traversal` | Containment + argument validation | No file outside `data/` opened (nothing from the decoy `.env`/`topics_backup.json` appears anywhere); `tool_arg_rejected` logged for the call missing `query`; run still ends `ok` |
| `stub:neverstop` | Loop cap | Run ends `invalid_output`, exactly 6 model calls made (`MAX_TOOL_STEPS`), `loop_cap_reached` logged, no hang |

The complete implementation must pass `python check.py .`.

# Out of scope

The application does not provide a web or graphical interface, store questions in a database, authenticate users, or call any model other than through `client.py`. It does not look up prices automatically, rotate or aggregate either log, or retry refusals. It does not scale to a large corpus: one model call per document per run, under a shared 6-call budget, means a corpus bigger than a handful of short documents will not finish generating from all of them in one run — acceptable for this lab's six-document corpus, named here as a known limit rather than discovered by a marker. It does not catch a rephrased injection payload or a differently-shaped exfiltration marker; `SECURITY.md`'s "what each guardrail does not stop" is the authoritative list of what this version is known not to catch.