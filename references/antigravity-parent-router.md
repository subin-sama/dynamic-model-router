# Antigravity automatic parent client

This user-launched, read-only text prototype lets one Antigravity parent choose its next model and native effort, then applies that pair between turns. Sequential native CLI processes resume the same conversation with `--conversation`; no worker conversation is created.

## Start

On macOS or Linux, with Node.js 20+, Git, Python 3.9+, and an installed, signed-in Antigravity CLI:

```bash
npx --yes github:subin-sama/dynamic-model-router antigravity
```

Enter a task at each prompt; `/quit` exits. Every task uses a route-selection turn followed by an execution turn. The parent selects from the account-visible `agy models` catalog. The controller validates the exact advertised variant/effort pair and passes native `--model` and `--effort` flags for execution. Subsequent turns retain the same conversation and its history.

The terminal shows `[Routing][status][parent]` receipts: an initial `unchanged` receipt with unknown current-task runtime values, the proposed `recommended` pair, then a `verified`, `unverified`, or `error` outcome. `verified` explicitly identifies model-variant evidence and catalog-mapped effort; it does not claim an independently observed effort budget.

From a clone or an installed skill directory, the equivalent command is:

```bash
python3 scripts/antigravity_parent_router.py
```

The client starts its own conversation in native plan mode. It is intended for text analysis and planning, rather than a full coding client. It does not attach to an existing App/IDE chat, replace the normal `agy` executable, or create a background service. Installing the global skill alone still does not add a missing self-switch tool to a running agent.

The global installer remains Node-only. This additional parent client needs Python; `DYNAMIC_MODEL_ROUTER_PYTHON` can select its executable when launching through `npx`. Windows routing is rejected with an explicit error; the prototype's pipe transport and process-group cleanup require a POSIX host.

## Options

```bash
npx --yes github:subin-sama/dynamic-model-router antigravity --help
npx --yes github:subin-sama/dynamic-model-router antigravity --cwd /path/to/project --objective speed
npx --yes github:subin-sama/dynamic-model-router antigravity --task "Summarize this design." --record result.json
```

`--tasks-json PATH` accepts an array of task strings for sequential execution. `--timeout SECONDS` bounds each CLI invocation. `--agy PATH` selects the native CLI executable. `--initial-model MODEL_VARIANT` sets only the starting variant, not a routing ladder. Without it, an unlocked first selection uses the CLI default.

`--model-lock MODEL_VARIANT` and `--effort-lock LEVEL` preserve explicit choices for selection and execution. Antigravity's advertised slugs identify effort variants, so an exact model-variant lock also restricts the compatible effort. Conflicting locks or starting settings fail before a model turn. Unknown catalog formats, unsupported pairs, rejected settings, context drift, and execution failures stop the controller without silently substituting settings or replaying a task.

`--validator-command-json` configures a trusted local answer checker; `--validator-timeout` bounds it. A checked answer failure can trigger a new native pair and recomputation, with at most two repair-routing changes/three candidates by default (`--max-repair-routes 0..2`). Every candidate is checked before acceptance. Checker errors and exhausted/locked repair choices stop the loop. No checker means validation is unavailable, not passed. See [answer validation](answer-validation.md); include all selection, failed execution, and repair turns when comparing time or usage.

## Runtime evidence

Passing flags records a **requested** pair. Successful execution or `init.model` alone does not prove effective settings. Optional `--telemetry PATH` consumes JSONL from an independently configured workspace `PreInvocation` hook. The controller does not install or modify hooks itself.

The hook should append only fields such as:

```json
{"conversationId":"CURRENT_CONVERSATION_ID","invocationNum":0,"modelName":"EXACT_RUNTIME_VARIANT"}
```

Only complete rows appended during the current invocation and matching its conversation can verify the exact runtime variant. Old rows, foreign conversations, replaced logs, and partial rows do not verify a request. A different runtime variant stops subsequent work without replaying completed execution.

Effort verification uses the catalog's mapping of the observed variant to its native effort. Antigravity's hook does not expose a separate effort or thinking-budget field; records state `catalog_variant_mapping_only` and `independent_effort_field: false`. Without usable telemetry, completed tasks remain explicitly unverified. Records retain public task text, final answers, decisions, and sanitized metadata; intermediate reasoning and raw streams are discarded.

## Validation

The live CLI 1.4.3 test selected and executed **Flash/low → Argon/high → Flash/low** in one parent conversation. Matching native hook observations verified every execution variant; six turns retained history and recalled the earlier marker correctly. The operator did not prescribe these work-unit pairs. See [validation](../VALIDATION.md#live-antigravity-external-controller-test).

Native flag and resume behavior: [headless CLI](https://antigravity.google/docs/cli/headless/), [invocation-only effort](https://antigravity.google/docs/cli/commands/effort/), and [runtime hooks](https://antigravity.google/docs/hooks).
