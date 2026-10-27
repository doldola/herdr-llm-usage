# herdr-llm-usage

A [herdr](https://herdr.dev) plugin that shows which LLM accounts are signed in on
the machine and how much subscription usage is left.

| Provider | Account shown | Usage shown |
|---|---|---|
| Claude Code (`~/.claude`, macOS Keychain) | email, plan, organization | 5-hour, weekly, per-model weekly, extra usage |
| Codex (`~/.codex/auth.json`) | email, plan | primary/secondary windows (5h / week), credits |
| Gemini CLI (`~/.gemini`) | active Google account | not supported yet |
| `ANTHROPIC_API_KEY`, `OPENAI_API_KEY`, `GEMINI_API_KEY` | masked key | none (no quota endpoint for API keys) |

The plugin only **reads** the logins the CLIs already keep. It never refreshes or
rewrites tokens, so it cannot sign Claude Code or Codex out. When a token has
expired it says so; open the CLI once and the next refresh picks up the new one.

Both usage endpoints are the private ones the official CLIs use
(`api.anthropic.com/api/oauth/usage`, `chatgpt.com/backend-api/wham/usage`).
They are not public APIs and may change.

Requires `python3` (3.8+, standard library only).

## Install

```bash
herdr plugin install <owner>/herdr-llm-usage
# or, from a local checkout
herdr plugin link /path/to/herdr-llm-usage
```

## Dashboard popup

```bash
herdr plugin pane open --plugin llm-usage --entrypoint dashboard
```

Bind it to a key in `~/.config/herdr/config.toml`:

```toml
[[keys.command]]
key = "prefix+u"
type = "plugin_action"
command = "llm-usage.open"
description = "LLM usage"
```

`r` refreshes, `q` or `Esc` closes. It also refreshes every 60 seconds.

## Sidebar

Every Claude and Codex agent pane gets these tokens, refreshed on agent
detection and status changes (provider requests are cached for 2 minutes):

| Token | Example |
|---|---|
| `$usage` | `5h 42% ↻2h 13m · week 18% ↻3d 4h` |
| `$usage_5h` | `42` (percent used, for color rules) |
| `$usage_week` | `18` |
| `$usage_account` | `me@example.com` |

Add them to the Agent sidebar layout, for example:

```toml
[ui.sidebar.agents]
rows = [
  ["state_icon", "agent", "state_text"],
  [{ token = "$usage", dim = true }],
  ["workspace", "tab"],
]
```

With herdr 0.9.0 or newer you can color the 5-hour value by how much is used:

```toml
[ui.sidebar.agents]
rows = [
  ["state_icon", "agent", "state_text"],
  [{ token = "$usage_5h", rules = [{ gt = 90, fg = "#f55", bold = true }, { gt = 70, fg = "#fc0" }] }, "$usage_account"],
  ["workspace", "tab"],
]
```

## Command line

```bash
python3 llm_usage.py status          # human readable
python3 llm_usage.py status --json   # machine readable
```

## Multiple accounts

The plugin reads the account the CLI would use from herdr's environment.
`CLAUDE_CONFIG_DIR` and `CODEX_HOME` are honored when set in the environment
herdr's server was started from.
