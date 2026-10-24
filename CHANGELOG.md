# Changelog

## Unreleased

- Added validated, credential-free model settings with atomic saves and timestamped backups.
- Added the Relay management app for connection status, model ordering, names, visibility, defaults, thinking levels, tool policies, diagnostics, and catalog preview.
- Added a loopback management API and production static serving without requiring Vite after installation.
- Added explicit save/apply/reload behavior that preserves unrelated Codex configuration.
- Added preservation-focused default-model updates with matching per-model reasoning effort and backups.
- Added a repeatable installer, Windows launchers, isolated development homes, and provider credential isolation in development mode.
- Added Python regression tests, source/credential validation, production UI checks, rendered-page checks, and Windows CI.
- Fixed diagnostic redaction for bare `Bearer` token values.
- Fixed the installer writing an unsupported reasoning effort for the shipped default model.

## 0.1.0 — 2026-10-24

- Imported the working local Codex subscription router.
- Added OpenAI, OpenCode Go, Claude Pro, and Kimi Code membership routes.
- Preserved Claude Computer Use namespace-tool conversion.
- Added per-model thinking controls and Kimi K3.1 Pro catalog support.
- Added sanitized example configuration, security guidance, and GUI roadmap.
