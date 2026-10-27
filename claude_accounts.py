"""Claude Code accounts through claude-swap (`cswap`), plus the plugin settings.

cswap swaps the stored login underneath Claude Code while holding Claude Code's
own credential locks, so running sessions keep going and use the new account
on their next request (Linux) or within about 30 seconds (macOS Keychain
cache). Without cswap installed, only the signed-in account is shown.
"""

import json
import os
import shutil
import subprocess
import time
from datetime import datetime
from pathlib import Path

CSWAP_TIMEOUT = 120
AUTO_INTERVAL = 60  # seconds between auto-switch checks
SWITCH_COOLDOWN = 10 * 60  # soonest-reset: seconds after a switch before the next
PREFER_MARGIN = 6 * 3600  # soonest-reset: how much earlier a reset must be to move off a usable account

# uv, pipx and Homebrew put tools here, and herdr's server may not have them on PATH.
EXTRA_PATHS = ("~/.local/bin", "~/.cargo/bin", "/opt/homebrew/bin", "/usr/local/bin")

DEFAULT_SETTINGS = {"auto_switch": False, "threshold": 90, "strategy": "best", "model": None}
STRATEGIES = ("best", "soonest-reset")


# ---------------------------------------------------------------- settings


def config_path():
    directory = os.environ.get("HERDR_PLUGIN_CONFIG_DIR") or Path.home() / ".config" / "herdr-llm-usage"
    Path(directory).mkdir(parents=True, exist_ok=True)
    return Path(directory) / "config.json"


def settings():
    try:
        stored = json.loads(config_path().read_text())
    except (OSError, ValueError):
        stored = {}
    return dict(DEFAULT_SETTINGS, **{k: v for k, v in stored.items() if k in DEFAULT_SETTINGS})


def save_settings(values):
    config_path().write_text(json.dumps(values, indent=2) + "\n")


def state_dir():
    path = Path(os.environ.get("HERDR_PLUGIN_STATE_DIR") or Path.home() / ".cache" / "herdr-llm-usage")
    path.mkdir(parents=True, exist_ok=True)
    return path


# ---------------------------------------------------------------- cswap


def cswap_path():
    found = shutil.which("cswap")
    if found:
        return found
    for directory in EXTRA_PATHS:
        candidate = Path(directory).expanduser() / "cswap"
        if candidate.is_file() and os.access(candidate, os.X_OK):
            return str(candidate)
    return None


def cswap(*args, timeout=CSWAP_TIMEOUT):
    binary = cswap_path()
    if not binary:
        raise RuntimeError("cswap not found; install it with `uv tool install claude-swap`")
    # No stdin: a prompt would otherwise hang a background hook until the timeout.
    return subprocess.run([binary, *args], capture_output=True, text=True, timeout=timeout,
                          stdin=subprocess.DEVNULL)


def herdr(*args):
    binary = os.environ.get("HERDR_BIN_PATH") or "herdr"
    return subprocess.run([binary, *args], capture_output=True, text=True, timeout=10)


def notify(title, body=""):
    args = ["notification", "show", title]
    if body:
        args += ["--body", body]
    herdr(*args)


def active_email():
    """The signed-in account as Claude Code records it; no network, no cswap."""
    configured = os.environ.get("CLAUDE_CONFIG_DIR")
    path = Path(configured) / ".claude.json" if configured else Path.home() / ".claude.json"
    try:
        account = json.loads(path.read_text()).get("oauthAccount") or {}
    except (OSError, ValueError):
        return None
    return account.get("emailAddress")


def accounts():
    """Rows of `cswap list --json`: number, email, active, usageStatus, usage, alias, disabled."""
    result = cswap("list", "--json")
    try:
        payload = json.loads(result.stdout)
    except ValueError:
        raise RuntimeError(result.stderr.strip()[:200] or "cswap list failed")
    if isinstance(payload.get("error"), dict):
        raise RuntimeError(payload["error"].get("message") or "cswap list failed")
    return payload.get("accounts") or []


def switch(target):
    """Switch to an account number (as a string); returns (switched, message)."""
    result = cswap("switch", str(target), "--json")
    try:
        payload = json.loads(result.stdout)
    except ValueError:
        payload = {}
    if result.returncode != 0 or payload.get("error"):
        error = payload.get("error")
        message = error.get("message") if isinstance(error, dict) else None
        raise RuntimeError(message or result.stderr.strip()[:200] or "cswap switch failed")
    email = (payload.get("to") or {}).get("email") or "?"
    return bool(payload.get("switched")), email


def save_current():
    result = cswap("add")
    lines = (result.stdout + result.stderr).strip().splitlines()
    if result.returncode != 0:
        raise RuntimeError(lines[-1] if lines else "cswap add failed")
    return lines[-1] if lines else "saved"


# ---------------------------------------------------------------- strategy


def iso_epoch(value):
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00")).timestamp()
    except ValueError:
        return None


def window_pcts(account, model):
    usage = account.get("usage") or {}
    pcts = [(usage.get(key) or {}).get("pct") for key in ("fiveHour", "sevenDay")]
    if model:
        pcts += [w.get("pct") for w in usage.get("scoped") or [] if (w.get("name") or "").lower() == model.lower()]
    return [p for p in pcts if p is not None]


def usable(account, threshold, model):
    if account.get("disabled") or account.get("usageStatus") != "ok":
        return False
    pcts = window_pcts(account, model)
    return bool(pcts) and max(pcts) < threshold


def week_reset(account):
    week = (account.get("usage") or {}).get("sevenDay") or {}
    return iso_epoch(week.get("resetsAt")) or float("inf")  # no window yet: nothing to lose


def pick(rows, values):
    """The account the configured strategy wants, or None when none is usable."""
    threshold, model = float(values["threshold"]), values.get("model")
    candidates = [a for a in rows if usable(a, threshold, model)]
    if not candidates:
        return None
    if values["strategy"] == "soonest-reset":
        # Spend the weekly quota that resets first, before it is lost.
        return min(candidates, key=lambda a: (week_reset(a), ((a.get("usage") or {}).get("sevenDay") or {}).get("pct") or 0))
    return min(candidates, key=lambda a: max(window_pcts(a, model)))


def auto_tick():
    """One auto-switch check, at most every AUTO_INTERVAL seconds, when enabled."""
    values = settings()
    if not values["auto_switch"] or not cswap_path():
        return
    stamp = state_dir() / "auto.last"
    try:
        if time.time() - stamp.stat().st_mtime < AUTO_INTERVAL:
            return
    except OSError:
        pass
    stamp.touch()
    if values["strategy"] != "soonest-reset":
        auto_best(values)
    else:
        auto_soonest_reset(values)


def auto_best(values):
    """cswap's own auto-switch: most headroom, with its cooldown and hysteresis."""
    args = ["auto", "--once", "--json", "--threshold", str(values["threshold"])]
    if values.get("model"):
        args += ["--model", str(values["model"])]
    try:
        result = cswap(*args)
    except (RuntimeError, subprocess.SubprocessError):
        return
    if result.returncode == 0:  # switched
        target = "?"
        for line in result.stdout.splitlines():
            try:
                target = (json.loads(line).get("to") or {}).get("email") or target
            except ValueError:
                continue
        notify("Claude auto-switched → " + target, "The previous account reached %s%%." % values["threshold"])
    elif result.returncode == 3:  # every account exhausted
        notify("All Claude accounts are near their limits", "No account has quota left to switch to.")


def auto_soonest_reset(values):
    """Move to the account whose weekly quota resets soonest, when that is worth a switch.

    Switches when the active account is at the threshold, or when another usable
    account's weekly reset comes more than PREFER_MARGIN earlier. A switch is
    followed by SWITCH_COOLDOWN without another, so nothing flip-flops.
    """
    stamp = state_dir() / "auto.switched"
    try:
        if time.time() - stamp.stat().st_mtime < SWITCH_COOLDOWN:
            return
    except OSError:
        pass
    try:
        rows = accounts()
    except (RuntimeError, subprocess.SubprocessError):
        return
    active = next((a for a in rows if a.get("active")), None)
    if not active or active.get("usageStatus") != "ok":
        return  # unknown usage: hold, as cswap auto does
    active_full = not usable(active, float(values["threshold"]), values.get("model"))
    target = pick(rows, values)
    if not target:
        if active_full:
            notify("All Claude accounts are near their limits", "No account has quota left to switch to.")
        return
    if target.get("number") == active.get("number"):
        return
    if not active_full and week_reset(target) > week_reset(active) - PREFER_MARGIN:
        return
    try:
        switched, email = switch(target["number"])
    except (RuntimeError, subprocess.SubprocessError) as exc:
        notify("Claude auto-switch failed", str(exc))
        return
    if switched:
        stamp.touch()
        notify("Claude auto-switched → " + email, "Its weekly quota resets soonest.")
