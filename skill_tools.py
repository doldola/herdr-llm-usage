"""Manage the skills an agent session can use: find unused or doubtful ones, disable, undo.

Skills are folders holding a SKILL.md, in the user's and the project's skills
folders (and in plugins, which their plugin manages). Disabling moves a skill
folder to a "skills-disabled" folder beside its skills folder, where the CLI
does not look, so it can be enabled again; every change can be undone.
"""

import json
import os
import shutil
import time
from pathlib import Path

import agent_activity
import agent_setup

UNUSED_DAYS = 30
MAX_TRANSCRIPTS = 300  # newest transcripts scanned for project-wide skill use


def state_dir():
    path = Path(os.environ.get("HERDR_PLUGIN_STATE_DIR") or Path.home() / ".cache" / "herdr-llm-usage")
    path.mkdir(parents=True, exist_ok=True)
    return path


def disabled_dir(skills_dir):
    return Path(skills_dir).parent / (Path(skills_dir).name + "-disabled")


def project_skill_uses(agent, transcript, days=UNUSED_DAYS):
    """Skill uses summed over the project's recent Claude sessions (this session's for Codex)."""
    if not transcript:
        return {}, 0
    transcript = Path(transcript)
    if agent != "claude":
        stats = agent_activity.read_session(agent, transcript)
        return dict(stats.get("skill_uses") or {}), 1
    since = time.time() - days * 86400
    files = sorted((p for p in transcript.parent.glob("*.jsonl") if p.stat().st_mtime >= since),
                   key=lambda p: -p.stat().st_mtime)[:MAX_TRANSCRIPTS]
    uses = {}
    for path in files:
        try:
            stats = agent_activity.read_session("claude", path)
        except (OSError, ValueError):
            continue
        for name, count in (stats.get("skill_uses") or {}).items():
            uses[name] = uses.get(name, 0) + count
    return uses, len(files)


def skill_dirs(agent, cwd):
    """(skills folder, source) pairs a user can manage for this agent's folder."""
    root = agent_setup.project_root(cwd)
    if agent == "claude":
        home = agent_setup.claude_home()
        dirs = [(home / "skills", "user")]
        for base in {Path(cwd) if cwd else None, root} - {None}:
            dirs.append((base / ".claude" / "skills", "project"))
    else:
        home = agent_setup.codex_home()
        dirs = [(home / "skills", "user")]
        if root:
            dirs += [(root / ".codex" / "skills", "project"), (root / ".agents" / "skills", "project")]
    return dirs


def scan(activity):
    """Every skill for the agent, enabled or disabled, with what may need attention."""
    agent, cwd = activity.get("agent"), activity.get("cwd")
    setup = agent_setup.setup_for(agent, cwd, activity.get("transcript")) or {}
    uses, sessions = project_skill_uses(agent, activity.get("transcript"))
    session_uses = activity.get("skill_uses") or {}
    entries = []
    for skill in setup.get("all_skills") or setup.get("skills") or []:
        entries.append(dict(skill, enabled=True))
    seen = {e["path"] for e in entries}
    for folder, source in skill_dirs(agent, cwd):  # disabled ones, so they can come back
        for skill in agent_setup.skills_in(disabled_dir(folder), source):
            if skill["path"] not in seen:
                entries.append(dict(skill, enabled=False))
    names = {}
    for entry in entries:
        names.setdefault(entry["name"], []).append(entry)
    for entry in entries:
        entry["uses"] = uses.get(entry["name"], 0)
        entry["session_uses"] = session_uses.get(entry["name"], 0)
        entry["duplicate"] = len([e for e in names[entry["name"]] if e["enabled"]]) > 1 and entry["enabled"]
        entry["lines"] = sum(1 for _ in open(entry["path"], "rb")) if os.path.isfile(entry["path"]) else 0
        entry["managed"] = not entry["source"].startswith("plugin")
    entries.sort(key=lambda e: (not e["enabled"], -e["session_uses"], -e["uses"], e["name"]))
    return {"entries": entries, "sessions": sessions, "agent": agent}


FILTERS = (
    ("all", lambda e: True),
    ("unused %dd" % UNUSED_DAYS, lambda e: e["enabled"] and not e["uses"] and not e["session_uses"]),
    ("duplicates", lambda e: e["duplicate"]),
    ("no description", lambda e: e["enabled"] and not e["description"]),
    ("disabled", lambda e: not e["enabled"]),
)


# ---------------------------------------------------------------- changes, each undoable


def _undo_path():
    return state_dir() / "skill-undo.json"


def _push_undo(step):
    try:
        steps = json.loads(_undo_path().read_text())
    except (OSError, ValueError):
        steps = []
    steps.append(step)
    _undo_path().write_text(json.dumps(steps[-50:]))


def _move(folder, target_parent):
    target = Path(target_parent) / Path(folder).name
    if target.exists():
        raise ValueError("%s already exists" % target)
    Path(target_parent).mkdir(parents=True, exist_ok=True)
    shutil.move(str(folder), str(target))
    return target


def disable(entry):
    if not entry["managed"]:
        raise ValueError("%s comes from %s; turn the plugin off with /plugin in Claude Code"
                         % (entry["name"], entry["source"]))
    folder = Path(entry["path"]).parent
    target = _move(folder, disabled_dir(folder.parent))
    _push_undo({"from": str(folder), "to": str(target), "name": entry["name"]})
    return target


def enable(entry):
    folder = Path(entry["path"]).parent  # inside a skills-disabled folder
    skills_dir = folder.parent.parent / folder.parent.name[:-len("-disabled")]
    target = _move(folder, skills_dir)
    _push_undo({"from": str(folder), "to": str(target), "name": entry["name"]})
    return target


def undo():
    try:
        steps = json.loads(_undo_path().read_text())
    except (OSError, ValueError):
        return None
    if not steps:
        return None
    step = steps.pop()
    _move(step["to"], Path(step["from"]).parent)
    _undo_path().write_text(json.dumps(steps))
    return "undid the move of " + step["name"]
