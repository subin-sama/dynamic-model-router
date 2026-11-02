# Validation

Last checked: 2026-11-02. The repository includes a portable skill, a one-command global installer, a Codex catalog inspector, and an optional read-only parent App Server client. Installation writes persistent user-wide routing instructions for supported local agents. It does not run a background service or install a hook into the current desktop composer.

## Offline tests

**47 tests passed** on the development host using Python 3.9.6:

| Component | Tests | Coverage |
| --- | ---: | --- |
| Catalog inspector | 11 | Visibility, sparse native effort support, duplicate/malformed metadata, freshness, field filtering, CLI errors |
| RPC transport | 13 | Event-before-response ordering, concurrent IDs, bounded deadlines/cleanup, safe request rejection, EOF, bounded stderr |
| Parent client | 23 | Model/effort locks, catalog eligibility, same-thread selection/application/execution, failed turns, missing telemetry, exact turn matching, startup effort, stream cleanup |

```bash
python3 -m unittest discover -s tests -v
```

The offline tests do not call Codex or a provider. Skill-creator structural validation also passed for the skill entrypoint.

## Installation checks

### One-command installer

The Node installer has **41 passing real-filesystem tests**: 31 core preservation/ownership/CLI cases and 10 host-adapter cases. Together with the 47 Python tests, the repository has **88 offline checks**. Tests cover original bytes and file modes, Unicode/BOM/CRLF, missing final newlines, backups, idempotency, effective override files, custom profile roots, Gemini comments and context filenames, shared payloads, legacy manual copies, symlink changes, concurrent edits, rollback, safe updates, and uninstall retaining newer user edits.

An independently reviewed npm tarball was installed through `npx --package=file:... dynamic-model-router --home <staging> --agents all`. All five global instruction targets were configured with their original byte prefixes retained and one managed block each. A second run made zero changes. Packaged uninstall retained the originals and a user instruction added after installation. These are real installation/filesystem tests, not provider or model calls.

The distribution is English-only, including documentation, installer output, and test fixtures. The installer intentionally preserves non-English user instructions. No credentials, personal profile files, or raw runtime session identifiers are included in the npm payload.

Installation support is verified for the five documented adapters. It configures user-wide context; it cannot force model compliance, override managed restrictions, or install a global hook into arbitrary closed AI products. Native model/effort behavior remains separately bounded below.

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

## Independent behavioral simulation

A separate agent reviewed twelve scenarios covering ordinary work, difficult debugging, user locks, unsupported settings, unavailable switching controls, existing Gemini Auto, image eligibility, missing credentials, bounded escalation, and unsafe attempts to repeat external actions or evade host restrictions. These were reasoning simulations, not runtime tests.

## Limits

- The parent prototype is a separate read-only text client. It does not make an existing Codex desktop chat switch automatically after skill installation, and is not a full coding client.
- Settings apply between turns, not to a request already in flight.
- Runtime verification establishes Codex's resolved settings, not independent provider-side backend attestation.
- No quality, latency, or cost improvement has been measured. Parent routing adds a selection turn per task; worker overhead is not always worthwhile.
- Claude Code and Gemini CLI guidance was checked against official documentation only. Account/version/organization capabilities must be discovered on the recipient's host.
- macOS was live-tested. POSIX process-group cleanup has an offline test; Windows cleanup covers the direct server only and has no live Windows validation.
