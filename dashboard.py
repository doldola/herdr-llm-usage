"""The tabbed panel behind the dashboard popup: Claude, Codex and Settings.

Claude and Codex tabs list every saved account with its usage and switch
between them; without saved accounts they show the signed-in one. Settings
holds the Claude auto-switch options, written to the plugin's config.json.
"""

import json
import os
import re
import select
import shutil
import subprocess
import sys
import termios
import threading
import time
import tty
import unicodedata

import agent_activity
import agent_setup
import claude_accounts
import codex_accounts
import llm_usage

TABS = ("Claude", "Codex", "Settings", "Agents")
AGENTS_REFRESH = 5  # seconds between Agents tab refreshes while it is shown
REFRESH_EVERY = 60
THRESHOLDS = (70, 75, 80, 85, 90, 95)
STRATEGY_NAMES = {"best": "most quota left", "soonest-reset": "weekly reset soonest first"}

DIM, BOLD, RESET = "\033[2m", "\033[1m", "\033[0m"
GREEN, RED, YELLOW, BLUE = "\033[32m", "\033[31m", "\033[33m", "\033[34m"


ANSI = re.compile(r"\x1b\[[0-9;?]*[A-Za-z]")


def fit(line, width):
    """Cut a line to `width` visible columns, keeping its colors (wide characters count as two)."""
    out, used, i = [], 0, 0
    while i < len(line):
        match = ANSI.match(line, i)
        if match:
            out.append(match.group(0))
            i = match.end()
            continue
        cell = 2 if unicodedata.east_asian_width(line[i]) in ("W", "F") else 1
        if used + cell > width:
            out.append(RESET)
            break
        out.append(line[i])
        used += cell
        i += 1
    return "".join(out)


def visible_width(text):
    plain = ANSI.sub("", text)
    return sum(2 if unicodedata.east_asian_width(ch) in ("W", "F") else 1 for ch in plain)


def wrap(line, width, indent=None):
    """Break a line into rows of at most `width` columns, at spaces when possible.

    Colors carry over to the continuation rows, which are indented like the
    line itself (or by `indent`), so nothing is hidden when a pane is narrow.
    """
    if width < 8 or visible_width(line) <= width:
        return [line]
    if indent is None:
        lead = len(ANSI.sub("", line)) - len(ANSI.sub("", line).lstrip(" "))
        indent = min(lead + 2, width // 3)
    rows, current, used, active = [], "", 0, ""
    for token in re.split(r"( +)", line):
        if not token:
            continue
        size = visible_width(token)
        if used + size > width and used > indent and not token.isspace():
            rows.append(current + RESET)
            current, used = " " * indent + active, indent
        if token.isspace():
            if used + size <= width:
                current, used = current + token, used + size
            elif used > indent:  # padding that does not fit ends the row instead of vanishing
                rows.append(current + RESET)
                current, used = " " * indent + active, indent
            continue
        i = 0
        while i < len(token):  # a word longer than the row is split where it overflows
            match = ANSI.match(token, i)
            if match:
                code = match.group(0)
                active = "" if code == RESET else active + code
                current += code
                i = match.end()
                continue
            cell = 2 if unicodedata.east_asian_width(token[i]) in ("W", "F") else 1
            if used + cell > width:
                rows.append(current + RESET)
                current, used = " " * indent + active, indent
            current, used = current + token[i], used + cell
            i += 1
    rows.append(current)
    return rows


def bar(used, width=18):
    filled = max(0, min(width, int(round(used / 100.0 * width))))
    color = RED if used >= 90 else YELLOW if used >= 70 else GREEN
    return color + "█" * filled + DIM + "░" * (width - filled) + RESET


def since(epoch):
    seconds = int(time.time() - epoch)
    if seconds < 60:
        return "just now"
    if seconds < 3600:
        return "%dm ago" % (seconds // 60)
    if seconds < 86400:
        return "%dh %dm ago" % (seconds // 3600, seconds % 3600 // 60)
    return "%dd ago" % (seconds // 86400)


def window_line(label, used, resets_at):
    reset = llm_usage.until(resets_at)
    reset = ("  ↻ " + reset) if reset and reset != "resetting" else ""
    return "        %-6s %s %5.1f%%%s" % (label[:6], bar(used), used, reset)


class Panel:
    def __init__(self):
        self.tab = 0
        self.cursor = [0, 0, 0, 0]
        self.message = ""
        self.claude = None  # list of cswap rows, or None while loading
        self.codex = None  # list of saved Codex accounts with usage
        self.usage = None  # llm_usage data: signed-in accounts, other logins
        self.loaded_at = 0.0
        self.agents = None  # activity per agent pane, or None until the Agents tab loads it
        self.agents_at = 0.0
        self.detail = None  # pane id shown in full on the Agents tab
        self.sidebar_busy = False

    # ------------------------------------------------------------ data

    def load(self):
        if claude_accounts.claude_hook_installed() and not claude_accounts.claude_hook_current():
            try:  # an older plugin version installed it; bring it up to date
                claude_accounts.set_claude_hook(True)
            except (RuntimeError, OSError):
                pass
        self.usage = llm_usage.cached(0)
        self.claude = []
        if claude_accounts.cswap_path():
            try:
                self.claude = claude_accounts.accounts()
            except (RuntimeError, subprocess.SubprocessError) as exc:
                self.message = RED + "cswap: %s" % exc + RESET
        live = codex_accounts.live_auth()
        live_id = codex_accounts.identity(live)[0]
        self.codex = []
        for account in codex_accounts.saved_accounts():
            active = account["id"] == live_id
            self.codex.append(dict(account, active=active,
                                   usage=codex_accounts.usage(live if active else account["auth"])))
        self.codex_unsaved = bool(live_id) and live_id not in [a["id"] for a in self.codex]
        self.loaded_at = time.time()

    def load_agents(self):
        """Activity for every Claude and Codex pane; also pushes the sidebar's activity tokens."""
        self.agents_at = time.time()
        if not claude_accounts.settings()["agent_monitor"]:
            self.agents = []
            return
        listing = llm_usage.herdr("agent", "list")
        try:
            panes = (json.loads(listing.stdout).get("result") or {}).get("agents") or []
        except ValueError:
            panes = []
        self.agents = [agent_activity.pane_activity(a) for a in panes if a.get("agent") in ("claude", "codex")]
        if not self.sidebar_busy:
            self.sidebar_busy = True

            def push():
                try:
                    llm_usage.cmd_sidebar([])
                finally:
                    self.sidebar_busy = False

            threading.Thread(target=push, daemon=True).start()

    def provider(self, name):
        return next((p for p in (self.usage or {}).get("providers", []) if p["provider"] == name), None)

    def refresh_sidebar(self):
        threading.Thread(target=llm_usage.cmd_sidebar, args=(["--force"],), daemon=True).start()

    # ------------------------------------------------------------ drawing

    def rows(self):
        if self.tab == 0:
            return self.claude or []
        if self.tab == 1:
            return self.codex or []
        if self.tab == 3:
            return self.agents or []
        return SETTINGS

    def draw(self):
        width = shutil.get_terminal_size().columns
        tabs = "  ".join((BOLD + "[%s]" + RESET if i == self.tab else DIM + " %s " + RESET) % name
                         for i, name in enumerate(TABS))
        out = [BOLD + "LLM usage" + RESET + "   " + tabs, ""]
        if self.usage is not None and self.claude is not None:  # nothing to show while loading
            out += (self.draw_claude, self.draw_codex, self.draw_settings, self.draw_agents)[self.tab]()
        out += ["", self.message, ""]
        keys = {
            0: "←→ tabs · ↑↓ select · enter switch · b switch by strategy · s save login · x remove · r refresh · q close",
            1: "←→ tabs · ↑↓ select · enter switch · b most quota · s save login · x remove · r refresh · q close",
            2: "←→ tabs · ↑↓ select · enter change · +/- threshold · c check now · q close",
            3: ("esc back · r refresh · q close" if self.detail else
                "←→ tabs · ↑↓ select · enter details · r refresh · q close"),
        }[self.tab]
        out.append(DIM + keys[:width] + RESET)
        sys.stdout.write("\033[H\033[2J" + "\r\n".join(fit(line, width) for line in out))
        sys.stdout.flush()

    def pointer(self, i):
        return BOLD + "›" + RESET if i == self.cursor[self.tab] else " "

    def draw_claude(self):
        lines = []
        if not claude_accounts.cswap_path():
            lines += self.signed_in("claude")
            lines += ["", "To save several Claude accounts and switch between them, install claude-swap:",
                      "  uv tool install claude-swap      (or: pipx install claude-swap)"]
            return lines
        if not self.claude:
            lines.append("No saved Claude accounts yet. Press s to save the one Claude Code is signed in to,")
            lines.append("then /login with the next account in Claude Code and press s again.")
            return lines
        for i, row in enumerate(self.claude):
            mark = GREEN + "●" + RESET if row.get("active") else " "
            name = row.get("alias") or row.get("email")
            extra = " ".join(x for x in (row.get("organizationName") and "[%s]" % row["organizationName"],
                                         row.get("disabled") and "(disabled)") if x)
            lines.append("%s %s %d %s%s%s  %s" % (self.pointer(i), mark, row.get("number", 0), BOLD, name, RESET,
                                                   DIM + extra + RESET))
            usage = row.get("usage")
            if not usage:
                lines.append("        " + DIM + (row.get("usageStatus") or "no usage").replace("_", " ") + RESET)
                continue
            for key, label in (("fiveHour", "5h"), ("sevenDay", "week")):
                window = usage.get(key)
                if window:
                    lines.append(window_line(label, window["pct"], claude_accounts.iso_epoch(window.get("resetsAt"))))
            for window in usage.get("scoped") or []:
                lines.append(window_line(window.get("name") or "model", window["pct"],
                                         claude_accounts.iso_epoch(window.get("resetsAt"))))
        values = claude_accounts.settings()
        state = "on, %s at %s%%" % (STRATEGY_NAMES[values["strategy"]], values["threshold"]) \
            if values["auto_switch"] else "off"
        lines += ["", DIM + "Auto-switch: %s (Settings tab)" % state + RESET]
        return lines

    def draw_codex(self):
        lines = []
        if not self.codex:
            lines += self.signed_in("codex")
            lines += ["", "Press s to save this login. To add another: `codex login` with the next account,",
                      "then press s again. Switching resumes running Codex panes when they are idle."]
            return lines
        for i, row in enumerate(self.codex):
            mark = GREEN + "●" + RESET if row["active"] else " "
            lines.append("%s %s %s%s%s  %s" % (self.pointer(i), mark, BOLD, row["email"], RESET,
                                               DIM + (row["plan"] or "") + RESET))
            if isinstance(row["usage"], dict) and row["usage"]:
                for label, window in row["usage"].items():
                    lines.append(window_line(label, window["used"], window.get("resets_at")))
            else:
                lines.append("        " + DIM + str(row["usage"] or "no usage") + RESET)
        if self.codex_unsaved:
            lines += ["", YELLOW + "The current Codex login is not saved yet: press s." + RESET]
        lines += ["", DIM + "Switching resumes running Codex panes on the new login once they are idle." + RESET]
        return lines

    def signed_in(self, name):
        """The signed-in account as the plain usage view shows it."""
        provider = self.provider(name)
        if not provider:
            return ["No %s login found on this machine." % name.title()]
        return [line for line in llm_usage.render({"providers": [provider], "fetched_at": time.time()})
                .split("\n")[:-1] if line]

    def draw_agents(self):
        if not claude_accounts.settings()["agent_monitor"]:
            return ["Agent monitoring is off.", "",
                    "When on, this tab and the sidebar show what each Claude and Codex pane is using:",
                    "the running tool, tool counts, skills, markdown files read, instruction files,",
                    "memory and context. It reads the session transcripts the CLIs keep on this",
                    "machine; nothing leaves it.", "",
                    "Press enter to turn it on (or use the Settings tab)."]
        if self.agents is None:
            return [DIM + "loading…" + RESET]
        if not self.agents:
            return ["No Claude or Codex panes."]
        if self.detail:
            activity = next((a for a in self.agents if a["pane"] == self.detail), None)
            if activity:
                return self.draw_agent_detail(activity)
            self.detail = None
        lines = []
        for i, a in enumerate(self.agents):
            status = {"working": YELLOW + "◐ working", "blocked": RED + "! blocked", "done": GREEN + "✓ done"}.get(
                a["status"], DIM + "○ " + str(a["status"] or "")) + RESET
            place = os.path.basename(a["cwd"] or "") or "?"
            now = ("  now " + BOLD + agent_activity.current_tool(a) + RESET) if agent_activity.current_tool(a) else ""
            ctx = agent_activity.context_label(a)
            lines.append("%s %s%s %s%s  %s%s%s  %s" % (self.pointer(i), BOLD, a["pane"], a["agent"], RESET, status,
                                                      ("  " + ctx) if ctx else "", now, DIM + place + RESET))
            if a["error"]:
                lines.append("      " + DIM + a["error"] + RESET)
                continue
            tools = sorted(a["tools"].items(), key=lambda kv: -kv[1])
            summary = " · ".join("%s %d" % (short_tool(n), c) for n, c in tools[:5])
            lines.append("      tools %d  %s" % (sum(a["tools"].values()), DIM + summary + RESET))
            extra = []
            if a["skills"]:
                extra.append("skills " + ", ".join(a["skills"][:3]))
            if a["md_files"]:
                extra.append("md " + ", ".join(os.path.basename(p) for p in a["md_files"][:3]))
            if extra:
                lines.append("      " + DIM + "   ".join(extra) + RESET)
        return lines

    def draw_agent_detail(self, a):
        return setup_view(a)

    def draw_settings(self):
        values = claude_accounts.settings()
        lines = [BOLD + "Claude auto-switch" + RESET,
                 DIM + "Checked when agents change state, at most once a minute." + RESET, ""]
        for i, (key, label, show) in enumerate(SETTINGS):
            lines.append("%s %-22s %s" % (self.pointer(i), label, show(values)))
        if values["auto_switch"] and not claude_accounts.cswap_path():
            lines += ["", RED + "Auto-switch needs claude-swap: uv tool install claude-swap" + RESET]
        lines += ["", BOLD + "Background activity" + RESET + DIM + "   (c: run the auto-switch check now)" + RESET]
        notes = claude_accounts.diagnostics()
        for kind, label in (("sidebar", "Sidebar update"), ("auto", "Auto-switch check"), ("monitor", "Monitor pane"),
                            ("error", "Last hook error")):
            entry = notes.get(kind)
            if not entry:
                lines.append("  %-20s %s" % (label, DIM + "never" + RESET))
                continue
            ago = since(entry["at"])
            text = entry["text"]
            color = RED if kind == "error" or "fail" in text or "error" in text else ""
            lines.append("  %-20s %s%s%s %s" % (label, color, text[:90], RESET, DIM + "(" + ago + ")" + RESET))
        lines += ["", DIM + "most quota left: switch to the account with the most headroom when the active one",
                  "  reaches the threshold (claude-swap's own auto-switch).",
                  "weekly reset soonest first: prefer the account whose weekly quota resets first, so",
                  "  quota about to reset is spent before it is lost." + RESET]
        others = [p for p in (self.usage or {}).get("providers", []) if p["provider"] not in ("claude", "codex")]
        notes = [n for p in (self.usage or {}).get("providers", []) for n in p["notes"] if "API_KEY" in n]
        if others or notes:
            lines += ["", BOLD + "Other logins" + RESET]
            for provider in others:
                lines.append("  %s  %s" % (provider["name"], provider.get("account") or ""))
                lines += ["    " + DIM + n + RESET for n in provider["notes"]]
            lines += ["  " + DIM + n + RESET for n in notes]
        return lines

    # ------------------------------------------------------------ actions

    def act(self, key, fd):
        rows = self.rows()
        cursor = self.cursor[self.tab]
        if key in (b"\r", b"\n") and self.tab == 3:
            if not claude_accounts.settings()["agent_monitor"]:
                self.message = change_setting("agent_monitor", self.claude) or ""
                self.agents = None
            elif rows:
                self.detail = rows[cursor]["pane"]
        elif key in (b"\r", b"\n"):
            if self.tab == 2:
                self.message = change_setting(SETTINGS[cursor][0], self.claude) or ""
            elif rows:
                self.switch(rows[cursor])
        elif key == b"s" and self.tab in (0, 1):
            self.save_login()
        elif key == b"b" and self.tab in (0, 1):
            self.switch_by_strategy()
        elif key == b"x" and self.tab in (0, 1) and rows:
            self.remove(rows[cursor], fd)
        elif key == b"c" and self.tab == 2:
            self.busy("checking…")
            try:
                claude_accounts.auto_tick(force=True)
                entry = claude_accounts.diagnostics().get("auto")
                self.message = "Auto-switch check: " + (entry["text"] if entry else "auto-switch is off")
            except Exception as exc:  # show it rather than crash the panel
                self.message = RED + "Auto-switch check failed: %s" % exc + RESET
            self.claude = None
        elif key in (b"+", b"=", b"-", b"_") and self.tab == 2:
            step = 5 if key in (b"+", b"=") else -5
            values = claude_accounts.settings()
            values["threshold"] = max(50, min(100, int(values["threshold"]) + step))
            claude_accounts.save_settings(values)

    def busy(self, text):
        self.message = DIM + text + RESET
        self.draw()

    def switch(self, row):
        try:
            if self.tab == 0:
                self.busy("switching Claude…")
                switched, email = claude_accounts.switch(row["number"])
                self.message = ("Claude → %s. Running sessions follow on their next request (~30s on macOS)."
                                % email if switched else "Already on " + email)
            else:
                self.busy("switching Codex…")
                email, changed = codex_accounts.switch(row["id"])
                self.message = ("Codex → %s. Running Codex panes resume on it when idle." % email
                                if changed else "Already on " + email)
        except (RuntimeError, codex_accounts.CodexError, subprocess.SubprocessError, OSError) as exc:
            self.message = RED + str(exc) + RESET
        self.claude = None
        self.refresh_sidebar()

    def switch_by_strategy(self):
        if self.tab == 0:
            if not self.claude:
                self.message = "No saved Claude accounts."
                return
            target = claude_accounts.pick(self.claude, claude_accounts.settings())
            if not target:
                self.message = YELLOW + "Every Claude account is at the threshold." + RESET
                return
            self.switch(target)
        else:
            best = codex_accounts.best_account()
            if best:
                self.switch(dict(best, number=None))

    def save_login(self):
        try:
            if self.tab == 0:
                self.busy("saving Claude login…")
                self.message = claude_accounts.save_current()
            else:
                self.message = "Saved " + codex_accounts.save_live()
        except (RuntimeError, codex_accounts.CodexError, subprocess.SubprocessError, OSError) as exc:
            self.message = RED + str(exc) + RESET
        self.claude = None

    def remove(self, row, fd):
        if self.tab == 0:
            # cswap asks for confirmation itself, so hand it the terminal.
            saved = termios.tcgetattr(fd)
            termios.tcsetattr(fd, termios.TCSADRAIN, ORIGINAL_TTY)
            sys.stdout.write("\033[H\033[2J\033[?25h")
            sys.stdout.flush()
            subprocess.call([claude_accounts.cswap_path(), "remove", str(row["number"])])
            input("\nPress Enter to go back. ")
            termios.tcsetattr(fd, termios.TCSADRAIN, saved)
            sys.stdout.write("\033[?25l")
        else:
            sys.stdout.write("\r\n\r\nRemove %s? [y/N] " % row["email"])
            sys.stdout.flush()
            if os.read(fd, 1) in (b"y", b"Y"):
                codex_accounts.remove(row["id"])
                self.message = "Removed " + row["email"]
        self.claude = None


SETUP_TTL = 30  # seconds a session's setup scan is reused
_setup_cache = {}


def cached_setup(activity):
    key = (activity.get("agent"), activity.get("cwd"), activity.get("transcript"))
    hit = _setup_cache.get(key)
    if hit and time.time() - hit[0] < SETUP_TTL:
        return hit[1]
    setup = agent_setup.setup_for(*key)
    _setup_cache[key] = (time.time(), setup)
    return setup


def fold_line(targets, index, section, hidden, expanded):
    """The selectable line that unfolds a long section, or folds it back."""
    if hidden <= 0:
        return []
    targets[index] = "expand:" + section
    return ["  " + DIM + ("▴ show fewer" if expanded else "… %d more (enter to show)" % hidden) + RESET]


def tidy(path):
    home = os.path.expanduser("~")
    return path.replace(home, "~", 1) if path else path


def file_line(entry, base=None):
    path = os.path.relpath(entry["path"], base) if base else tidy(entry["path"])
    when = ("  " + since(entry["mtime"])) if entry.get("mtime") else ""
    return "  %-44s %s" % (path, DIM + "%d lines%s" % (entry["lines"], when) + RESET)


SKILLS_SHOWN = 16  # skills listed before the rest fold into a "more" line
MEMORY_SHOWN = 12


def setup_view(a, targets=None, expanded=()):
    """What a session is set up with, marked with what it has used so far.

    When `targets` is a dict, the index of every line that names a file is
    mapped to that file's path, so a caller can let the user open it.
    """
    targets = {} if targets is None else targets  # a value of "expand:<section>" folds or unfolds it
    status = {"working": YELLOW + "◐ working", "blocked": RED + "! blocked", "done": GREEN + "✓ done"}.get(
        a.get("status"), DIM + "○ " + str(a.get("status") or "")) + RESET
    ctx = agent_activity.context_label(a)
    lines = ["%s%s %s%s  %s  %s" % (BOLD, a["pane"], a["agent"], RESET, status,
                                    DIM + " · ".join(x for x in (a.get("model"), ctx) if x) + RESET),
             DIM + "%s   session %s%s" % (tidy(a.get("cwd") or ""), (a.get("session") or "?")[:13],
                                          " (guessed)" if a.get("guessed") else "") + RESET]
    if a.get("error"):
        lines += ["", YELLOW + a["error"] + RESET]
    setup = cached_setup(a) or {}
    used_skills = a.get("skill_uses") or {}
    used_mcp = a.get("mcp") or {}

    instructions = setup.get("instructions") or []
    lines += ["", BOLD + "Instructions" + RESET + DIM + "  %d files · %d lines" % (
        len(instructions) + len(setup.get("rules") or []),
        sum(e["lines"] for e in instructions + (setup.get("rules") or []))) + RESET]
    for entry in instructions + (setup.get("rules") or []):
        targets[len(lines)] = entry["path"]
        lines.append(file_line(entry))
    if not instructions:
        lines.append("  " + DIM + "none" + RESET)

    if a.get("agent") == "claude":
        memory = setup.get("memory") or []
        lines += ["", BOLD + "Memory" + RESET + DIM + "  %d files" % len(memory) + RESET]
        base = os.path.dirname(memory[0]["path"]) if memory else None
        shown = memory if "memory" in expanded else memory[:MEMORY_SHOWN]
        for entry in shown:
            targets[len(lines)] = entry["path"]
            lines.append(file_line(entry, base))
        lines += fold_line(targets, len(lines), "memory", len(memory) - MEMORY_SHOWN, "memory" in expanded)
        if not memory:
            lines.append("  " + DIM + "none for this project" + RESET)

    skills = setup.get("skills") or []
    names = {k["name"] for k in skills}
    extra = [n for n in used_skills if n not in names]  # used but not found on disk (e.g. built in)
    lines += ["", BOLD + "Skills" + RESET + DIM + "  %d available · %d used this session" % (
        len(skills), len(used_skills)) + RESET]
    ordered = sorted(skills, key=lambda k: (-used_skills.get(k["name"], 0), k["name"]))
    for skill in ordered if "skills" in expanded else ordered[:SKILLS_SHOWN]:
        count = used_skills.get(skill["name"], 0)
        mark = GREEN + "●" + RESET if count else DIM + "○" + RESET
        if skill.get("path"):
            targets[len(lines)] = skill["path"]
        lines.append("  %s %-22s %s %s%s" % (mark, skill["name"][:22], DIM + "%-16s" % skill["source"][:16] + RESET,
                                                 DIM + skill["description"][:60] + RESET,
                                                 ("  " + GREEN + "×%d" % count + RESET) if count else ""))
    lines += fold_line(targets, len(lines), "skills", len(ordered) - SKILLS_SHOWN, "skills" in expanded)
    lines += ["  %s %s  ×%d" % (GREEN + "●" + RESET, n, used_skills[n]) for n in extra]

    mcp = setup.get("mcp") or []
    lines += ["", BOLD + "MCP servers" + RESET + DIM + "  %d configured · %d used" % (len(mcp), len(used_mcp)) + RESET]
    cells = []
    for server in mcp:
        count = sum(c for name, c in used_mcp.items() if name == server["name"] or server["name"] in name)
        cells.append((GREEN + "● " if count else DIM + "○ ") + server["name"] + RESET +
                     DIM + " (%s)" % server["scope"] + RESET + (" ×%d" % count if count else ""))
    cells += [GREEN + "● " + RESET + name + " ×%d" % c for name, c in used_mcp.items()
              if not any(name == s["name"] or s["name"] in name for s in mcp)]
    lines += ["  " + "   ".join(cells)] if cells else ["  " + DIM + "none" + RESET]

    others = []
    for label, key in (("Subagents", "agents"), ("Commands", "commands"), ("Plugins", "plugins")):
        items = setup.get(key) or []
        if items:
            others.append("%s%s%s %s" % (BOLD, label, RESET, DIM + ", ".join(items[:8]) +
                                          (" …" if len(items) > 8 else "") + RESET))
    hooks = setup.get("hooks") or {}
    if hooks:
        others.append(BOLD + "Hooks" + RESET + " " + DIM + " · ".join("%s %d" % kv for kv in sorted(hooks.items())) + RESET)
    if others:
        lines += [""] + others
    settings = {k: v for k, v in (setup.get("settings") or {}).items() if v not in (None, "", 0)}
    if settings:
        lines += ["", BOLD + "Settings" + RESET + " " + DIM + " · ".join("%s %s" % kv for kv in settings.items()) + RESET]

    tools = sorted((a.get("tools") or {}).items(), key=lambda kv: -kv[1])
    now = agent_activity.current_tool(a)
    lines += ["", BOLD + "This session" + RESET + DIM + "  %d tool calls" % sum(a.get("tools", {}).values()) + RESET]
    if now:
        lines.append("  running  " + BOLD + now + RESET)
    lines.append("  tools    " + (DIM + " · ".join("%s %d" % (short_tool(n), c) for n, c in tools[:8]) + RESET
                                  if tools else DIM + "none yet" + RESET))
    if a.get("md_files"):
        lines.append("  md read")
        for path in a["md_files"][:10]:
            full = os.path.expanduser(path)
            if not os.path.isabs(full) and a.get("cwd"):
                full = os.path.join(a["cwd"], full)
            if os.path.isfile(full):
                targets[len(lines)] = full
            lines.append("    " + tidy(full) + ("" if os.path.isfile(full) else DIM + "  (not found)" + RESET))
    return lines


def short_tool(name):
    if name.startswith("mcp__") and name.count("__") >= 2:
        _, server, tool = name.split("__", 2)
        return "%s:%s" % (server, tool)
    return name


def change_setting(key, claude_rows):
    """Apply one Settings change; returns a message for the panel, if any."""
    if key == "claude_hook":
        enable = not claude_accounts.claude_hook_installed()
        try:
            claude_accounts.set_claude_hook(enable)
        except (RuntimeError, OSError) as exc:
            return RED + str(exc) + RESET
        if not enable:
            return "Removed the Claude Code hook."
        return ("Added a Stop hook to %s. New Claude sessions use it; running ones pick it up after "
                "/hooks in each session or a restart." % claude_accounts.claude_settings_path())
    values = claude_accounts.settings()
    if key == "agent_monitor":
        values["agent_monitor"] = not values["agent_monitor"]
        claude_accounts.save_settings(values)
        return ("Agent monitoring on: see the Agents tab; the sidebar gets $tool, $skill and $ctx."
                if values["agent_monitor"] else "Agent monitoring off.")
    if key == "auto_switch":
        values["auto_switch"] = not values["auto_switch"]
    elif key == "threshold":
        later = [t for t in THRESHOLDS if t > int(values["threshold"])]
        values["threshold"] = later[0] if later else THRESHOLDS[0]
    elif key == "strategy":
        order = claude_accounts.STRATEGIES
        values["strategy"] = order[(order.index(values["strategy"]) + 1) % len(order)]
    elif key == "model":
        names = sorted({w.get("name") for r in claude_rows or [] for w in (r.get("usage") or {}).get("scoped") or []
                        if w.get("name")})
        options = [None] + names
        current = values.get("model")
        values["model"] = options[(options.index(current) + 1) % len(options)] if current in options else None
    claude_accounts.save_settings(values)


SETTINGS = (
    ("auto_switch", "Auto-switch", lambda v: (GREEN + "on" if v["auto_switch"] else DIM + "off") + RESET),
    ("threshold", "Switch at", lambda v: "%s%% used" % v["threshold"]),
    ("strategy", "Strategy", lambda v: STRATEGY_NAMES[v["strategy"]]),
    ("model", "Also watch model", lambda v: v.get("model") or DIM + "none (5h and week only)" + RESET),
    ("agent_monitor", "Agent monitoring",
     lambda v: (GREEN + "on" if v["agent_monitor"] else DIM + "off") + RESET
     + DIM + "  (tools, skills, files, memory per pane; Agents tab and sidebar)" + RESET),
    ("claude_hook", "Check while Claude works",
     lambda v: (GREEN + "on" if claude_accounts.claude_hook_installed() else DIM + "off") + RESET
     + DIM + "  (Claude Code hook, at most once a minute; covers long turns)" + RESET),
)

ORIGINAL_TTY = None


def run():
    global ORIGINAL_TTY
    fd = sys.stdin.fileno()
    ORIGINAL_TTY = termios.tcgetattr(fd)
    panel = Panel()
    try:
        tty.setcbreak(fd)
        sys.stdout.write("\033[?25l")
        while True:
            if panel.claude is None or time.time() - panel.loaded_at > REFRESH_EVERY:
                keep = panel.message  # e.g. the result of the switch that triggered this reload
                panel.busy("loading…")
                panel.message = ""
                panel.load()
                panel.message = panel.message or keep
            if panel.tab == 3 and (panel.agents is None or time.time() - panel.agents_at > AGENTS_REFRESH):
                panel.load_agents()
            rows = panel.rows()
            panel.cursor[panel.tab] = min(panel.cursor[panel.tab], max(0, len(rows) - 1))
            panel.draw()
            wait = AGENTS_REFRESH if panel.tab == 3 else REFRESH_EVERY
            if not select.select([sys.stdin], [], [], wait)[0]:
                continue
            key = os.read(fd, 3)
            if panel.detail and key in (b"\x1b", b"\x7f", b"\x1b[D", b"h"):
                panel.detail = None
                continue
            if key in (b"q", b"Q", b"\x1b", b"\x03"):
                return 0
            panel.message = ""
            if key in (b"\x1b[C", b"\t", b"l"):
                panel.tab = (panel.tab + 1) % len(TABS)
            elif key in (b"\x1b[D", b"\x1b[Z", b"h"):
                panel.tab = (panel.tab - 1) % len(TABS)
            elif key in (b"1", b"2", b"3", b"4"):
                panel.tab = int(key) - 1
            elif key in (b"\x1b[A", b"k"):
                panel.cursor[panel.tab] = max(0, panel.cursor[panel.tab] - 1)
            elif key in (b"\x1b[B", b"j"):
                panel.cursor[panel.tab] = min(len(panel.rows()) - 1, panel.cursor[panel.tab] + 1)
            elif key == b"r":
                panel.claude = None
                panel.agents = None
            else:
                panel.act(key, fd)
    finally:
        sys.stdout.write("\033[?25h")
        sys.stdout.flush()
        termios.tcsetattr(fd, termios.TCSADRAIN, ORIGINAL_TTY)


# ---------------------------------------------------------------- monitor pane

MONITOR_REFRESH = 3  # seconds


def usage_header(usage):
    """One line per signed-in Claude/Codex account: 5-hour and weekly use with reset countdowns."""
    lines = []
    for provider in (usage or {}).get("providers", []):
        if provider["provider"] not in ("claude", "codex"):
            continue
        parts = []
        for window in provider["windows"]:
            if window["label"] not in ("5h", "week"):
                continue
            used = window["used"]
            color = RED if used >= 90 else YELLOW if used >= 70 else GREEN
            reset = llm_usage.until(window.get("resets_at")).replace(" ", "")
            parts.append("%s %s%d%%%s%s" % (window["label"], color + BOLD, round(used), RESET,
                                            DIM + " ↻" + reset + RESET if reset else ""))
        status = "   ".join(parts) or DIM + (provider.get("error") or "no usage") + RESET
        lines.append("%s%-6s%s %s  %s" % (BOLD, provider["name"], RESET, status, DIM + (provider.get("account") or "") + RESET))
    return lines


FOLLOW_POLL = 1.0  # seconds between checks of which agent is selected
MONITOR_RATIO = 0.65  # share of the width the agent keeps when the monitor joins its tab


def herdr_json(*args):
    result = llm_usage.herdr(*args)
    try:
        return json.loads(result.stdout).get("result") or {}
    except ValueError:
        return {}


class Monitor:
    """Shows the agent selected in herdr, and follows it to other tabs."""

    def __init__(self):
        self.pane = os.environ.get("HERDR_PANE_ID")  # this monitor's own pane
        self.shown = None  # herdr agent entry being shown
        self.activity = None
        self.usage = None
        self.scroll = 0
        self.follow = True
        self.message = ""
        self.panel = Panel()  # for its detail drawing and the sidebar push
        self.sidebar_at = 0.0
        self.moved = (None, 0.0)  # tab this monitor last moved to, and when
        self.targets = {}  # line index -> file path, for the lines that name a file
        self.selected = 0  # position in the sorted target lines
        self.viewing = None  # path of the file open in the viewer
        self.expanded = set()  # sections unfolded past their first entries
        self.view_scroll = 0

    def poll(self):
        agents = herdr_json("agent", "list").get("agents") or []
        watched = [a for a in agents if a.get("agent") in ("claude", "codex")]
        focused = next((a for a in watched if a.get("focused")), None)
        previous = (self.shown or {}).get("pane_id")
        if focused:
            self.shown = focused
        elif self.shown:  # focus is on this monitor or a plain pane: keep showing the last agent
            self.shown = next((a for a in watched if a.get("pane_id") == previous), None)
        if not self.shown and watched:
            self.shown = watched[0]
        if self.shown and self.shown.get("pane_id") != previous:
            self.scroll = self.selected = 0
        if self.shown and focused and self.follow:
            self.join_tab(focused)
        self.activity = agent_activity.pane_activity(self.shown) if self.shown else None
        if time.time() - self.sidebar_at > MONITOR_REFRESH:
            self.sidebar_at = time.time()
            self.usage = llm_usage.cached(llm_usage.CACHE_TTL)
            self.panel.agents_at = 0
            self.panel.load_agents()  # keeps the sidebar tokens current too

    def join_tab(self, agent):
        """Move this monitor next to the selected agent when that agent is in another tab."""
        if not self.pane:
            return
        mine = (herdr_json("pane", "get", self.pane).get("pane") or {}).get("tab_id")
        if not mine or mine == agent.get("tab_id"):
            return
        if self.moved[0] == agent.get("tab_id") and time.time() - self.moved[1] < 10:
            return  # a move is in flight or was refused; do not repeat it every second
        self.moved = (agent.get("tab_id"), time.time())
        moved = herdr_json("pane", "move", self.pane, "--tab", agent["tab_id"], "--split", "right",
                           "--target-pane", agent["pane_id"], "--ratio", str(MONITOR_RATIO), "--no-focus")
        new_id = ((moved.get("move_result") or {}).get("pane") or {}).get("pane_id")
        if new_id:
            self.pane = new_id
        elif not moved:
            self.message = DIM + "could not follow to the agent's tab; press f to stop following" + RESET

    def lines(self):
        self.targets = {}
        if not claude_accounts.settings()["agent_monitor"]:
            return ["Agent monitoring is off.", "",
                    "Press enter to turn it on. This pane then shows the agent you select in",
                    "herdr: running tool, tool counts, skills, markdown files, instructions,",
                    "memory and context, read from the session transcript on this machine."]
        if not self.shown:
            return ["No Claude or Codex agents."]
        a = self.shown
        targets = {}
        view = setup_view(self.activity, targets, self.expanded) if self.activity else [a.get("pane_id") or "?"]
        provider = "Claude" if a.get("agent") == "claude" else "Codex"
        usage = [line for line in usage_header(self.usage) if line.startswith(BOLD + provider)]
        shift = len(usage)  # the usage lines go in after the first line
        self.targets = {i + (shift if i >= 1 else 0): path for i, path in targets.items()}
        return view[:1] + usage + view[1:]


def run_monitor():
    """A pane beside your work showing the agent selected in herdr's sidebar.

    A crash would close the pane before anyone could read why, so it is shown
    in the pane and kept in the diagnostics until a key is pressed.
    """
    claude_accounts.note("monitor", "started in pane %s" % os.environ.get("HERDR_PANE_ID"))
    try:
        return _run_monitor()
    except Exception:
        import traceback

        detail = traceback.format_exc()
        claude_accounts.note("monitor", "crashed: " + detail.strip().splitlines()[-1])
        sys.stdout.write("\033[?25h\033[0m\r\nThe monitor stopped:\r\n\r\n" + detail.replace("\n", "\r\n")
                         + "\r\nPress any key to close this pane.")
        sys.stdout.flush()
        try:
            tty.setcbreak(sys.stdin.fileno())  # any key, not a whole line
            os.read(sys.stdin.fileno(), 1)
        except (OSError, termios.error):
            pass
        return 1


VIEW_LIMIT = 4000  # lines of a file the viewer reads


def markdown_rows(path, width):
    """A markdown file as display rows: headings bold, code dimmed, long lines wrapped."""
    try:
        with open(path, encoding="utf-8", errors="replace") as handle:
            text = [next(handle, None) for _ in range(VIEW_LIMIT)]
    except OSError as exc:
        return [RED + str(exc) + RESET]
    rows, in_code = [], False
    for line in (t.rstrip("\n") for t in text if t is not None):
        if line.lstrip().startswith("```"):
            in_code = not in_code
            rows.append(DIM + line + RESET)
            continue
        if in_code:
            styled = DIM + line + RESET
        elif line.startswith("#"):
            styled = BOLD + BLUE + line + RESET
        elif line.strip().startswith("---") and not line.strip("-").strip():
            styled = DIM + line + RESET
        else:
            styled = line
        rows += wrap(styled, width)
    return rows


def _run_monitor():
    fd = sys.stdin.fileno()
    saved = termios.tcgetattr(fd)
    monitor = Monitor()
    next_poll = 0.0
    try:
        tty.setcbreak(fd)
        sys.stdout.write("\033[?25l")
        while True:
            if time.time() >= next_poll:
                try:
                    monitor.poll()
                except Exception as exc:  # keep the pane alive and say why
                    monitor.message = RED + "%s: %s" % (type(exc).__name__, exc) + RESET
                next_poll = time.time() + FOLLOW_POLL
            size = shutil.get_terminal_size()
            room = max(1, size.lines - 2)
            if monitor.viewing:
                rows = [BOLD + tidy(monitor.viewing) + RESET, DIM + "─" * min(size.columns, 60) + RESET]
                rows += markdown_rows(monitor.viewing, size.columns)
                monitor.view_scroll = max(0, min(monitor.view_scroll, len(rows) - room))
                out = rows[monitor.view_scroll:monitor.view_scroll + room]
                hint = "↑↓ space b g G · esc back  %d/%d" % (
                    min(len(rows), monitor.view_scroll + room), len(rows))
            else:
                try:
                    body = monitor.lines()
                except Exception as exc:  # one odd session must not take the pane down
                    body = [RED + "Could not show this agent: %s: %s" % (type(exc).__name__, exc) + RESET]
                files = sorted(monitor.targets)
                monitor.selected = max(0, min(monitor.selected, len(files) - 1))
                chosen = files[monitor.selected] if files else None
                rows, chosen_row = [], 0
                for index, line in enumerate(body):
                    if index == chosen:
                        line = BOLD + "›" + RESET + line[1:] if line.startswith(" ") else line
                        chosen_row = len(rows)
                    rows += wrap(line, size.columns)
                if monitor.message:
                    rows += wrap(monitor.message, size.columns)
                # keep the selected file in view
                if chosen_row < monitor.scroll:
                    monitor.scroll = chosen_row
                elif chosen_row >= monitor.scroll + room:
                    monitor.scroll = chosen_row - room + 1
                monitor.scroll = max(0, min(monitor.scroll, len(rows) - room))
                out = rows[monitor.scroll:monitor.scroll + room]
                hint = "↑↓ file · enter read · f follow %s · q close" % ("on" if monitor.follow else "off")
            out.append(DIM + hint + RESET)
            sys.stdout.write("\033[H\033[2J" + "\r\n".join(fit(line, size.columns) for line in out))
            sys.stdout.flush()
            if not select.select([sys.stdin], [], [], FOLLOW_POLL)[0]:
                continue
            key = os.read(fd, 3)
            monitor.message = ""
            if monitor.viewing:
                page = max(1, room - 2)
                if key in (b"\x1b", b"q", b"h", b"\x1b[D", b"\x7f"):
                    monitor.viewing = None
                elif key in (b"j", b"\x1b[B"):
                    monitor.view_scroll += 1
                elif key in (b"k", b"\x1b[A"):
                    monitor.view_scroll = max(0, monitor.view_scroll - 1)
                elif key in (b" ", b"\x1b[6"):
                    monitor.view_scroll += page
                elif key in (b"b", b"\x1b[5"):
                    monitor.view_scroll = max(0, monitor.view_scroll - page)
                elif key == b"g":
                    monitor.view_scroll = 0
                elif key == b"G":
                    monitor.view_scroll = 10 ** 9
                continue
            if key in (b"q", b"Q", b"\x03"):
                # Hand focus to the agent first: a client still focused on this pane after it
                # closes sends its next keybinding to a pane that no longer exists.
                target = (monitor.shown or {}).get("pane_id")
                if target:
                    llm_usage.herdr("agent", "focus", target)
                claude_accounts.note("monitor", "closed with q, focus back to %s" % (target or "?"))
                return 0
            if key in (b"j", b"\x1b[B"):
                monitor.selected += 1
            elif key in (b"k", b"\x1b[A"):
                monitor.selected = max(0, monitor.selected - 1)
            elif key in (b"\r", b"\n"):
                if not claude_accounts.settings()["agent_monitor"]:
                    monitor.message = change_setting("agent_monitor", None) or ""
                    next_poll = 0
                elif monitor.targets:
                    files = sorted(monitor.targets)
                    target = monitor.targets[files[min(monitor.selected, len(files) - 1)]]
                    if target.startswith("expand:"):
                        monitor.expanded ^= {target.split(":", 1)[1]}
                    else:
                        monitor.viewing, monitor.view_scroll = target, 0
            elif key == b"f":
                monitor.follow = not monitor.follow
            elif key == b"r":
                next_poll = 0
    finally:
        sys.stdout.write("\033[?25h")
        sys.stdout.flush()
        termios.tcsetattr(fd, termios.TCSADRAIN, saved)
