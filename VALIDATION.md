# Validation

Last checked: 2026-11-17. The repository includes a portable skill, a one-command global installer, catalog/capability discovery, a specialized-tool chooser, optional same-parent clients, and a separate cross-provider text-work controller. Installation writes persistent user-wide routing instructions and, for Claude Code, a native prompt-submission hook. It does not run a background service, patch desktop renderers, or change an in-flight request.

## Offline tests

**226 Python tests passed** on the development host:

| Component | Tests | Coverage |
| --- | ---: | --- |
| Catalog inspector | 11 | Visibility, sparse native effort support, duplicate/malformed metadata, freshness, field filtering, CLI errors |
| RPC transport | 13 | Event-before-response ordering, concurrent IDs, bounded deadlines/cleanup, safe request rejection, EOF, bounded stderr |
| Parent client | 34 | Model/effort locks, catalog eligibility, same-thread selection/application/execution, failed turns, missing telemetry, exact turn matching, startup effort, stream cleanup, validation and bounded repair |
| Antigravity parent client | 37 | Exact native variants, locks on selection and execution, same-conversation sequencing, context drift, fresh telemetry, missing/mismatched runtime evidence, bounded transport, process cleanup, validation and bounded repair |
| Routing receipts | 5 | Compact output, unknown values, truthful Codex and Antigravity verified/unverified/error outcomes, scope and evidence qualifiers |
| Answer validator | 8 | Strict checker results, unavailable/error states, literal command arguments, deadlines, bounded I/O, process cleanup and repair-budget validation |
| Cross-provider controller | 43 | Per-machine onboarding, provider changes, task preferences, exact locks, missing auth, stale plans, native Gemini values, timeout cleanup, private diagnostics, separate answer/runtime outcomes |
| CLI provider adapters | 41 | Destination CLI catalogs, optional provider capability metadata, auth filtering, native arguments, Gemini settings, actual result shapes, error classification, aliases and partial runtime evidence |
| Capability selection engine | 22 | Output/input distinctions, multiple/single/no candidates, exact locks, hidden/unavailable interfaces, route-scoped authentication, duplicate observations and discovery-only native flags |
| Capability CLI integration | 12 | Specialized task classification, pending/explicit choices, schema snapshots, wrong-machine rejection, unchanged text selection and artifact rejection before dispatch |

```bash
python3 -m unittest discover -s tests -v
```

The offline tests do not call Codex or a provider. Skill-creator structural validation also passed for the skill entrypoint.

## Installation checks

### One-command installer

The Node suite has **95 passing tests**: 37 original preservation/ownership/CLI/integration cases, 13 host-adapter cases, 3 launcher cases, 21 native Claude hook installation cases, and 21 hook-runtime cases. Together with the 226 Python tests, the repository has **321 offline checks**. Tests cover original bytes and modes, Unicode/BOM/CRLF, missing final newlines, backups, idempotency, custom configuration roots, hook ownership/privacy, metadata failure and caching, literal arguments, bounded child-tree cleanup, concurrent edits, rollback, and safe uninstall retaining newer user changes.

The npm tarball was installed through `npx --package=file:... dynamic-model-router --home <staging> --agents all`. All six global instruction targets were configured with their original byte prefixes retained and one managed block each. An Antigravity-only installation was also checked independently of the other adapters. Second runs made zero changes. Packaged uninstall retained the originals and user instructions added after installation. These are real installation/filesystem tests, not provider or model calls.

Documentation and installer output are in English. The cross-provider controller includes English and Thai onboarding templates, and the hosting agent localizes its question to the user. The installer intentionally preserves non-English user instructions. No credentials, personal profile files, or raw runtime session identifiers are included in the npm payload.

For 0.6.0, `npm pack --dry-run` confirmed both new Python scripts and their reference documentation are included. An actual install into an isolated temporary `--home` configured all six host adapters across two skill locations. The new scripts, shared RPC dependency, and cross-provider reference matched the repository byte-for-byte. Real user profiles were not modified by this check.

Installation support is verified for the six documented adapters. Antigravity uses the officially documented common App/CLI/IDE paths, but global policy loading in each running surface has not been live-tested. The separate CLI runtime test below used workspace activation. Setup detects competing same-name CLI/legacy skills before writing and preserves unresolved manual copies. It configures user-wide context; it cannot force model compliance, override managed restrictions, or install a global hook into arbitrary closed AI products. Native model/effort behavior remains separately bounded below.

### Standard alternatives

The standard `skills` CLI discovers the repository-root `SKILL.md` without a custom package. A real project-scoped installation using `npx skills add subin-sama/dynamic-model-router --agent codex --yes` succeeded in an isolated workspace, including a check with skills 1.7.4 and Node.js 24.6.0. The installed skill, license, and controller scripts matched the repository, its controller help command worked, and all 47 offline tests passed from that installed copy. Discovery and listing were also verified through the CLI.

Codex's bundled `skill-installer` helper was tested independently with repository path `.` and explicit name `dynamic-model-router`, using a separate destination. It installed successfully. Neither installation test modified the user's global skill copy or `AGENTS.md`.

The documented `-g` option is the standard CLI's global scope switch; the live installation tests used project/custom destinations to avoid duplicate user-wide installations. Standard installation does not itself add always-on instructions to `AGENTS.md`.

## Cross-provider invocation checks (2026-11-05)

The new controller was exercised on macOS using a small sorting/arithmetic task with a nonce, and its answer was checked independently. These are invocation checks, not comparative quality or cost benchmarks.

| Provider | Requested model / effort | Invocation and answer check | Runtime-setting evidence |
| --- | --- | --- | --- |
| Antigravity | `gemini-4-argon-low` / `low` | Completed; answer passed | JSON did not report effective model or effort; unverified |
| Codex CLI | `gpt-5.6-luna` / `low` | Completed; answer passed | JSON did not report effective model or effort; unverified |
| Claude Code | `fable` / `low` | Attempt stopped at missing login; user chose to record this prerequisite | No completed inference or verified pair |
| Gemini CLI | `gemini-3-pro-preview` / `LOW` | Attempt stopped at missing authentication, exit 41 | No completed inference or verified thinking setting |

Live testing exposed a difference between the desktop Codex cache and the standalone CLI's catalog. The adapter now queries the destination CLI's `model/list` first; after correcting the model selection, its real invocation passed. Antigravity's actual `SUCCESS`/`response` JSON shape is covered by regression tests. Its plan mode is preserved by not combining it with the slash-expansion disabling flag. Gemini's structured startup errors on stderr are classified as prerequisites, not reasoning failures.

The first installed-skill subset had 127 passing Python tests; the complete 0.6.0 repository suite had 188. An independent forward review of a new user's machine passed: detect that machine's CLIs first, distinguish an installed app from a usable CLI, ask about additional providers, and do not infer setup permission from an optional unanswered question.

CLI presence, dispatch controls, account access, effective settings, and answer acceptance remain separate statuses. The controller does not change the current parent model, silently weaken native restrictions, install another provider, or retry external actions. Gemini native configuration is tested offline; successful live Gemini and Claude inference still require authentication. Linux and Windows live provider execution was not tested in this pass.

## Capability discovery and user choice (0.7.0)

The policy now identifies required output/tool capabilities before ranking providers. A current tool snapshot drives `capabilities` and specialized `plan --requires` decisions. Multiple distinct eligible interfaces require a user choice unless already selected; zero eligible interfaces yields `blocked` with reasons. Exact backend model IDs stay unknown when unexposed. Native provider metadata is discovery-only until a callable output interface exists. The text runner rejects artifact/tool plans before any provider discovery or process invocation.

On 2026-11-17, read-only discovery found the installed Claude, Antigravity and Codex CLIs on the development machine; Gemini CLI was absent. Codex's native `modelProvider/capabilities/read` reported image generation, web search and namespace tools, without a thread or inference. This advertises provider capability, not a per-model image backend, account entitlement or successful image generation. Unsupported/malformed optional metadata preserves a valid model catalog and returns unknown capability flags.

The current Codex host exposed two distinct image interfaces in tool metadata: native `image_gen__imagegen` and Canva's `generate_image`. A snapshot of those real visible schemas produced `choice_required` with no selected candidate and no dispatch authorization. Both backend model IDs stayed unknown. Removing the snapshot produced `blocked`, with the Codex provider flag kept separately as non-dispatchable discovery evidence. A synthetic explicit candidate selection resolved to `ready`, and the text runner rejected that plan. No real user choice was recorded, no preference was changed, and no image generation or provider inference was performed for these checks. Tools visible in this host are not thereby available to a separate Claude or Antigravity process.

Independent forward-testing also exercised a Claude-hosted image request with two mock image tools, provider metadata only, an explicit selected tool, and vision/input-only models. All four outcomes matched the declared interface/choice boundaries. Six execution guard probes and two top-level `run --execute` probes stopped before provider/process entrypoints. A discovered duplicate-observation case was fixed and independently rechecked: the same provider/tool/model with differing capability declarations no longer appears as two choices. Distinct explicit models can remain separate routes.

These checks establish discovery, filtering and choice behavior, not generated-image quality or account access. The hosting agent still classifies the user's semantic requirements and must resolve the selected tool in the executing host. A missing cross-app bridge is not created by a manifest or skill installation. See [capability routing](references/capability-routing.md) for the snapshot schema and host handoff contract.

The 0.7.0 npm tarball passed isolated fresh installation and upgrade from committed 0.6.0 across all six adapters, with exact outside-block bytes/backups, bundled-module imports, chooser help, zero-change reinstall and exact original-file restoration on uninstall. Development Codex, Claude Code and Antigravity activation was also updated with original instruction bytes preserved outside one managed block per file. Prior manually updated product files were backed up before reconciling installer ownership hashes; the manual Codex copy remained unowned and its unrelated local documentation was preserved. A repeat global setup made zero changes.

## Native Claude Code activation (0.8.0)

A real natural-image request under 0.7.0 found the installed skill available but did not invoke its body or machine-discovery helper. It made four current-host `ToolSearch` calls, established no qualified executable image routes, and ended with setup/prompt-writing choices instead of an image-generator menu. No generator was attempted. The final text preceded an `error_max_budget_usd` result; the process exited 1. This failed/partial probe is preserved rather than relabeled as a pass.

Version 0.8.0 adds a native `UserPromptSubmit` hook that executes the fixed read-only discovery helper before Claude responds and injects a canonical short policy from the installed skill plus a sanitized machine snapshot. It labels cached/unavailable metadata and provider-only image support. It does not inject fabricated callable tools, authorize generation, alter the parent model/effort or send the user prompt to other providers.

The hook and installer passed 42 new offline cases, including private cache/audit behavior, configuration-root invalidation, UTF-8 metadata under an ASCII parent environment, interpreter failures, simultaneous refreshes, and timeouts with descendants that start a separate process group. An independent unchanged heartbeat fixture reproduced the initial descendant-cleanup leak and confirmed its correction. Installation preserves existing Claude settings, model/permissions/environment values and other hooks; ownership state contains no original settings values. Fresh installation and upgrade from 0.7.0 through a real npm tarball passed all-six-adapter preservation, repeat-zero and exact-uninstall checks.

Global activation on the development machine preserved all three instruction files byte-for-byte and every pre-existing Claude setting semantically, adding exactly one managed native hook. The manual Codex skill remained unowned. The first live 0.8.0 attempt proved native activation: the `UserPromptSubmit` response contained the canonical policy verbatim, matching installed skill/runtime hashes and a fresh snapshot hash. It correctly detected Claude, agy and Codex, with Gemini absent; Codex image support stayed provider-metadata-only. A separate auditor confirmed the hook output preceded the response. The account then returned a session-limit error with zero inference tokens, so this attempt establishes activation only, not image-choice behavior. Existing user plugin hooks also supplied startup context; the test did not disable those customizations.

After the reported quota reset, two bounded real Claude Code 2.1.211 runs repeated the same ordinary image request without naming the skill, asking for a menu, supplying fabricated tool manifests, or overriding model/effort. Both completed with exit 0 and `is_error: false`; native initialization reported inherited `claude-opus-4-8[1m]`, with effective effort unexposed. The first read the installed skill body and correctly described Codex's advertised-only image capability, but still offered unsupported connector/authentication setup claims. That partial result was retained and motivated tighter fresh-evidence and handoff instructions.

The final run received the revised canonical policy through the actual native hook, used two host-tool searches, identified Codex's advertised image support and missing artifact bridge, and asked before handoff. It omitted the prior Canva authentication/setup and prompt-writing suggestions. The final run took 44.209 seconds wall time; both post-reset runs together reported 2.119445 in the CLI's USD-denominated usage counters, which is not proof of an actual subscription charge. No model switch, image generation or provider-side image access was tested.

Independent review confirmed voluntary stopping: the two completed runs recorded three and two guarded tool calls respectively, with zero generator attempts and zero blocked attempts. The final response still included connector capability exclusions that could not be independently verified from the captured public schemas/results; those statements are not accepted as capability facts. Ranked searches also do not establish exhaustive absence. The audit file contained one additional cache-hit row without a matching owned response in the captured native stream; it is not counted as a second model run or independent activation proof.

**Verified:** automatic native discovery/context delivery, advertised-only Codex reporting, and a user-facing handoff question before generation. **Not established:** two qualified callable image routes, an interactive multi-generator picker, successful handoff/generation, or universally correct model interpretation. The final semantic outcome remains partial rather than a full capability-choice pass. Existing startup plugins retained their normal context; this was not a pristine, skill-only ablation.

See [native activation and its evidence boundaries](references/claude-activation.md). A hook makes discovery/context delivery deterministic when it runs successfully; actual interpretation and a multiple-generator user choice still require live model evidence with qualified callable routes.

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

## Answer validation and bounded repair (0.5.0)

Both optional read-only parent clients now run an independent configured checker before accepting a candidate. A checked answer failure carries the original task, candidate and failed-check feedback into another permitted routing decision, with at most two routing changes and three candidates. Exact user locks, live catalog eligibility, strictly higher same-model native effort, and rejection of repeated failed pairs are enforced. A selector assesses cross-model suitability; a different ID alone is not proof of stronger reasoning.

Offline tests cover automatic effort/model repair, precise feedback, unchanged acceptance criteria, exhausted budgets, locked pairs, checker errors, unavailable checks and runtime verification before answer validation. Failed checked candidates are withheld from successful final output. Command checkers have bounded I/O and a deadline; injected trusted Python callbacks must implement their own deadline. Independent cross-review found no blocking issue in either client or the shared checker.

A real 0.5.0 npm tarball passed isolated installation for all six adapters, preserving mixed BOM/CRLF/non-English/no-final-newline originals and six exact backups. Both distinct installed payload roots imported the shared validation and receipt modules, and both clients exposed the checker/repair flags. Reinstall made zero changes; uninstall restored all six originals byte-for-byte and removed only the owned payloads. These checks made no provider calls.

The portable policy and managed global instructions carry the same validation requirement. The development user's three configured instruction files retained every byte outside the managed block; each retained exactly one block and a repeat setup made zero changes. The pre-existing manual Codex skill retained its frontmatter and installer ownership status while its policy body and known controller code were updated. Other manual reference files were preserved.

The preceding pilot without a repair gate answered one of three frozen tasks correctly with adaptive routing, versus three of three with fixed `gpt-6.1-sol` / `medium`. Adaptive routing used 78,871 reported tokens and 83.369 seconds, including selection, versus 35,105 tokens and 46.326 seconds for fixed settings. This negative result motivated the gate; it is not a benefit claim. Model/effort evidence matched for every completed turn.

The new live Codex comparison used the same frozen cases/oracle, equal check/feedback/three-candidate budgets, and alternating arm order. Fixed remained `gpt-6.1-sol` / `medium`. Adaptive first-pass correctness was 2/3; it blocked two wrong extraction candidates and automatically repaired `gpt-6-luna / low` → `gpt-6-luna / medium` → `gpt-6.1-sol / medium`. Final accepted correctness was 3/3 for both arms. Fixed used 35,639 tokens and 49.730 seconds; adaptive used 136,212 tokens and 99.738 seconds, including all selectors and failed attempts. Thus the gate demonstrated recovery, while this pilot showed approximately 2.006× time and 3.822× tokens versus fixed settings. No monetary cost was measured.

An independent auditor matched all 13 new native turns' settings, usage and public final answers, regraded all eight candidates and verified all 13 experiment threads were archived. The predeclared historical-error replay was correctly skipped after fresh adaptive failure. This was a separate fresh-thread pipeline using the production validator and repair guard, not an end-to-end test of the packaged same-parent client or an ordinary desktop parent switch. Global instructions were shared, so it was not a pure skill-on/off ablation. Antigravity's new repair path was tested offline only. [Sanitized results, recorded answers, frozen cases, oracle and a local regrader](https://github.com/subin-sama/dynamic-model-router/tree/main/benchmarks/2026-11-04-quality-gate) are included for review. Three synthetic cases do not establish general superiority.

No universal correctness checker is supplied. Without a task-appropriate checker, the clients report validation as unavailable and preserve their prior behavior. Installing this policy does not add a model-switch control to an ordinary desktop chat.

## Independent behavioral simulation

A separate agent reviewed twelve scenarios covering ordinary work, difficult debugging, user locks, unsupported settings, unavailable switching controls, existing Gemini Auto, image eligibility, missing credentials, bounded escalation, and unsafe attempts to repeat external actions or evade host restrictions. These were reasoning simulations, not runtime tests.

## Limits

- The parent prototype is a separate read-only text client. It does not make an existing Codex desktop chat switch automatically after skill installation, and is not a full coding client.
- Settings apply between turns, not to a request already in flight.
- Runtime verification establishes Codex's resolved settings, not independent provider-side backend attestation.
- Routing adds selection turns and repair can add further failed attempts. A small correctness pilot does not establish general quality, latency or monetary savings; reported tokens are not a monetary-cost measurement.
- Historical cross-provider text-controller checks stopped at missing Claude/Gemini authentication. The later Claude native-activation probes completed inference, but did not establish an executable image bridge or multiple-generator choice. Gemini successful inference remains untested. Account/version/organization capabilities must still be discovered on each recipient's host.
- macOS was live-tested. POSIX process-group cleanup has an offline test; Windows cleanup covers the direct server only and has no live Windows validation.
