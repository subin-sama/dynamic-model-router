# Match the requested output to an available interface

Use this workflow when the task needs a specific tool or output modality, especially when the current chat cannot perform it. The hosting agent identifies the requirement from the user's request; the helper does not guess task meaning from a keyword. Creating an image, editing an image and describing an attached image are different requirements.

## Gather current evidence

Run the normal provider discovery first. Inspect the current host's callable tools, connected plugins and native capability catalogs. Do not scan credentials, dump MCP environment values, or run a paid inference just to populate a menu. Reuse a current snapshot; refresh when the host, tools, provider versions or availability change.

Claude Code's [native activation hook](claude-activation.md) can supply this machine snapshot before the model responds. Use it alongside current-host tool discovery; MCP tool search alone is not a local-provider inventory. A failed search does not prove missing authentication. When no generator is callable but an installed provider advertises image support, present a clearly labeled handoff possibility and its missing bridge instead of treating the provider as absent or recommending unrelated setup.

Codex's native `modelProvider/capabilities/read` can advertise provider-level image generation without starting a model turn. It does not identify the image backend, prove access on every model, or implement an artifact adapter. Older clients may not support this metadata method; unknown stays unknown. A model catalog's image input modality and a CLI's `--image` attachment flag do not establish image output.

The cross-provider text adapters return **text only**. Their model catalogs are useful for text delegation, not a list of image generators. The separate [Codex image bridge](codex-image-bridge.md) implements a native image artifact path with explicit selection and independent output checks. Probe that bridge before treating it as eligible; its presence does not establish account access. A native or connected tool must expose the required operation and a usable output path. A chat hosted by Claude can have such a tool through a connector; do not exclude it solely because the language model does not itself emit pixels.

## Export a host-tool snapshot

The helper cannot see another app's runtime tools. The hosting agent must export only interfaces it actually sees in a current tool schema or native tool catalog. Keep this per-run data outside the installed/distributed skill. Example shape, with illustrative IDs:

```json
{
  "schema_version": 1,
  "tools": [
    {
      "id": "host-image-tool",
      "provider": "provider-id",
      "tool": "actual_callable_tool_name",
      "model": null,
      "capabilities": ["image_generation", "image_editing"],
      "available": true,
      "execution_mode": "native_tool",
      "evidence": {"kind": "host_tool_schema", "source": "Current host tool definition"}
    }
  ]
}
```

Supported capability IDs are `text_generation`, `image_generation`, `image_editing`, `vision`, `audio_generation`, `audio_transcription`, and `video_generation`. Declare only operations supported by the actual schema. Native effort values, costs, quotas and exact image-model IDs must not be invented when unexposed. Additional requirements such as transparency, reference-image support or a particular output format still need checking against the selected tool's schema.

Tool routes use `native_tool` or `external_tool`, with explicit available status and evidence kind `host_tool_schema`, `native_tool_catalog`, or `runtime_observation`. An external route must have an existing supported bridge; another app being installed is insufficient. Known missing authentication or hidden/unavailable interfaces are excluded. Tool authentication is scoped separately from the same provider's unrelated text CLI login. The helper treats snapshots as caller-supplied evidence, not cryptographic attestation. It never executes a tool name, URL, command or argument supplied in a manifest.

## Filter and choose

Resolve `SKILL_DIR` to the installed skill and use the current machine's inventory:

```sh
python3 "$SKILL_DIR/scripts/cross_cli_router.py" capabilities \
  --inventory work/providers.json --required image_generation \
  --host-tools work/host-tools.json --output work/image-options.json
```

The output is a recommendation with `runtime_verified: false` and `dispatch_authorized: false`:

- `choice_required`: multiple distinct qualified interfaces. Localize the options and ask the user to choose; send no generation request while waiting.
- `ready`: one interface, or an explicit compatible candidate/provider/model selection resolved the menu. This means eligible for the hosting agent to resolve, not account-access tested or already executed.
- `blocked`: no eligible interface or the explicit selection conflicts with requirements. Show the exclusions and any discovery-only native metadata. A text prompt, SVG/code proposal, or unsupported provider cannot silently replace a requested generated image.

Each option should name its provider, actual tool/channel, exposed model (or "not exposed"), and relevant access/evidence limits. Two observations of the same route are not two image models. Do not manufacture a model ranking or infer a backend model from the tool's branding. A missing adapter, login requirement or unreachable app should be listed separately from usable choices.

After the user chooses, resolve the exact candidate again:

```sh
python3 "$SKILL_DIR/scripts/cross_cli_router.py" capabilities \
  --inventory work/providers.json --required image_generation \
  --host-tools work/host-tools.json --candidate SELECTED_ID
```

`--provider` and `--model` constrain the menu independently. An exact model lock cannot match a tool that hides its backend model. `plan --requires image_generation` (or `--task-kind image_generation`) uses the same filter instead of ranking text models. Tool routes do not accept fabricated reasoning-effort controls.

The helper never calls the generator. The hosting agent invokes the selected **currently exposed** tool through its own supported API, within the original task's authorization and the tool's instructions. Recheck authentication, required inputs, output format and artifact result. If this host cannot invoke a tool in another app, explain that missing bridge and offer a concrete handoff; do not promise automatic cross-app generation. The existing `run --execute` command deliberately rejects capability/tool plans and non-text requirements before starting a process.

For example, when a Claude-hosted task asks for an image, discover its connected image tools first, then other reachable routes. If two image tools qualify, ask which to use. If only a Codex provider capability flag is visible but no callable image interface is available in that host, report it as discovery-only and explain the required handoff or integration. Do not dispatch to an arbitrary Claude/Codex/Antigravity text model and claim that an image was generated.

## Evidence and validation

Keep discovery, choice, invocation, runtime settings, generated artifact and artifact quality as separate outcomes. The deterministic chooser tests prove filtering and selection behavior; metadata probes prove only the advertised capability. A real generation test needs an authorized request and an actual image/audio/video artifact. Do not generate sample media merely because this workflow is being configured.
