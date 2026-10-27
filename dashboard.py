"""The tabbed panel behind the dashboard popup: Claude, Codex and Settings.

Claude and Codex tabs list every saved account with its usage and switch
between them; without saved accounts they show the signed-in one. Settings
holds the Claude auto-switch options, written to the plugin's config.json.
"""

import os
import select
import shutil
import subprocess
import sys
import termios
import threading
import time
import tty

import claude_accounts
import codex_accounts
import llm_usage

TABS = ("Claude", "Codex", "Settings")
REFRESH_EVERY = 60
THRESHOLDS = (70, 75, 80, 85, 90, 95)
STRATEGY_NAMES = {"best": "most quota left", "soonest-reset": "weekly reset soonest first"}

DIM, BOLD, RESET = "\033[2m", "\033[1m", "\033[0m"
GREEN, RED, YELLOW, BLUE = "\033[32m", "\033[31m", "\033[33m", "\033[34m"


def bar(used, width=18):
    filled = max(0, min(width, int(round(used / 100.0 * width))))
    color = RED if used >= 90 else YELLOW if used >= 70 else GREEN
    return color + "█" * filled + DIM + "░" * (width - filled) + RESET


def window_line(label, used, resets_at):
    reset = llm_usage.until(resets_at)
    reset = ("  ↻ " + reset) if reset and reset != "resetting" else ""
    return "        %-6s %s %5.1f%%%s" % (label[:6], bar(used), used, reset)


class Panel:
    def __init__(self):
        self.tab = 0
        self.cursor = [0, 0, 0]
        self.message = ""
        self.claude = None  # list of cswap rows, or None while loading
        self.codex = None  # list of saved Codex accounts with usage
        self.usage = None  # llm_usage data: signed-in accounts, other logins
        self.loaded_at = 0.0

    # ------------------------------------------------------------ data

    def load(self):
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
        return SETTINGS

    def draw(self):
        width = shutil.get_terminal_size().columns
        tabs = "  ".join((BOLD + "[%s]" + RESET if i == self.tab else DIM + " %s " + RESET) % name
                         for i, name in enumerate(TABS))
        out = [BOLD + "LLM usage" + RESET + "   " + tabs, ""]
        if self.usage is not None and self.claude is not None:  # nothing to show while loading
            out += (self.draw_claude, self.draw_codex, self.draw_settings)[self.tab]()
        out += ["", self.message, ""]
        keys = {
            0: "←→ tabs · ↑↓ select · enter switch · b switch by strategy · s save login · x remove · r refresh · q close",
            1: "←→ tabs · ↑↓ select · enter switch · b most quota · s save login · x remove · r refresh · q close",
            2: "←→ tabs · ↑↓ select · enter change · +/- threshold · q close",
        }[self.tab]
        out.append(DIM + keys[:width] + RESET)
        sys.stdout.write("\033[H\033[2J" + "\r\n".join(out))
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

    def draw_settings(self):
        values = claude_accounts.settings()
        lines = [BOLD + "Claude auto-switch" + RESET,
                 DIM + "Checked when agents change state, at most once a minute." + RESET, ""]
        for i, (key, label, show) in enumerate(SETTINGS):
            lines.append("%s %-22s %s" % (self.pointer(i), label, show(values)))
        if values["auto_switch"] and not claude_accounts.cswap_path():
            lines += ["", RED + "Auto-switch needs claude-swap: uv tool install claude-swap" + RESET]
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
        if key in (b"\r", b"\n"):
            if self.tab == 2:
                change_setting(SETTINGS[cursor][0], self.claude)
            elif rows:
                self.switch(rows[cursor])
        elif key == b"s" and self.tab in (0, 1):
            self.save_login()
        elif key == b"b" and self.tab in (0, 1):
            self.switch_by_strategy()
        elif key == b"x" and self.tab in (0, 1) and rows:
            self.remove(rows[cursor], fd)
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


def change_setting(key, claude_rows):
    values = claude_accounts.settings()
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
            rows = panel.rows()
            panel.cursor[panel.tab] = min(panel.cursor[panel.tab], max(0, len(rows) - 1))
            panel.draw()
            if not select.select([sys.stdin], [], [], REFRESH_EVERY)[0]:
                continue
            key = os.read(fd, 3)
            if key in (b"q", b"Q", b"\x1b", b"\x03"):
                return 0
            panel.message = ""
            if key in (b"\x1b[C", b"\t", b"l"):
                panel.tab = (panel.tab + 1) % len(TABS)
            elif key in (b"\x1b[D", b"\x1b[Z", b"h"):
                panel.tab = (panel.tab - 1) % len(TABS)
            elif key in (b"1", b"2", b"3"):
                panel.tab = int(key) - 1
            elif key in (b"\x1b[A", b"k"):
                panel.cursor[panel.tab] = max(0, panel.cursor[panel.tab] - 1)
            elif key in (b"\x1b[B", b"j"):
                panel.cursor[panel.tab] = min(len(panel.rows()) - 1, panel.cursor[panel.tab] + 1)
            elif key == b"r":
                panel.claude = None
            else:
                panel.act(key, fd)
    finally:
        sys.stdout.write("\033[?25h")
        sys.stdout.flush()
        termios.tcsetattr(fd, termios.TCSADRAIN, ORIGINAL_TTY)
