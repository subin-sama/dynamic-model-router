---
name: dynamic-model-router
description: Dynamically select available models and native reasoning settings for task phases and delegated work. Use when automatic routing is enabled or a user asks to adapt quality, latency, or cost in AI agents such as Codex, Claude Code, Gemini CLI, Antigravity, OpenCode, Copilot CLI, or an API agent.
---

# Dynamic Model Router

Choose an appropriate model AND its native reasoning setting for the work about to run. Reassess as the work changes. Use real runtime controls when available; distinguish a recommendation from an applied setting.

## Capability check

At activation, identify the host, its exposed controls, current settings if observable, and explicit user constraints. Read only that host's section of [references/hosts.md](references/hosts.md). Reuse this capability snapshot until the host changes or rejects a selection.

Use the host's current tool schema, account-visible catalog, or configured agent definitions as the source of model IDs and settings. Official provider documentation describes capabilities but does not prove account access. A cached catalog is a planning hint. For Codex only, `python3 scripts/inspect_models.py` inspects the local model cache without contacting a service or reading credentials.

Determine the available execution mode:

| Mode | Actual capability | What to do |
| --- | --- | --- |
| `native-auto` | The host's own automatic router is already enabled | Retain its routing; distinguish Auto policy from an unknown effective model ID. Assess reasoning controls separately. |
| `native-turn` | A supported host operation configures a subsequent turn | Apply at the supported boundary and retain history. Do not claim to modify a request already in flight. |
| `native-skill` | The host implements model/effort skill metadata | Use a supported configured profile within its documented scope. Static metadata does not become dynamic because the body contains conditions. |
| `native-worker` | A tool or configured subagent supports model and/or reasoning selection | Route a bounded work unit to that worker; retain the main agent as coordinator. |
| `external-run` | An authorized CLI/API controller can start a separate run | Pass validated native settings and an explicit handoff. Treat it as a separate run. |
| `advisory` | No usable controls, unknown capabilities, or overrides forbidden | Recommend once, disclose the limitation, and continue useful work on the current runtime. |

Prefer a host's existing automatic router when it meets the objective; avoid creating a competing loop. Otherwise choose the most direct permitted mode. A tool argument is not permission to use it. Respect restrictions on overrides, inheritance, data sharing, and delegation. Do not evade a host restriction through another CLI, API, UI, config edit, or self-messaging. Do not create user-owned chats merely to route work or rewrite persistent defaults to simulate a per-task switch.

## Select for the current work unit

Honor user locks independently: a fixed model can still permit effort selection, and fixed effort can still permit model selection. A request for automatic routing permits choosing among available options within its scope; it does not override host rules or an explicit fixed choice. If a locked combination is unavailable, explain the conflict instead of silently substituting.

Judge the next phase using ambiguity, interacting constraints, unfamiliarity, relevant context size, verification difficulty, and observed failures. Treat tools, modalities, privacy requirements, and context limits as eligibility filters before optimizing speed or cost. File count, prompt length, and domain names alone do not determine difficulty. Consequence determines validation rigor and applicable authorization; it does not automatically require maximum reasoning.

Use these roles as a starting point, not model names:

| Work shape | Model role | Reasoning target |
| --- | --- | --- |
| Extraction, direct lookup, formatting, fully specified local change | Fast suitable model | Light |
| Ordinary implementation, synthesis, bounded bug with a reproduction | General-purpose or task-specialized model | Standard |
| Ambiguous debugging, architecture, interacting systems, difficult tradeoffs | Strong model suited to the domain | Deep |
| Demonstrated hard reasoning bottleneck after deeper work has failed | Strongest suitable available model | Intensive, bounded |

Map roles from current host descriptions, trustworthy capability data, user preferences, and observed results. Roles may resolve to the same model. Keep the current suitable model when context transfer or a new worker would cost more than it saves. Do not launch a worker for a trivial task merely to use a cheaper model.

Choose model and effort as a pair. A fast model with greater effort and a stronger model with lighter effort can both be reasonable; effort does not create another model's capabilities. Prefer the least resource-intensive pair reasonably likely to meet acceptance criteria. With no stated objective, balance quality and responsiveness. Do not invent exact prices, speedups, or savings.

Map Light/Standard/Deep/Intensive to **that model and host's supported native settings**, not a universal enum. If the host exposes `low`, `medium`, and `high`, these can provide light/standard/deep starting points. If there is no supported reasoning control, omit effort and use the default. A thinking switch, token budget, adaptive reasoning policy, and output verbosity are different controls. Never send foreign-provider effort labels or invent an `auto` value. An explicit user setting must be supported exactly; do not silently clamp it.

## Apply and check

Retain a compact decision in working context: phase, model, native reasoning setting or default, mode, reason, and status. Use `recommended` for a plan, `requested` after submitting settings, `applied` when the host acknowledges their application, and `verified` when effective runtime values are reported and match. Keep `unknown` for current settings the host does not expose. Do not infer the actual model from writing style.

For unchanged or inherited settings, record their source and any observable effective values; no change was requested, so do not manufacture a change status or an application event.

For a worker or external run, send the goal, relevant input or exact file pointers, settled decisions, constraints, acceptance checks, and edit ownership. Preserve enough context for correctness without forwarding the whole conversation by default. Keep sequential decisions sequential; parallelize independent units only when coordination is justified. Workers complete their assigned unit rather than recursively routing more workers unless the parent explicitly delegates orchestration.

Pass settings through documented arguments or supported configured agents/profiles. Use only tools actually available in this host. A successful dispatch proves a worker/run started; it does not alone prove that settings survived environment overrides or caps. Retain `requested` until the host acknowledges application, and reserve `verified` for matching effective values. A successful task result alone does not verify settings. Report inherited or omitted effort honestly.

If a selection is rejected, refresh capabilities and choose a supported alternative only if constraints allow it. Do not repeat the rejected pair. State a meaningful fallback. A permission or authorization denial is a boundary, not a routing failure.

## Reassess with evidence

Reassess at investigation → design → implementation → validation, changed requirements, or a failed substantive attempt that reveals greater difficulty. Do not switch after every tool call or during an active run.

- **Increase** when competing hypotheses, cross-system interactions, a failed reasoned approach, or difficult acceptance evidence expose a reasoning bottleneck. State the bottleneck in one sentence. A deeper setting on the same model can be enough.
- **Decrease** when uncertainty is resolved and the remaining unit is mechanical or narrowly specified. Carry forward decisions and acceptance criteria; do not reopen settled design.
- **Resolve prerequisites** for missing input, credentials, tools, context, or unavailable dependencies. More effort does not supply evidence or permission.

Default to at most two upward routing changes for the same unresolved work unit, not an automatic retry ladder. Increasing model and effort together in one selection counts as one change. Do not evade the limit through ineffective retries at an unchanged pair. Reaching the limit stops escalation, not useful work: report the unresolved blocker or uncertainty and the input or changed approach that would help. Preserve stricter user budgets. Do not repeat external or irreversible actions merely to test another model. Accept results against the original criteria using relevant tests, sources, or visual/audio evidence.

## Communication and activation

Emit one short, visible routing receipt at the start of each task, before substantive work. Update it when the selected pair, execution scope, evidence status, fallback, or outcome meaningfully changes. Reuse the same receipt while these stay unchanged; do not repeat it after every tool call. Use chat commentary when the host provides it, otherwise ordinary assistant text.

In Markdown-capable chats, use a compact blockquote with a colored status indicator, bold status and scope, inline-code model/native effort, and an optional short reason. Keep it to two or three short lines with Markdown hard breaks; do not wrap the whole receipt in a code fence or use headings, tables, or raw bracket-log tags. Localize status, scope, labels, and reason to the user's language. Keep model IDs and native effort values exact. For example:

```markdown
> 🟦 **Routing · Recommended**\
> **External · agy** · Model `gemini-4-argon-high` · Effort `high`\
> Review plot clues and the ending's logic.
```

Identify the actual execution target: Parent, Worker with its name, or External with its name. A worker change is not a parent change. Include the previous pair only when it is known and useful. When Markdown is unavailable, use the same information in a compact plain-text line. Honor an explicit user presentation preference. Terminal clients retain their existing `[Routing][status][scope] model=value; effort=value` log format; chat presentation does not change structured records.

Use 🟦 recommended, 🟨 requested, 🟪 applied, 🟩 verified, ⚪ unchanged, 🟧 unverified, and 🟥 error beside the localized textual status. Color supplements the label; use text alone if emoji rendering is unavailable. The host controls the emoji appearance, text colors, fonts, and spacing. This instruction-only chat format does not provide CSS or live animation; do not simulate animation with repeated messages, artificial status changes, or a prerecorded spinner that implies live execution.

- `recommended`: a proposed pair, with no claim of application.
- `requested`: settings submitted through a supported control; dispatch alone is not verification.
- `applied`: the host acknowledges application within the reported scope.
- `verified`: effective runtime evidence matches. Qualify partial evidence, such as a verified model variant with effort mapped from its catalog rather than an independent effort field.
- `unchanged`: no setting change was requested; identify inherited/current settings when observable. Render unknown values as a short localized "not exposed" label when the host does not expose them; if both are unexposed, combine them as "Model/effort: not exposed". Keep `unknown` in raw logs or records. Unknown values do not establish a verified pair.
- `unverified` or `error`: a requested outcome lacks runtime evidence, or a change/execution failed. Report the fallback and avoid a false success receipt.

Emit the highest status the evidence supports, not a fabricated sequence of all lifecycle stages. A recommendation must never be presented as an applied change. If a change finishes with verification, missing evidence, or a mismatch, report that outcome visibly; do not leave only a pre-execution selection message. Never infer IDs or effort from writing style or a successful answer.

In advisory mode, explain once that the recommended pair cannot be applied through this host and the current runtime remains in use. For example:

```markdown
> ⚪ **Routing · Unchanged**\
> **Parent** · Model/effort: not exposed\
> This host has no permitted parent switch; current settings remain in use.
```

These are assistant-generated chat receipts, not a native app banner or an unconditional host event log. Do not invent a receipt for an event that did not happen, log private reasoning, or create persistent log files unless requested or already configured.

Automatic skill discovery is not a guaranteed always-on hook. Explicit invocation or applicable project instructions can activate this workflow; [references/hosts.md](references/hosts.md) describes host boundaries. The workflow automates selection after activation, and automates execution only where a real permitted control exists.
