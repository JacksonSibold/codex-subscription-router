# Roadmap

## Phase 1 — Working baseline

- [x] Preserve the multi-subscription Responses router.
- [x] Include the Claude Computer Use namespace-tool bridge.
- [x] Include Kimi K3.1 Pro through the Kimi Code membership Responses API.
- [x] Include per-model thinking controls for Claude, Kimi, and OpenCode Go.
- [x] Publish only sanitized source and example configuration.

## Phase 2 — Declarative router configuration

- [x] Move provider, model, display name, visibility, ordering, thinking, and tool-policy preferences into a validated local file.
- [x] Provide safe defaults and migration from the original hardcoded catalog.
- [x] Add atomic saves and timestamped backups.
- [x] Add isolated validation that does not restart Codex or the router.
- [x] Keep credentials separate from shareable model preferences.
- [x] Separate stable picker route IDs from editable upstream model IDs.

## Phase 3 — Relay desktop GUI

- [x] Provider dashboard with connection status and sign-in actions.
- [x] Grouped add-model dropdown and click-to-edit existing rows.
- [x] Model show/hide, rename, order, remove, route ID, upstream ID, and default selection.
- [x] Thinking-level editor constrained by each model's capabilities.
- [x] Tool-policy editor for shell, Computer Use, web search, and connected apps.
- [x] Cross-provider subagent catalog controls.
- [x] Usage dashboard with account, model, daily, and recent-request views.
- [x] Sanitized logs and diagnostics with secret redaction.
- [x] Responsive production UI served directly by the local manager.

## Phase 4 — Non-disruptive apply and lifecycle management

- [x] Validate new preferences before applying them.
- [x] Generate a new catalog without restarting Codex.
- [x] Provide explicit save and apply/reload controls.
- [x] Preserve unrelated projects, plugins, providers, and credentials in `config.toml`.
- [x] Enable Codex agents while preserving other `[agents]` settings.
- [x] Update the selected default model and its own reasoning effort without restarting Codex.
- [x] Keep active Codex conversations running; picker changes may appear in new chats.
- [ ] Add automatic transactional rollback across settings, catalog, and config updates.
- [ ] Add an explicit one-click rollback UI for timestamped backups.

## Phase 5 — Packaging and contributor workflow

- [x] Add automated Python tests for settings, routing, OAuth, local adapters, usage, stream translation, Computer Use, tool policies, installer merging, Apply safety, diagnostics, and catalog generation.
- [x] Add isolated rendered-UI checks for Overview, Models, Connections, Usage, and Capabilities.
- [x] Add a repeatable installer with backups and preservation-focused Codex configuration merging.
- [x] Add Windows, Linux, and macOS CI for unit tests, source validation, production build, and rendered UI.
- [x] Add allowlisted release archives, portable launchers, checksums, and tag-triggered GitHub publishing.
- [x] Add protected current-user credential storage for Linux and macOS.
- [ ] Add a dedicated uninstaller with preview and rollback support.
- [x] Formalize release versioning and changelog practice for `1.0.0`.
- [ ] Add signed and notarized native installers.

## Phase 6 — Accounts, local models, and delegation

- [x] Add Relay-owned Claude PKCE OAuth without requiring OpenCode.
- [x] Add Claude token refresh and expiry status.
- [x] Add Ollama/LM Studio/custom loopback model discovery and editing.
- [x] Add OpenAI Chat Completions and Responses local protocol adapters.
- [x] Add streaming function/custom-tool and Computer Use translation for local models.
- [x] Add usage capture across every connected provider/account and local endpoint.
- [x] Add a credential-free local usage ledger and UI.
- [x] Add live Codex, Claude, and Kimi subscription allowance cards with reset times.
- [x] Populate Add model with OpenAI, Claude, Kimi, and OpenCode provider catalogs.
- [x] Refresh and search every active connected-account catalog, with cached/fallback behavior for provider outages.
- [x] Link the Codex installation on this PC from Connections while preserving unrelated configuration.
- [x] Apply the blue Relay interface theme.
- [x] Enable any eligible model as a cross-provider child-agent target.
- [x] Ship Windows, Linux, and macOS release archives for `1.0.0`.

## Phase 7 — Relay 1.0 acceptance

- [x] Audit every requested account, model, OAuth, usage, local-model, delegation, theme, and packaging behavior.
- [x] Include arbitrary custom/edited provider model IDs in generated catalogs.
- [x] Show connected accounts with zero routed requests and keep historical ledger labels.
- [x] Verify all five provider lanes can serve as parent or child routes under catalog eligibility rules.
- [x] Centralize the release version across Python, UI metadata, health/state APIs, archives, CI, and documentation.
- [x] Test packaged manager/router startup from Windows, Linux, and macOS archives.
- [x] Publish downloadable checksums and verify the published assets after release.
- [x] Draft complete 1.0.0 release notes with honest archive and compatibility limits.

## Post-1.0

1. Implement automatic rollback and a backup browser.
2. Add a tested cross-platform uninstaller that never deletes provider credential stores.
3. Add optional OS keychain integration for Relay credentials.
4. Add signed and notarized native installers.
5. Expand opt-in live compatibility tests for local servers and provider-specific Computer Use.
