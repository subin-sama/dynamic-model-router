# Validation

Last checked: 2026-11-04. The repository includes a portable skill, a one-command global installer, a Codex catalog inspector, and an optional read-only parent App Server client. Installation writes persistent user-wide routing instructions for supported local agents. It does not run a background service or install a hook into the current desktop composer.

## Offline tests

**79 tests passed** on the development host using Python 3.9.6:

| Component | Tests | Coverage |
| --- | ---: | --- |
| Catalog inspector | 11 | Visibility, sparse native effort support, duplicate/malformed metadata, freshness, field filtering, CLI errors |
| RPC transport | 13 | Event-before-response ordering, concurrent IDs, bounded deadlines/cleanup, safe request rejection, EOF, bounded stderr |
| Parent client | 23 | Model/effort locks, catalog eligibility, same-thread selection/application/execution, failed turns, missing telemetry, exact turn matching, startup effort, stream cleanup |
| Antigravity parent client | 27 | Exact native variants, locks on selection and execution, same-conversation sequencing, context drift, fresh telemetry, missing/mismatched runtime evidence, bounded transport, repeated-interrupt process cleanup |
| Routing receipts | 5 | Compact output, unknown values, truthful Codex and Antigravity verified/unverified/error outcomes, scope and evidence qualifiers |

```bash
python3 -m unittest discover -s tests -v
```

The offline tests do not call Codex or a provider. Skill-creator structural validation also passed for the skill entrypoint.

## Installation checks

### One-command installer

The Node installer and launcher have **53 passing tests**: 37 preservation/ownership/CLI/integration cases, 13 host-adapter cases, and 3 launcher cases. Together with the 79 Python tests, the repository has **132 offline checks**. Tests cover original bytes and file modes, Unicode/BOM/CRLF, missing final newlines, backups, idempotency, effective override files, custom profile roots, Gemini comments and context filenames, shared payloads, legacy manual copies, Antigravity detection and shadow-copy conflicts, symlink changes, concurrent edits, rollback, safe updates, uninstall retaining newer user edits, literal launcher arguments, and child exit propagation.

The npm tarball was installed through `npx --package=file:... dynamic-model-router --home <staging> --agents all`. All six global instruction targets were configured with their original byte prefixes retained and one managed block each. An Antigravity-only installation was also checked independently of the other adapters. Second runs made zero changes. Packaged uninstall retained the originals and user instructions added after installation. These are real installation/filesystem tests, not provider or model calls.

The distribution is English-only, including documentation, installer output, and test fixtures. The installer intentionally preserves non-English user instructions. No credentials, personal profile files, or raw runtime session identifiers are included in the npm payload.

Installation support is verified for the six documented adapters. Antigravity uses the officially documented common App/CLI/IDE paths, but global policy loading in each running surface has not been live-tested. The separate CLI runtime test below used workspace activation. Setup detects competing same-name CLI/legacy skills before writing and preserves unresolved manual copies. It configures user-wide context; it cannot force model compliance, override managed restrictions, or install a global hook into arbitrary closed AI products. Native model/effort behavior remains separately bounded below.

### Standard alternatives

The standard `skills` CLI discovers the repository-root `SKILL.md` without a custom package. A real project-scoped installation using `npx skills add subin-sama/dynamic-model-router --agent codex --yes` succeeded in an isolated workspace, including a check with skills 1.7.4 and Node.js 24.6.0. The installed skill, license, and controller scripts matched the repository, its controller help command worked, and all 47 offline tests passed from that installed copy. Discovery and listing were also verified through the CLI.

Codex's bundled `skill-installer` helper was tested independently with repository path `.` and explicit name `dynamic-model-router`, using a separate destination. It installed successfully. Neither installation test modified the user's global skill copy or `AGENTS.md`.

The documented `-g` option is the standard CLI's global scope switch; the live installation tests used project/custom destinations to avoid duplicate user-wide installations. Standard installation does not itself add always-on instructions to `AGENTS.md`.

## Live native-worker test

Two real runs used the desktop-bundled Codex CLI `0.166.0-alpha.5.1`. Work-unit model/effort pairs were not prescribed by the harness; the parent chose them after reading the unchanged skill.

| Parent baseline | Work | Selected worker pair | Result |
| --- | --- | --- | --- |
| Sol / low | Concurrency investigation | Sol / high | Matching native dispatch, applied settings, and new worker turn context; completed |
| Luna / low | ID sorting | Luna / low | Matching evidence; completed |
| Luna / low | Concurrency investigation | Astra / high | Matching evidence; completed |

Both parent runs completed with exit code 0. Parent and worker scopes were checked separately. Copied parent contexts in a fork were excluded before matching the worker's own execution turn. This proves worker routing for the tested run, not parent self-switching through a skill alone.

## Live same-parent client test

The added App Server client ran **one parent thread** through three selection turns and three execution turns, without workers:

| Work | Parent-selected pair | Execution runtime | Result |
| --- | --- | --- | --- |
| Sort IDs and remember a token | Luna / low | Luna / low | Completed |
| Investigate leases, stale workers, idempotency, and crash recovery | Sol / high | Sol / high | Completed |
| Recall the token and add integers | Luna / low | Luna / low | Completed; token and arithmetic correct |

All six turns completed. Native applied-setting events and each execution `turn_context` matched the parent's selection. History stayed on the same thread; the final request did not repeat the remembered token. The harness set only the initial parent baseline, not the work-unit selections.

A final-build smoke test also selected Luna / low, executed with that pair, and returned its expected marker. After the main live run, narrow hardening covered incomplete metadata, models without explicit reasoning controls, omitted startup defaults, and stream-buffer cleanup. The complete offline suite passed afterward.

Raw session/turn identifiers, timestamps, rollout filenames, and personal paths are kept out of the public repository. The table reports observations rather than fabricated demonstration telemetry.

## Live Antigravity parent test

Antigravity CLI **1.4.3** ran the unchanged skill in an isolated workspace, with an applicable `AGENTS.md` and a real account-visible model catalog. One `stream-json` process received three sequential tasks. The operator supplied no `--model` or `--effort` override and did not change settings between tasks. Workers, nested runs, and persistent configuration rewrites were excluded from this same-parent test.

| Task | Parent-selected recommendation | Host-reported runtime variant |
| --- | --- | --- |
| Sort integers and remember a marker | `gemini-3.8-flash-low` / `low` | `gemini-4-argon-medium` |
| Analyze concurrent claims, stale leases, and side-effect crash recovery | `claude-opus-5-5-high` / `high` | `gemini-4-argon-medium` |
| Recall the marker and add integers | `gemini-3.8-flash-low` / `low` | `gemini-4-argon-medium` |

All selected pairs appeared in the captured catalog. Each final response explicitly reported `advisory` and `recommended`, with no claim that a switch was applied. All three turns returned `SUCCESS`; the process exited 0. One initialization, matching conversation IDs, cumulative turn counts 1 → 2 → 3, and correct marker recall plus the sum establish continuity of the tested parent conversation. Completion status is not a quality benchmark for the debugging answer.

A workspace-only `PreInvocation` hook recorded five invocations, all reporting `gemini-4-argon-medium` in the same conversation. The hook retained only phase, conversation ID, invocation number, and model name. Sanitized event evidence retained the exposed tool names and final responses without private reasoning text. No native same-parent model/effort switch tool appeared in the initialization inventory.

Native `/effort` inspection before and after the test reported `medium`, with `low`, `medium`, and `high` available. The catalog labels the observed runtime variant Medium. The hook does not expose an independent effort or thinking-budget field; standalone effort inspection alone does not establish the setting for each earlier invocation.

**Observed result: automatic model/effort selection worked as recommendations; automatic parent switching did not occur in this skill-only CLI test.** This does not establish the behavior of Antigravity App, IDE, future versions, or a separate external controller. The later controller test is described separately below.

Sources: [headless session protocol and native flags](https://antigravity.google/docs/cli/headless/), [runtime hook contract](https://antigravity.google/docs/hooks), [native effort behavior](https://antigravity.google/docs/cli/commands/effort/).

## Live Antigravity external controller test

The added [parent client](references/antigravity-parent-router.md) ran three tasks through one logical Antigravity CLI 1.4.3 parent conversation. Each task used a route-selection turn followed by an execution turn. Sequential native CLI processes resumed the same conversation with explicit supported model/effort flags. No workers, fixed routing ladder, or persistent model defaults were used.

| Work | Parent-selected pair | Execution `PreInvocation.modelName` | Result |
| --- | --- | --- | --- |
| Sort integers and remember a marker | `gemini-3.8-flash-low` / `low` | `gemini-3.8-flash-low` | Matched |
| Analyze leases, stale workers, and crash recovery | `gemini-4-argon-high` / `high` | `gemini-4-argon-high` | Matched |
| Recall the earlier marker and add integers | `gemini-3.8-flash-low` / `low` | `gemini-3.8-flash-low` | Matched |

The parent chose these work-unit pairs from its live account-visible catalog. The controller started the first selection without model/effort overrides, then applied each validated choice using native flags. All six turns returned successful results with cumulative counts 1 through 6 and the same conversation ID. The last execution recalled the earlier marker, which was not repeated in that task, and returned the correct sum.

Six independent workspace-hook observations covered selection and execution. Each execution observation matched its parent's selected exact model variant. The native catalog associates those variants with low/high/low effort; no independent effort-budget field is exposed by this hook. Records explicitly distinguish verified variants from that catalog-mapped effort evidence. Native default effort inspection after the run still reported `medium`, matching the earlier baseline.

A separate two-turn feasibility probe changed from Flash/low to Opus/high through the same native conversation ID and retained a remembered marker. That probe establishes cross-model history continuity; its operator-prescribed settings are not counted as automatic selection evidence.

The full run used the Node `antigravity` launcher. A later narrow cleanup change fixed a reproduced duplicate-SIGINT orphan-process case and passed the offline descendant-heartbeat test. The final implementation's offline suite passed afterward. A real npm-tarball `npx` smoke test then independently selected Flash/low, executed with a matching native variant, retained one conversation over two turns, and returned its expected marker and arithmetic result. Packaged launcher help and the six-host install/reinstall/uninstall preservation checks also passed.

**Observed result: the external controller enabled parent-selected, automatically applied model/effort variants between turns with retained history.** The controller is a separate user-launched macOS/Linux read-only text prototype. This result does not mean installing the skill patches an existing App/IDE chat or changes an in-flight request.

## Visible routing receipts

The 0.3.1 skill requires a task-start receipt and updates for meaningful setting, scope, evidence, fallback, or outcome changes. The managed installation block carries the same requirement, including when it reuses an older manual skill. A real-filesystem migration test upgraded an older owned block while preserving the user's original instructions, later additions, exact backup bytes, repeat-install idempotence, and uninstall boundaries.

Five additional Python checks exercise public receipt formatting and truthful CLI outcomes. They cover unknown values, single-line formatting, unsupported status rejection, verified/unverified/error output, and Antigravity's model-variant-only effort qualifier. The CLI adapters retain their previous structured record schemas and do not claim runtime verification from dispatch or completed answers alone.

Global receipt instructions were applied to the development user's Codex and Claude Code profiles with prior instruction bytes retained as exact prefixes and two backups created. The manual Codex skill's communication section was updated with its preceding content preserved; it remains unowned by the installer. A repeat setup made zero changes.

A real read-only text task through the desktop-bundled Codex CLI 0.166.0-alpha.5.1 loaded those global instructions without a skill invocation or a request to display a receipt. It emitted an initial `[Routing][unchanged][parent]` receipt with unknown model/effort values and then answered the sorting task correctly. This verifies that one normal Codex engine conversation produced the requested chat text; no desktop renderer automation was performed. The separate older PATH CLI was incompatible with the current configuration and is not counted as a successful check. Claude Code's CLI was not signed in, so its configuration was installed and checked but no live Claude response is claimed.

Normal-chat receipts are generated assistant messages. This instruction and installer validation does not establish a native desktop event hook or guarantee that every model will obey the receipt instruction in every chat.

### Compact chat presentation (0.3.2)

Chat instructions now request a compact two- or three-line Markdown blockquote with localized status, scope, labels, and reason; model IDs and native effort values remain exact. Unknown values can be combined into a localized "Model/effort: not exposed" label. Terminal receipts and structured record schemas are unchanged. An independent review found no scope or evidence regressions, and all 132 offline checks plus skill structural validation passed.

The updated managed blocks were applied to the development user's Codex and Claude Code profiles. Bytes outside each block were verified unchanged, each file retained exactly one block, and a repeat install made zero changes. The manual Codex skill's preceding content was preserved while updating its communication section.

A new ordinary read-only Codex CLI task answered a minutes-to-hours question correctly but omitted the task-start receipt. This is a recorded instruction-compliance failure, not evidence that automatic display works on every task. A separate new task with explicit `$dynamic-model-router` invocation, without asking for a presentation format or overriding model/effort, emitted the compact blockquote with an Unchanged/Parent status and unexposed settings before the correct answer. These tasks used different-language prompts and are observations, not a controlled comparison proving that invocation alone determines compliance. No desktop renderer automation or live Claude response is claimed for this update.

### Colored status indicators (0.3.3)

The chat policy and installer summary now pair each textual status with a colored emoji: blue for recommended, yellow for requested, purple for applied, green for verified, white for unchanged, orange for unverified, and red for error. Color supplements the localized label; green retains the same runtime-evidence requirement and partial-evidence qualifiers. Terminal receipts and structured records are unchanged. The instructions explicitly avoid claiming CSS control or live animation over the host chat, and prohibit artificial status changes or repeated messages to imitate progress.

All 132 offline checks and skill structural validation passed. An independent review found no evidence-status regressions. This presentation-only update did not repeat provider runs; the normal-chat compliance limitation recorded for 0.3.2 still applies. Host emoji rendering may vary, so no identical appearance across apps is claimed.

### Text presentation restored (0.4.1)

At the user's request, the 0.4.0 native HTML receipt feature was reverted to the compact colored Markdown presentation. The skill and managed instruction block explicitly supersede earlier native-card preferences. The renderer, template, and native receipt recipe are no longer distributed. Model/effort selection, terminal receipts, and runtime-evidence rules are unchanged.

An isolated update from the actual 0.4.0 npm tarball to 0.4.1 passed for all six adapters: unchanged obsolete owned renderer files were removed, original instruction bytes and user additions were preserved, and a repeat installation made zero changes. The Node suite passed 53 tests, skill structural validation passed, and the 79 Python tests passed on retry. The initial Python run encountered the previously observed macOS `os.killpg` permission error in unchanged parent-client process-cleanup tests; no parent-client code was changed or test skipped for this presentation rollback.

The user's supplied screenshot establishes that the native Antigravity card had rendered, but its presentation was rejected. Existing conversation messages and artifacts are not changed by this rollback. No new provider run is needed to validate removal of the native presentation workflow.

## Independent behavioral simulation

A separate agent reviewed twelve scenarios covering ordinary work, difficult debugging, user locks, unsupported settings, unavailable switching controls, existing Gemini Auto, image eligibility, missing credentials, bounded escalation, and unsafe attempts to repeat external actions or evade host restrictions. These were reasoning simulations, not runtime tests.

## Limits

- The parent prototype is a separate read-only text client. It does not make an existing Codex desktop chat switch automatically after skill installation, and is not a full coding client.
- Settings apply between turns, not to a request already in flight.
- Runtime verification establishes Codex's resolved settings, not independent provider-side backend attestation.
- No quality, latency, or cost improvement has been measured. Parent routing adds a selection turn per task; worker overhead is not always worthwhile.
- Claude Code and Gemini CLI guidance was checked against official documentation only. Account/version/organization capabilities must be discovered on the recipient's host.
- macOS was live-tested. POSIX process-group cleanup has an offline test; Windows cleanup covers the direct server only and has no live Windows validation.
