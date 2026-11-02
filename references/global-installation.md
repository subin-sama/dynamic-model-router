# Global installation adapters

The one-command installer configures **user-wide routing instructions**, not a background daemon or a forced model switch. It writes a managed English block containing the selected installed `SKILL.md` path and asks the agent to apply that policy to every task. The user's surrounding instructions remain untouched, whatever language they use.

## Targets

| Agent ID | Instruction root and file | Skill candidates |
| --- | --- | --- |
| `codex` | `CODEX_HOME` or `~/.codex`; effective `AGENTS.override.md` when nonempty, otherwise `AGENTS.md` | Shared `~/.agents/skills/dynamic-model-router`, or an existing Codex-home `skills/dynamic-model-router` |
| `claude-code` | `CLAUDE_CONFIG_DIR` or `~/.claude`; `CLAUDE.md` | Config-root `skills/dynamic-model-router`, with an existing shared copy reusable |
| `gemini-cli` | `GEMINI_CLI_HOME` or the OS home, then `.gemini`; configured global context filename or `GEMINI.md` | The same home root's `.agents/skills/dynamic-model-router` or `.gemini/skills/dynamic-model-router` |
| `opencode` | `OPENCODE_CONFIG_DIR`, otherwise `XDG_CONFIG_HOME/opencode` or `~/.config/opencode`; `AGENTS.md` | Shared or native config-root `skills/dynamic-model-router` |
| `github-copilot` | `COPILOT_HOME` or `~/.copilot`; `copilot-instructions.md` | Shared or config-root `skills/dynamic-model-router` |

`GEMINI_CLI_HOME` replaces the home root; the installer appends `.gemini`. `CLAUDE_CONFIG_DIR`, `COPILOT_HOME`, and `CODEX_HOME` identify their configuration directories directly. The installer reads existing environment overrides without changing them.

Gemini settings support comments. The adapter reads system-default, user, and system settings to honor `context.fileName`, including safe filename arrays. It does not evaluate JavaScript, accept trailing commas, or change administrator settings. Future workspace settings and Gemini's own trust/security decisions can still affect what it loads.

OpenCode configuration-directory behavior is version-sensitive. The installer reports the actual target it chose. Applicable project instructions can override user-wide guidance across hosts; managed policies and explicit user choices remain authoritative.

## Selection and inspection

With no options, setup targets detected supported agents. Configuration-directory presence or a corresponding executable is a detection signal, not proof of a tested runtime version. `--agents all` explicitly configures all five adapters. Unsupported IDs fail without partial setup.

```bash
npx --yes github:subin-sama/dynamic-model-router --agents codex,gemini-cli --dry-run
npx --yes github:subin-sama/dynamic-model-router --agents all --json
```

`--home PATH` is an isolated staging mode. It ignores real profile environment overrides and is useful for installation testing without changing the actual user's home. It does not rewrite `HOME` or `CODEX_HOME`.

## Unsupported automatic activation

Cursor can discover skill files, but its dependable all-project User Rules mechanism is account/UI-backed and file-backed global rules have version limitations. This installer does not modify private application databases or claim that copying a skill enables all-project Cursor activation.

Hosted ChatGPT/Claude web or mobile products and arbitrary closed AI applications do not share these local instruction paths. Use their supported custom-instruction, plugin, or agent integration. A universal policy format does not imply a universal installation hook.

## Preservation and removal

Setup prepares all selected changes before writing, backs up changed instruction files, and maintains a uniquely marked routing block. Repeating setup updates only that block. Malformed markers and detected conflicting edits stop installation. Backups are recovery copies, not files automatically restored over future user work.

Uninstall removes only recorded managed activation and unchanged installer-owned payload files. Modified files, user additions, manual installations, and shared payloads still referenced by other configured agents are preserved.

## Primary sources checked 2026-11-02

- Codex: [global instructions](https://learn.chatgpt.com/docs/agent-configuration/agents-md), [skill discovery](https://learn.chatgpt.com/docs/build-skills).
- Claude Code: [user memory/instructions](https://code.claude.com/docs/en/memory), [skills](https://code.claude.com/docs/en/skills), [environment overrides](https://code.claude.com/docs/en/env-vars).
- Gemini CLI: [global context](https://geminicli.com/docs/cli/gemini-md/), [skills](https://geminicli.com/docs/cli/skills/), [configuration](https://geminicli.com/docs/reference/configuration/), [global storage implementation](https://github.com/google-gemini/gemini-cli/blob/main/packages/core/src/config/storage.ts), [settings merge/parser](https://github.com/google-gemini/gemini-cli/blob/main/packages/cli/src/config/settings.ts).
- OpenCode: [rules](https://docs.opencode.ai/docs/rules/), [skills](https://docs.opencode.ai/docs/skills/), [configuration](https://docs.opencode.ai/docs/config/), [custom-directory behavior](https://github.com/anomalyco/opencode/issues/28658).
- GitHub Copilot CLI: [global instructions](https://docs.github.com/en/copilot/how-tos/copilot-cli/customize-copilot/add-custom-instructions), [skills](https://docs.github.com/en/copilot/how-tos/copilot-cli/customize-copilot/add-skills), [configuration root](https://docs.github.com/en/copilot/reference/copilot-cli-reference/cli-config-dir-reference).
- Cursor: [skills](https://cursor.com/help/customization/skills), [User Rules](https://cursor.com/docs/rules), [vendor-reported global file-rule limitation](https://forum.cursor.com/t/why-can-t-i-see-my-rules-i-have-to-go-into-the-settings-to-find-them-previously-restarting-cursor-would-make-them-load-but-now-they-simply-dont-show-up-at-all/168811/9).
