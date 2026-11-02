# Dynamic Model Router

[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)

A portable agent skill that chooses a suitable **model and native reasoning effort for each task phase**, then applies the choice through controls the host actually supports.

[ภาษาไทย](README.th.md) · [Host compatibility](references/hosts.md) · [Validation](VALIDATION.md)

Use a fast suitable pair for routine work, deepen reasoning when uncertainty and interacting constraints justify it, and reduce intensity when the remaining work becomes straightforward. Model names are discovered locally rather than pinned to a universal ranking. Explicit user locks are preserved.

## Two ways to use it

| Mode | What it does |
| --- | --- |
| Portable skill | Guides routing in Codex, Claude Code, Gemini CLI, or an API agent. Applies choices through permitted host controls; otherwise reports a recommendation honestly. |
| Optional Codex parent client | Lets one parent conversation choose its next model/effort pair, applies it between turns, and preserves history. This is a **separate, read-only text prototype**, not a hook in an existing desktop chat or a full coding client. |

The skill does not guarantee activation on every message. A prompt saying “think harder” is not proof that the runtime reasoning setting changed. Actual setting support and permissions depend on the host, client version, and account.

## Install the skill

Clone the repository into **one** skill directory your host discovers. The repository root contains `SKILL.md`.

Codex, or Gemini CLI installations supporting the shared skill directory:

```bash
git clone https://github.com/subin-sama/dynamic-model-router.git \
  "$HOME/.agents/skills/dynamic-model-router"
```

Claude Code:

```bash
git clone https://github.com/subin-sama/dynamic-model-router.git \
  "$HOME/.claude/skills/dynamic-model-router"
```

For a project-only installation, use `.agents/skills/dynamic-model-router` or `.claude/skills/dynamic-model-router` in that project. Some Codex versions also support a configured Codex-home skills directory. Refresh/reopen the host if needed and avoid installing duplicate copies in directories it scans.

Invoke in Codex:

```text
$dynamic-model-router Investigate this bug. Choose model and effort as the work changes.
```

Invoke in Claude Code:

```text
/dynamic-model-router Investigate this bug and choose suitable model/effort settings.
```

In Gemini CLI, ask it to activate the `dynamic-model-router` skill through its normal consent flow. When Gemini's native Auto already meets the objective, the skill retains that router instead of introducing a competing loop.

## Run the Codex parent prototype

Requires Python **3.9+**, an installed Codex CLI with the necessary App Server methods, and an existing Codex sign-in. The scripts use only the Python standard library.

From the installed or cloned repository:

```bash
python3 scripts/codex_parent_router.py
```

Enter tasks to continue one parent conversation; `/quit` exits. For each task, the parent selects a pair in a short selection turn and the client applies it before the execution turn. This adds **one selection turn per task**. There is no measured cost or speed improvement claim.

You can also pass tasks directly:

```bash
python3 scripts/codex_parent_router.py \
  --task 'Remember token LANTERN-42. Sort these IDs: B, A, B.' \
  --task 'Return the remembered token.'
```

Options include `--objective balanced|speed|quality`, independent `--model-lock` and `--effort-lock`, `--codex /path/to/codex`, and `--timeout`. An optional `--transcript PATH` records task text and results locally. See the [parent client guide](references/codex-parent-router.md).

This prototype disables shell, plugins, apps, memories, and subagents. It does not modify global model defaults. It changes the parent **between turns**, not during an in-flight request.

## What has been tested

- **47 offline tests** for catalog handling, exact native settings/locks, RPC transport, same-parent sequencing, failures, and runtime-evidence handling.
- Real Codex native-worker routing: worker dispatches matched the resolved runtime model and effort.
- Real same-parent routing on one continuous conversation: **Luna/low → Sol/high → Luna/low**, with history retained and matching execution `turn_context` values.
- A final-build live smoke test completed with matching runtime settings.

Live tests used the desktop-bundled Codex CLI `0.166.0-alpha.5.1` on macOS. Claude Code and Gemini CLI integration guidance was checked against official documentation, not live-tested in those runtimes. Windows transport is not live-tested. See [VALIDATION.md](VALIDATION.md) for boundaries and the public test summary; private runtime session identifiers are not published.

Run the offline suite without a Codex account or provider calls:

```bash
python3 -m unittest discover -s tests -v
```

The Codex-only cache inspector is also available:

```bash
python3 scripts/inspect_models.py
```

It reads only the chosen local model catalog and does not launch a model or establish account entitlement.

## Contributing

Open an issue or pull request with the host/version, reproducible behavior, and sanitized evidence. Keep model selection separate from runtime application and verification. Run the offline tests for Python changes. Provider-backed tests should be explicitly requested and described separately from mocks or simulations.

## License

[MIT](LICENSE) — Copyright (c) 2026 subin-sama. You may use, modify, redistribute, and use the project commercially under the license terms. Preserve the copyright and permission notice. The software is provided without warranty.
