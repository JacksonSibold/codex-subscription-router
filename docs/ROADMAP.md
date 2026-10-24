# Roadmap

## Phase 1 — Working baseline (this initial commit)

- Preserve the currently working multi-subscription router.
- Include the Claude Computer Use namespace-tool bridge.
- Include Kimi K3.1 Pro through the Kimi Code membership Responses API.
- Include per-model thinking controls for Claude and OpenCode Go.
- Publish only sanitized source and example configuration.

## Phase 2 — Declarative router configuration

- Move provider, model, display-name, visibility, ordering, thinking, and tool-policy settings into a validated local settings file.
- Add safe defaults and migration from the current hardcoded catalog.
- Add atomic writes and timestamped backups.
- Add read-only validation that does not restart Codex or the router.
- Keep credentials separate from shareable model preferences.

## Phase 3 — Desktop GUI

- Provider dashboard with connection status and sign-in actions.
- Model picker customization: show/hide, rename, reorder, and choose the default.
- Thinking-level editor constrained by each model's capabilities.
- Tool-policy editor for shell, Computer Use, web search, and connected tools.
- Subagent defaults and per-model delegation policies.
- Sanitized logs and diagnostics with secret redaction.

## Phase 4 — Non-disruptive apply and lifecycle management

- Validate new settings before applying them.
- Generate a new catalog without disturbing active Codex sessions.
- Add explicit apply/reload controls rather than restarting on every edit.
- Preserve active conversations and roll back failed changes.
- Make Codex restarts optional and clearly indicated.

## Phase 5 — Packaging and contributor workflow

- Add automated tests for routing, stream translation, credentials isolation, and catalog generation.
- Add a repeatable installer and uninstaller.
- Document release versioning and changelog practice.
- Add CI for syntax, unit tests, and secret scanning.
