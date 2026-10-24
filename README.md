# Relay — Codex Subscription Router

Relay is a local, cross-platform router that puts OpenAI, OpenCode Go, Claude plans, Kimi Code, and local OpenAI-compatible models behind one Codex model picker. Each request stays on its own provider lane, with its own credential and protocol adapter.

> **Project status:** Relay 0.3.0 is the current release line for Windows, Linux, and macOS. The desktop archives are unsigned portable bundles and require Python 3.11 or newer. Signed/notarized native installers, a dedicated uninstaller, and automatic transactional rollback remain future work.

Relay is an independent project, not an OpenAI, Anthropic, Kimi, or OpenCode product. Provider eligibility, billing rules, model identifiers, and API behavior remain controlled by each provider.

## What it does

- Presents five provider lanes in one loopback Codex catalog.
- Connects any eligible Claude plan directly with Relay-owned PKCE OAuth; OpenCode is not required.
- Adds Ollama, LM Studio, and custom loopback OpenAI-compatible models.
- Discovers local models from `/v1/models`.
- Tracks provider-reported subscription allowances plus routed token usage across every configured account and local endpoint.
- Supports model editing, stable picker route IDs, editable upstream model IDs, and a grouped add-model dropdown populated with OpenAI, Claude, Kimi, and OpenCode provider catalogs.
- Enables cross-provider subagents: an eligible Claude parent can target a Kimi child, an OpenAI parent can target a local model, and so on.
- Keeps credentials isolated by provider and never forwards a ChatGPT credential to a third-party or local endpoint.
- Generates the Codex catalog from credential-free preferences, with atomic saves, backups, validation, and a guarded Apply flow.
- Avoids restarting Codex during ordinary save, apply, and catalog reload operations.

## Platforms and release archives

| Platform | Release | API-key and Relay OAuth storage | Launchers |
| --- | --- | --- | --- |
| Windows 10/11 | `.zip` | Current-user environment registry | `.cmd` |
| macOS 13+ | `.tar.gz` | Owner-only file under `~/Library/Application Support/Relay` | `.sh`, `.command` |
| Linux | `.tar.gz` | Owner-only file under `$XDG_CONFIG_HOME/relay` or `~/.config/relay` | `.sh` |

The archives contain a static production UI, Python router, installer, launchers, examples, and open-source model catalog. They do not contain provider credentials, OAuth tokens, logs, local settings, generated catalogs, usage databases, or build dependencies.

Download the archive for your OS from [GitHub Releases](https://github.com/JacksonSibold/codex-subscription-router/releases/latest):

- `relay-<version>-windows.zip`
- `relay-<version>-linux.tar.gz`
- `relay-<version>-macos.tar.gz`
- `SHA256SUMS.txt`

These are portable archives, not signed `.exe`, `.msi`, `.dmg`, or package-manager installers.

## Providers

| Provider | Authentication | Models | Notes |
| --- | --- | --- | --- |
| OpenAI | Existing Codex / ChatGPT sign-in | OpenAI catalog entries | Native Codex tools and connected apps |
| Claude | Relay-owned PKCE OAuth for the eligible Claude plan you sign into | Built-in Claude catalog plus custom IDs | Anthropic Messages adapter; OpenCode not required |
| Kimi Code | Write-only `KIMI_API_KEY` | Kimi routes added by the user | Native Kimi Responses lane |
| OpenCode Go | Write-only `OPENCODE_API_KEY` | OpenCode Go catalog and custom IDs | Responses lane with per-model metadata |
| Local | None by default, or a named local credential | Any model reported by a loopback `/v1/models` endpoint | Chat Completions or Responses wire protocol |

### Claude sign-in without OpenCode

1. Open **Connections → Claude → Start Claude sign-in**.
2. Complete the provider authorization page in your browser.
3. Copy the authorization code Claude displays, paste it into Relay, and choose **Connect**.

Use the provider account picker to sign in with whichever eligible Claude plan you have, including Pro, Max, Team, or Enterprise where Claude Code access is included. Relay stores the resulting access/refresh token set through its current-user credential store. It never reads or changes the separate Claude Code configuration. Older installations with an existing OpenCode Anthropic token can continue to use it as a fallback, but Relay OAuth is preferred. As with any OAuth integration, provider approval and subscription eligibility are required and may change.

### Local model setup

In **Model picker → Add model → Local model**, enter a loopback base URL and use **Discover**:

- Ollama commonly uses `http://127.0.0.1:11434/v1` with OpenAI Chat Completions.
- LM Studio commonly uses `http://127.0.0.1:1234/v1` with OpenAI Chat Completions.
- A compatible server that implements the OpenAI Responses API can use the Responses protocol instead.

Only `localhost`, `127.0.0.0/8`, and other loopback addresses are accepted. Redirects are not followed. Local discovery and inference never forward Codex's ChatGPT credential. If a local server requires a key, configure an uppercase credential variable name on the model and set that credential in the current-user store or process environment.

## Cross-provider subagents

When **Cross-provider subagents** is enabled on a route, Relay advertises Codex multi-agent v2 support for that model. The installer also writes `[agents] enabled = true`. Because every upstream lane is exposed through Relay's single `mixed` Codex provider, Codex resolves a child model from the same active catalog while Relay selects the child's actual provider per request.

This enables combinations such as:

- Claude parent → Kimi child
- OpenAI parent → local child
- OpenCode parent → Claude child
- Kimi parent → OpenAI child

A model must be visible, its provider enabled, and its subagent control enabled to be selectable as a child. This is catalog eligibility, not a separate per-model allowlist.

## Relay management app

- **Overview:** provider readiness, picker inventory, usage, and router state.
- **Connections:** Codex sign-in, Relay-owned Claude OAuth, Kimi/OpenCode key forms, and local endpoint summary.
- **Model picker:** provider-populated add-model dropdown, click-to-edit rows, editable upstream IDs, show/hide, ordering, defaults, endpoint/protocol editing, and per-model policies.
- **Usage:** live Codex, Claude, and Kimi subscription allowances; token totals; per-provider/account activity; daily chart; model distribution; and recent request status.
- **Capabilities:** honest per-provider tool and delegation behavior.
- **Diagnostics:** loopback health, sanitized logs, safe settings export, and local file locations.

Credential-found status means a local credential or endpoint was found. It is not a billed inference test.

## Tool support

- **OpenAI:** native Codex tools, hosted web search, and connected-app behavior remain on the OpenAI route.
- **Claude:** shell/function tools work. Relay maps Codex `mcp__node_repl` and `mcp__cua_repl` namespaces so Claude can use Computer Use. Large connected-app namespaces remain excluded.
- **Kimi and OpenCode Go:** shell/function tools work; Computer Use namespaces are bridged. OpenAI-only hosted search and connected-app namespaces are removed before forwarding.
- **Local:** function tools and freeform custom tools are translated to Chat Completions tool calls, then translated back into Responses events. Computer Use namespaces use the same bridge. Compatibility depends on the local model's tool-calling quality.
- **Thinking:** the picker exposes only the levels configured for each model. Claude uses Anthropic effort output; Responses lanes receive Responses reasoning; Chat Completions receives `reasoning_effort` when the request supplies one.

## Run without installing into Codex

Extract a release archive and start the router and manager:

Windows:

```powershell
.\Start Router.cmd
.\Start Relay.cmd
```

macOS or Linux:

```bash
chmod +x *.sh *.command
./Start Router.sh
./Start Relay.sh
```

Relay listens only on loopback. The router uses `127.0.0.1:18765`; the management app uses `127.0.0.1:18766`. These launch files do not change Codex configuration or restart Codex.

## Install into Codex

> **Explicit action required:** installation writes beneath the selected Codex home and may merge `config.toml` when `--configure-codex` is supplied. Review your configuration and use an isolated `--codex-home` for rehearsals.

Windows:

```powershell
python scripts\install.py --configure-codex
```

macOS or Linux:

```bash
python3 scripts/install.py --configure-codex
```

The installer:

- Copies router Python files and the production UI to `<codex-home>/model-router`.
- Copies launchers, the OpenCode catalog, and generates `mixed-models.json`.
- Preserves existing Relay preferences and creates defaults only when absent.
- Creates timestamped backups before replacing installed files or changing `config.toml`.
- Merges the `mixed` provider, desktop reasoning choices, `[agents] enabled = true`, the selected default model, and that model's reasoning effort.
- Preserves unrelated projects, plugins, providers, and credentials.
- Does not restart Codex or a running router.

Use `--codex-home <path>` for an isolated installation.

## Usage and allowances

Relay reads live plan allowance percentages and reset times from Codex, Claude OAuth, and Kimi Code where the provider exposes them. OpenCode and local lanes show routed token activity without claiming a subscription percentage.

Relay also records, for each routed request:

- UTC timestamp
- provider and non-secret account label
- stable picker route ID
- HTTP status
- input, cached, output, reasoning, and total token counts when the upstream exposes them

Prompts, responses, API keys, and OAuth tokens are not stored in the allowance response or the ledger. Allowance requests disable redirects so a provider credential cannot be forwarded to another host. The default runtime database is `model-router/router-usage.sqlite` (or the project-local equivalent). Override it with `CODEX_ROUTER_USAGE_DB`.

## Development

Requirements:

- Python 3.11 or newer
- Node.js 20 or newer
- Codex Desktop / CLI
- Chrome or Edge for rendered UI checks

From the project root:

```bash
cd app
npm ci
npm run dev
```

The development preview is `http://localhost:7100/`. Development mode uses only `.dev-codex` for Codex state, Relay credentials, OpenCode fallback state, and usage data. It never writes live Codex configuration or signals the live router.

Run all checks:

```bash
python -m unittest discover -s tests -v
python scripts/validate.py
git diff --check
cd app
npm run build
npm run test:ui
```

Build local release archives:

```bash
python scripts/package_release.py --platform windows --version 0.3.0
python scripts/package_release.py --platform linux --version 0.3.0
python scripts/package_release.py --platform macos --version 0.3.0
```

## Apply and rollback behavior

- **Save** validates and atomically replaces credential-free preferences with timestamped backups.
- **Save & generate** in isolated development mode builds the catalog without changing Codex or signaling a live router.
- **Save & apply** in an installed layout generates the catalog in a temporary location, saves preferences, updates only selected Codex top-level defaults, and asks a running router to reload.
- Picker and subagent changes may appear in new chats; active conversations are not forcibly restarted.
- A failed temporary catalog generation does not replace preferences.
- Automatic transactional rollback is not implemented. The installer, settings saver, and Codex default updater retain timestamped backups for manual recovery.

## Repository layout

```text
app/                         React/Vite Relay UI, development isolation, rendered checks
catalog/                     OpenCode Go picker definitions
docs/                        Roadmap
examples/                    Credential-free Codex and settings examples
router/
  router.py                  Responses routing, catalog generation, usage capture
  manager.py                 Loopback management API and production UI server
  anthropic_oauth.py         Relay-owned Claude PKCE OAuth
  anthropic_adapter.py       Claude Messages/Responses stream and tool adapter
  local_adapter.py           Loopback Chat/Responses adapter and discovery
  usage_store.py             Credential-free SQLite usage ledger
  subscription_usage.py      Live provider plan allowances and safe parsers
  credentials.py             Current-user credential storage
  settings.py                Versioned settings schema, migration, validation, backup
  codex_config.py            Preservation-focused Codex default updates
  namespace_tools.py         Computer Use namespace bridge
scripts/
  install.py                 Installer and Codex config merge
  package_release.py         Allowlisted Windows/Linux/macOS packaging
  validate.py                Syntax, examples, path, and credential scan
tests/                       Python regression, routing, OAuth, local, usage, package tests
.github/workflows/           Three-OS CI and tag-triggered release publication
```

## Credentials and privacy

- Codex/ChatGPT authorization remains in Codex.
- Claude Relay OAuth, Kimi keys, OpenCode keys, and optional local credentials use Relay's current-user credential store.
- On Windows the store is the current-user environment registry.
- On macOS and Linux the store is a JSON file with owner-only file and directory permissions. This is permission-based protection, not an OS keychain or full-disk encryption claim.
- Relay's management API binds only to loopback. Mutating endpoints require a local request header and do not expose CORS access to arbitrary websites.
- Settings validation rejects credential-shaped values.
- Diagnostic logs are redacted before reaching the browser.
- Provider credentials never intentionally cross into another provider's lane.

## Known limitations

- Provider OAuth, model IDs, quotas, allowance endpoints, and tool behavior can change without notice.
- Claude OAuth is a user-mediated browser code flow built on the provider's public client flow; it is not a guarantee of subscription eligibility.
- Connected-app namespaces and hosted web search remain OpenAI-only.
- Local model quality, tool calling, context size, and image support vary by server/model.
- Archives are not signed or notarized native installers.
- Automatic rollback and a dedicated uninstaller are not implemented.

See [CHANGELOG.md](CHANGELOG.md) and [docs/ROADMAP.md](docs/ROADMAP.md).