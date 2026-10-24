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

## Phase 3 — Relay desktop GUI

- [x] Provider dashboard with connection status and sign-in actions.
- [x] Model customization: show/hide, rename, reorder, add/remove, and choose the default.
- [x] Thinking-level editor constrained by each model's capabilities.
- [x] Tool-policy editor for shell, Computer Use, web search, and connected apps.
- [x] Per-model subagent catalog controls.
- [x] Sanitized logs and diagnostics with secret redaction.
- [x] Responsive production UI served directly by the local manager.

## Phase 4 — Non-disruptive apply and lifecycle management

- [x] Validate new preferences before applying them.
- [x] Generate a new catalog without restarting Codex.
- [x] Provide explicit save and apply/reload controls.
- [x] Preserve unrelated projects, plugins, providers, and credentials in `config.toml`.
- [x] Update the selected default model and its own reasoning effort without restarting Codex.
- [x] Keep active Codex conversations running; picker changes may appear in new chats.
- [ ] Add automatic transactional rollback across settings, catalog, and config updates.
- [ ] Add an explicit one-click rollback UI for timestamped backups.

## Phase 5 — Packaging and contributor workflow

- [x] Add automated Python tests for settings, routing, stream translation, Computer Use, tool policies, installer merging, Apply safety, diagnostics, and catalog generation.
- [x] Add isolated rendered-UI checks for all main pages.
- [x] Add a repeatable installer with backups and preservation-focused Codex configuration merging.
- [x] Add Windows CI for unit tests, source validation, production build, and rendered UI.
- [ ] Add a dedicated uninstaller with preview and rollback support.
- [ ] Formalize release versioning and changelog automation.

## Next

1. Implement automatic rollback and a backup browser.
2. Add a tested uninstaller that never deletes provider credential stores.
3. Add opt-in live compatibility tests that use temporary homes and mock upstream responses.
4. Expand provider-specific Computer Use and connected-tool capability reporting.
