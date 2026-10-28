"""What each agent pane is using: tools, skills, markdown files, instructions, memory, context.

Reads the session transcripts Claude Code and Codex keep on this machine; herdr
reports each pane's session id (`herdr integration install claude|codex`).
Nothing leaves the machine. Transcripts are read incrementally: each session's
running totals and read offset are cached in the plugin state directory, so a
refresh only parses lines written since the last one.

The transcript formats are not public APIs. Anything unexpected is skipped,
and a pane whose transcript cannot be read shows why instead of failing.
"""

import json
import os
import re
import time
from pathlib import Path

CACHE_VERSION = 1
MAX_RECENT = 12  # markdown files and skills kept per session, newest first
MD_PATH = re.compile(r"""(?:^|[\s'"=(])((?:~|\.{0,2}/)?[\w@.~/+-]*\.md)\b""")


def state_dir():
    path = Path(os.environ.get("HERDR_PLUGIN_STATE_DIR") or Path.home() / ".cache" / "herdr-llm-usage") / "activity"
    path.mkdir(parents=True, exist_ok=True)
    return path


def claude_home():
    return Path(os.environ.get("CLAUDE_CONFIG_DIR") or Path.home() / ".claude")


def codex_home():
    return Path(os.environ.get("CODEX_HOME") or Path.home() / ".codex")


# ---------------------------------------------------------------- transcripts


def find_transcript(agent, session_id, cwd):
    """(path, guessed) for a pane's session, or (None, reason)."""
    if agent == "claude":
        projects = claude_home() / "projects"
        if session_id:
            found = sorted(projects.glob("*/%s.jsonl" % session_id))
            if found:
                return found[0], False
        if cwd:  # no session id: newest transcript of the pane's project
            folder = projects / re.sub(r"[^A-Za-z0-9]", "-", cwd)
            candidates = sorted(folder.glob("*.jsonl"), key=lambda p: p.stat().st_mtime, reverse=True)
            if candidates:
                return candidates[0], True
        return None, "no transcript (install `herdr integration install claude` for session ids)"
    if agent == "codex":
        if not session_id:
            return None, "no session id (run `herdr integration install codex`)"
        cached = _codex_paths().get(session_id)
        if cached and Path(cached).exists():
            return Path(cached), False
        sessions = codex_home() / "sessions"
        # Newest day folders first; a running session is almost always recent.
        for root, dirs, files in os.walk(sessions):
            dirs.sort(reverse=True)
            for name in files:
                if name.endswith(session_id + ".jsonl"):
                    path = Path(root) / name
                    _remember_codex_path(session_id, path)
                    return path, False
        return None, "transcript not found under %s" % sessions
    return None, "not supported for %s" % agent


def _codex_paths():
    try:
        return json.loads((state_dir() / "codex-paths.json").read_text())
    except (OSError, ValueError):
        return {}


def _remember_codex_path(session_id, path):
    paths = _codex_paths()
    paths[session_id] = str(path)
    (state_dir() / "codex-paths.json").write_text(json.dumps(paths))


def empty_stats():
    return {"tools": {}, "skills": [], "md_files": [], "pending": {}, "context": None,
            "context_window": None, "last_tool": None, "last_at": None, "model": None}


def _push_recent(items, value):
    if value in items:
        items.remove(value)
    items.insert(0, value)
    del items[MAX_RECENT:]


def _count(stats, name):
    stats["tools"][name] = stats["tools"].get(name, 0) + 1
    stats["last_tool"] = name


def _start(stats, call_id, name):
    pending = stats["pending"]
    pending[call_id] = name
    for stale in list(pending)[:-20]:  # calls whose results were never written (interrupted turns)
        pending.pop(stale)


def _md_in(text):
    return [m for m in MD_PATH.findall(text or "") if len(m) > 3]


def apply_claude(stats, entry):
    message = entry.get("message") or {}
    if entry.get("type") == "assistant":
        usage = message.get("usage") or {}
        if usage:
            stats["context"] = sum(usage.get(k) or 0 for k in
                                   ("input_tokens", "cache_creation_input_tokens", "cache_read_input_tokens"))
        stats["model"] = message.get("model") or stats["model"]
    for part in message.get("content") or [] if isinstance(message.get("content"), list) else []:
        if not isinstance(part, dict):
            continue
        if part.get("type") == "tool_use":
            name = part.get("name") or "?"
            data = part.get("input") or {}
            _count(stats, name)
            _start(stats, part.get("id") or name, name)
            if name == "Skill":
                skill = data.get("skill") or data.get("command") or data.get("name")
                if skill:
                    _push_recent(stats["skills"], str(skill))
            path = data.get("file_path") or data.get("path") or ""
            if isinstance(path, str) and path.endswith(".md"):
                _push_recent(stats["md_files"], path)
                if path.endswith("SKILL.md"):
                    _push_recent(stats["skills"], Path(path).parent.name)
        elif part.get("type") == "tool_result":
            stats["pending"].pop(part.get("tool_use_id"), None)
    stats["last_at"] = entry.get("timestamp") or stats["last_at"]


def apply_codex(stats, entry):
    kind, payload = entry.get("type"), entry.get("payload") or {}
    if kind == "response_item":
        item = payload.get("type")
        if item in ("function_call", "custom_tool_call", "local_shell_call", "web_search_call", "tool_search_call"):
            name = payload.get("name") or item.replace("_call", "")
            if payload.get("namespace"):
                name = "%s.%s" % (payload["namespace"], name)
            _count(stats, name)
            if payload.get("call_id"):
                _start(stats, payload["call_id"], name)
            text = payload.get("arguments") or payload.get("input") or json.dumps(payload.get("action") or "")
            for path in _md_in(text if isinstance(text, str) else json.dumps(text)):
                _push_recent(stats["md_files"], path)
                if path.endswith("SKILL.md"):
                    _push_recent(stats["skills"], Path(path).parent.name)
        elif item in ("function_call_output", "custom_tool_call_output", "tool_search_output"):
            stats["pending"].pop(payload.get("call_id"), None)
    elif kind == "event_msg" and payload.get("type") == "token_count":
        info = payload.get("info") or {}
        last = info.get("last_token_usage") or {}
        if last.get("input_tokens") is not None:
            stats["context"] = last["input_tokens"]
        stats["context_window"] = info.get("model_context_window") or stats["context_window"]
    elif kind == "turn_context":
        stats["model"] = payload.get("model") or stats["model"]
    stats["last_at"] = entry.get("timestamp") or stats["last_at"]


def read_session(agent, path):
    """Running totals for a transcript, parsing only what was appended since last time."""
    cache_path = state_dir() / ("%s-%s.json" % (agent, path.stem[-48:]))
    try:
        cache = json.loads(cache_path.read_text())
    except (OSError, ValueError):
        cache = {}
    size = path.stat().st_size
    if cache.get("version") != CACHE_VERSION or cache.get("path") != str(path) or cache.get("offset", 0) > size:
        cache = {"version": CACHE_VERSION, "path": str(path), "offset": 0, "stats": empty_stats()}
    stats, apply = cache["stats"], apply_claude if agent == "claude" else apply_codex
    with open(path, "rb") as handle:
        handle.seek(cache["offset"])
        chunk = handle.read()
    end = chunk.rfind(b"\n") + 1  # leave a line still being written for next time
    for line in chunk[:end].splitlines():
        try:
            entry = json.loads(line)
        except ValueError:
            continue
        if isinstance(entry, dict):
            apply(stats, entry)
    cache["offset"] += end
    if end:
        tmp = cache_path.with_suffix(".tmp")
        tmp.write_text(json.dumps(cache))
        os.replace(tmp, cache_path)
    return stats


# ---------------------------------------------------------------- files around a session


def instruction_files(agent, cwd):
    """Instruction files the agent loads for this directory, by the CLI's documented lookup."""
    found = []
    if agent == "claude":
        found += [claude_home() / "CLAUDE.md"]
        folders = list(reversed([Path(cwd)] + list(Path(cwd).parents))) if cwd else []
        for folder in folders:
            found += [folder / "CLAUDE.md", folder / "CLAUDE.local.md", folder / ".claude" / "CLAUDE.md"]
        if cwd:
            found += sorted((Path(cwd) / ".claude" / "rules").glob("**/*.md"))
    elif agent == "codex":
        found += [codex_home() / "AGENTS.override.md", codex_home() / "AGENTS.md"]
        folders = list(reversed([Path(cwd)] + list(Path(cwd).parents))) if cwd else []
        for folder in folders:
            found += [folder / "AGENTS.override.md", folder / "AGENTS.md"]
    seen, result = set(), []
    for path in found:
        if path.is_file() and path not in seen:
            seen.add(path)
            result.append(path)
    return result


def memory_files(agent, transcript):
    """Claude's auto memory for the transcript's project, newest first."""
    if agent != "claude" or not transcript:
        return []
    folder = transcript.parent / "memory"
    files = [p for p in folder.glob("**/*.md") if p.is_file()]
    return sorted(files, key=lambda p: p.stat().st_mtime, reverse=True)


def mcp_servers(tools):
    servers = {}
    for name, count in tools.items():
        if name.startswith("mcp__"):
            server = name.split("__")[1] if name.count("__") >= 2 else name
            servers[server] = servers.get(server, 0) + count
    return servers


# ---------------------------------------------------------------- per pane


def pane_activity(agent_info):
    """Everything the Agents tab shows for one herdr agent entry."""
    agent = agent_info.get("agent")
    session = agent_info.get("agent_session") or {}
    session_id = session.get("value") if session.get("kind") == "id" else None
    cwd = agent_info.get("foreground_cwd") or agent_info.get("cwd")
    result = {"pane": agent_info.get("pane_id"), "agent": agent, "status": agent_info.get("agent_status"),
              "cwd": cwd, "session": session_id, "error": None, "guessed": False}
    try:
        path, extra = find_transcript(agent, session_id, cwd)
        if path is None:
            result["error"] = extra
            stats = empty_stats()
        else:
            result["guessed"] = extra
            stats = read_session(agent, path)
        result.update(stats)
        result["running"] = list(stats["pending"].values())[-1:] if stats["pending"] else []
        result["instructions"] = [str(p) for p in instruction_files(agent, cwd)]
        result["memory"] = [str(p) for p in memory_files(agent, path)]
        result["mcp"] = mcp_servers(stats["tools"])
        result["transcript"] = str(path) if path else None
    except (OSError, ValueError) as exc:
        result["error"] = "%s: %s" % (type(exc).__name__, exc)
    return result


def current_tool(activity):
    """Short label for the sidebar: the running tool, or nothing when the agent is idle."""
    if activity.get("status") != "working" or not activity.get("running"):
        return None
    name = activity["running"][0]
    if name.startswith("mcp__") and name.count("__") >= 2:
        _, server, tool = name.split("__", 2)
        return "%s:%s" % (server, tool)
    return name


def short_tokens(count):
    if count is None:
        return None
    return "%dk" % round(count / 1000.0) if count >= 1000 else str(count)


def context_label(activity):
    used, window = activity.get("context"), activity.get("context_window")
    if used is None:
        return None
    if window:
        return "ctx %d%%" % round(100.0 * used / window)
    return "ctx " + short_tokens(used)


def sidebar_values(activity):
    """The short strings the sidebar shows for a pane."""
    return {"tool": current_tool(activity), "skill": (activity.get("skills") or [None])[0],
            "ctx": context_label(activity)}


def age(timestamp):
    if not timestamp:
        return None
    try:
        from datetime import datetime

        then = datetime.fromisoformat(str(timestamp).replace("Z", "+00:00")).timestamp()
    except ValueError:
        return None
    return max(0, time.time() - then)
