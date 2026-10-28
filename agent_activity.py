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

CACHE_VERSION = 3
MAX_RECENT = 12  # markdown files and skills kept per session, newest first
MD_PATH = re.compile(r"""(?:^|[\s'"=(])((?:~|\.{0,2}/)?[\w@.~/+-]*\.md)\b""")
COMMAND_NAME = re.compile(r"<command-name>/?([^<\s]+)</command-name>")
MAX_FLOWS = 30  # workflows and subagents kept per session, newest last
FLOW_TITLE_KEYS = ("description", "name", "title", "workflow", "subject", "prompt")
NOTICE = re.compile(r"""(?i)(?:workflow|agent|task)\W{0,3}["'“]?(.{1,80}?)["'”]?\W{0,3}(?:has\s+)?(completed|finished|failed|cancelled|canceled|killed|stopped)""")
STATUS_TAG = re.compile(r"<status>\s*(\w+)\s*</status>")


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
    return {"tools": {}, "skills": [], "skill_uses": {}, "md_files": [], "pending": {}, "context": None,
            "context_window": None, "last_tool": None, "last_at": None, "model": None,
            "skill_at": {}, "turn_at": None, "flows": {}, "tasks": {}, "task_ids": {}, "task_list": None}


def skill_name(name):
    """The bare skill name: "plugin:skill" and "/skill" both become "skill"."""
    return str(name).strip().lstrip("/").split(":")[-1]


def _use_skill(stats, name, when=None):
    name = skill_name(name)
    if not name:
        return
    stats.setdefault("skill_at", {})[name] = when or stats.get("last_at")
    _push_recent(stats["skills"], name)
    stats["skill_uses"][name] = stats["skill_uses"].get(name, 0) + 1


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


def _text_of(content):
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "\n".join(_text_of(p.get("text") if p.get("type") == "text" else p.get("content"))
                         for p in content if isinstance(p, dict))
    return ""


FLOW_TOOLS = ("Agent", "Task")  # subagents; any tool with "workflow" in its name is a workflow
TASK_TOOLS = ("TaskCreate", "TaskUpdate", "TodoWrite")


def _flow_title(data):
    for key in FLOW_TITLE_KEYS:
        value = data.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip().splitlines()[0][:80]
    return None


def _start_flow(stats, call_id, name, data, when):
    kind = "agent" if name in FLOW_TOOLS else "workflow"
    flows = stats["flows"]
    flows[call_id] = {"kind": kind, "title": _flow_title(data) or data.get("subagent_type") or name,
                      "type": data.get("subagent_type") or data.get("model"), "status": "running",
                      "background": bool(data.get("run_in_background")), "at": when, "end": None}
    for stale in list(flows)[:-MAX_FLOWS]:
        flows.pop(stale)


def _finish_flow(stats, flow, status, when):
    if flow["status"] == "running":
        flow["status"], flow["end"] = status, when


def _flow_result(stats, call_id, part, when):
    flow = stats["flows"].get(call_id)
    if not flow:
        return
    text = _text_of(part.get("content")).lower()
    if part.get("is_error"):
        _finish_flow(stats, flow, "failed", when)
    elif flow["background"] or any(w in text for w in ("running in the background", "launched", "started in the background",
                                                         "is running", "agent id", "task id")):
        flow["background"] = True  # its result arrives later as a notice
    else:
        _finish_flow(stats, flow, "completed", when)


def _notice(stats, text, when):
    """Mark background workflows and agents done from the notices the CLI writes into the conversation."""
    status = None
    tag = STATUS_TAG.search(text)
    if tag:
        status = tag.group(1).lower()
    running = [f for f in stats["flows"].values() if f["status"] == "running" and f["background"]]
    if not running:
        return
    match = NOTICE.search(text)
    status = status or (match.group(2).lower() if match else None)
    if not status or status in ("running", "pending", "in_progress"):
        return
    status = "completed" if status in ("completed", "finished", "done", "success", "succeeded") else "failed"
    for flow in reversed(running):  # the newest flow whose title the notice names, else the only one running
        if flow["title"] and flow["title"].lower()[:40] in text.lower():
            _finish_flow(stats, flow, status, when)
            return
    if len(running) == 1:
        _finish_flow(stats, running[0], status, when)


def _task_call(stats, call_id, name, data):
    tasks = stats["tasks"]
    if name == "TodoWrite":
        stats["tasks"] = {str(i): {"subject": str(t.get("content") or t.get("subject") or "")[:80],
                                   "status": t.get("status") or "pending"}
                          for i, t in enumerate(data.get("todos") or []) if isinstance(t, dict)}
    elif name == "TaskCreate":
        tasks["call:" + str(call_id)] = {"subject": str(data.get("subject") or data.get("title") or "")[:80],
                                        "status": "pending"}
    elif name == "TaskUpdate":
        task_id = str(data.get("taskId") or data.get("task_id") or data.get("id") or "")
        key = stats["task_ids"].get(task_id, task_id)
        task = tasks.setdefault(key, {"subject": "#" + task_id, "status": "pending"})
        if data.get("subject"):
            task["subject"] = str(data["subject"])[:80]
        if data.get("status"):
            task["status"] = data["status"]
        if data.get("status") == "deleted":
            tasks.pop(key, None)


def _task_result(stats, call_id, part):
    key = "call:" + str(call_id)
    if key in stats["tasks"]:
        found = re.search(r"#\s*(\w+)", _text_of(part.get("content")))
        if found:
            stats["task_ids"][found.group(1)] = key


def _task_reminder(stats, attachment):
    items = attachment.get("content")
    if isinstance(items, list):
        stats["task_list"] = [{"subject": str(t.get("subject") or t.get("content") or t.get("title") or "")[:80],
                               "status": t.get("status") or "pending"} for t in items if isinstance(t, dict)]


def task_summary(activity):
    """(done, in progress, total) of the session's task list, or None."""
    tasks = activity.get("task_list")
    if tasks is None:
        tasks = list((activity.get("tasks") or {}).values())
    if not tasks:
        return None
    done = sum(1 for t in tasks if t["status"] in ("completed", "done"))
    doing = sum(1 for t in tasks if t["status"] == "in_progress")
    return done, doing, len(tasks), tasks


def apply_claude(stats, entry):
    for key, value in empty_stats().items():  # caches written before a field existed
        stats.setdefault(key, value)
    when = entry.get("timestamp") or stats["last_at"]
    if entry.get("type") == "attachment":
        attachment = entry.get("attachment") or {}
        if attachment.get("type") == "task_reminder":
            _task_reminder(stats, attachment)
        return
    message = entry.get("message") or {}
    if entry.get("type") == "user" and not entry.get("isSidechain"):
        content = message.get("content")
        is_result = isinstance(content, list) and any(isinstance(p, dict) and p.get("type") == "tool_result"
                                                      for p in content)
        text = _text_of(content)
        if not is_result and not entry.get("isMeta"):
            if not text.lstrip().startswith("<"):
                stats["turn_at"] = when  # a prompt the user typed starts a new turn
            for command in COMMAND_NAME.findall(text):
                stats["turn_at"] = when
                _use_skill(stats, command, when)
        if is_result or "orkflow" in text or "<task-notification>" in text or "<status>" in text:
            _notice(stats, text, when)
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
            call_id = part.get("id") or name
            _start(stats, call_id, name)
            if name in FLOW_TOOLS or "workflow" in name.lower():
                _start_flow(stats, call_id, name, data, when)
            elif name in TASK_TOOLS:
                _task_call(stats, call_id, name, data)
            if name == "Skill":
                skill = data.get("skill") or data.get("command") or data.get("name")
                if skill:
                    _use_skill(stats, str(skill), when)
            path = data.get("file_path") or data.get("path") or ""
            if isinstance(path, str) and path.endswith(".md"):
                _push_recent(stats["md_files"], path)
                if path.endswith("SKILL.md"):
                    _use_skill(stats, Path(path).parent.name, when)
        elif part.get("type") == "tool_result":
            call_id = part.get("tool_use_id")
            stats["pending"].pop(call_id, None)
            _flow_result(stats, call_id, part, when)
            _task_result(stats, call_id, part)
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
                    _use_skill(stats, Path(path).parent.name)
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


def turn_skill(activity):
    """The newest skill loaded since the user's last prompt; for Codex, the newest one."""
    skills, turn = activity.get("skills") or [], activity.get("turn_at")
    if not skills:
        return None
    if activity.get("agent") != "claude" or not turn:
        return skills[0]
    at = (activity.get("skill_at") or {}).get(skills[0])
    return skills[0] if at and str(at) >= str(turn) else None


def sidebar_values(activity):
    """The short strings the sidebar shows for a pane."""
    return {"tool": current_tool(activity), "skill": turn_skill(activity),
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
