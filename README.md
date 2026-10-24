# Codex Subscription Router

A local Windows router that lets one Codex model picker use multiple existing coding subscriptions while keeping each provider's credentials on its own route.

> **Project status:** working router baseline. A graphical management app and declarative model customization are planned in [the roadmap](docs/ROADMAP.md).

## Current providers

| Provider | Model source | Authentication | Thinking controls |
| --- | --- | --- | --- |
| OpenAI | GPT models selected in the router | Existing Codex / ChatGPT sign-in; credentials are forwarded only to OpenAI | Native Codex support |
| Claude Pro | Claude Sonnet 5.5 and Opus 5.5 | Anthropic OAuth already connected in OpenCode | Low, medium, high, xhigh, max |
| Kimi Code membership | Kimi K3.1 Pro | `KIMI_API_KEY` from the Kimi Code Console | Low, high, max |
| OpenCode Go | Configurable catalog entries | `OPENCODE_API_KEY` | Per-model levels from OpenCode capability metadata |

The router listens only on `127.0.0.1:18765`. Codex uses its normal Responses API protocol for OpenAI, OpenCode Go, and Kimi. A local adapter translates Claude requests between Responses and Anthropic Messages formats.

## Tool support

- **OpenAI:** native Codex tools and connected-app behavior remain on the OpenAI route.
- **Claude:** shell/function tools work. The adapter also maps the Codex `mcp__node_repl` and `mcp__cua_repl` namespace groups so Claude can use Computer Use. Large connected-app namespaces remain excluded.
- **Kimi and OpenCode Go:** shell/function tools work. OpenAI-only connected-app namespaces and hosted web-search declarations are removed before forwarding.
- **Thinking:** the generated catalog exposes only the effort levels configured for each model.

Broader Computer Use parity and configurable tool policies are roadmap items; the current baseline does not claim that every provider supports every OpenAI-only tool.

## Repository layout

```text
router/
  router.py                 Main local routing service and catalog generator
  anthropic_adapter.py     Claude protocol, OAuth, tools, and stream adapter
catalog/
  opencode-go-models.json  OpenCode Go picker definitions
examples/
  config.toml              Minimal Codex configuration snippet
docs/
  ROADMAP.md               GUI and customization plan
```

## Planned management app

The desktop GUI will provide:

- Sign-in and connection-status pages for all four providers.
- Model visibility, display names, ordering, and default-model selection.
- Per-model thinking levels and tool-access policies.
- Computer Use and subagent capability controls.
- Configuration validation, safe backups, and non-disruptive apply/reload behavior.
- A sanitized diagnostics view that never displays access or refresh tokens.

See [docs/ROADMAP.md](docs/ROADMAP.md) for the implementation sequence.

## Security and privacy

- Do not commit `.codex/auth.json`, OpenCode `auth.json`, Claude credentials, API keys, logs, sessions, or reasoning-origin state.
- The example configuration contains no credentials or user-specific absolute paths.
- OpenAI authorization is never intentionally forwarded to Claude, Kimi, or OpenCode Go.
- Kimi requests preserve Codex's real client `User-Agent` rather than impersonating another client.
- Runtime files are excluded through `.gitignore`; review changes before publishing them.

## Development requirements

- Windows 11
- Python 3.11 or newer
- Codex Desktop / CLI
- Existing subscriptions and provider authorization for the routes you enable

The current router uses only the Python standard library. The GUI may add dependencies later.

## Current customization

Until the GUI is available, advanced users can edit:

- `OPENAI_PICKS`, `ANTHROPIC_PICKS`, and `KIMI_PICKS` in `router/router.py`.
- `GO_REASONING` in `router/router.py` for per-model thinking options.
- `catalog/opencode-go-models.json` for OpenCode Go model definitions.

The live Codex installation is intentionally separate from this source repository. Nothing in this repository restarts or modifies Codex by itself.
