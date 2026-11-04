# Answer validation and bounded automatic repair

Model/effort verification and answer correctness are separate checks. A host can confirm the requested settings while the answer is wrong. Version 0.5.0 adds a validation gate and bounded repair to the optional read-only parent clients; the portable skill asks other hosts to use their own appropriate checks.

## Choose checks before the answer

Use checks derived from the original task: tests, schema validation, independently recomputed counts/arithmetic, simulated transitions, or constraint validators. For factual work, verify against appropriate authoritative evidence. Subjective review and self-review should not be described as deterministic proof. No package can supply a universal correctness oracle for every task.

A useful check should identify a failed requirement without changing the task to fit the candidate. A test that only confirms that some text was returned, or that the model reports confidence, is not a correctness check.

## Trusted local checker interface

The parent clients accept an optional human-configured argument array:

```bash
python3 scripts/codex_parent_router.py \
  --validator-command-json '["python3", "/absolute/path/to/checker.py"]' \
  --validator-timeout 10 \
  --max-repair-routes 2 \
  --task 'Perform the task whose acceptance criteria the checker implements.'
```

The Antigravity client accepts the same validation options:

```bash
python3 scripts/antigravity_parent_router.py \
  --validator-command-json '["python3", "/absolute/path/to/checker.py"]' \
  --task 'Perform the task whose acceptance criteria the checker implements.'
```

Use a trusted checker appropriate to that task. The model cannot choose or modify the command. Arguments are passed without a shell. The checker runs locally with the invoking user's permissions; the model's read-only sandbox does not sandbox an external checker.

The checker reads one JSON object on stdin:

```json
{"task":"Original task text","answer":"Candidate answer text"}
```

It writes a JSON result on stdout and exits successfully when the check itself ran, whether the answer passed or failed:

```json
{"passed":false,"feedback":["The reported count is inconsistent with the listed records."]}
```

`passed` must be a boolean. Feedback is an optional string or list of strings. Keep it brief and factual; it is passed to the next selection/execution as data. A nonzero exit, timeout, malformed result, or checker exception is a **checker error**, not an answer failure. It stops automatic repair rather than spending more model effort.

Embedding applications can instead pass a Python callback `validator(task, answer)` returning the same result. Callbacks run in-process and must implement their own deadline; the command checker's timeout does not apply to them. The shared `validate_answer` helper normalizes the result to `passed`, `failed`, `error`, or `unavailable`. With no checker, answer validation is `unavailable`; the clients preserve the existing execution behavior and do not invent an accepted/verified answer.

## Repair behavior

1. Select a supported pair, execute the original task, and retain the candidate internally.
2. Check effective runtime settings with the existing host-specific mechanism. A runtime mismatch, context drift, rejected control, authentication failure, or transport error is not a reason to replay the task.
3. Validate the answer. Only a passing candidate is accepted when a checker is configured.
4. On a checked answer failure, send the original task, candidate, and precise failed-check feedback into a new routing decision. Choose higher supported native effort on the same model or another model suited to the demonstrated failure.
5. Validate the repair pair against the live catalog and independent user locks. Do not revisit a failed pair as an escalation. Recompute the answer and run the same checker again.

The default limit is two repair-routing changes and three candidate attempts. `--max-repair-routes 0` checks the first candidate without automatic escalation. An exhausted budget or a fully locked pair stops with validation failure instead of printing a known-failed candidate as a successful final answer. The selector assesses cross-model suitability; a different model ID alone does not prove that it is stronger. Same-model effort increases use that host's supported native ordering, not a universal provider enum.

Every failed attempt and check is retained in the requested transcript/record. Runtime-verified settings never imply that answer validation passed. CLI receipts retain the existing text presentation; HTML cards and animation are not reintroduced.

The clients are read-only text prototypes, so repair recomputes text. Do not adapt this loop to replay a deployment, purchase, external message, or other irreversible action. Repairing an explanation is different from executing the original action again.

## Costs and evidence

Each repair can add another selection and execution turn, as well as the local check. Include every failed attempt, selection, validation and repair in measured time and usage. Better final correctness does not by itself establish lower cost or latency. A comparison with a fixed pair should give it the same checks and feedback budget, without allowing the fixed pair to change.

A deterministic test with fake model responses exercises the control flow, not provider quality. Live tests need matching per-turn runtime evidence and unchanged independent acceptance checks. Report first-pass and final accepted accuracy separately. If a live run has no failed candidate, do not claim that it demonstrated live escalation.

The ordinary Codex or Antigravity App/IDE agent still needs a permitted native model/effort control to apply a selection. Installing this skill or a checker does not add one. When no switch is exposed, the agent can review/repair on its current runtime and accurately disclose the limitation.
