# Answer-validation routing pilot — 2026-11-04

The validation gate blocked two wrong answers and repaired the affected task automatically. Both pipelines ultimately passed all three tasks. Adaptive routing was slower and used more reported tokens in this pilot; no general savings claim follows.

Skill version: **0.5.0**. Native Codex CLI: **0.166.0-alpha.5.1**. This experiment used separate read-only App Server threads and the production `validate_answer` and `validate_repair_route` helpers. It did not change the model of an already-open desktop chat and did not exercise the packaged same-parent client end to end.

| Pipeline | First pass | Final accepted | Candidates | Model turns | Time | Reported tokens |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Fixed `gpt-6.1-sol` / `medium` | 3/3 | 3/3 | 3 | 3 | 49.730s | 35,639 |
| Skill-guided adaptive + validation | 2/3 | 3/3 | 5 | 10 | 99.738s | 136,212 |

Adaptive/fixed: **2.006× time**, **3.822× reported tokens**. These totals include all failed candidates, selector turns and repairs. Reported tokens are not money or subscription credits.

## Observed task results

| Task | Adaptive path | Result |
| --- | --- | --- |
| Extract identifiers and count valid rows | `gpt-6-luna / low` failed → `gpt-6-luna / medium` failed → `gpt-6.1-sol / medium` passed | Both wrong candidates failed `valid_rows` and were not accepted |
| Inventory race and sequential atomic claims | `gpt-6.1-sol / low` | First-pass success |
| Constrained scheduling | `gpt-6.1-sol / medium` | First-pass success; independently checked optimum 37 |

The fixed pair passed every task on its first attempt. The adaptive extraction task exercised both an actual native effort increase and a model change, with exact runtime evidence for each completed turn. This is fresh model failure and recovery, not a simulated or forced wrong response. The conditional historical-failure replay was declared before inference and skipped because fresh adaptive failure occurred; it made zero additional model calls.

The two failed adaptive candidates used **22,115 tokens**. Adaptive selection turns used **78,478 tokens**; accepted candidate executions used the remaining **35,619 tokens**. Selection overhead is material in this fresh-thread setup.

## Comparison method

The same three cases and grader from the preceding pilot were frozen byte-for-byte before any inference. Extraction is checked by independent parsing/counting. Inventory is checked by simulation and allowed locking behavior. Scheduling is checked against an exhaustive dynamic-programming oracle. Only failed check names were returned to either model; golden values and grader internals were not provided.

Both arms received the same checker, failed-check feedback and maximum of three candidate attempts. Fixed repairs would retain the exact fixed pair. Adaptive repairs must pass the production catalog/lock/no-repeat guard and increase supported native effort on the same model or select a model suited to the observed failure. Fixed did not need a retry. The overall predeclared cap was 27 model turns; 13 were used. Turn deadlines were 120 seconds and arm deadlines 300 seconds.

Arm order alternated fixed/adaptive, adaptive/fixed, fixed/adaptive. Execution threads had identical developer instructions; selector reasoning was not forwarded. The adaptive selector read the complete updated skill. Account-visible native model metadata supplied supported pairs, and provider fallback was disabled. Global instruction sources were fingerprinted and matched across all turns. Those instructions were shared by both arms, so this is a pipeline comparison, **not a pure skill-on/off ablation**.

Time includes thread creation, runtime inspection, answer checks and about 0.4 seconds per turn to drain usage events. Shared startup/catalog work and archival are excluded. Each fresh single-turn thread contributes its final cumulative token-usage total once. Cached tokens are a subset of input tokens; reasoning tokens are a subset of output tokens. Neither is added again. Fixed cached input: **26,880**; adaptive cached input: **43,520**. Cache/order/service variability limits timing generalization.

## Independent verification and limits

A separate auditor matched all **13 completed turns** to their exact owned native rollout runtime settings, token totals and public final answers, then independently regraded all **8 candidates**. No failed candidate was accepted. All 13 owned experiment threads were archived. Raw session/turn IDs, personal paths, credentials and private reasoning are omitted from this public record.

This is one run per arm over three synthetic regression cases. It demonstrates a working validation/recovery mechanism, not broad accuracy or cost superiority. The earlier ungated pilot scored adaptive 1/3 versus fixed 3/3, but differences between runs are not a controlled causal estimate. The direct evidence here is that a failed initial answer was blocked, repaired and checked again.

The repository's **161 offline checks** passed, including both Codex and Antigravity repair loops. The new live quality comparison was performed in Codex only; Antigravity's new repair loop has offline validation, not a new live-provider quality benchmark. A task-appropriate checker is required for this acceptance gate. No universal checker or missing desktop model-switch control is supplied.

## Review the recorded results

`results.json` contains sanitized native usage/settings and the eight public candidate answers. `cases.json` and `score_outputs.py` are the unchanged frozen cases and oracle. Run:

```bash
python3 regrade_recorded.py
```

This regrades recorded answers locally and makes no model calls. The archived runtime audit is summarized above; personal native rollout files are intentionally not distributed.
