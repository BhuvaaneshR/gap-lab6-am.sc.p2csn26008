# samples/

Three files go here. You write all three.

## valid_response.json

Carried forward from Lab 4. One model reply, in **your** schema, that your
program must accept and process normally.

## invalid_response.json

Carried forward from Lab 4. One model reply that is **valid JSON** but that
your validation must **reject**. `json.loads` has to succeed on it.

## run_log_sample.jsonl     <- new in Lab 5

Evidence. **At least 20 lines** copied from your real `run_log.jsonl`,
after you have run the program enough times to have something worth
reading.

- One JSON object per line, exactly as your program wrote them.
- The nine fields on every line. Do not tidy them up by hand.
- At least five lines must come from runs against a **real provider**,
  not the stub.
- Nothing secret: no key, no full prompt, no full reply.

`run_log.jsonl` itself is in `.gitignore` and must never be committed.
This file is the committed extract of it.
