# Native Claude Code activation

Version 0.8.0 installs a Claude Code `UserPromptSubmit` command hook. Plain instructions alone did not reliably activate machine discovery in a real Claude probe. This hook runs before the model receives each submitted prompt, collects a bounded read-only provider snapshot, and injects a short policy fragment from the installed `SKILL.md` together with that evidence.

## What runs

The global installer adds one command to `UserPromptSubmit` in the selected Claude configuration root's `settings.json`. It points to Node and the installed `scripts/claude_activation_hook.mjs`, with a 45-second native hook timeout. The runtime has a 35-second discovery deadline and invokes only the fixed `cross_cli_router.py discover --models` helper through Python 3.9+.

Discovery can contact native provider metadata services, but sends no user prompt or inference request to those providers. The hook never changes the parent model/effort, starts a delegated task, generates an image, logs in, installs a connector, or authorizes a handoff. It does not classify the prompt by keyword; Claude still identifies the user's required capability semantically.

The inserted context contains the canonical activation fragment between `claude-activation` markers in `SKILL.md`, its source/hash, and a sanitized snapshot of detected CLIs, advertised model/effort values, authentication status where exposed, and provider-scoped image flags. A metadata-only image flag remains discovery-only. Current-host image tools are not observed by the hook and must be checked in that host. It cannot turn Codex's native image support into a callable bridge inside Claude.

Current schemas/results and labeled snapshots take precedence over restored conversation summaries as capability evidence. Missing search results do not establish an authentication failure. Without an executable route, the response should identify a discovered provider's advertised support and the missing bridge, then ask about that handoff; unrelated setup suggestions are not qualified generator choices.

## Cache and failures

Sanitized discovery is cached for five minutes under the user's state directory: `XDG_STATE_HOME/dynamic-model-router`, `LOCALAPPDATA/dynamic-model-router` on Windows, or `~/.local/state/dynamic-model-router`. Cache files use owner-only permissions where supported. Installation, helper/policy changes, executable fingerprints, expiry, or an explicit `--no-cache` refresh invalidate the cached view. A cache hit is labeled as cached evidence; recheck a selected interface before dispatch. Concurrent or failed refreshes report stale/unavailable rather than inventing a current snapshot.

Missing Python, malformed output, discovery timeout, or unavailable metadata produces an explicit prerequisite message plus activation guidance. The original user prompt is allowed to continue. Existing `disableAllHooks` or higher-priority host restrictions remain in force; an installed but disabled hook is not a successful runtime activation.

The hook does not retain the prompt or full MCP configuration. Optional `DYNAMIC_MODEL_ROUTER_HOOK_AUDIT_FILE` records only the event, discovery status, cache status, policy source, skill hash and snapshot hash for a requested local test. It is off by default. Keep per-user cache/audit data out of distributed skills and shared reports.

## Installation preservation

Run the normal one-command installer again. It preserves existing Claude settings, model defaults, permissions, plugins and other hooks, and backs up the exact original settings privately. The ownership registry stores only the managed hook entry, hashes and container metadata, not the user's settings or environment values. Repeat installation makes no duplicate hook. Uninstall removes only the owned command, retaining other commands added alongside it; unchanged settings can be restored byte-for-byte from their backup. A modified or duplicated managed command is preserved as a conflict instead of overwritten.

A reused manual skill must contain the current activation runtime before a native hook can be installed. The installer preserves old manual contents and reports the missing runtime rather than pointing Claude at a nonexistent script. Other hosts retain their existing activation methods.

## Verify actual behavior

Use a fresh ordinary Claude request without naming the skill or supplying a fake tool manifest. Capture native hook evidence and the public tool/answer trace separately. Check that machine discovery reached the prompt, that current-host capabilities were assessed, and that any choice was requested before generation. Two qualified executable routes are needed to establish the multiple-generator chooser branch; a discovery-only handoff question does not prove that branch.

Keep earlier failed probes. A blocked generator attempt is not proof of voluntary stopping, and a budget/transport failure is not a successful end-to-end run. Headless `--print` can return a user-choice question as text without rendering an interactive picker. The hook makes activation and metadata collection deterministic; it does not guarantee that every model will correctly interpret the supplied evidence.
