"""Codex accounts: saved ChatGPT logins swapped into ~/.codex/auth.json.

A running Codex keeps the login it started with, so after a swap every Codex
pane is restarted in place, once it is idle, with `codex <same options> resume
<session>`. The conversation continues; only the process is new.

Accounts are stored next to Codex's own login, in $CODEX_HOME/accounts/, with
the same file permissions.
"""

import base64
import fcntl
import json
import os
import re
import shlex
import subprocess
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

USAGE_URLS = (
    "https://chatgpt.com/backend-api/wham/usage",
    "https://chatgpt.com/backend-api/codex/usage",
)
WAIT_FOR_IDLE = 3 * 3600  # seconds a pane may stay busy before its restart is given up
EXIT_TIMEOUT = 20

# Codex options that take a value; anything else starting with "-" is a flag.
VALUE_OPTIONS = {
    "-m", "--model", "-c", "--config", "-p", "--profile", "-s", "--sandbox",
    "-a", "--ask-for-approval", "-C", "--cd", "-i", "--image", "--add-dir",
    "--local-provider", "--enable", "--disable", "--remote", "--remote-auth-token-env",
}
SUBCOMMANDS = {"resume", "fork"}


class CodexError(Exception):
    pass


# ---------------------------------------------------------------- storage


def home():
    return Path(os.environ.get("CODEX_HOME") or Path.home() / ".codex")


def auth_file():
    return home() / "auth.json"


def accounts_dir():
    path = home() / "accounts"
    path.mkdir(mode=0o700, parents=True, exist_ok=True)
    return path


def read_json(path):
    try:
        return json.loads(Path(path).read_text())
    except (OSError, ValueError):
        return None


def write_private(path, data):
    """Write JSON readable only by the user, replacing the file atomically."""
    path = Path(path)
    tmp = path.with_name("." + path.name + ".tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as handle:
        json.dump(data, handle, indent=2)
    os.replace(tmp, path)


def check_file_storage():
    config = home() / "config.toml"
    try:
        text = config.read_text()
    except OSError:
        return
    match = re.search(r'^\s*cli_auth_credentials_store\s*=\s*"(\w+)"', text, re.M)
    if match and match.group(1) != "file":
        raise CodexError("Codex stores its login in the %s, not auth.json; set "
                         'cli_auth_credentials_store = "file" in %s' % (match.group(1), config))


def claims(auth):
    token = ((auth or {}).get("tokens") or {}).get("id_token") or ""
    try:
        payload = token.split(".")[1]
        return json.loads(base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4)))
    except (IndexError, ValueError):
        return {}


def identity(auth):
    """(account key, email, plan) for a stored or live auth.json."""
    info = claims(auth)
    openai = info.get("https://api.openai.com/auth") or {}
    account_id = ((auth or {}).get("tokens") or {}).get("account_id") or openai.get("chatgpt_account_id")
    email = info.get("email")
    if not account_id or not email:
        return None, email, None
    return account_id, email, openai.get("chatgpt_plan_type")


def slot_path(account_id):
    return accounts_dir() / (re.sub(r"[^A-Za-z0-9_-]", "_", account_id) + ".json")


def saved_accounts():
    accounts = []
    for path in sorted(accounts_dir().glob("*.json")):
        auth = read_json(path)
        account_id, email, plan = identity(auth)
        if account_id:
            accounts.append({"id": account_id, "email": email, "plan": plan, "auth": auth, "path": path})
    accounts.sort(key=lambda a: (a["email"] or "", a["id"]))
    return accounts


def live_auth():
    return read_json(auth_file())


def save_live():
    """Store the login Codex is using now; returns its email."""
    check_file_storage()
    auth = live_auth()
    account_id, email, _plan = identity(auth)
    if not account_id:
        raise CodexError("Codex is not signed in with ChatGPT (no tokens in %s)" % auth_file())
    write_private(slot_path(account_id), auth)
    return email


def remove(account_id):
    slot_path(account_id).unlink()


# ---------------------------------------------------------------- usage


def usage(auth):
    """{'5h': pct, 'week': pct, ...} or an error string. Never refreshes tokens."""
    tokens = (auth or {}).get("tokens") or {}
    if not tokens.get("access_token"):
        return "no token"
    headers = {"Authorization": "Bearer " + tokens["access_token"], "User-Agent": "codex-cli"}
    if tokens.get("account_id"):
        headers["chatgpt-account-id"] = tokens["account_id"]
    for url in USAGE_URLS:
        try:
            request = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(request, timeout=10) as response:
                data = json.loads(response.read().decode("utf-8"))
            break
        except urllib.error.HTTPError as exc:
            if exc.code == 404:
                continue
            return "token expired" if exc.code == 401 else "HTTP %d" % exc.code
        except (urllib.error.URLError, OSError, ValueError):
            return "unreachable"
    else:
        return "unavailable"
    windows = {}
    for kind in ("primary", "secondary"):
        entry = ((data.get("rate_limit") or {}).get(kind + "_window")) or {}
        if entry.get("used_percent") is None:
            continue
        seconds = entry.get("limit_window_seconds") or 0
        label = "5h" if abs(seconds - 18000) <= 1800 else "week" if abs(seconds - 604800) <= 60480 else kind
        windows[label] = {"used": float(entry["used_percent"]), "resets_at": entry.get("reset_at")}
    return windows


def headroom(entry):
    """How much quota an account has left, by its tightest window."""
    if not isinstance(entry, dict) or not entry:
        return -1
    return 100 - max(w["used"] for w in entry.values())


# ---------------------------------------------------------------- switching


def herdr(*args):
    binary = os.environ.get("HERDR_BIN_PATH") or "herdr"
    return subprocess.run([binary, *args], capture_output=True, text=True, timeout=15)


def herdr_json(*args):
    result = herdr(*args)
    try:
        return json.loads(result.stdout).get("result") or {}
    except ValueError:
        return {}


def codex_agents():
    return [a for a in herdr_json("agent", "list").get("agents") or [] if a.get("agent") == "codex"]


def foreground(pane):
    """(codex process argv or None, whether the pane has a shell beneath it)."""
    info = herdr_json("pane", "process-info", "--pane", pane).get("process_info") or {}
    shell_pid = info.get("shell_pid")
    for process in info.get("foreground_processes") or []:
        argv = process.get("argv") or shlex.split(process.get("cmdline") or "")
        if any(Path(part).name.startswith("codex") for part in argv[:2]):
            return argv, process.get("pid") != shell_pid
    return None, True


def relaunch_args(argv):
    """The user's options from a running Codex command line, without session or prompt."""
    start = next((i for i, part in enumerate(argv) if Path(part).name.startswith("codex")), None)
    if start is None:
        return []
    args, kept, i = argv[start + 1:], [], 0
    while i < len(args):
        part = args[i]
        if part in SUBCOMMANDS:
            break  # the old session target follows; the new one is appended later
        if part in VALUE_OPTIONS and i + 1 < len(args):
            kept += [part, args[i + 1]]
            i += 2
            continue
        if part.startswith("-"):
            kept.append(part)
        # a bare word is the initial prompt, which must not be sent again
        i += 1
    return kept


def switch(account_id):
    """Make account_id the Codex login and schedule running panes to restart."""
    check_file_storage()
    target = next((a for a in saved_accounts() if a["id"] == account_id), None)
    if not target:
        raise CodexError("no saved Codex account %s" % account_id)
    live = live_auth()
    live_id, _email, _plan = identity(live)
    if live_id == account_id:
        return target["email"], False
    if live_id:
        write_private(slot_path(live_id), live)  # keep the freshest tokens of the account we leave
    write_private(auth_file(), target["auth"])
    schedule_restarts(account_id)
    return target["email"], True


def best_account():
    best, best_room = None, -2
    live_id, _e, _p = identity(live_auth())
    for account in saved_accounts():
        auth = live_auth() if account["id"] == live_id else account["auth"]
        room = headroom(usage(auth))
        if room > best_room:
            best, best_room = account, room
    return best


# ---------------------------------------------------------------- restarts


def state_dir():
    path = Path(os.environ.get("HERDR_PLUGIN_STATE_DIR") or Path.home() / ".cache" / "herdr-llm-usage")
    path.mkdir(parents=True, exist_ok=True)
    return path


def schedule_restarts(account_id):
    """Every Codex process running now started with another login; remember them."""
    pending = {}
    for agent in codex_agents():
        pane = agent.get("pane_id")
        argv, _has_shell = foreground(pane)
        if pane and argv:
            pending[pane] = {"argv": argv}
    write_private(state_dir() / "codex-restart.json", {"account": account_id, "panes": pending})
    opened = herdr("plugin", "action", "invoke", (os.environ.get("HERDR_PLUGIN_ID") or "llm-usage") + ".codex-restart")
    if opened.returncode != 0:
        run_restarts()  # outside herdr's action runner, do it here


def session_id(pane):
    agent = herdr_json("agent", "get", pane).get("agent") or {}
    session = agent.get("agent_session") or {}
    if session.get("agent") == "codex" and session.get("kind") == "id":
        return session.get("value"), agent.get("agent_status")
    return None, agent.get("agent_status")


def restart_pane(pane, argv, account_id, results):
    deadline = time.time() + WAIT_FOR_IDLE
    while True:
        sid, status = session_id(pane)
        if status is None:
            results[pane] = "closed"
            return
        if status in ("idle", "done"):
            break
        if time.time() > deadline:
            results[pane] = "still busy; restart it yourself"
            return
        time.sleep(3)
    if not sid:
        results[pane] = "no session id (run `herdr integration install codex`)"
        return
    current, has_shell = foreground(pane)
    if not current:
        results[pane] = "codex already exited"
        return
    if not has_shell:
        results[pane] = "codex is the pane's own process; restart it yourself"
        return
    # A busy old process may have refreshed its token and rewritten auth.json meanwhile.
    live = live_auth()
    live_id, _e, _p = identity(live)
    if live_id != account_id:
        if live_id:
            write_private(slot_path(live_id), live)
        target = read_json(slot_path(account_id))
        if target:
            write_private(auth_file(), target)
    herdr("agent", "prompt", pane, "/quit")
    for attempt in range(EXIT_TIMEOUT * 2):
        time.sleep(0.5)
        if foreground(pane)[0] is None:
            break
        if attempt == EXIT_TIMEOUT:
            herdr("pane", "send-keys", pane, "ctrl+c", "ctrl+c")
    else:
        results[pane] = "codex did not exit"
        return
    command = ["codex", *relaunch_args(argv), "resume", sid]
    herdr("pane", "run", pane, " ".join(shlex.quote(part) for part in command))
    results[pane] = "resumed"


def run_restarts():
    """Restart every pending Codex pane once it is idle. One runner at a time."""
    lock = open(state_dir() / "codex-restart.lock", "w")
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        return {}  # a runner is already waiting on the panes
    try:
        results = {}
        while True:
            plan = read_json(state_dir() / "codex-restart.json") or {}
            panes = {p: v for p, v in (plan.get("panes") or {}).items() if p not in results}
            if not panes:
                break
            threads = [threading.Thread(target=restart_pane, args=(pane, info["argv"], plan["account"], results))
                       for pane, info in panes.items()]
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join()
            # A newer switch while we waited lists panes again, including ones restarted above.
            latest = read_json(state_dir() / "codex-restart.json") or {}
            if latest == plan:
                break
            results = {p: r for p, r in results.items() if p not in (latest.get("panes") or {})}
        (state_dir() / "codex-restart.json").unlink(missing_ok=True)
        return results
    finally:
        lock.close()
