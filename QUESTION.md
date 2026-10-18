# Question

My average is **1.12 model calls per question paper** (28 calls over 25 real runs, from `run_log.jsonl`).

The 0.12 above 1.0 is three papers whose first reply was unusable and needed the repair retry. Two were fixed by the retry and one ended `invalid_output`. All four unusable calls had `completion_tokens` equal to 2000, my `max_tokens`, so the JSON was cut off. The log does not show the reasoning, so I infer it: the model's hidden reasoning plus the answer sometimes exceeds the budget.

So the prompt's wording is not the problem. The gap shows my prompt plus `max_tokens = 2000` leaves too little room for a reasoning model. I would raise `max_tokens` before touching the wording.
