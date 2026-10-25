# Changelog

## 1.0.1 — 2026-10-24

- Fixed Windows Codex configuration updates so backslashes in `model_catalog_json` are written literally and the resulting TOML re-parses successfully.
- Fixed generated and custom Relay catalog entries so every non-OpenAI route carries `base_instructions`, uses direct tool mode, and avoids Responses-lite parsing. This prevents Codex from rejecting the mixed catalog at startup.
- Expanded release verification so an archive fails if any generated catalog entry lacks Codex instruction metadata.
- Re-verified the installed Windows build with a live Codex request through the default Relay route.

## 1.0.0 — 2026-10-24

- Promoted Relay to the 1.0 release line with one version source shared by Python, the manager API, the UI build, package metadata, archives, and release validation.
- Fixed the catalog generator so custom or edited OpenAI and OpenCode upstream IDs are included even when they are absent from `models_cache.json` or `opencode-go-models.json`; every visible route on an enabled provider now receives provider-appropriate catalog metadata.
- Expanded cross-provider verification to cover OpenAI, OpenCode, Claude, Kimi, and local child routes, including edited upstream IDs and credential isolation.
- Updated the Usage page to track connected provider accounts and each configured local endpoint even when they have zero requests, aligned inventory with the exact routed-ledger labels, and retained historical account labels after disconnect or removal.
- Kept Codex, Claude, Kimi, and OpenCode account inventory separate from live subscription percentages, so unsupported allowance APIs remain clearly ledger-only; unexpired legacy OpenCode Anthropic tokens can also populate Claude allowances.
- Made Claude adapter headers report the actual host OS and CPU architecture, including macOS Apple Silicon, Linux x64, and Windows.
- Fixed development credential status so keys entered into Relay's isolated development store are detected without reading live user credentials.
- Added a packaged-archive launch and installer test that extracts each release, starts its manager and router in an isolated home, verifies version, launchers, static UI, API, provider catalog, usage inventory, and router health, then installs into a temporary Codex home and checks preserved configuration.
- Added Python 3.11 compatibility CI, three-platform package smoke tests, tag/version enforcement, executable-mode checks, release notes, and post-publication download/checksum verification.
- Updated documentation and release instructions for the portable Windows, Linux, and macOS 1.0 archives.

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
