"""Tidy a Claude Code project's memory: find what needs attention, archive, undo.

Claude keeps a project's memory as markdown files in
~/.claude/projects/<project>/memory/, with MEMORY.md as the index it loads at
session start. Every session of the project shares them, so nothing here
deletes: archiving moves a file to memory-archive/ next to memory/ (outside
what Claude reads) and drops its index line, and every change can be undone.
"""

import hashlib
import json
import os
import re
import shutil
import time
from pathlib import Path

INDEX = "MEMORY.md"
OLD_DAYS = 30
LINK = re.compile(r"\]\(([^)#\s]+\.md)\)")
FRONTMATTER = re.compile(r"^(name|description|title):\s*(.*)$")


def state_dir():
    path = Path(os.environ.get("HERDR_PLUGIN_STATE_DIR") or Path.home() / ".cache" / "herdr-llm-usage")
    path.mkdir(parents=True, exist_ok=True)
    return path


def _read(path):
    try:
        return Path(path).read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""


def summary(text):
    """A one-line description: the front matter's description, else the first heading or line."""
    lines = text.splitlines()
    if lines and lines[0].strip() == "---":
        meta = {}
        for line in lines[1:]:
            if line.strip() == "---":
                break
            match = FRONTMATTER.match(line.strip())
            if match:
                meta[match.group(1)] = match.group(2).strip().strip("'\"")
        if meta.get("description") or meta.get("title") or meta.get("name"):
            return meta.get("description") or meta.get("title") or meta.get("name")
    for line in lines:
        stripped = line.strip().lstrip("#").strip()
        if stripped and stripped != "---":
            return stripped
    return ""


def index_links(memory_dir):
    """File names MEMORY.md links to, in order."""
    return [m.group(1) for m in LINK.finditer(_read(Path(memory_dir) / INDEX))]


def scan(memory_dir):
    """Every memory file with what may need attention, plus the index's broken links."""
    memory_dir = Path(memory_dir)
    linked = {Path(name).as_posix() for name in index_links(memory_dir)}
    now, entries, by_title, by_hash = time.time(), [], {}, {}
    for path in sorted(memory_dir.glob("**/*.md")):
        if any(part.startswith(".") for part in path.relative_to(memory_dir).parts):
            continue
        text = _read(path)
        relative = path.relative_to(memory_dir).as_posix()
        stat = path.stat()
        entry = {"path": str(path), "name": relative, "size": stat.st_size, "lines": text.count("\n") + 1,
                 "mtime": stat.st_mtime, "summary": summary(text), "index": relative == INDEX,
                 "in_index": relative in linked, "old": now - stat.st_mtime > OLD_DAYS * 86400, "duplicate_of": []}
        entries.append(entry)
        if not entry["index"]:
            title = re.sub(r"[^a-z0-9가-힣]+", "", (entry["summary"] or relative).lower())
            by_title.setdefault(title, []).append(entry)
            by_hash.setdefault(hashlib.sha1(text.strip().encode()).hexdigest(), []).append(entry)
    for groups in (by_title, by_hash):
        for group in groups.values():
            if len(group) > 1:
                for entry in group:
                    entry["duplicate_of"] = sorted({e["name"] for e in group if e is not entry} | set(entry["duplicate_of"]))
    names = {e["name"] for e in entries}
    broken = [name for name in linked if name not in names]
    return {"dir": str(memory_dir), "entries": entries, "broken": sorted(broken),
            "size": sum(e["size"] for e in entries), "linked": len(linked)}


FILTERS = (
    ("all", lambda e: True),
    ("not in index", lambda e: not e["index"] and not e["in_index"]),
    ("duplicates", lambda e: bool(e["duplicate_of"])),
    ("old %dd+" % OLD_DAYS, lambda e: e["old"] and not e["index"]),
)


# ---------------------------------------------------------------- changes, each undoable


def _undo_path():
    return state_dir() / "memory-undo.json"


def _push_undo(step):
    try:
        steps = json.loads(_undo_path().read_text())
    except (OSError, ValueError):
        steps = []
    steps.append(step)
    _undo_path().write_text(json.dumps(steps[-50:]))


def _write_index(memory_dir, text):
    path = Path(memory_dir) / INDEX
    tmp = path.with_name("." + INDEX + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)


def _drop_index_lines(memory_dir, names):
    """Remove the index lines that link to any of `names`; returns the removed lines."""
    old = _read(Path(memory_dir) / INDEX)
    removed, kept = [], []
    for line in old.splitlines(True):
        (removed if any(m.group(1) in names for m in LINK.finditer(line)) else kept).append(line)
    if removed:
        _write_index(memory_dir, "".join(kept))
    return removed


def _append_index_lines(memory_dir, lines):
    text = _read(Path(memory_dir) / INDEX)
    missing = [line if line.endswith("\n") else line + "\n" for line in lines if line.strip() and line not in text]
    if missing:
        _write_index(memory_dir, text + ("" if not text or text.endswith("\n") else "\n") + "".join(missing))


# Undo touches only the lines a change added or removed, so index lines that
# other Claude sessions wrote in the meantime are kept.


def archive(memory_dir, name):
    """Move one memory file out of what Claude reads, and drop its index line."""
    memory_dir = Path(memory_dir)
    source = memory_dir / name
    if name == INDEX:
        raise ValueError("MEMORY.md is the index; archive the files it lists instead")
    target = memory_dir.parent / "memory-archive" / time.strftime("%Y%m%d") / name
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists():
        target = target.with_name("%s-%d%s" % (target.stem, int(time.time()), target.suffix))
    removed = _drop_index_lines(memory_dir, {name})
    shutil.move(str(source), str(target))
    _push_undo({"kind": "archive", "dir": str(memory_dir), "name": name, "archived": str(target), "removed": removed})
    return target


def add_to_index(memory_dir, name, description):
    title = Path(name).stem.replace("-", " ").replace("_", " ")
    line = "- [%s](%s)%s\n" % (title, name, (" — " + description) if description else "")
    _append_index_lines(memory_dir, [line])
    _push_undo({"kind": "index", "dir": str(memory_dir), "name": name, "added": line, "removed": []})


def drop_broken(memory_dir):
    broken = set(scan(memory_dir)["broken"])
    if not broken:
        return 0
    removed = _drop_index_lines(memory_dir, broken)
    _push_undo({"kind": "index", "dir": str(memory_dir), "name": "broken links", "added": None, "removed": removed})
    return len(broken)


def undo():
    """Reverse the last change; returns what was undone, or None."""
    try:
        steps = json.loads(_undo_path().read_text())
    except (OSError, ValueError):
        return None
    if not steps:
        return None
    step = steps.pop()
    memory_dir = Path(step["dir"])
    if step["kind"] == "archive":
        destination = memory_dir / step["name"]
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(step["archived"], str(destination))
    if step.get("added"):
        text = _read(memory_dir / INDEX)
        _write_index(memory_dir, text.replace(step["added"], "", 1))
    _append_index_lines(memory_dir, step.get("removed") or [])
    _undo_path().write_text(json.dumps(steps))
    return "undid: " + ("archive of " if step["kind"] == "archive" else "index change for ") + step["name"]
