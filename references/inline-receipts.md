# Native inline routing receipts

Use this recipe only when the current host exposes its native graphical rendering workflow. It adds a presentation layer to the same routing decisions and evidence rules. It does not switch models, subscribe to runtime events, or patch the application.

## Presentation and data

`scripts/render_receipt.py` uses the bundled `assets/receipt.html` template. Python 3.9+ is needed for this optional helper; the installer itself still only needs Node.js. Provide a JSON receipt, choose the host, and write a **new** HTML path for each meaningful snapshot:

```bash
python3 scripts/render_receipt.py --host codex --input receipt.json --output /authorized/thread/path/routing-receipt-example.html
```

The helper prints reference metadata; the assistant must publish it through the host's actual response workflow. A successful file write is not proof that a native frame rendered.

For example, `receipt.json` can contain:

```json
{
  "status": "unchanged",
  "scope": "parent",
  "model": null,
  "effort": null,
  "reason": "Continue with inherited host settings."
}
```

Optional `labels` overrides use `routing`, `parent`, `worker`, `external`, `model`, `effort`, `not_exposed`, `evidence`, `snapshot`, and the seven status keys. Omitted labels stay in English; the calling agent supplies translations when needed.

Keep the receipt compact: status, actual execution scope, exact model/native effort, one short reason, and any evidence qualifier. The status values are `recommended`, `requested`, `applied`, `verified`, `unchanged`, `unverified`, and `error`. Use `parent`, `worker:name`, or `external:name` for scope. Unknown settings stay null; the card displays a localized "not exposed" label. Label overrides and the reason can follow any user language without translating model IDs or native effort values.

`verified` needs an explicit model and evidence text. Evidence text remains visible, including a model-variant-only or catalog-mapped effort qualifier. The helper validates presentation input; it cannot independently authenticate the caller's evidence. A completed answer or an animated card never verifies runtime settings.

All markup data is escaped. The component uses local CSS, a bounded entry transition and hover interaction, and reduced-motion handling. It has no network requests, external fonts, polling, simulated percentage, model switch button, or automatic status progression. A card is a snapshot, not a live connection. Do not overwrite a file already embedded and assume the host will refresh it.

## Codex desktop

1. Check for the host's first-party `visualize` skill and follow its current contract. Graphical availability does not imply that Codex CLI or an IDE extension can render the same surface.
2. Select an explicitly writable task-owned path, preferably the thread visualization root exposed in the environment. Use a lowercase kebab-case HTML basename and do not hardcode another user's home or thread ID.
3. Render with `--host codex`. This emits an HTML **fragment**, not a document wrapper.
4. Publish the native visualization reference in the response phase permitted by the host. The installed first-party workflow uses this final-response reference on its own line:

```text
visualize{"path":"/authorized/thread/path/routing-receipt-example.html"}
```

When the contract permits references only in the final response, use the compact text receipt at task start and the native card for the final evidence/outcome. Do not open a separate browser window. A same-window side panel is a fallback only when the user accepts it; it is different from an inline message.

## Antigravity App

1. Check for the App's built-in `generative_ui` skill and follow its current artifact workflow. The App can activate this skill from the task or applicable instructions without requiring the user to type `/generative_ui` each time.
2. Render with `--host antigravity` to a scratch path. This emits a self-contained HTML document.
3. Use the App's native artifact-writing tool to publish that HTML in the **current conversation's artifact directory**, with `ArtifactMetadata.UserFacing: true`. A shell-created file alone does not establish native artifact registration. Do not guess or reuse another conversation's directory.
4. Embed the actual registered artifact in the assistant response:

```html
<agent-embed src="file:///actual/conversation/artifact-directory/routing-receipt-example.html"></agent-embed>
```

Keep it compact enough for the App's 500px inline frame, with a transparent outer surface and no viewport-height layout. The host supplies theme variables. The card stays inside the existing conversation; opening its artifact card in the side panel is optional.

The CLI cannot display these widgets. The inspected standalone IDE's native agent transcript has no established equivalent renderer contract here; use the text fallback unless that exact host exposes one. A standard VS Code webview is a separate editor view and must not be described as an inline chat message.

## Activation, updates, and fallback

The global installer distributes the renderer, template, and this recipe to installer-owned skill copies. It preserves manual installations; if a reused manual copy lacks these new files, use its existing update mechanism or retain the text fallback. Do not overwrite user files to force rich presentation.

Applicable instructions request the native card when supported. They are not a guaranteed always-on event hook. Existing chats may need to reload instructions, and model compliance remains a separate check. If artifact creation, native embedding, or rendering fails, report that limitation and use the compact text receipt. Never relabel a failed rendering attempt as a verified model change.

Sources checked 2026-11-04:

- [OpenAI visualizations](https://learn.chatgpt.com/docs/visualizations)
- [OpenAI artifact viewer](https://learn.chatgpt.com/docs/artifacts-viewer)
- [Antigravity generative UI](https://antigravity.google/docs/commands/generative-ui)
- [Antigravity customization discovery](https://antigravity.google/docs/customization-discovery)

The exact native contracts were also checked against the installed first-party Codex visualization skill and Antigravity App 2.29.0's built-in generative UI skill. No proprietary implementation text is included in this package.
