# herdr-llm-usage

A [herdr](https://herdr.dev) plugin that puts your LLM accounts in one panel:
which accounts are signed in, how much subscription usage each has left, and
switching between them without losing running sessions.

| | Shows | Switches |
|---|---|---|
| **Claude Code** | 5-hour, weekly and per-model usage for every saved account | Live, through [claude-swap](https://github.com/realiti4/claude-swap): running sessions keep going and use the new account on their next request (Linux) or within about 30 seconds (macOS Keychain cache). |
| **Codex** | primary/secondary windows and credits for every saved account | Saved logins are swapped into `~/.codex/auth.json`; each running Codex pane is restarted in place once idle, with its original options and `codex resume <session>`. The conversation continues. |
| Gemini CLI, API keys | the signed-in Google account, masked `*_API_KEY`s | — |

Claude can also switch on its own before an account runs out.

![Claude tab: usage for every saved account](assets/panel-claude.png)

<p>
  <img src="assets/panel-codex.png" alt="Codex tab" width="49%">
  <img src="assets/panel-settings.png" alt="Settings tab: auto-switch" width="49%">
</p>

<sub>Screenshots use example accounts.</sub>

## Requirements

- `python3` (3.8+, standard library only)
- To save and switch Claude accounts: `uv tool install claude-swap` (or
  `pipx install claude-swap`). Without it, the panel shows the signed-in
  account only.
- To resume Codex panes after a switch: `herdr integration install codex`, so
  herdr knows each pane's session id. Codex must keep its login in `auth.json`
  (the default `cli_auth_credentials_store = "file"`).

## Install

```bash
herdr plugin install doldola/herdr-llm-usage
```

Update later with `herdr plugin update`.

## The panel

```toml
[[keys.command]]
key = "prefix+u"
type = "plugin_action"
command = "llm-usage.open"
description = "LLM usage"
```

Keybindings and sidebar rows belong to the herdr client, so apply changes to
them with **menu → reload config** in herdr (or detach and reattach);
`herdr server reload-config` reloads only the server's settings.

| Tab | Keys |
|---|---|
| all | `←` `→` or `Tab` / `1` `2` `3` tabs · `↑` `↓` select · `r` refresh · `q` close |
| Claude | `enter` switch to the selected account · `b` switch by the configured strategy · `s` save the login Claude Code is signed in to · `x` remove |
| Codex | `enter` switch · `b` switch to the account with the most quota · `s` save the current Codex login · `x` remove |
| Settings | `enter` change the selected option · `+` `-` threshold |

Settings are stored in `config.json` in the plugin config directory
(`herdr plugin config-dir llm-usage`).

### Adding accounts

Each CLI saves whichever account it is signed in to. Save the current one
first, then sign in to the next account and save that too:

| | Sign in | Save |
|---|---|---|
| Claude | `/login` in Claude Code | `s` on the Claude tab |
| Codex | `codex login` | `s` on the Codex tab |

Signing in replaces the login every running session of that CLI uses.

### What a Codex switch does

1. Saves the current `auth.json` into its account slot, so the freshest tokens
   are kept, and writes the chosen account's login into `auth.json`.
2. For every Codex pane running at that moment, waits until the agent is idle
   (up to three hours), sends `/quit`, and runs
   `codex <original options> resume <session id>` in the same pane. The
   original prompt argument is not sent again.
3. Shows a notification listing panes it could not restart: no session id
   (install the integration), Codex launched as the pane's own process instead
   of from a shell, or still busy after three hours.

Saved Codex logins live in `$CODEX_HOME/accounts/` (default
`~/.codex/accounts/`), readable only by you, like `auth.json`.

## Claude auto-switch

Turn it on in the Settings tab. On agent status changes, at most once a minute,
the plugin checks the active account against the threshold:

- **most quota left**: claude-swap's own auto-switch; moves to the account with
  the most headroom when the active one reaches the threshold, with
  claude-swap's cooldown and hysteresis.
- **weekly reset soonest first**: prefers the usable account (every window
  below the threshold) whose weekly quota resets first, so quota about to reset
  is spent before it is lost. It switches when the active account reaches the
  threshold, or when another usable account resets more than 6 hours sooner,
  and waits 10 minutes after a switch before considering another.

"Also watch model" adds that model's weekly window (for example Fable) to the
threshold check. Each switch shows a herdr notification.

"Check while Claude works" adds hooks to Claude Code's `settings.json` that run
`herdr plugin action invoke llm-usage.tick` in the background after tool calls
and when a turn ends, at most once a minute across all panes (and nothing
outside herdr). herdr's own hooks only run when an agent changes state, so a
single long turn would otherwise go unchecked; this keeps the sidebar and
auto-switch current during it. Other hooks and settings are kept, a backup is
saved next to the file once, and turning it off removes only these hooks. New
Claude sessions use it; running ones pick it up after `/hooks` or a restart.

The Settings tab also shows when the sidebar and the auto-switch check last ran
and what they did; `c` runs the check at once.

## Agents

Turn on "Agent monitoring" in the Settings tab (it is off by default). The
Agents tab then lists every Claude and Codex pane with the tool it is running
now, tool counts, skills used, markdown files read and context use; `enter`
shows one pane in full, adding MCP servers, the instruction files its CLI
loads for that folder (`CLAUDE.md`, `.claude/rules`, `AGENTS.md`) and Claude's
memory files for the project.

It reads the session transcripts the CLIs keep on this machine
(`~/.claude/projects/…/<session>.jsonl`, `~/.codex/sessions/…/rollout-…<session>.jsonl`),
using the session id herdr reports for each pane, so install the integrations:
`herdr integration install claude` and `herdr integration install codex`.
Nothing leaves the machine. Transcripts are read incrementally, so refreshing
only parses what was appended. Their format is not a public API; a pane that
cannot be read shows why, and the rest of the plugin is unaffected.

Instruction files are the ones the CLI's lookup rules load for the pane's
folder, not an observation that they were read.

### Monitor pane

A pane beside your work that shows the agent you select in herdr's sidebar:

```bash
herdr plugin action invoke llm-usage.monitor
```

Select an agent in the sidebar and, within a second, the monitor shows that
session's setup and how it is used:

- **Instructions**: the `CLAUDE.md` chain and `.claude/rules` (or `AGENTS.md`
  for Codex), with line counts and when they last changed
- **Memory**: Claude's memory files for the project
- **Skills**: every skill available to the session (user, project and enabled
  plugins), with the ones used this session marked and counted
- **MCP servers**: configured servers by scope (user, local, project, Codex
  config), marked when used
- **Subagents, commands, plugins, hooks** and **settings** (permission mode and
  rule counts; Codex model, reasoning effort, approval and sandbox)
- **This session**: the running tool, tool counts, markdown files read, model
  and context

`↑` `↓` choose a file (instruction files, rules, memory, a skill's
`SKILL.md`, markdown files the session read) and `enter` opens it in a reader
(`↑` `↓`, `space`/`b` to page, `g`/`G`, `esc` back). Long lines wrap to the
pane's width instead of being cut off, so a narrow monitor still shows
everything.

When the selected agent is in another tab, the monitor moves into that tab,
to its right (`f` turns this off). `r` refreshes, `q` closes and returns
focus to the agent. Selecting the monitor itself keeps the last agent on screen. It also
keeps the sidebar tokens below current while it is open.

Setup comes from the files each CLI loads for the session's folder, by their
documented locations; it describes what is configured, and the marks show what
the transcript says was used.

While monitoring is on, the sidebar also gets:

| Token | Example |
|---|---|
| `$tool` | `Bash`, `Edit`, `notion:notion-search` (only while the agent works) |
| `$skill` | `docx` (the last skill used) |
| `$ctx` | `ctx 24%` (Codex) or `ctx 92k` (Claude, tokens in the last request) |

```toml
[ui.sidebar.agents]
rows = [
  ["state_icon", "agent", "state_text", { token = "$tool", fg = "#f9e2af", dim = false }],
  [{ token = "$skill", fg = "#cba6f7", dim = false }, { token = "$ctx", dim = false }],
  ["workspace", "tab"],
]
```

## Sidebar

Every Claude and Codex agent pane gets these tokens, refreshed on agent
detection and status changes (provider requests are cached for 2 minutes):

| Token | Example |
|---|---|
| `$usage` | `5h 42% ↻2h13m · week 18% ↻3d4h` |
| `$usage_5h` | `42` (percent used, for color rules) |
| `$usage_week` | `18` |
| `$usage_5h_reset` | `↻2h55m` |
| `$usage_week_reset` | `↻5d9h` |
| `$usage_account` | `me@example.com` (the signed-in account) |

For a narrow sidebar, one short row per window with the percentage colored by
how much is used (herdr 0.9.0 or newer). A row disappears when the provider has
no such window (Codex Pro, for example, has only the weekly one).

```toml
[ui.sidebar.agents]
rows = [
  ["state_icon", "agent", "state_text"],
  [{ token = "$usage_5h", fg = "#a6e3a1", bold = true, dim = false, rules = [{ gt = 90, fg = "#f38ba8" }, { gt = 70, fg = "#f9e2af" }] }, { token = "$usage_5h_reset", fg = "#cdd6f4", dim = false }],
  [{ token = "$usage_week", fg = "#a6e3a1", bold = true, dim = false, rules = [{ gt = 90, fg = "#f38ba8" }, { gt = 70, fg = "#f9e2af" }] }, { token = "$usage_week_reset", fg = "#cdd6f4", dim = false }],
  [{ token = "$usage_account", fg = "#89b4fa", dim = false }],
  ["workspace", "tab"],
]
```

Custom tokens are dimmed unless the style says `dim = false`.

## Command line

```bash
python3 llm_usage.py status          # human readable
python3 llm_usage.py status --json   # machine readable
```

## Notes

- The usage endpoints are the private ones the official CLIs use
  (`api.anthropic.com/api/oauth/usage`, `chatgpt.com/backend-api/wham/usage`)
  and may change. Tokens are only read for usage; nothing here refreshes them.
- Neither Claude Code nor Codex officially supports multiple accounts. Both
  switching paths work with the CLIs' own credential storage and may need
  updates when that changes.
- The plugin reads the accounts of herdr's environment; `CLAUDE_CONFIG_DIR` and
  `CODEX_HOME` are honored when set there.

## License

[MIT](LICENSE)
