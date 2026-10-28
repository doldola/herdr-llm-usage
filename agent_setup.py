"""The setup an agent session runs with: instructions, memory, skills, MCP servers and settings.

Read from the files Claude Code and Codex load for the session's folder, by
their documented locations. This describes what is configured; agent_activity
says what the session actually used, and the monitor puts the two together.
"""

import json
import os
import re
from pathlib import Path

FRONTMATTER_KEY = re.compile(r"^(name|description):\s*(.*)$")


def _read_json(path):
    try:
        return json.loads(Path(path).read_text())
    except (OSError, ValueError):
        return None


def _lines(path):
    try:
        with open(path, "rb") as handle:
            return sum(1 for _ in handle)
    except OSError:
        return 0


def file_entry(path):
    path = Path(path)
    try:
        mtime = path.stat().st_mtime
    except OSError:
        mtime = None
    return {"path": str(path), "lines": _lines(path), "mtime": mtime}


def project_root(cwd):
    """The nearest folder holding .git, else the folder itself."""
    if not cwd:
        return None
    folder = Path(cwd)
    for candidate in [folder] + list(folder.parents):
        if (candidate / ".git").exists():
            return candidate
    return folder


def frontmatter(path):
    """name and description from a SKILL.md or agent file's YAML front matter."""
    info = {}
    try:
        with open(path, encoding="utf-8", errors="replace") as handle:
            if handle.readline().strip() != "---":
                return info
            for line in handle:
                if line.strip() == "---":
                    break
                match = FRONTMATTER_KEY.match(line.strip())
                if match:
                    info[match.group(1)] = match.group(2).strip().strip("'\"")
    except OSError:
        pass
    return info


def skills_in(folder, source):
    found = []
    for skill_md in sorted(Path(folder).glob("*/SKILL.md")):
        meta = frontmatter(skill_md)
        found.append({"name": meta.get("name") or skill_md.parent.name, "description": meta.get("description", ""),
                      "source": source, "path": str(skill_md)})
    return found


def named_files(folder, pattern="*.md"):
    return sorted(p.stem for p in Path(folder).glob(pattern)) if Path(folder).is_dir() else []


def _folders_from_root(cwd):
    """cwd and its parents, outermost first."""
    if not cwd:
        return []
    return list(reversed([Path(cwd)] + list(Path(cwd).parents)))


# ---------------------------------------------------------------- Claude Code


def claude_home():
    return Path(os.environ.get("CLAUDE_CONFIG_DIR") or Path.home() / ".claude")


def claude_user_json():
    configured = os.environ.get("CLAUDE_CONFIG_DIR")
    return _read_json(Path(configured) / ".claude.json" if configured else Path.home() / ".claude.json") or {}


def claude_setup(cwd, transcript=None):
    home, root = claude_home(), project_root(cwd)
    project_dirs = [d for d in {Path(cwd) if cwd else None, root} if d]

    instructions = [home / "CLAUDE.md"]
    for folder in _folders_from_root(cwd):
        instructions += [folder / "CLAUDE.md", folder / "CLAUDE.local.md", folder / ".claude" / "CLAUDE.md"]
    rules = []
    for base in [home] + project_dirs:
        rules += sorted((base / ".claude" / "rules" if base != home else base / "rules").glob("**/*.md"))

    settings_files = [home / "settings.json"]
    for base in project_dirs:
        settings_files += [base / ".claude" / "settings.json", base / ".claude" / "settings.local.json"]
    settings = [(path, _read_json(path)) for path in settings_files if path.is_file()]

    enabled_plugins = {}
    hooks, allow, deny, mode, model, output_style = {}, 0, 0, None, None, None
    for _path, data in settings:
        data = data or {}
        for name, on in (data.get("enabledPlugins") or {}).items():
            enabled_plugins[name] = bool(on)
        for event, groups in (data.get("hooks") or {}).items():
            count = sum(len(g.get("hooks") or []) for g in groups if isinstance(g, dict))
            hooks[event] = hooks.get(event, 0) + count
        permissions = data.get("permissions") or {}
        allow += len(permissions.get("allow") or [])
        deny += len(permissions.get("deny") or [])
        mode = permissions.get("defaultMode") or mode
        model = data.get("model") or model
        output_style = data.get("outputStyle") or output_style

    skills = skills_in(home / "skills", "user")
    for base in project_dirs:
        skills += skills_in(base / ".claude" / "skills", "project")
    plugin_names = {name.split("@")[0] for name, on in enabled_plugins.items() if on}
    for skill_md in sorted((home / "plugins").glob("**/skills/*/SKILL.md")):
        plugin = _plugin_of(skill_md, home / "plugins")
        if plugin_names and plugin not in plugin_names:
            continue
        meta = frontmatter(skill_md)
        skills.append({"name": meta.get("name") or skill_md.parent.name, "description": meta.get("description", ""),
                       "source": "plugin:" + plugin, "path": str(skill_md)})
    skills = _unique(skills, "name")

    user_json = claude_user_json()
    mcp = [{"name": n, "scope": "user"} for n in (user_json.get("mcpServers") or {})]
    for base in project_dirs:
        local = ((user_json.get("projects") or {}).get(str(base)) or {}).get("mcpServers") or {}
        mcp += [{"name": n, "scope": "local"} for n in local]
        mcp += [{"name": n, "scope": "project"} for n in ((_read_json(base / ".mcp.json") or {}).get("mcpServers") or {})]
    mcp = _unique(mcp, "name")

    agents = named_files(home / "agents")
    commands = named_files(home / "commands")
    for base in project_dirs:
        agents += named_files(base / ".claude" / "agents")
        commands += named_files(base / ".claude" / "commands")

    memory = []
    if transcript:
        memory = sorted((Path(transcript).parent / "memory").glob("**/*.md"), key=lambda p: -p.stat().st_mtime)

    return {
        "instructions": [file_entry(p) for p in _existing(instructions)],
        "rules": [file_entry(p) for p in _existing(rules)],
        "memory": [file_entry(p) for p in memory],
        "skills": skills,
        "mcp": mcp,
        "agents": sorted(set(agents)),
        "commands": sorted(set(commands)),
        "hooks": hooks,
        "plugins": sorted(name for name, on in enabled_plugins.items() if on),
        "settings": {"permission mode": mode, "allow rules": allow, "deny rules": deny, "model": model,
                     "output style": output_style},
        "settings_files": [str(p) for p, _ in settings],
    }


def _plugin_of(skill_md, plugins_dir):
    """The plugin a cached skill belongs to: the folder holding its skills/ directory."""
    parts = skill_md.relative_to(plugins_dir).parts
    index = parts.index("skills") if "skills" in parts else 1
    candidates = [p for p in parts[:index] if not re.fullmatch(r"[0-9a-f.]{6,}|v?\d+(\.\d+)*", p)]
    return candidates[-1] if candidates else parts[0]


def _existing(paths):
    seen, result = set(), []
    for path in paths:
        if path.is_file() and path.resolve() not in seen:
            seen.add(path.resolve())
            result.append(path)
    return result


def _unique(items, key):
    seen, result = set(), []
    for item in items:
        if item[key] not in seen:
            seen.add(item[key])
            result.append(item)
    return result


# ---------------------------------------------------------------- Codex


def codex_home():
    return Path(os.environ.get("CODEX_HOME") or Path.home() / ".codex")


def read_toml(path):
    """Enough TOML for Codex's config.toml: tables, and string/number/boolean values."""
    data = {}
    current = data
    try:
        text = Path(path).read_text()
    except OSError:
        return data
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        header = re.fullmatch(r"\[\[?([^\]]+)\]\]?(\s*#.*)?", line)
        if header:
            current = data
            for part in re.findall(r'"[^"]*"|[^.]+', header.group(1)):
                current = current.setdefault(part.strip().strip('"'), {})
            continue
        if "=" in line:
            key, value = (x.strip() for x in line.split("=", 1))
            if value[:1] in ("'", '"'):
                end = value.find(value[0], 1)
                value = value[1:end] if end > 0 else value[1:]
            else:
                value = value.split("#", 1)[0].strip()
                if value in ("true", "false"):
                    value = value == "true"
            current[key.strip('"')] = value
    return data


def codex_setup(cwd, transcript=None):
    home, root = codex_home(), project_root(cwd)
    instructions = [home / "AGENTS.override.md", home / "AGENTS.md"]
    for folder in _folders_from_root(cwd):
        if root and root not in [folder] + list(folder.parents):
            continue  # Codex reads AGENTS.md from the project root down to cwd
        instructions += [folder / "AGENTS.override.md", folder / "AGENTS.md"]
    config = read_toml(home / "config.toml")
    profile = (config.get("profiles") or {}).get(config.get("profile") or "", {})
    pick = lambda key: profile.get(key, config.get(key))
    skills = skills_in(home / "skills", "user")
    if root:
        skills += skills_in(root / ".codex" / "skills", "project") + skills_in(root / ".agents" / "skills", "project")
    return {
        "instructions": [file_entry(p) for p in _existing(instructions)],
        "rules": [],
        "memory": [],
        "skills": _unique(skills, "name"),
        "mcp": [{"name": n, "scope": "config"} for n in (config.get("mcp_servers") or {})],
        "agents": [],
        "commands": named_files(home / "prompts"),
        "hooks": {},
        "plugins": [],
        "settings": {"model": pick("model"), "reasoning effort": pick("model_reasoning_effort"),
                     "approval": pick("approval_policy"), "sandbox": pick("sandbox_mode"), "profile": config.get("profile")},
        "settings_files": [str(home / "config.toml")] if (home / "config.toml").is_file() else [],
    }


def setup_for(agent, cwd, transcript=None):
    if agent == "claude":
        return claude_setup(cwd, transcript)
    if agent == "codex":
        return codex_setup(cwd, transcript)
    return None
