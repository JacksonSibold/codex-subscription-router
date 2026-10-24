# Codex Subscription Router

A local Windows router that lets one Codex model picker use multiple existing coding subscriptions while keeping each provider's credentials on its own route.

> **Project status:** validated router, declarative settings, Relay management app, installer, and contributor CI are implemented. Automatic rollback and a dedicated uninstaller remain future work.

This is an independent local project, not an OpenAI, Anthropic, Kimi, or OpenCode product.

## What it does

- Presents OpenAI, OpenCode Go, Claude Pro, and Kimi Code models through one Codex provider.
- Keeps each provider's credentials on its own upstream lane.
- Generates an ordered Codex model catalog from credential-free local preferences.
- Provides a loopback-only Relay app for connection status, model customization, tool policies, diagnostics, and explicit apply.
- Validates changes and creates timestamped backups before replacing settings or Codex top-level model keys.
- Avoids restarting Codex during ordinary save, apply, and router-reload operations.

## Providers

| Provider | Model source | Authentication | Thinking controls |
| --- | --- | --- | --- |
| OpenAI | GPT models selected in the router | Existing Codex / ChatGPT sign-in; credentials are forwarded only to OpenAI | Native Codex support |
| Claude Pro | Claude Sonnet 5.5 and Opus 5.5 | Anthropic OAuth already connected in OpenCode | Low, medium, high, xhigh, max |
| Kimi Code membership | Kimi K3.1 Pro | `KIMI_API_KEY` from the Kimi Code Console | Low, high, max |
| OpenCode Go | Configurable catalog entries | `OPENCODE_API_KEY` | Per-model levels from OpenCode capability metadata |

The router listens only on `127.0.0.1:18765`. Codex uses its normal Responses API protocol for OpenAI, OpenCode Go, and Kimi. A local adapter translates Claude requests between Responses and Anthropic Messages formats.

## Relay management app

Relay includes:

- Overview with provider routes, credential-presence status, and picker summary.
- Official Codex and OpenCode sign-in actions, plus write-only Kimi and OpenCode API-key forms.
- Model search, show/hide, drag ordering, accessible ordering controls, renaming, add/remove, and default selection.
- Per-model thinking levels and shell, Computer Use, web-search, connected-app, and subagent-catalog policies.
- Generated-catalog preview, capability matrix, sanitized diagnostics, and safe settings export.
- A production static build served by the local manager, so Vite is not required after installation.

Credential-found status means a local store or environment entry was found. It is not a billed inference test.

## Tool support

- **OpenAI:** native Codex tools and connected-app behavior remain on the OpenAI route.
- **Claude:** shell/function tools work. The adapter maps the Codex `mcp__node_repl` and `mcp__cua_repl` namespace groups so Claude can use Computer Use. Large connected-app namespaces remain excluded.
- **Kimi and OpenCode Go:** shell/function tools work. OpenAI-only connected-app namespaces and hosted web-search declarations are removed before forwarding.
- **Thinking:** the generated catalog exposes only effort levels configured for each model.
- **Subagents:** the setting controls Codex's multi-agent catalog flag; it is not a separate router-level permission system.

Broader Computer Use parity and provider-specific compatibility still vary by upstream model. The router does not claim that every provider supports every OpenAI-only tool.

## Development preview

Requirements:

- Windows 11
- Python 3.11 or newer
- Node.js 20 or newer
- Codex Desktop / CLI
- Existing subscriptions and provider authorization for the routes you enable

From the project root:

```powershell
cd app
npm ci
npm run dev
```

The logical preview URL is `http://localhost:7100/`. Development mode uses the repository's `.dev-codex` directory by default. It never writes the live Codex configuration, never inspects the live Codex or OpenCode credential stores, and never signals a live router to reload.

Run the local checks:

```powershell
cd ..
python -m unittest discover -s tests -v
python scripts/validate.py
git diff --check
cd app
npm run build
npm run test:ui
```

The rendered UI check writes screenshots to `artifacts/` and stops its child processes when it finishes.

## Installing into Codex

> **Explicit action required:** installation writes beneath the selected Codex home and may merge `config.toml` when `--configure-codex` is supplied. Back up and review your configuration first. Development and test commands do not perform installation.

Build the interface, then run the installer from the project root:

```powershell
cd app
npm ci
npm run build
cd ..
python scripts/install.py --configure-codex
```

By default, the installer:

- Copies router Python files and the production UI to `%USERPROFILE%\.codex\model-router`.
- Copies `Start Router.cmd` and `Start Relay.cmd` to `%USERPROFILE%\.codex`.
- Copies the OpenCode catalog and generates `%USERPROFILE%\.codex\mixed-models.json`.
- Preserves an existing router settings file; defaults are created only when absent.
- Creates timestamped backups before replacing installed files or changing `config.toml`.
- Merges the `mixed` provider, desktop reasoning choices, default model, and that model's default reasoning effort into existing Codex configuration without removing unrelated projects, plugins, or provider settings.
- Does not restart Codex or a running router.

Start the router when convenient, then open Relay:

```powershell
& "$HOME\.codex\Start Router.cmd"
& "$HOME\.codex\Start Relay.cmd"
```

`Start Relay.cmd` opens the local management page at `http://127.0.0.1:18766/`. Use `--codex-home <path>` for an isolated installation target during testing; do not point guided tests at the live home.

## Apply and rollback behavior

- **Save** validates and atomically replaces credential-free router preferences with timestamped backups.
- **Save & apply** builds the catalog in a temporary location first, saves preferences, replaces the generated catalog, updates only the top-level `model` and `model_reasoning_effort` keys in an existing Codex `config.toml`, and asks a running router to reload.
- Apply does not restart Codex, rewrite provider credentials, or replace unrelated Codex configuration.
- Picker changes may appear in new chats; active Codex conversations are not forcibly restarted.
- Failed temporary catalog generation does not replace preferences.
- Automatic rollback is not implemented yet. If a later step fails, restore the relevant timestamped backup manually.

The source development workflow uses `.dev-codex` and reports `live_apply: false`. The installer's configured layout uses the selected Codex home and enables the explicit live Apply path.

## Repository layout

```text
app/                         React/Vite Relay interface and isolated UI checks
catalog/                     OpenCode Go picker definitions
docs/                        Roadmap and contributor documentation
examples/                    Credential-free Codex and settings examples
router/
  router.py                  Local routing service and catalog generation
  manager.py                 Loopback management API and production UI server
  settings.py                Versioned settings schema, validation, backups, and atomic save
  codex_config.py            Preservation-focused Codex default-model updates
  anthropic_adapter.py       Claude protocol, OAuth, tools, and stream adapter
  namespace_tools.py         Computer Use namespace bridge
scripts/
  install.py                 Configurable installer and Codex config merge
  validate.py                Syntax, examples, personal-path, and credential scan
tests/                       Python regression tests
.github/workflows/ci.yml     Windows test, validation, build, and rendered-UI CI
```

## Local configuration and credentials

Installed runtime files live under the selected Codex home:

```text
.codex/model-router/router-settings.json
.codex/model-router/router-settings.json.backup-*
.codex/mixed-models.json
.codex/opencode-go-models.json
```

Preferences contain model metadata and policies only. Credentials stay in the provider's own store:

- Codex/ChatGPT authorization remains in Codex.
- Claude Pro authorization remains in OpenCode's Anthropic OAuth store.
- Kimi and OpenCode keys can be entered write-only in Relay and are stored in the Windows current-user environment.

## Security and privacy

- Do not commit `.codex/auth.json`, OpenCode `auth.json`, API keys, logs, sessions, or reasoning-origin state.
- Relay's management API is loopback-only and requires a local manager request header for mutations.
- No management endpoint returns a credential; settings validation rejects credential-shaped values.
- Diagnostic log output is redacted before it reaches the browser.
- Development mode reads and writes only its isolated `.dev-codex` paths for Codex/OpenCode state.
- OpenAI authorization is never intentionally forwarded to Claude, Kimi, or OpenCode Go.
- Kimi requests preserve Codex's real client `User-Agent` rather than impersonating another client.
- Runtime files and backups are excluded through `.gitignore`; review staged changes before publishing.

## Roadmap

See [docs/ROADMAP.md](docs/ROADMAP.md) for delivered milestones and remaining work. Planned follow-ups include a dedicated uninstaller, automatic transactional rollback, and broader cross-provider compatibility tests.
