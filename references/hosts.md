# Host adapters

Read only the relevant host section. Live instructions, tools, versions, and supported values take precedence over these examples. These notes do not grant new controls or permissions.

## Codex

Inspect collaboration tools and configured custom agents. Model/effort overrides may be exposed but restricted by policy. Some hosts require fresh child context for an override; others expose configured agent types. Follow the actual schema rather than assuming a `spawn_agent` signature. Prefer native workers for bounded units when model settings are selectable. If they inherit settings only, report inheritance.

For a local planning inventory, run `python3 scripts/inspect_models.py`; `--catalog PATH` reads another Codex-format catalog. `--model ID --effort LEVEL` checks an exact advertised pair. This read-only cache check is not a server validation, entitlement check, ranking, or launcher. It excludes hidden models. A cache from a different client may advertise settings the destination client cannot use. Never use it for another provider.

If the user authorized an external Codex run and host rules allow it, check `codex exec --help` first. Documented selection uses `codex exec --model MODEL -c 'model_reasoning_effort="LEVEL"'`. Transfer context explicitly. Retain applicable sandbox and approval boundaries; do not add bypass flags or use a new process to evade native restrictions.

No general control to change the current Codex response in flight is assumed. Use advisory mode when no permitted control exists. Do not modify global `config.toml` during ordinary routing.

For explicitly requested parent routing, this package includes an optional **user-launched, read-only text prototype**: [codex-parent-router.md](codex-parent-router.md). It runs one parent thread through a separate App Server client, lets the parent select each next execution pair, and applies the choice between turns. It does not install a hook into an existing desktop chat. Do not launch it recursively as a workaround from a restricted agent.

Local skill discovery is documented under `.agents/skills` for repository/user scopes; some installations also expose configured Codex-home directories. Install once in a location the recipient's client discovers.

Sources checked 2026-11-02:

- [Skills and discovery](https://learn.chatgpt.com/docs/build-skills)
- [Custom agents and reasoning](https://learn.chatgpt.com/docs/agent-configuration/subagents)
- [Model reasoning configuration](https://learn.chatgpt.com/docs/config-file/config-reference)
- [CLI reference](https://learn.chatgpt.com/docs/developer-commands?surface=cli)

## Claude Code

Claude Code documents `model` and `effort` skill frontmatter. These overrides apply for the remainder of the current turn; `context: fork` scopes them to a child instead. They are supported host metadata, not an effect of writing "think harder" in the skill body. This portable skill intentionally leaves those fields unset so it does not pin every task to one static pair.

Prefer the exposed Agent tool or existing configured profiles for dynamic selection. Inspect the actual schema: per-invocation model overrides can accept a narrower alias set than subagent definitions. Per-invocation effort for non-fork subagents is documented for v2.1.292+; older clients may not support it. Configured subagents can also declare model and effort. Environment settings and organization model/effort limits can override selections. Use runtime task information (such as `/tasks`, when available) to verify effective settings.

User-facing `/model`, `/effort`, `--model`, and `--effort` are documented controls; their presence in the UI does not make them callable tools. Interactive `/model <name>` can save a user default. Avoid changing persistent defaults for routing; use supported session-only selection or workers. A newly selected effort may take effect on the next message. Confirm model-specific levels in the installed client rather than sending Codex labels.

For profile-based routing, select an already configured profile with a valid local pair. A fixed frontmatter field is not a dynamic classifier. Do not rewrite the active skill to make its static metadata conditional, or manufacture tool arguments not exposed by the host.

Personal skills live at `~/.claude/skills/<name>/SKILL.md`; project skills at `.claude/skills/<name>/SKILL.md`. The portable skill policy can be installed unchanged; native overrides still depend on the installed version/tools.

Sources checked 2026-11-02; CLI execution not tested:

- [Skills and frontmatter](https://code.claude.com/docs/en/skills)
- [Model and effort configuration](https://code.claude.com/docs/en/model-config)
- [Subagent controls](https://code.claude.com/docs/en/sub-agents)

## Gemini CLI

Gemini CLI's model picker offers a built-in **Auto** mode that routes by task complexity. Prefer it when it meets the user's goal. Discover available models/account options from the installed client. A manual `/model` command is user-facing unless an actual callable control exists. If Auto is already selected, retain it and use this skill for phase/evidence/verification discipline rather than a second competing model router.

Reasoning configuration differs from Codex and Claude. Gemini CLI documents `modelConfigs.customAliases` and `modelConfigs.overrides`; overrides can match model/agent scope per request. Nested `generateContentConfig.thinkingConfig` is provider-native configuration. Supported thinking fields and values vary by selected model and client; an API budget or thinking level is not automatically a tool-accessible CLI effort setting. Do not invent a universal `effort` parameter.

Custom agent frontmatter supports `model`, with inheritance when omitted; the documented schema does not establish an `effort` field. Agent-scoped generation overrides are another configured control. Do not invent per-call arguments or nested subagent routing. Do not rewrite global settings merely to enable this workflow. Without exposed controls or existing profiles, report native Auto/default reasoning or advisory mode accurately.

User skill locations include `~/.gemini/skills` and `~/.agents/skills`; project locations include `.gemini/skills` and `.agents/skills`. Within the same tier the `.agents` alias takes precedence. `gemini skills install` supports repositories/local directories. Skill activation is through the host's consent flow; the skill cannot bypass it.

Sources checked 2026-11-02; CLI execution not tested:

- [Model selection and Auto](https://geminicli.com/docs/cli/model/)
- [Generation settings](https://geminicli.com/docs/cli/generation-settings/)
- [Subagents](https://geminicli.com/docs/core/subagents/)
- [Skills](https://geminicli.com/docs/cli/skills/)

## API agents and other hosts

Use an existing authorized controller, not a new undeclared API client. Before each new request/work unit, select a model and only provider-native reasoning fields supported by that exact endpoint/model. The skill does not contain an API gateway, proxy, background service, or API credentials.

A model-list response commonly establishes IDs, not full modality/tool/reasoning support or pricing. Use current endpoint schemas, official model documentation, or the controller's validated registry. Do not infer identical effort semantics across providers. Configuring a future request does not alter an in-flight request.

If a controller exposes per-turn settings, apply them at the documented boundary and record reported effective settings when available. OpenAI's separate Agents API documents session updates that apply to later turns; this does not establish an equivalent tool in a Codex chat.

- [OpenAI agent session configuration](https://developers.openai.com/api/docs/guides/agents-api/configuration)
