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
herdr plugin install doldola/herdr-llm-usage
# or, from a local checkout
herdr plugin link /path/to/herdr-llm-usage
```

Update a GitHub install with `herdr plugin update`.

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
| `$usage_5h_reset` | `↻2h55m` |
| `$usage_week_reset` | `↻5d9h` |
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

For a narrow sidebar, show one short row per window, with the percentage
colored by how much is used (herdr 0.9.0 or newer). It renders as `20 · ↻2h55m`
and `8 · ↻5d9h`; a row disappears when the provider has no such window (Codex
Pro, for example, has only the weekly one).

```toml
[ui.sidebar.agents]
rows = [
  ["state_icon", "agent", "state_text"],
  [{ token = "$usage_5h", fg = "#a6e3a1", bold = true, rules = [{ gt = 90, fg = "#f38ba8" }, { gt = 70, fg = "#f9e2af" }] }, { token = "$usage_5h_reset", dim = true }],
  [{ token = "$usage_week", fg = "#a6e3a1", bold = true, rules = [{ gt = 90, fg = "#f38ba8" }, { gt = 70, fg = "#f9e2af" }] }, { token = "$usage_week_reset", dim = true }],
  ["workspace", "tab"],
]
```

## Cat

### In the sidebar

Every agent row (any agent, not only Claude and Codex) gets a `$pet` token
that follows the agent's state:

| State | `$pet` |
|---|---|
| working | `=^o^= ~~` |
| blocked | `=^O^= !` |
| done | `=^ω^= ♪` |
| idle | `=^.^=` |
| unknown | `=^?^=` |

```toml
[ui.sidebar.agents]
rows = [
  ["state_icon", "agent", "state_text", { token = "$pet", fg = "#f5a962", dim = false, rules = [{ contains = "!", fg = "#f38ba8", bold = true }, { contains = "~", fg = "#f9e2af" }] }],
  ["workspace", "tab"],
]
```

### In a pane

A pixel cat lives in a small pane below your work and reacts to your agents:

| Agents | Cat |
|---|---|
| any blocked | stops and looks at you with a `!` bubble |
| any working | runs back and forth, faster with more agents working |
| all idle | wanders, sits, blinks, wags its tail; dozes off after 90 seconds |
| none | sleeps |

The bottom line shows agent counts and the usage the sidebar already cached,
and the cat warns you when any window is above 90%. It never calls the
providers itself. It needs a truecolor terminal.

```bash
herdr plugin action invoke llm-usage.pet
```

```toml
[[keys.command]]
key = "prefix+m"
type = "plugin_action"
command = "llm-usage.pet"
description = "cat"
```

Press `q` inside the pane to close it.

## Command line

```bash
python3 llm_usage.py status          # human readable
python3 llm_usage.py status --json   # machine readable
```

## Multiple accounts

The plugin reads the account the CLI would use from herdr's environment.
`CLAUDE_CONFIG_DIR` and `CODEX_HOME` are honored when set in the environment
herdr's server was started from.
