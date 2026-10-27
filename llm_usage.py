#!/usr/bin/env python3
"""LLM provider accounts and subscription usage for herdr.

Reads the logins that Claude Code and Codex already keep on this machine and
asks each provider for the current rate-limit windows. Tokens are only read,
never refreshed or written, so the CLIs stay signed in exactly as they were.

Commands:
  status [--json]   print every provider once
  dashboard         full-screen view for a herdr popup pane (r refresh, q quit)
  sidebar           report usage tokens onto agent panes (herdr event hook)
  open              open the dashboard popup (herdr action)
"""

import base64
import json
import os
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

CACHE_TTL = 120  # seconds between provider requests from sidebar hooks
TOKEN_TTL_MS = 15 * 60 * 1000  # sidebar values vanish if hooks stop refreshing them
SOURCE = "llm-usage"
HTTP_TIMEOUT = 10

CLAUDE_USAGE_URL = "https://api.anthropic.com/api/oauth/usage"
# Anthropic's edge rejects unknown User-Agents on the OAuth endpoints.
CLAUDE_USER_AGENT = "claude-code/2.1.71"
CODEX_USAGE_URLS = (
    "https://chatgpt.com/backend-api/wham/usage",
    "https://chatgpt.com/backend-api/codex/usage",
)
CODEX_USER_AGENT = "codex-cli"

AGENT_PROVIDERS = {"claude": "claude", "codex": "codex", "gemini": "gemini"}


class Unavailable(Exception):
    """The provider cannot report usage right now; the message says why."""


# ---------------------------------------------------------------- helpers


def read_json(path):
    try:
        return json.loads(Path(path).read_text())
    except (OSError, ValueError):
        return None


def http_json(url, headers):
    request = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(request, timeout=HTTP_TIMEOUT) as response:
        return json.loads(response.read().decode("utf-8"))


def jwt_claims(token):
    try:
        payload = token.split(".")[1]
        return json.loads(base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4)))
    except (AttributeError, IndexError, ValueError):
        return {}


def iso_to_epoch(value):
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00")).timestamp()
    except ValueError:
        return None


def window_label(seconds, fallback):
    for label, length in (("5h", 5 * 3600), ("day", 86400), ("week", 7 * 86400), ("month", 30 * 86400)):
        if seconds and abs(seconds - length) / length <= 0.1:
            return label
    return fallback


def mask(secret):
    return secret[:7] + "…" + secret[-4:] if len(secret) > 14 else "set"


# ---------------------------------------------------------------- Claude


def claude_home():
    return Path(os.environ.get("CLAUDE_CONFIG_DIR") or Path.home() / ".claude")


def claude_credentials():
    found = read_json(claude_home() / ".credentials.json")
    if found is None and sys.platform == "darwin" and shutil.which("security"):
        # Claude Code keeps its login in the macOS Keychain instead of a file.
        try:
            raw = subprocess.run(
                ["security", "find-generic-password", "-s", "Claude Code-credentials", "-w"],
                capture_output=True, text=True, timeout=5,
            ).stdout.strip()
            found = json.loads(raw) if raw else None
        except (OSError, ValueError, subprocess.SubprocessError):
            found = None
    return (found or {}).get("claudeAiOauth") or {}


def claude_account_file():
    configured = os.environ.get("CLAUDE_CONFIG_DIR")
    return Path(configured) / ".claude.json" if configured else Path.home() / ".claude.json"


def claude_windows(usage):
    windows = []
    limits = usage.get("limits")
    if isinstance(limits, list):
        names = {"session": "5h", "weekly_all": "week"}
        for entry in limits:
            if not isinstance(entry, dict) or entry.get("percent") is None:
                continue
            kind = entry.get("kind") or "?"
            label = names.get(kind, kind)
            if kind == "weekly_scoped":
                model = ((entry.get("scope") or {}).get("model") or {})
                label = "week " + (model.get("display_name") or model.get("id") or "model")
            windows.append({"label": label, "used": float(entry["percent"]),
                            "resets_at": iso_to_epoch(entry.get("resets_at"))})
        return windows
    # Older response shape: one object per window.
    for key, label in (("five_hour", "5h"), ("seven_day", "week"),
                       ("seven_day_opus", "week Opus"), ("seven_day_sonnet", "week Sonnet")):
        entry = usage.get(key)
        if isinstance(entry, dict) and entry.get("utilization") is not None:
            windows.append({"label": label, "used": float(entry["utilization"]),
                            "resets_at": iso_to_epoch(entry.get("resets_at"))})
    return windows


def fetch_claude():
    result = {"provider": "claude", "name": "Claude", "account": None, "plan": None,
              "org": None, "windows": [], "notes": [], "error": None}
    account = (read_json(claude_account_file()) or {}).get("oauthAccount") or {}
    result["account"] = account.get("emailAddress")
    result["org"] = account.get("organizationName")
    login = claude_credentials()
    tier = login.get("subscriptionType") or login.get("rateLimitTier")
    if isinstance(tier, str):
        result["plan"] = tier.replace("default_claude_", "")
    if os.environ.get("ANTHROPIC_API_KEY"):
        result["notes"].append("ANTHROPIC_API_KEY " + mask(os.environ["ANTHROPIC_API_KEY"])
                               + " (API key billing has no quota endpoint)")
    token = login.get("accessToken")
    if not token:
        if not result["account"] and not result["notes"]:
            return None  # Claude Code was never used here
        result["error"] = "not signed in with a subscription (run claude /login)"
        return result
    if (login.get("expiresAt") or 0) / 1000 < time.time():
        result["error"] = "login token expired; open Claude Code once to renew it"
        return result
    try:
        usage = http_json(CLAUDE_USAGE_URL, {
            "Authorization": "Bearer " + token,
            "anthropic-beta": "oauth-2025-04-20",
            "User-Agent": CLAUDE_USER_AGENT,
        })
    except urllib.error.HTTPError as exc:
        result["error"] = {401: "token rejected; open Claude Code to renew it",
                           403: "no subscription usage for this login",
                           429: "usage endpoint rate limited; retry shortly"}.get(exc.code, "HTTP %d" % exc.code)
        return result
    except (urllib.error.URLError, OSError, ValueError) as exc:
        result["error"] = "request failed: %s" % exc
        return result
    result["windows"] = claude_windows(usage)
    extra = usage.get("extra_usage")
    if isinstance(extra, dict) and extra.get("is_enabled"):
        used, limit = extra.get("used_credits"), extra.get("monthly_limit")
        if used is not None and limit:
            result["notes"].append("extra usage: %s / %s" % (used, limit))
        else:
            result["notes"].append("extra usage enabled")
    return result


# ---------------------------------------------------------------- Codex


def codex_home():
    return Path(os.environ.get("CODEX_HOME") or Path.home() / ".codex")


def codex_windows(limits, prefix=""):
    windows = []
    for kind in ("primary", "secondary"):
        entry = (limits or {}).get(kind + "_window")
        if not isinstance(entry, dict) or entry.get("used_percent") is None:
            continue
        label = window_label(entry.get("limit_window_seconds"), kind)
        windows.append({"label": (prefix + " " + label).strip(), "used": float(entry["used_percent"]),
                        "resets_at": entry.get("reset_at")})
    return windows


def fetch_codex():
    result = {"provider": "codex", "name": "Codex", "account": None, "plan": None,
              "org": None, "windows": [], "notes": [], "error": None}
    auth = read_json(codex_home() / "auth.json")
    if os.environ.get("OPENAI_API_KEY"):
        result["notes"].append("OPENAI_API_KEY " + mask(os.environ["OPENAI_API_KEY"])
                               + " (API key billing has no quota endpoint)")
    if auth is None:
        return result if result["notes"] else None
    if auth.get("OPENAI_API_KEY") and not auth.get("tokens"):
        result["account"] = "API key login"
        result["notes"].append("Codex is signed in with an API key; no subscription limits")
        return result
    tokens = auth.get("tokens") or {}
    claims = jwt_claims(tokens.get("id_token"))
    openai_auth = claims.get("https://api.openai.com/auth") or {}
    result["account"] = claims.get("email")
    result["plan"] = openai_auth.get("chatgpt_plan_type")
    if not tokens.get("access_token"):
        result["error"] = "not signed in (run codex login)"
        return result
    headers = {"Authorization": "Bearer " + tokens["access_token"], "User-Agent": CODEX_USER_AGENT}
    if tokens.get("account_id"):
        headers["chatgpt-account-id"] = tokens["account_id"]
    usage = None
    for url in CODEX_USAGE_URLS:
        try:
            usage = http_json(url, headers)
            break
        except urllib.error.HTTPError as exc:
            if exc.code == 404:
                continue
            result["error"] = {401: "token rejected; run codex once to renew it",
                               403: "request blocked (403); retry later"}.get(exc.code, "HTTP %d" % exc.code)
            return result
        except (urllib.error.URLError, OSError, ValueError) as exc:
            result["error"] = "request failed: %s" % exc
            return result
    if not isinstance(usage, dict):
        result["error"] = "usage endpoint not found"
        return result
    result["plan"] = usage.get("plan_type") or result["plan"]
    result["windows"] = codex_windows(usage.get("rate_limit"))
    for extra in usage.get("additional_rate_limits") or []:
        if isinstance(extra, dict):
            result["windows"] += codex_windows(extra.get("rate_limit"), extra.get("limit_name") or "")
    credits = usage.get("credits")
    if isinstance(credits, dict) and credits.get("has_credits"):
        result["notes"].append("credits: " + ("unlimited" if credits.get("unlimited")
                                              else str(credits.get("balance"))))
    return result


# ---------------------------------------------------------------- Gemini


def fetch_gemini():
    home = Path(os.environ.get("GEMINI_CLI_HOME") or Path.home()) / ".gemini"
    accounts = read_json(home / "google_accounts.json")
    has_key = bool(os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY"))
    if not accounts and not has_key:
        return None
    result = {"provider": "gemini", "name": "Gemini", "account": (accounts or {}).get("active"),
              "plan": None, "org": None, "windows": [], "notes": [], "error": None}
    if has_key:
        key = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
        result["notes"].append("API key " + mask(key))
    result["notes"].append("quota reporting not supported for Gemini yet")
    return result


PROVIDERS = (fetch_claude, fetch_codex, fetch_gemini)


def collect():
    results = []
    for fetch in PROVIDERS:
        try:
            found = fetch()
        except Exception as exc:  # one broken provider must not hide the others
            found = {"provider": fetch.__name__[6:], "name": fetch.__name__[6:].title(), "account": None,
                     "plan": None, "org": None, "windows": [], "notes": [], "error": "internal error: %s" % exc}
        if found:
            results.append(found)
    return {"fetched_at": time.time(), "providers": results}


# ---------------------------------------------------------------- cache


def state_dir():
    path = Path(os.environ.get("HERDR_PLUGIN_STATE_DIR") or Path.home() / ".cache" / "herdr-llm-usage")
    path.mkdir(parents=True, exist_ok=True)
    return path


def cached(max_age):
    """Fresh data, from the cache when it is young enough, with one fetcher at a time."""
    cache = state_dir() / "cache.json"
    data = read_json(cache)
    if data and time.time() - data.get("fetched_at", 0) < max_age:
        return data
    lock_path = state_dir() / "fetch.lock"
    try:
        import fcntl
        lock = open(lock_path, "w")
        fcntl.flock(lock, fcntl.LOCK_EX)
    except (ImportError, OSError):
        lock = None
    try:
        data = read_json(cache)  # another hook may have fetched while we waited
        if data and time.time() - data.get("fetched_at", 0) < max_age:
            return data
        data = collect()
        tmp = cache.with_suffix(".tmp")
        tmp.write_text(json.dumps(data))
        os.replace(tmp, cache)
        return data
    finally:
        if lock:
            lock.close()


# ---------------------------------------------------------------- rendering


def until(epoch):
    if not epoch:
        return ""
    left = int(epoch - time.time())
    if left <= 0:
        return "resetting"
    days, rest = divmod(left, 86400)
    hours, rest = divmod(rest, 3600)
    minutes = rest // 60
    if days:
        return "%dd %dh" % (days, hours)
    if hours:
        return "%dh %02dm" % (hours, minutes)
    return "%dm" % minutes


def bar(used, width=24):
    filled = max(0, min(width, int(round(used / 100.0 * width))))
    color = "\033[31m" if used >= 90 else "\033[33m" if used >= 70 else "\033[32m"
    return color + "█" * filled + "\033[2m" + "░" * (width - filled) + "\033[0m"


def render(data, color=True):
    lines = []
    for p in data["providers"]:
        title = p["name"]
        details = [x for x in (p.get("account"), p.get("plan"), p.get("org")) if x]
        lines.append(("\033[1m%s\033[0m" % title if color else title)
                     + ("  " + " · ".join(details) if details else ""))
        for w in p["windows"]:
            left = 100 - w["used"]
            meter = bar(w["used"]) if color else ""
            reset = until(w.get("resets_at"))
            lines.append("  %-14s %s %5.1f%% used  %5.1f%% left%s" % (
                w["label"], meter, w["used"], left, ("  resets in " + reset) if reset and reset != "resetting"
                else ("  " + reset if reset else "")))
        for note in p["notes"]:
            lines.append("  " + note)
        if p.get("error"):
            lines.append(("  \033[31m! %s\033[0m" if color else "  ! %s") % p["error"])
        lines.append("")
    if not data["providers"]:
        lines.append("No Claude Code, Codex or Gemini login found on this machine.")
    stamp = datetime.fromtimestamp(data["fetched_at"]).strftime("%H:%M:%S")
    lines.append(("\033[2mupdated %s\033[0m" if color else "updated %s") % stamp)
    return "\n".join(lines)


# ---------------------------------------------------------------- commands


def cmd_status(args):
    data = cached(0)
    if "--json" in args:
        print(json.dumps(data, indent=2))
    else:
        print(render(data, color=sys.stdout.isatty()))
    return 0


def cmd_dashboard(_args):
    import select
    import termios
    import tty

    fd = sys.stdin.fileno()
    saved = termios.tcgetattr(fd)
    refresh_every = 60
    try:
        tty.setcbreak(fd)
        sys.stdout.write("\033[?25l")
        force = True
        data = None
        while True:
            if force or data is None or time.time() - data["fetched_at"] >= refresh_every:
                sys.stdout.write("\033[H\033[2J\033[2mfetching…\033[0m")
                sys.stdout.flush()
                data = cached(0 if force else refresh_every)
                force = False
            sys.stdout.write("\033[H\033[2J\033[1mLLM usage\033[0m   \033[2mr refresh · q close\033[0m\n\n")
            sys.stdout.write(render(data).replace("\n", "\r\n") + "\r\n")
            sys.stdout.flush()
            ready, _, _ = select.select([sys.stdin], [], [], 30)
            if ready:
                key = os.read(fd, 1)
                if key in (b"q", b"Q", b"\x1b", b"\x03"):
                    return 0
                if key in (b"r", b"R"):
                    force = True
    finally:
        sys.stdout.write("\033[?25h")
        sys.stdout.flush()
        termios.tcsetattr(fd, termios.TCSADRAIN, saved)


def herdr(*args):
    binary = os.environ.get("HERDR_BIN_PATH") or "herdr"
    return subprocess.run([binary, *args], capture_output=True, text=True, timeout=10)


def sidebar_tokens(provider):
    windows = provider["windows"]
    tokens = {"usage": None, "usage_5h": None, "usage_week": None, "usage_account": provider.get("account")}
    if provider.get("error") and not windows:
        tokens["usage"] = "usage: " + provider["error"][:60]
        return tokens
    parts = []
    for w in windows:
        if w["label"] == "5h":
            tokens["usage_5h"] = "%d" % round(w["used"])
        elif w["label"] == "week":
            tokens["usage_week"] = "%d" % round(w["used"])
        else:
            continue
        reset = until(w.get("resets_at"))
        parts.append("%s %d%%%s" % (w["label"], round(w["used"]), (" ↻" + reset) if reset else ""))
    tokens["usage"] = " · ".join(parts) or None
    return tokens


def cmd_sidebar(_args):
    listing = herdr("agent", "list")
    if listing.returncode != 0:
        print(listing.stderr.strip(), file=sys.stderr)
        return 1
    try:
        agents = (json.loads(listing.stdout).get("result") or {}).get("agents") or []
    except ValueError:
        return 1
    wanted = {AGENT_PROVIDERS.get(a.get("agent")) for a in agents} - {None}
    if not wanted:
        return 0
    # A fresh server has no tokens on its panes, and the refresh action asks for new numbers.
    fresh_start = os.environ.get("HERDR_PLUGIN_EVENT") == "startup"
    manual = bool(os.environ.get("HERDR_PLUGIN_ACTION_ID"))
    data = cached(0 if manual else CACHE_TTL)
    by_provider = {p["provider"]: p for p in data["providers"]}
    reported = {} if fresh_start or manual else read_json(state_dir() / "reported.json") or {}
    for agent in agents:
        provider = by_provider.get(AGENT_PROVIDERS.get(agent.get("agent")))
        pane = agent.get("pane_id")
        if not provider or not pane:
            continue
        tokens = sidebar_tokens(provider)
        key = json.dumps([tokens, data["fetched_at"]], sort_keys=True)
        if reported.get(pane) == key:
            continue
        args = ["pane", "report-metadata", pane, "--source", SOURCE, "--ttl-ms", str(TOKEN_TTL_MS)]
        for name, value in tokens.items():
            args += ["--token", "%s=%s" % (name, value)] if value else ["--clear-token", name]
        if herdr(*args).returncode == 0:
            reported[pane] = key
    (state_dir() / "reported.json").write_text(json.dumps(reported))
    return 0


def cmd_open(_args):
    plugin = os.environ.get("HERDR_PLUGIN_ID") or "llm-usage"
    opened = herdr("plugin", "pane", "open", "--plugin", plugin, "--entrypoint", "dashboard")
    if opened.returncode != 0:
        print(opened.stderr.strip(), file=sys.stderr)
    return opened.returncode


def main(argv):
    commands = {"status": cmd_status, "dashboard": cmd_dashboard, "sidebar": cmd_sidebar, "open": cmd_open}
    if not argv or argv[0] not in commands:
        print(__doc__.strip())
        return 2
    return commands[argv[0]](argv[1:])


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
