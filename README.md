# Dynamic Model Router

[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)

A portable model and reasoning-effort routing skill, with a **one-command global installer** that preserves existing user instructions.

## Install and enable globally

```bash
npx --yes github:subin-sama/dynamic-model-router
```

The command detects supported agents, installs the skill, backs up their existing global instruction files, and adds an identifiable routing block for **every task in every project**. You do not need to edit `AGENTS.md`, `CLAUDE.md`, or `GEMINI.md` yourself. Existing user content, including non-English text, stays intact.

To configure all six supported agents, including ones not yet installed:

```bash
npx --yes github:subin-sama/dynamic-model-router --agents all
```

Requires Node.js **20+**, npm/npx, and Git for installation from GitHub. No npm account, separate API key, global npm package, or background service is needed. Restart or refresh your agents after setup so they load their global instructions.

Preview without changing files:

```bash
npx --yes github:subin-sama/dynamic-model-router --agents all --dry-run
```

## Supported global activation

| Agent | Default global instruction file | Automatic setup |
| --- | --- | --- |
| Codex | `~/.codex/AGENTS.md`, or an existing nonempty global `AGENTS.override.md` | Yes |
| Claude Code | `~/.claude/CLAUDE.md` | Yes |
| Gemini CLI | `~/.gemini/GEMINI.md`, honoring configured context filenames | Yes |
| Antigravity App / CLI / IDE | `~/.gemini/AGENTS.md` | Yes |
| OpenCode | `~/.config/opencode/AGENTS.md` | Yes |
| GitHub Copilot CLI | `~/.copilot/copilot-instructions.md` | Yes |

The installer respects supported custom configuration-home environment variables and reuses valid existing skill installations. Fresh shared installs use `~/.agents/skills/dynamic-model-router` where the host supports that location; native locations are used when needed to avoid conflicting copies. See [host integration](references/global-installation.md) for exact paths and scope.

For Antigravity only, run `npx --yes github:subin-sama/dynamic-model-router --agents antigravity`. Its App, CLI, and IDE share the skill at `~/.gemini/config/skills/dynamic-model-router`. Setup checks for competing copies in CLI-specific and legacy locations before writing; see [Antigravity installation details](references/global-installation.md#antigravity).

The routing policy is agent-agnostic. **Automatic setup is limited to hosts with verified user-wide local instruction mechanisms.** Cursor's account-level User Rules and hosted chat products need their own integration; this command does not pretend to configure every AI product. Project, session, organization, and host restrictions still apply.

## Existing instructions and updates

- Existing instruction bytes are preserved outside the managed block, including Unicode, BOMs, CRLF, and missing final newlines.
- Changed instruction files are backed up before replacement. State and backups are stored under `~/.config/dynamic-model-router/`.
- Re-running the command updates its own block without appending duplicates. Detected conflicting edits stop the operation.
- Valid manual skill copies are reused without overwriting their contents. Installer-owned files are updated only while their recorded contents remain unchanged.
- Existing file symlinks are retained, shared targets are deduplicated, and failed operations roll back their own changes where no concurrent edit is detected.

Run the install command again for managed updates. Select particular agents with `--agents codex,claude-code`.

Remove managed activation and unchanged installer-owned files:

```bash
npx --yes github:subin-sama/dynamic-model-router uninstall
```

Uninstall preserves user additions, modified files, and pre-existing manual installations. It does not restore an old whole-file backup over newer user instructions.

## What routing does

Choose a fast suitable model/effort pair for routine work, deepen reasoning when uncertainty and interacting constraints justify it, and reduce intensity when the remaining work becomes straightforward. Discover model names and supported native settings from the host rather than using a fixed universal ranking. Preserve explicit user model and effort choices.

Global activation makes this policy part of the host's user instructions. **Actual model changes require a control the host exposes and permits.** The skill distinguishes recommendations, submitted settings, applied settings, and runtime verification. Installing it does not create a missing switch control or change a request already in flight.

Read [SKILL.md](SKILL.md) for the portable policy and [host capabilities](references/hosts.md) for runtime boundaries.

## Visible routing receipts

Normal Codex and Claude Code chats that load this skill are instructed to show a compact receipt at task start and update it for meaningful setting, scope, evidence, or outcome changes:

> 🟦 **Routing · Recommended**\
> **External · agy** · Model `gemini-4-argon-high` · Effort `high`\
> Review plot clues and the ending's logic.

Chat receipts use two or three short blockquote lines, with localized status, scope, labels, and reason. Model IDs and native effort values stay exact. Scope identifies Parent, Worker with its name, or External with its name. A worker change must not be presented as a parent change. Unexposed values read "not exposed" in the user's language; both can be combined as "Model/effort: not exposed". Plain-text hosts use a compact line instead. Explicit presentation preferences take priority.

Version 0.4.1 restores this text presentation and removes the 0.4.0 HTML receipt renderer. Routing notices do not create native cards, artifacts, panels, or animation by default. Updating an installer-owned copy removes unchanged obsolete renderer files; manual installations remain under their owner's control. Model/effort selection and its evidence rules stay the same.

Colored emoji supplement the textual status: 🟦 recommended, 🟨 requested, 🟪 applied, 🟩 verified, ⚪ unchanged, 🟧 unverified, and 🟥 error. The text label remains readable without color. Emoji appearance, fonts, spacing, and text colors depend on the host. This package supplies chat instructions, not a custom CSS renderer or live animation. Animated UI would need a host-supported rendering integration; no such integration is installed by this skill.

`recommended` means proposed, `requested` means submitted, `applied` requires host acknowledgement, and `verified` requires matching runtime evidence. Inherited/no-change settings use `unchanged`; unexposed values stay `unknown`. Missing evidence or a failed outcome produces `unverified` or `error`. The skill reports the highest supported status rather than inventing a sequence of lifecycle events.

These are **assistant-generated chat messages**, not a native desktop banner or guaranteed host event log. Host loading and model compliance still matter, and a receipt does not create a model-switch control. Updated installer blocks include the reporting requirement even when an older manual skill is reused. Re-run setup for managed global instruction updates; existing chats may need to reload their instructions.

The optional CLI parent clients retain the `[Routing][status][scope] model=value; effort=value` terminal format before selection and after execution. They report verified, unverified, or error outcomes automatically, with Antigravity effort evidence qualified as catalog mapping. Optional `--record` (Antigravity) and `--transcript` (Codex) save their unchanged structured records; normal chat reporting does not create persistent log files.

## Standard skill-manager alternative

If you want only skill files and prefer managing activation yourself:

```bash
npx skills add subin-sama/dynamic-model-router -g -a codex -y
```

The standard `skills` CLI discovers this repository's root `SKILL.md`, but does not edit global instruction files. Its current release requires Node.js 22.20+. The one-command installer above includes global activation.

## Optional Codex parent client

The package also contains a separate, **read-only text prototype** that lets one parent conversation select and apply its next model/effort pair between turns while retaining history. It does not attach a hook to an existing desktop chat or act as a full coding client.

From a repository clone or installed skill folder, with Python 3.9+ and an existing Codex sign-in:

```bash
python3 scripts/codex_parent_router.py
```

Enter tasks to continue one conversation; `/quit` exits. It adds one selection turn per task. See the [parent client guide](references/codex-parent-router.md).

## Antigravity automatic parent client

To let the parent choose and apply its next model/effort pair automatically:

```bash
npx --yes github:subin-sama/dynamic-model-router antigravity
```

This separate **read-only text prototype** uses native CLI flags between turns while resuming one parent conversation. It was live-tested with parent-selected **Flash/low → Argon/high → Flash/low**, matching runtime variants, and retained history. It requires macOS/Linux, Python 3.9+, and a signed-in `agy` CLI in addition to the Node/Git installation requirements. It does not change an existing App/IDE chat or make global installation alone switch its runtime. See the [Antigravity client guide](references/antigravity-parent-router.md).

## Validation and development

The Python components have **79 offline tests**, plus real Codex worker and same-parent routing checks. The Codex same-parent test selected **Luna/low → Sol/high → Luna/low**, with matching runtime settings and retained history. The installer and launcher have additional real-filesystem Node tests for preservation, overrides, repeat installation, ownership, symlinks, rollback, and uninstall. See [VALIDATION.md](VALIDATION.md).

Antigravity CLI **1.4.3 was live-tested** in two separate modes. The skill-only test produced recommendations without changing runtime; the added external parent client selected and applied native variants between turns successfully. Antigravity global activation paths are checked against official documentation; App and IDE runtime routing remain untested. See [the live-test evidence](VALIDATION.md#live-antigravity-parent-test).

From a repository clone, run offline tests without a provider account:

```bash
npm test
python3 -m unittest discover -s tests -v
```

No quality, cost, or latency improvement is promised. Runtime checks establish the tested Codex configuration, not universal model-selection quality or independent provider-side attestation.

Contributions should include the host/version, reproducible behavior, and sanitized evidence. New global adapters need official instruction-path documentation and preservation tests.

## License

[MIT](LICENSE) — Copyright (c) 2026 subin-sama. Preserve the copyright and permission notice when redistributing. The software is provided without warranty.
