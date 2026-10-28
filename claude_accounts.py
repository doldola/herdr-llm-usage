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

DEFAULT_SETTINGS = {"auto_switch": False, "threshold": 90, "strategy": "best", "model": None,
                    "agent_monitor": False}
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


def note(kind, text):
    """Remember what a background hook last did, for the Settings tab."""
    path = state_dir() / "diagnostics.json"
    try:
        data = json.loads(path.read_text())
    except (OSError, ValueError):
        data = {}
    data[kind] = {"at": time.time(), "text": text}
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data))
    os.replace(tmp, path)


def clear_note(kind):
    data = diagnostics()
    if kind in data:
        data.pop(kind)
        path = state_dir() / "diagnostics.json"
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(data))
        os.replace(tmp, path)


def diagnostics():
    try:
        return json.loads((state_dir() / "diagnostics.json").read_text())
    except (OSError, ValueError):
        return {}


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


# ---------------------------------------------------------------- Claude Code hook

# Runs the plugin's tick action while Claude works (after tool calls) and when a
# turn ends, so the sidebar and auto-switch keep up during long turns, when no
# herdr agent-state event fires. The shell part allows one run a minute across
# all panes, returns at once (the action runs in the background), and does
# nothing outside herdr.
HOOK_MARKER = "llm-usage.tick"
HOOK_EVENTS = ("PostToolUse", "Stop")
HOOK_COMMAND = (
    '[ -n "$HERDR_PANE_ID" ] && command -v herdr >/dev/null 2>&1 || exit 0; '
    's="${TMPDIR:-/tmp}/herdr-llm-usage.tick"; n=$(date +%s); l=$(cat "$s" 2>/dev/null || echo 0); '
    '[ $((n - l)) -lt 60 ] && exit 0; echo "$n" > "$s"; '
    '(herdr plugin action invoke llm-usage.tick >/dev/null 2>&1 &); exit 0'
)


def claude_settings_path():
    return Path(os.environ.get("CLAUDE_CONFIG_DIR") or Path.home() / ".claude") / "settings.json"


def _claude_hooks():
    try:
        return json.loads(claude_settings_path().read_text()).get("hooks") or {}
    except (OSError, ValueError):
        return {}


def claude_hook_installed():
    hooks = _claude_hooks()
    return any(HOOK_MARKER in json.dumps(hooks.get(event) or []) for event in ("PostToolUse", "Stop"))


def claude_hook_current():
    """Whether the installed hook is this version's (every event, current command)."""
    hooks = _claude_hooks()
    return all(any(h.get("command") == HOOK_COMMAND for group in hooks.get(event) or []
                   for h in group.get("hooks") or [])
               for event in HOOK_EVENTS)


def set_claude_hook(enabled):
    """Add or remove the hooks in Claude Code's settings.json, keeping everything else."""
    path = claude_settings_path()
    try:
        text = path.read_text()
        data = json.loads(text)
    except FileNotFoundError:
        text, data = None, {}
    except ValueError:
        raise RuntimeError("%s is not valid JSON; not touching it" % path)
    hooks = data.setdefault("hooks", {})
    for event in ("PostToolUse", "Stop"):
        groups = [group for group in hooks.get(event) or [] if HOOK_MARKER not in json.dumps(group)]
        if enabled and event in HOOK_EVENTS:
            group = {"hooks": [{"type": "command", "command": HOOK_COMMAND}]}
            if event == "PostToolUse":
                group = dict({"matcher": "*"}, **group)
            groups.append(group)
        if groups:
            hooks[event] = groups
        else:
            hooks.pop(event, None)
    if not hooks:
        data.pop("hooks")
    backup = path.with_name(path.name + ".llm-usage.bak")
    if text is not None and not backup.exists():
        backup.write_text(text)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name("." + path.name + ".tmp")
    tmp.write_text(json.dumps(data, indent=2) + "\n")
    os.replace(tmp, path)


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


def auto_tick(force=False):
    """One auto-switch check, at most every AUTO_INTERVAL seconds, when enabled."""
    values = settings()
    if not values["auto_switch"]:
        return
    if not cswap_path():
        note("auto", "cswap not found on PATH or in ~/.local/bin")
        return
    stamp = state_dir() / "auto.last"
    try:
        if not force and time.time() - stamp.stat().st_mtime < AUTO_INTERVAL:
            return
    except OSError:
        pass
    stamp.touch()
    try:
        if values["strategy"] != "soonest-reset":
            auto_best(values)
        else:
            auto_soonest_reset(values)
    except Exception as exc:  # a hook has nowhere else to report
        note("auto", "error: %s: %s" % (type(exc).__name__, exc))
        raise


def auto_best(values):
    """cswap's own auto-switch: most headroom, with its cooldown and hysteresis."""
    args = ["auto", "--once", "--json", "--threshold", str(values["threshold"])]
    if values.get("model"):
        args += ["--model", str(values["model"])]
    try:
        result = cswap(*args)
    except (RuntimeError, subprocess.SubprocessError) as exc:
        note("auto", "cswap auto failed: %s" % exc)
        return
    if result.returncode == 0:  # switched
        target = "?"
        for line in result.stdout.splitlines():
            try:
                target = (json.loads(line).get("to") or {}).get("email") or target
            except ValueError:
                continue
        note("auto", "switched to " + target)
        notify("Claude auto-switched → " + target, "The previous account reached %s%%." % values["threshold"])
    elif result.returncode == 3:  # every account exhausted
        note("auto", "every account is at the threshold")
        notify("All Claude accounts are near their limits", "No account has quota left to switch to.")
    elif result.returncode == 2:
        note("auto", "no switch needed")
    else:
        note("auto", "cswap auto exited %d: %s" % (result.returncode, (result.stderr or result.stdout).strip()[-200:]))


def auto_soonest_reset(values):
    """Move to the account whose weekly quota resets soonest, when that is worth a switch.

    Switches when the active account is at the threshold, or when another usable
    account's weekly reset comes more than PREFER_MARGIN earlier. A switch is
    followed by SWITCH_COOLDOWN without another, so nothing flip-flops.
    """
    stamp = state_dir() / "auto.switched"
    try:
        left = SWITCH_COOLDOWN - (time.time() - stamp.stat().st_mtime)
        if left > 0:
            note("auto", "waiting %d min after the last switch" % (left // 60 + 1))
            return
    except OSError:
        pass
    try:
        rows = accounts()
    except (RuntimeError, subprocess.SubprocessError) as exc:
        note("auto", "cswap list failed: %s" % exc)
        return
    active = next((a for a in rows if a.get("active")), None)
    if not active:
        note("auto", "cswap reports no active account")
        return
    if active.get("usageStatus") != "ok":
        note("auto", "holding: active account usage is %s" % active.get("usageStatus"))
        return  # unknown usage: hold, as cswap auto does
    active_full = not usable(active, float(values["threshold"]), values.get("model"))
    target = pick(rows, values)
    if not target:
        note("auto", "every account is at the threshold" if active_full else "no other usable account")
        if active_full:
            notify("All Claude accounts are near their limits", "No account has quota left to switch to.")
        return
    if target.get("number") == active.get("number"):
        note("auto", "staying on %s (its weekly quota resets soonest)" % active.get("email"))
        return
    if not active_full and week_reset(target) > week_reset(active) - PREFER_MARGIN:
        note("auto", "staying on %s (below the threshold)" % active.get("email"))
        return
    try:
        switched, email = switch(target["number"])
    except (RuntimeError, subprocess.SubprocessError) as exc:
        note("auto", "switch to %s failed: %s" % (target.get("email"), exc))
        notify("Claude auto-switch failed", str(exc))
        return
    if switched:
        stamp.touch()
        note("auto", "switched to " + email)
        notify("Claude auto-switched → " + email, "Its weekly quota resets soonest.")
