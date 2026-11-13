"""Install the activity hooks into a film folder's `.claude/settings.local.json` (and nowhere else).

The hooks make Claude Code call `moshfilm activity` around every tool call, which feeds the panel's working card.
Existing keys and other hooks in the file are kept; our entries are recognised by their command and replaced.
"""
from __future__ import annotations

import json
import shlex
import sys
from pathlib import Path

from . import store

EVENTS = ("UserPromptSubmit", "PreToolUse", "PostToolUse", "PostToolUseFailure", "Stop")


class HooksError(Exception):
    pass


def _settings_path(folder: Path) -> Path:
    return Path(folder) / ".claude" / "settings.local.json"


def activity_command() -> str:
    """The shell command a hook runs: the `moshfilm` next to this Python if there is one, else `python -m`."""
    # -I (isolated mode) keeps the cwd, where Claude writes files, off sys.path: a planted json.py must not run.
    # `moshfilm.hook` imports only the activity module, so it starts much faster than the full CLI
    return f"{shlex.quote(sys.executable)} -I -m moshfilm.hook"


def _is_ours(command: object) -> bool:
    if not isinstance(command, str):
        return False
    try:
        words = shlex.split(command)
    except ValueError:
        return False
    if words[-2:] == ["-m", "moshfilm.hook"]:
        return True
    return words[-1:] == ["activity"] and any(  # older installs: `<path>/moshfilm activity`
        Path(w).name == "moshfilm" or w == "moshfilm.cli" for w in words[:-1])


def _entry() -> dict:
    return {"hooks": [{"type": "command", "command": activity_command(), "timeout": 5}]}


def _read(path: Path) -> dict:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}
    except ValueError as exc:
        raise HooksError(f"{path} is not valid JSON ({exc}); fix it or remove it first") from exc
    hooks = data.get("hooks", {}) if isinstance(data, dict) else None
    if not isinstance(hooks, dict) or not all(
            isinstance(g, list) and all(isinstance(x, dict) for x in g) for g in hooks.values()):
        raise HooksError(f"{path} does not have the expected shape (hooks must map events to lists of groups)")
    return data


def _check_inside(folder: Path) -> Path:
    """The settings path, refusing symlinks that would send the write outside the film folder."""
    path = _settings_path(folder)
    root = Path(folder).resolve()
    try:
        path.parent.resolve().relative_to(root)
        path.resolve().relative_to(root)
    except ValueError:
        raise HooksError(f"{path} resolves outside the film folder; refusing to touch it") from None
    if path.is_symlink():
        raise HooksError(f"{path} is a symlink; refusing to replace it")
    return path


def _strip(data: dict) -> None:
    """Remove our hook entries (and anything left empty by that) from `data` in place."""
    hooks = data.get("hooks", {})
    for event in list(hooks):
        groups = hooks[event]
        if not isinstance(groups, list):
            continue
        kept = []
        for group in groups:
            inner = group.get("hooks") if isinstance(group, dict) else None
            if isinstance(inner, list):
                rest = [h for h in inner if not (isinstance(h, dict) and _is_ours(h.get("command")))]
                if len(rest) != len(inner):
                    if not rest:
                        continue
                    group = {**group, "hooks": rest}
            kept.append(group)
        if kept:
            hooks[event] = kept
        else:
            del hooks[event]
    if not hooks:
        data.pop("hooks", None)


def install(folder: Path) -> bool:
    """Write or merge the hooks. True when the file changed."""
    folder = Path(folder)
    if not folder.is_dir():
        raise HooksError(f"{folder} is not a folder")
    path = _check_inside(folder)
    before = path.read_text(encoding="utf-8") if path.exists() else None
    data = _read(path)
    _strip(data)
    hooks = data.setdefault("hooks", {})
    for event in EVENTS:
        hooks.setdefault(event, []).append(_entry())
    if json.dumps(data, indent=2, ensure_ascii=False) + "\n" == before:
        return False
    store.write_json_atomic(path, data)
    return True


def uninstall(folder: Path) -> bool:
    """Remove our hooks, keeping everything else. True when something was removed."""
    folder = Path(folder)
    path = _check_inside(folder)
    if not path.exists():
        return False
    data = _read(path)
    before = json.dumps(data, sort_keys=True)
    _strip(data)
    if json.dumps(data, sort_keys=True) == before:
        return False
    if data:
        store.write_json_atomic(path, data)
    else:
        path.unlink()
        try:
            path.parent.rmdir()
        except OSError:
            pass
    return True
