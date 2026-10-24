# Changelog

## 0.3.0 — 2026-10-24

- Added Relay-owned Claude PKCE OAuth, including manual authorization-code completion, refresh, and expiry handling; OpenCode is no longer required.
- Added Ollama, LM Studio, and custom loopback OpenAI-compatible model support with `/v1/models` discovery.
- Added Chat Completions and Responses protocol adapters for local models, including function tools, freeform custom tools, Computer Use namespace bridging, streaming, and token usage.
- Added a credential-free SQLite usage ledger for OpenAI, OpenCode, Claude, Kimi, local routes, and failed requests.
- Added per-account and per-model usage aggregation, daily token charts, recent-request status, and an Overview usage metric.
- Added live provider-reported subscription allowances for Codex, Claude, and Kimi, including used percentages, remaining percentages, reset times, and plan labels; OpenCode and local lanes remain token-ledger-only where no allowance API exists.
- Added provider-populated OpenAI, Claude, Kimi, and OpenCode catalogs to the Add model dropdown, with configured routes clearly marked.
- Added legacy Claude default-label normalization so any eligible Claude plan is presented as Claude without renaming custom routes.
- Added a blue interface theme across all Relay pages.
- Added stable picker route IDs with editable upstream model IDs.
- Added a grouped add-model dropdown, click-to-edit model rows, explicit Edit actions, and local endpoint/protocol editing.
- Enabled multi-agent v2 catalog entries for every eligible route and `[agents] enabled = true` in the installer, allowing cross-provider child models.
- Added usage, subscription-allowance, local-discovery, and OAuth management endpoints plus isolated development credential/usage paths.
- Added tests for OAuth, local discovery and streaming, tool translation, usage capture, allowance parsing and credential isolation, provider catalogs, upstream aliases, local routing, Kimi child routing, settings migration, and release packaging.
- Added Linux, Windows, and macOS release archives, tag-triggered publication, checksums, three-OS CI, and rendered UI checks for Overview, Models, Connections, Usage, and Capabilities.
- Updated documentation, settings examples, version metadata, and release packaging instructions for schema version 2 and version 0.3.0.
- Preserved unrelated Codex projects, plugins, providers, and credentials during installer and Apply operations.

## 0.2.0 — 2026-10-24

- Added validated, credential-free model settings with atomic saves and timestamped backups.
- Added the Relay management app for connection status, model ordering, names, visibility, defaults, thinking levels, tool policies, diagnostics, and catalog preview.
- Added a loopback management API and production static serving without requiring Vite after installation.
- Added explicit save/apply/reload behavior that preserves unrelated Codex configuration.
- Added preservation-focused default-model updates with matching per-model reasoning effort and backups.
- Added a repeatable installer, Windows launchers, isolated development homes, and provider credential isolation in development mode.
- Added Python regression tests, source/credential validation, production UI checks, rendered-page checks, and Windows CI.
- Fixed diagnostic redaction for bare `Bearer` token values.
- Fixed the installer writing an unsupported reasoning effort for the shipped default model.
- Added Windows, Linux, and macOS release archives, portable launch scripts, and three-OS CI.
- Added owner-only credential storage for Linux and macOS while retaining the Windows current-user store.
- Added release packaging tests, archive checksums, and tag-triggered GitHub publishing.

## 0.1.0 — 2026-10-24

- Imported the working local Codex subscription router.
- Added OpenAI, OpenCode Go, Claude, and Kimi Code membership routes.
- Preserved Claude Computer Use namespace-tool conversion.
- Added per-model thinking controls and Kimi K3.1 Pro catalog support.
- Added sanitized example configuration, security guidance, and GUI roadmap.
