# Codex parent router prototype

This optional launcher runs **one parent conversation** through Codex App Server. For each task, the parent first selects a model/native effort pair, then the launcher applies those settings and starts the execution turn on the **same thread ID**. The next task can increase or decrease settings while preserving conversation history.

It is a separate client, not an automatic hook into the currently open Codex desktop chat. It changes settings between turns, not in a request already running. Installing the skill alone does not start this client or connect it to a desktop composer.

## Run

Requires Python 3.9+ and a Codex CLI with App Server `model/list`, `thread/settings/update`, `turn/start.outputSchema`, and persistent rollout `turn_context` support. It uses Codex's existing sign-in; no separate Platform API key is required. The desktop-bundled executable is detected on macOS when present; otherwise it uses `codex` on PATH. Use `--codex /path/to/codex` to choose a client explicitly.

This prototype considers only models that advertise explicit reasoning settings. It excludes models without those settings because omission/null is not assumed to reset the previous model's effort safely.

Run from the extracted skill folder:

```bash
python3 scripts/codex_parent_router.py
```

Enter a task at the prompt. The parent chooses settings before performing it. Enter another task to continue the same conversation, or `/quit` to stop. This initial prototype is **read-only text work**: shell, plugins, apps, memories, and subagent features are disabled for its thread. It does not yet serve as a full coding client or attach to an existing desktop conversation.

One task:

```bash
python3 scripts/codex_parent_router.py \
  --task 'Explain the race conditions in this code: ...' \
  --transcript parent-routing-result.json
```

Multiple tasks on the same parent:

```bash
python3 scripts/codex_parent_router.py \
  --task 'Remember token LANTERN-42. Sort these IDs: B, A, B.' \
  --task 'Explain a difficult concurrency design: ...' \
  --task 'Return the remembered token.'
```

`--objective` accepts `balanced` (default), `speed`, or `quality`. `--model-lock` and `--effort-lock` constrain the selections independently. `--initial-model` chooses only the starting parent model; it does not prescribe work-unit selections. `--tasks-file` accepts a JSON array of task strings. `--timeout` is the deadline per selection/execution turn.

An optional transcript contains task text, route reasons, responses, turn IDs, and effective settings when observable. Choose its location appropriately; the launcher does not upload that file or include it in another user's installation.

## What actually changes

1. `model/list` supplies visible IDs and supported effort values from the running host.
2. A selection turn on the parent follows `SKILL.md` and returns a constrained route JSON. No worker is used.
3. The launcher validates the exact pair and locks, then calls `thread/settings/update` while the thread is idle.
4. The execution turn starts without a new thread or manual history replay.
5. The launcher checks the execution turn's `turn_context` for matching resolved settings. If the host omits those values, it labels the result unverified. A mismatch stops the client; it does not repeat execution.

Each task costs **two turns**, including the selection turn. Selection currently uses the parent's existing settings, so choosing a light follow-up after a deep task still has routing overhead. No cost or speed improvement is promised. Unsupported settings, authorization failures, or failed execution stop the client rather than silently selecting an unrelated fallback or repeating side effects.

App Server is an evolving interface. Verify the installed version and account's capabilities. The local transport and cleanup are tested on macOS; POSIX process groups are cleaned up on macOS/Linux. Windows transport is not live-tested and its stdlib cleanup covers only the direct server process.

Public summaries of the live parent and worker tests are in [VALIDATION.md](../VALIDATION.md). Raw session identifiers and local rollout evidence are not part of the public repository.

Official source: [Codex App Server](https://learn.chatgpt.com/docs/app-server). The runtime schema shipped with the tested Codex version specifies that `thread/settings/update.model` and `.effort` apply to subsequent turns. This does not establish an equivalent tool in every Codex desktop chat.
