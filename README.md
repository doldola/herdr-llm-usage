# herdr-llm-usage

A [herdr](https://herdr.dev) plugin for the LLM side of your agents: how much
subscription usage every account has left, switching accounts without losing
running sessions, and what each agent session is set up with and actually uses.

- **Usage**: 5-hour, weekly and per-model usage with reset countdowns, for every
  saved Claude Code and Codex account, in a panel and in the sidebar.
- **Account switching**: Claude switches live, running sessions keep going;
  Codex panes resume the same session on the new login once they are idle.
- **Auto-switch**: Claude moves to another account at a threshold, by most
  quota left or by whichever weekly quota resets soonest.
- **Agent monitor**: a pane beside your work that follows the agent you select
  and shows its running workflows, instructions, memory, skills, MCP servers,
  hooks and settings, marked with what the session has used. You can read the
  markdown files, tidy the project's memory and turn skills off and on from it.

![Agent monitor](assets/monitor.png)

<p>
  <img src="assets/panel-claude.png" alt="Claude tab: usage for every saved account" width="49%">
  <img src="assets/panel-settings.png" alt="Settings tab" width="49%">
</p>

<sub>Screenshots use example accounts and sessions.</sub>

## Contents

- [Who it is for](#who-it-is-for)
- [Quick start](#quick-start)
- [Install](#install)
- [The panel: `prefix+u`](#the-panel-prefixu)
- [Accounts and switching](#accounts-and-switching)
- [Claude auto-switch](#claude-auto-switch)
- [Agent monitor: `prefix+m`](#agent-monitor-prefixm)
- [Sidebar](#sidebar)
- [Configuration](#configuration)
- [Files it reads and writes](#files-it-reads-and-writes)
- [Troubleshooting](#troubleshooting)
- [FAQ](#faq)
- [Uninstall](#uninstall)
- [Privacy and data](#privacy-and-data)

## Who it is for

You run Claude Code or Codex in herdr, and one or more of these is true:

- You hit the 5-hour or weekly limit and want to see it coming, per account.
- You have more than one subscription (work and personal, a team seat and a
  Max plan) and switch between them by logging out and in.
- An agent behaves differently from one project to the next and you want to
  see what it is loading: which `CLAUDE.md` files, how much memory, which of
  your 40 skills it actually uses, which MCP servers it calls.
- You start workflows or subagents and want to know which are still running.

Each part works on its own. Usage needs nothing extra; switching needs
claude-swap for Claude; the monitor needs herdr's agent integrations.

## Quick start

1. Install the plugin and add the two keys (see [Install](#install)), then
   **menu → reload config** in herdr.
2. Press `prefix+u`. The **Claude** and **Codex** tabs show the account each
   CLI is signed in to, with its usage.
3. To keep several accounts: press `s` to save the current login, sign in to
   the next account in the CLI (`/login` in Claude Code, `codex login`), and
   press `s` again. Repeat per account. `enter` on an account switches to it.
4. Optional: in the **Settings** tab turn on **Auto-switch** and pick a
   strategy, and **Check while Claude works** so long turns are checked too.
5. Optional: in the **Settings** tab turn on **Agent monitoring**, then press
   `prefix+m`. Select an agent in herdr's sidebar; the monitor shows it.

## Install

```bash
herdr plugin install doldola/herdr-llm-usage
```

Update later with `herdr plugin update`. Then add the keys to
`~/.config/herdr/config.toml`:

```toml
[[keys.command]]
key = "prefix+u"
type = "plugin_action"
command = "llm-usage.open"
description = "LLM usage"

[[keys.command]]
key = "prefix+m"
type = "plugin_action"
command = "llm-usage.monitor"
description = "Agent monitor"
```

Keybindings and sidebar rows are read by the herdr client: apply changes with
**menu → reload config** in herdr, or detach and reattach.
`herdr server reload-config` reloads only the server's settings. Both keys are
free in herdr's defaults; pick others if you have bound them.

Without a key, the same actions run from a shell inside herdr:
`herdr plugin action invoke llm-usage.open` and `llm-usage.monitor`.

### Requirements

| For | You need |
|---|---|
| Everything | herdr 0.7.5 or later, `python3` (3.8+, standard library only), Linux or macOS |
| Saving and switching Claude accounts, auto-switch | [claude-swap](https://github.com/realiti4/claude-swap): `uv tool install claude-swap` (or `pipx install claude-swap`). Without it, the Claude tab shows the signed-in account only. |
| Per-pane sessions (Codex resume, agent monitor) | herdr's integrations, so it knows each pane's session id: `herdr integration install claude` and `herdr integration install codex` |
| Codex switching | Codex keeping its login in `auth.json` (the default `cli_auth_credentials_store = "file"`) |

Usage is shown for subscription logins (Claude Pro/Max/Team, ChatGPT plans
with Codex). API-key logins have no 5-hour or weekly window; the Settings tab
lists them under other logins.

## The panel: `prefix+u`

A popup with four tabs. `←` `→`, `Tab` or `1`–`4` change tabs, `↑` `↓`
select, `r` refreshes, `q` closes.

| Tab | Shows | Keys |
|---|---|---|
| **Claude** | every saved account with 5-hour, weekly and per-model usage | `enter` switch · `b` switch by strategy · `s` save the current login · `x` remove |
| **Codex** | every saved account with its windows | `enter` switch · `b` most quota left · `s` save the current login · `x` remove |
| **Settings** | auto-switch, monitoring and hook options, background activity, other logins (Gemini, API keys) | `enter` change · `+` `-` threshold · `c` run the auto-switch check now |
| **Agents** | every Claude and Codex pane: running tool, context, tool counts, skills, markdown read | `enter` details |

### Reading an account

Each account shows one bar per usage window, the percent used, and when the
window resets:

```
› ● 1 work@example.com  [Example Inc]
        5h     ████████████░░░░░░  68.0%  ↻ 2h10m
        week   ███████░░░░░░░░░░░  41.0%  ↻ 3d4h
        fable  ████░░░░░░░░░░░░░░  22.0%  ↻ 3d4h
    2 me@example.com
        5h     ██░░░░░░░░░░░░░░░░  12.0%  ↻ 4h05m
        week   ████████████████░░  91.0%  ↻ 18h
```

- `●` marks the account the CLI is signed in to now; `›` is the selection.
  The number is claude-swap's slot number, and a team account shows its
  organization.
- **5h** is the rolling 5-hour session limit, **week** the weekly limit.
  Claude also has per-model weekly limits on some plans (for example Fable),
  shown as their own rows. Codex shows the windows its plan has; Pro plans
  have no 5-hour window.
- Bars turn yellow at 70% and red at 90%. `↻` is the time until the window
  resets and the percent drops back.
- Usage is fetched at most every two minutes per account; `r` fetches now.

## Accounts and switching

### Adding accounts

Each CLI saves whichever account it is signed in to. Save the current one
first, then sign in to the next account and save that too:

| | Sign in | Save |
|---|---|---|
| Claude | `/login` in Claude Code | `s` on the Claude tab |
| Codex | `codex login` | `s` on the Codex tab |

Signing in replaces the login that every running session of that CLI uses.
`x` removes a saved account from the list; it does not sign you out of it.

### Switching

- **Claude**: claude-swap swaps the stored login underneath Claude Code while
  holding Claude Code's own credential locks. Running sessions are not
  restarted: they use the new account on their next request (Linux) or within
  about 30 seconds (macOS Keychain cache). Conversation, context and running
  tools are untouched.
- **Codex**: a running Codex keeps the login it started with, so a switch
  1. saves the current `auth.json` into its account slot (keeping the freshest
     tokens) and writes the chosen login into `auth.json`;
  2. waits for each running Codex pane to be idle (up to three hours), sends
     `/quit`, and runs `codex <original options> resume <session>` in the same
     pane, so the conversation continues on the new login; the original prompt
     argument is not sent again;
  3. shows a notification for panes it could not restart.

  New Codex panes use the new login straight away. Saved Codex logins live in
  `~/.codex/accounts/` (or `$CODEX_HOME/accounts/`), readable only by you,
  like `auth.json`.

`b` switches by the configured strategy (Claude) or to the account with the
most quota left (Codex), without having to compare the bars yourself.

## Claude auto-switch

Turn it on in the Settings tab. The active account is checked against the
threshold (90% by default, `+` `-` to change) whenever an agent changes state,
at most once a minute:

| Strategy | Behaviour |
|---|---|
| most quota left | claude-swap's own auto-switch: at the threshold, move to the account with the most headroom, with its cooldown and hysteresis |
| weekly reset soonest first | prefer the usable account (every window below the threshold) whose weekly quota resets first, so quota about to reset is spent before it is lost; switch when the active account hits the threshold or another usable one resets over 6 hours sooner, then wait 10 minutes |

An example of **weekly reset soonest first**, with a 90% threshold:

| Account | 5h | week | weekly reset |
|---|---|---|---|
| A (active) | 40% | 55% | in 5 days |
| B | 10% | 70% | in 18 hours |
| C | 95% | 20% | in 2 days |

B resets more than 6 hours before A and is usable, so the plugin moves to B:
the 30% of B's week that would otherwise be lost in 18 hours gets used first.
C is skipped while its 5-hour window is above 90%. When B reaches 90%, the next
usable account with the soonest reset takes over.

**Also watch model** adds a model's weekly window (for example Fable) to the
check, so an account whose model limit is full counts as full. Every switch
shows a herdr notification naming the new account and the reason.

**Check while Claude works** adds hooks to Claude Code's `settings.json` that
run `herdr plugin action invoke llm-usage.tick` in the background after tool
calls and at the end of a turn, at most once a minute across all panes, and do
nothing outside herdr. herdr's own hooks run only when an agent changes state,
so a single long turn would otherwise go unchecked. Other hooks and settings
are kept, a backup is saved next to the file once, and turning it off removes
only these hooks. Running Claude sessions pick it up after `/hooks` or a
restart.

**Background activity** in the Settings tab shows when the sidebar update, the
auto-switch check and the monitor last ran and what they did, and the last
hook error. `c` runs the auto-switch check now and shows its decision.

## Agent monitor: `prefix+m`

Turn on **Agent monitoring** in the Settings tab (off by default), then open
the monitor. It opens to the right of the focused pane and shows the agent you
select in herdr's sidebar, within a second of selecting it.

### What it shows

| Section | Claude | Codex |
|---|---|---|
| Header | pane, status, model, context use, folder, session id | same |
| Workflows | workflows and subagents the session started, and its task list | — |
| Instructions | `CLAUDE.md` chain, `.claude/rules` | `AGENTS.md` chain |
| Memory | the project's memory files (`m` tidies them) | — |
| Skills | user, project and enabled-plugin skills, marked by use (`s` manages them) | `~/.codex/skills`, project skills (`s`) |
| MCP servers | user, local and project (`.mcp.json`) servers; used ones marked | `config.toml` servers |
| Also | subagents, commands, plugins, hooks, permission mode and rule counts | prompts, model, reasoning effort, approval, sandbox |
| This session | running tool, tool counts, markdown files read | same |

Why these: everything in Instructions, Memory's index, every skill's
description and every MCP server's tool list is loaded into the model's
context before your first prompt. A long `CLAUDE.md` chain, a memory index
full of stale entries or 60 skills nobody uses cost context on every turn and
make the agent pick the wrong tool more often. The monitor puts what is
configured next to what the session actually used, so you can see what to
trim. Line counts are shown for each file for the same reason.

### Workflows

```
Workflows  1 running · 3 this session
  ◐ deploy-check          workflow · running 4m
  ✓ Find callers          Explore · 29s · 2m ago
  ✗ migrate-db            workflow · 1m · 10m ago
  tasks: 11 (8 done · 1 in progress)
    ▸ write tests
```

- Each workflow and each subagent (the `Agent`/`Task` tool) the session
  started, with its title and subagent type.
- `◐` running, with how long so far; `✓` finished, `✗` failed, with how long
  it took and when it ended. Running ones are listed first, then the five most
  recent finished ones.
- A foreground subagent is done when its result comes back. A background
  workflow or subagent is done when its completion notice arrives in the
  conversation.
- `tasks:` is the session's task list (`TaskCreate`/`TaskUpdate` or
  `TodoWrite`): how many, how many done, and the ones in progress.

### Skills

```
Skills  24 available · 3 used this session · 1 this turn
  ◉ loaded this turn  ● loaded earlier in the session  ○ not loaded
  ◉ code-review         plugin:engineering   Review code changes ...   ×2
  ● docx                user                 Create and edit Word ...  ×1
  ○ pdf                 user                 Read and fill PDFs ...
```

A skill counts as loaded when:

1. the agent calls the Skill tool for it,
2. you run it yourself as `/name`, or
3. the agent reads its `SKILL.md`.

`◉` means it was loaded since your last prompt, so it shapes the current
answer; `●` means an earlier turn of this session loaded it; `○` means it was
not loaded. The CLI shows every skill's description to the model, but only
these three load a skill's instructions, so a skill the agent merely could use
stays `○`. `×2` is how many times. Skills loaded this turn are listed first.
Plugin skills (`plugin:skill`) and skills called by their folder name match
too; a skill loaded but not found on disk (built in) is listed at the end.

### Moving around

- `↑` `↓` choose a line: an instruction file, rule, memory file, a skill's
  `SKILL.md` or a markdown file the session read; `enter` opens it in a reader
  (`↑` `↓`, `space` / `b` page, `g` / `G` top and bottom, `esc` back).
- Long sections fold into a "… N more" line; `enter` on it unfolds, `c` folds
  everything back.
- Lines wrap to the pane's width, so a narrow monitor still shows everything.
- When the selected agent is in another tab, the monitor moves into that tab,
  to its right; `f` turns that off. Selecting the monitor itself keeps the
  last agent on screen.
- `r` refreshes, `q` closes and returns focus to the agent.

| Key | Does |
|---|---|
| `↑` `↓` / `j` `k` | select a line |
| `enter` | read the file, unfold a section, or open the memory or skill manager |
| `c` | fold long sections back |
| `m` | tidy memory (Claude) |
| `s` | manage skills |
| `f` | follow the selected agent across tabs, on or off |
| `r` | refresh now |
| `q` | close, back to the agent |

Shortcuts also work with a Korean (2-set) input method: Hangul letters are read
as the key in the same place.

### Tidying memory: `m`

Claude Code keeps a project's memory as markdown files in
`~/.claude/projects/<project>/memory/`, with `MEMORY.md` as the index it loads
at the start of every session. Every Claude session in that project folder
shares it, and it grows as sessions save things. `m` (or `enter` on the Memory
heading) opens it for the selected agent's project. `tab` / `shift+tab` (or
`→`) switch filters:

| Filter | Finds | Why it matters |
|---|---|---|
| all | every memory file | |
| not in index | files `MEMORY.md` does not link to | Claude finds them only by chance |
| duplicates | files with the same title or the same content | the same fact loaded twice, or two versions that disagree |
| old 30d+ | files not changed for 30 days | facts that may no longer be true |

Links in `MEMORY.md` to files that no longer exist are listed above the files.

| Key | Does |
|---|---|
| `enter` | read the file |
| `d` | archive it: move it to `memory-archive/<date>/` beside `memory/`, outside what Claude reads, and drop its `MEMORY.md` line |
| `a` | add a `MEMORY.md` line for it, using its description |
| `x` | drop `MEMORY.md` lines that link to missing files |
| `u` | undo the last change (repeatable) |
| `esc` / `←` | back to the monitor |

Nothing is deleted. Undo puts back only the lines and files a change touched,
so index lines other sessions wrote in the meantime are kept. Running sessions
read the index when they start, so changes apply to new sessions.

### Managing skills: `s`

`s` (or `enter` on the Skills heading) lists every skill the selected agent can
use, including ones you disabled. For Claude, use is counted over the
project's sessions of the last 30 days; for Codex, over the current session.
`tab` / `shift+tab` (or `→`) switch filters:

| Filter | Finds | Why it matters |
|---|---|---|
| all | every skill | |
| unused 30d | skills no session used | their descriptions still take context in every session |
| duplicates | the same skill name in more than one place | the CLI uses one; the other is dead weight or a surprise |
| no description | skills without a description | the agent cannot judge when to use them |
| disabled | skills you turned off | to bring one back |

| Key | Does |
|---|---|
| `enter` | read the `SKILL.md` |
| `d` | disable: move the skill folder to `skills-disabled/` beside its skills folder, where the CLI does not look |
| `e` | enable a disabled skill again |
| `u` | undo the last change (repeatable) |
| `esc` / `←` | back to the monitor |

Plugin skills are managed by their plugin: turn the plugin off with `/plugin`
in Claude Code. Disabling a project skill moves a file in the project, so git
sees the change. New sessions see the change; running ones may keep the skill
list they started with.

### Where the information comes from

Setup comes from the files each CLI loads for the session's folder, by their
documented locations: it says what is configured, not that the CLI read it.
Use (the marks, counts, workflows, tasks, context) comes from the session's
transcript, the log each CLI writes in `~/.claude/projects/` or
`~/.codex/sessions/`. Transcripts are read incrementally, so a refresh only
reads what was written since the last one.

## Sidebar

Agent panes get tokens you can place in herdr's sidebar rows:

| Token | Example | |
|---|---|---|
| `$usage_5h`, `$usage_week` | `82` | percent used, for color rules |
| `$usage_5h_reset`, `$usage_week_reset` | `↻3h30m`, `↻2d2h` | time to reset |
| `$usage` | `5h 82% ↻3h30m · week 73% ↻2d2h` | both windows in one |
| `$usage_account` | `me@example.com` | signed-in account |
| `$tool` | `Bash`, `notion:notion-search` | running tool, while working (monitoring on) |
| `$skill` | `docx` | skill loaded since your last prompt (monitoring on) |
| `$ctx` | `ctx 24%` (Codex), `ctx 92k` (Claude) | context use (monitoring on) |

A layout for a narrow sidebar, with usage colored at 70% and 90%:

```toml
[ui.sidebar.agents]
rows = [
  ["state_icon", "agent", "state_text", { token = "$tool", fg = "#f9e2af", dim = false }],
  [{ token = "$skill", fg = "#cba6f7", dim = false }, { token = "$ctx", fg = "#cdd6f4", dim = false }],
  [{ token = "$usage_5h", fg = "#a6e3a1", bold = true, dim = false, rules = [{ gt = 90, fg = "#f38ba8" }, { gt = 70, fg = "#f9e2af" }] }, { token = "$usage_5h_reset", fg = "#cdd6f4", dim = false }],
  [{ token = "$usage_week", fg = "#a6e3a1", bold = true, dim = false, rules = [{ gt = 90, fg = "#f38ba8" }, { gt = 70, fg = "#f9e2af" }] }, { token = "$usage_week_reset", fg = "#cdd6f4", dim = false }],
  ["workspace", "tab"],
]
```

Custom tokens are dimmed unless the style says `dim = false`, and a row
disappears when none of its tokens has a value (Codex Pro, for example, has no
5-hour window). Tokens refresh on agent state changes, through the Claude hook,
and every few seconds while the monitor or the Agents tab is open. Usage
tokens expire after 15 minutes without a refresh and activity tokens after 5,
so the sidebar never shows old numbers as current.

## Configuration

Everything is set from the Settings tab. The values live in `config.json` in
`herdr plugin config-dir llm-usage`:

| Key | Default | Meaning |
|---|---|---|
| `auto_switch` | `false` | switch Claude accounts automatically |
| `threshold` | `90` | percent of a window at which an account counts as full |
| `strategy` | `"best"` | `"best"` (most quota left) or `"soonest-reset"` (weekly reset soonest first) |
| `model` | `null` | a model whose weekly window the check also watches, for example `"fable"` |
| `agent_monitor` | `false` | read transcripts for the monitor, the Agents tab and the activity tokens |

**Check while Claude works** is not stored here; it is the presence of the
plugin's hooks in Claude Code's `settings.json`.

## Files it reads and writes

| Path | Read / written | What |
|---|---|---|
| macOS Keychain `Claude Code-credentials`, `~/.claude/.credentials.json` | read | the Claude login, to fetch usage |
| `~/.codex/auth.json` | read; written on a Codex switch | the Codex login |
| `~/.codex/accounts/` | written | saved Codex logins (mode 600) |
| claude-swap's own store | through `cswap` | saved Claude logins |
| `~/.claude/settings.json` | written only when you turn on **Check while Claude works** | the two hooks, with a one-time `.llm-usage.bak` backup |
| `~/.claude/projects/`, `~/.codex/sessions/` | read | session transcripts and Claude memory |
| `memory/`, `memory-archive/` of a project | written only from the memory manager | archive moves and `MEMORY.md` lines |
| skills folders, `skills-disabled/` | written only from the skill manager | disable and enable moves |
| `herdr plugin config-dir llm-usage` | written | `config.json` |
| herdr's plugin state directory | written | usage cache, transcript offsets, undo history, diagnostics |

## Troubleshooting

| Symptom | Check |
|---|---|
| A key does nothing, or is missing from `prefix+?` | apply the config with **menu → reload config** (not `herdr server reload-config`) |
| A key in the monitor does nothing | `herdr plugin update`, then close the monitor with `q` and open it again; the old one keeps running the old code |
| Sidebar numbers stop changing | Settings → Background activity; turn on **Check while Claude works** for long turns |
| "not signed in with a subscription" | the CLI uses an API key or is logged out; `/login` in Claude Code |
| Monitor or Agents tab says "no transcript" or "no session id" | `herdr integration install claude` / `codex`, then start a new session |
| Monitor shows "(guessed)" next to the session | herdr has no session id for the pane, so the newest transcript in the folder is shown; install the integration |
| Claude switching is unavailable | install claude-swap; `cswap list` should show your accounts |
| Codex panes did not resume | the notification lists why; panes must run Codex from a shell |
| A workflow stays `◐` after it finished | its completion notice had a form the plugin does not recognize; please open an issue |

`herdr plugin log list --plugin llm-usage` shows each hook and action run with
its exit code and output.

## FAQ

**Does it use my tokens or slow the agent down?**
No. It reads files and asks the usage endpoints, which do not count against
your limits. Nothing runs inside the agent; the optional Claude hook only
starts a background command, at most once a minute.

**Do running sessions really keep going after a Claude switch?**
Yes. Claude Code reads its login on each request, and claude-swap replaces it
while holding Claude Code's own locks. The conversation, its context and any
running tool are untouched.

**Why does Codex wait for idle panes?**
Codex reads its login once at start. The only way to move a running session to
another login is to quit and resume it, and doing that in the middle of a turn
would cut the turn off.

**Is switching between subscriptions allowed?**
Check the terms of your plans. The plugin only switches between logins you
have yourself signed in to; it does not share or pool accounts.

**Does it work without herdr?**
`python3 llm_usage.py status [--json]` prints the signed-in accounts' usage
from any shell. The panel, monitor and sidebar need herdr.

**Is the memory or skill manager safe on a project other people use?**
Memory lives in your home folder and is yours alone. Disabling a project
skill moves a folder inside the project, which git shows as a change for you
to commit or undo.

## Uninstall

1. If **Check while Claude works** is on, turn it off in the Settings tab
   first, so the hooks are removed from Claude Code's `settings.json`.
2. `herdr plugin uninstall llm-usage`
3. Remove the two `[[keys.command]]` entries and any `$usage…`, `$tool`,
   `$skill` or `$ctx` tokens from `~/.config/herdr/config.toml`.

Saved Codex logins stay in `~/.codex/accounts/` and Claude logins in
claude-swap until you remove them. Archived memory and disabled skills stay
where they were moved.

## Privacy and data

- Everything is read from files on this machine: the CLIs' logins, settings,
  instruction and memory files, and session transcripts. Nothing is sent
  anywhere except the usage requests below.
- Usage comes from the private endpoints the official CLIs use
  (`api.anthropic.com/api/oauth/usage`, `chatgpt.com/backend-api/wham/usage`).
  Tokens are only read; this plugin never refreshes them. claude-swap does its
  own token handling when it switches.
- Transcripts are parsed incrementally, with running totals cached in the
  plugin state directory.

## Notes

- The usage endpoints and transcript formats are not public APIs and may
  change; a part that cannot be read shows why, and the rest keeps working.
- Neither Claude Code nor Codex officially supports multiple accounts; both
  switching paths work with the CLIs' own credential storage.
- The plugin uses the accounts of herdr's environment; `CLAUDE_CONFIG_DIR` and
  `CODEX_HOME` are honored when set there.

## License

[MIT](LICENSE)
