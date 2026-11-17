# Create a native Codex image from Claude Code

Use this bridge when the current host can execute local Python commands and the user wants an image through Codex. It uses the installed Codex App Server and its native image tool; it does not ask a text CLI to pretend to produce an image, call an unrelated generator, or change the current Claude parent model.

## Discover and choose

Resolve `SKILL_DIR` to this installed skill. The Claude native hook supplies `image_bridge.script` when the bundled script and local Codex CLI are present. Presence is not account access or successful generation. Check the actual native prerequisites without inference:

```sh
python3 "$SKILL_DIR/scripts/codex_image_bridge.py" probe
```

Runtime discovery checks PATH and supported system/user macOS Codex or ChatGPT application bundles, using bounded read-only version commands. It selects the newest detected compatible native protocol. `--codex /absolute/path/to/codex` on `probe` and `prepare` pins an explicit runtime instead. The pending ticket binds its resolved executable, version and identity fingerprint; replacement or an App update requires resolving that prerequisite before a new invocation. Several installations of Codex are not several image backends.

Use the returned route evidence. Keep the Codex chat model separate from the image backend; a hidden image backend stays "not exposed". A capability advertisement or image-input modality alone cannot establish a working generator. Respect configured model/effort choices; resolve an incompatible default explicitly instead of silently changing it.

An App's configured default can be absent from another installed CLI's catalog. If the current request has no conflicting explicit lock, the hosting router can choose a catalog-supported coordinator and its native effort for this separate image worker. Pass that pair to `probe` and `prepare` using `--model` and `--effort`, show it as the worker's coordinator settings, and retain the global defaults. Preparation binds the pair to the ticket; generation cannot replace it with another pair. An incompatible explicit user lock remains a blocker. Coordinator choices are not additional image backends.

Prepare the exact requested image in a new local request file:

```sh
python3 "$SKILL_DIR/scripts/codex_image_bridge.py" prepare \
  --prompt "The user's requested image" --request-file work/image-request.json
```

Preparation sends no inference and creates no image. Show the qualified Codex route alongside any other genuinely callable image routes, including their access limits. Ask the user to select before invoking this cross-provider bridge unless their current instruction already explicitly selected it. A request to choose first applies even when Codex is the only eligible route. Offer cancellation separately; a Cancel option does not count as a second image generator. Do not invent extra models or providers to fill a menu.

Use the host's native question tool when available, or ask a short question in chat and wait for the reply. Never interpret silence, an option being displayed, or a prepared request as a selection. A headless test may supply a clearly labeled operator selection under its authorized protocol; that is not a saved user preference.

## Execute only the selected request

After the user's compatible selection, run the exact prepared request:

```sh
python3 "$SKILL_DIR/scripts/codex_image_bridge.py" generate \
  --request-file work/image-request.json --selected-route codex-native-image \
  --output work/generated-image.png --execute
```

When invoking through a host shell tool, give that tool a timeout longer than the bridge deadline: the default native deadline is 240 seconds, so allow at least 270 seconds in the outer tool. An explicit `--timeout 300` needs an outer timeout above 300 seconds. Otherwise the host can terminate a valid generation before its native result is collected.

The explicit route and execution switch are required. They record the caller's selected route; they are not cryptographic proof that a human selected it. The hosting agent remains responsible for honoring the actual conversation. Request state prevents replay after an invocation has started. Do not silently prepare a new request or retry a generation after timeout/failure; first report the outcome and retain the original choice and evidence.

Cancel a pending request without invoking a provider:

```sh
python3 "$SKILL_DIR/scripts/codex_image_bridge.py" cancel --request-file work/image-request.json
```

The bridge starts an isolated native run, with unrelated integrations disabled where supported and server approval requests declined. It accepts matching native image-generation results, decodes and validates image bytes, and writes a new artifact without overwriting an existing file. It does not accept an assistant claim, Markdown URL, arbitrary saved-path read, or code drawing as proof of native image generation.

## Check and deliver

Optional `--evidence-file NEW_FILE` or `DYNAMIC_MODEL_ROUTER_IMAGE_EVIDENCE_FILE` enables private native evidence for a requested test. It records matching event identities, artifact hashes and bounded public worker messages, including failures; it excludes reasoning, authentication data and image payloads. It is off by default. A failure does not unconsume a request or authorize a replay.

Current native image items may provide inline bytes or a durable file reference. The bridge prefers inline bytes. A file reference requires the matching native item's saved path inside the active thread's `CODEX_HOME/generated_images` directory, with no symlinks and bounded PNG validation. An opaque remote file ID alone remains unresolved; do not invent a download endpoint.

Inspect the returned image file and show it through this host's normal image/file presentation. Use the complete actual artifact path when the host needs a local file; do not abbreviate it with ellipses. Keep these claims separate: discovery eligibility, user selection, native invocation, matching image item, validated artifact, and visual quality. A valid PNG and native completion establish an actual output, not that every visual detail satisfies the prompt. Do not claim an image backend model or native reasoning value that was not reported.

This bridge currently covers text-to-image output. Reference-image editing, transparency controls, exact resolution, alternative backends and Windows live provider execution require their own supported controls and tests; do not infer them from general Codex image support.
