"""What Claude is doing right now: steps of the current turn and a plan checklist, in .moshfilm/activity.json.

Claude Code hooks feed it through `moshfilm activity` (see `handle_hook`). Labels are short, plain and built only
from the tool name and the film-relative shape of a path or command, never from file contents or output.
Every read-modify-write runs inside `store.locked`.
"""
from __future__ import annotations

import re
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from filelock import Timeout

from . import store

STALE_AFTER = timedelta(minutes=10)  # a turn with no sign of life this long is treated as ended (Stop never came)
MAX_STEPS = 200
HOOK_LOCK_TIMEOUT = 0.5  # Claude kills a hook after 5 s; give up on the lock long before that

_SAFE_NAMES = {"film.json", "proposals.json", "comments.json"}
_MOSHFILM = re.compile(r"\bmoshfilm\s+([a-z]+)")
_BASH_LABELS = {
    "check": "Checking the film", "voice": "Making narration", "export": "Exporting",
    "propose": "Proposing a change", "reply": "Replying in the chat", "say": "Sending a chat message",
    "open": "Opening the editor", "new": "Creating a film", "sample": "Creating a film",
}
_SKIPPED = {"plan", "status", "watch", "activity", "hooks", "resolve"}  # bookkeeping: not worth a step


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(moment: datetime | None = None) -> str:
    return (moment or _now()).isoformat(timespec="milliseconds")


def _path(folder: Path) -> Path:
    return Path(folder) / ".moshfilm" / "activity.json"


def _empty() -> dict[str, Any]:
    return {"turn": None, "plan": []}


def _load(folder: Path) -> dict[str, Any]:
    try:
        data = store.read_json(_path(folder), None)
    except ValueError:  # half-written or damaged: start again
        data = None
    if not isinstance(data, dict):
        return _empty()
    return {"turn": data.get("turn") if isinstance(data.get("turn"), dict) else None,
            "plan": data.get("plan") if isinstance(data.get("plan"), list) else []}


def _save(folder: Path, data: dict[str, Any]) -> None:
    store.write_json_atomic(_path(folder), data)


# --------------------------------------------------------------------------- labels


def _rel(folder: Path, raw: Any) -> str | None:
    """A path as film-relative posix text, or None when it is not inside the film folder."""
    if not isinstance(raw, str) or not raw:
        return None
    p = Path(raw)
    root = Path(folder).resolve()
    try:
        return (p if p.is_absolute() else root / p).resolve().relative_to(root).as_posix()
    except (ValueError, OSError):
        return None


def _scenes(folder: Path) -> list[tuple[str, str | None]]:
    """(id, file) of every scene in film.json, read as plain JSON (no model import: hooks must be fast)."""
    try:
        rows = store.read_json(Path(folder) / "film.json", {}).get("scenes", [])
        return [(r["id"], r.get("file")) for r in rows if isinstance(r, dict) and isinstance(r.get("id"), str)]
    except (OSError, ValueError, AttributeError):
        return []


def _scene_number(folder: Path, rel: str) -> str:
    scenes = _scenes(folder)
    for i, (_, file) in enumerate(scenes):
        if file == rel:
            return f"{i + 1:02d}"
    digits = re.search(r"\d+", Path(rel).stem)
    return f"{int(digits.group()):02d}" if digits else Path(rel).stem


def _file_label(folder: Path, verb: str, raw: Any) -> str:
    rel = _rel(folder, raw)
    editing = verb == "Editing"
    if rel is None:
        return f"{verb} a file"
    parts = rel.split("/")
    if parts[0] == "scenes" and len(parts) == 2 and rel.endswith(".js"):
        if _is_scene_file(folder, rel):
            return f"{verb} scene {_scene_number(folder, rel)}"
        return f"{verb} a scene helper"
    if rel in _SAFE_NAMES:
        return f"{verb} {rel}"
    if parts[0] == "sources" and not editing:
        return "Reading a source document"
    return f"{verb} a file"


def _is_scene_file(folder: Path, rel: str) -> bool:
    """A scene file is one film.json names, or (when the film does not know it yet) one named like s3.js."""
    if rel in {file for _, file in _scenes(folder)}:
        return True
    return bool(re.fullmatch(r"scenes/[A-Za-z]*\d+\.js", rel))


def scene_of(folder: Path, tool: str, tool_input: dict) -> str | None:
    """The id of the scene (per film.json) whose file a Read/Edit/Write step targets, else None."""
    if tool not in ("Read", "Edit", "Write", "MultiEdit"):
        return None
    rel = _rel(folder, tool_input.get("file_path"))
    return next((sid for sid, file in _scenes(folder) if rel and file == rel), None)


def label_for(folder: Path, tool: str, tool_input: dict | None) -> str | None:
    """A short plain label for a tool call, or None for calls that are not worth showing."""
    tool_input = tool_input if isinstance(tool_input, dict) else {}
    if tool == "Read":
        return _file_label(folder, "Reading", tool_input.get("file_path"))
    if tool in ("Edit", "Write", "MultiEdit", "NotebookEdit"):
        return _file_label(folder, "Editing", tool_input.get("file_path"))
    if tool in ("Glob", "Grep", "LS"):
        return "Searching the film"
    if tool in ("WebFetch", "WebSearch"):
        return "Looking something up"
    if tool in ("Task", "Agent"):
        return "Delegating a task"
    if tool == "TodoWrite":
        return "Updating its to-do list"
    if tool == "Bash":
        command = tool_input.get("command")
        found = _MOSHFILM.search(command) if isinstance(command, str) else None
        if found:
            sub = found.group(1)
            if sub in _SKIPPED:
                return None
            if sub in _BASH_LABELS:
                return _BASH_LABELS[sub]
        return "Running a command"
    return "Using a tool"


# --------------------------------------------------------------------------- turns


def _failed(payload: dict) -> bool:
    if payload.get("hook_event_name") == "PostToolUseFailure":
        return True
    resp = payload.get("tool_response")
    if not isinstance(resp, dict):
        return False
    if resp.get("is_error") is True or resp.get("success") is False or resp.get("error"):
        return True
    for key in ("exit_code", "exitCode", "returncode"):
        if isinstance(resp.get(key), int) and not isinstance(resp.get(key), bool) and resp[key] != 0:
            return True
    return False


def _end_turn(turn: dict, at: str) -> None:
    for step in turn["steps"]:
        if step["state"] == "running":
            step["state"] = "done"
            step["ended"] = at
    turn["ended"] = at


def _anchor(folder: Path) -> str | None:
    """The latest delivered chat or comment: the item the card sits under."""
    try:
        rows = store.read_json(Path(folder) / "comments.json", {}).get("items", [])
    except (OSError, ValueError, AttributeError):
        return None
    delivered = [r for r in rows if isinstance(r, dict) and r.get("state") == "delivered" and r.get("kind") != "event"]
    return max(delivered, key=lambda r: r.get("delivered_at") or "").get("id") if delivered else None


def _expired(turn: dict) -> bool:
    try:
        return _now() - datetime.fromisoformat(turn["updated"]) > STALE_AFTER
    except (KeyError, ValueError, TypeError):
        return True


def _current_turn(folder: Path, data: dict) -> dict:
    turn = data["turn"]
    if turn and not turn.get("ended") and _expired(turn):
        _end_turn(turn, turn.get("updated") or _iso())
    if not turn or turn.get("ended"):
        stamp = _iso()
        turn = data["turn"] = {"id": uuid.uuid4().hex[:8], "started": stamp, "updated": stamp, "ended": None,
                               "item": _anchor(folder), "steps": []}
    return turn


def find_film(cwd: Any) -> Path | None:
    """The film folder for a hook's cwd: the folder itself or the nearest parent that holds film.json."""
    if not isinstance(cwd, str) or not cwd:
        return None
    try:
        start = Path(cwd).resolve()
    except OSError:
        return None
    for p in (start, *start.parents):
        if (p / "film.json").is_file():
            return p
    return None


def handle_hook(payload: Any, lock_timeout: float = HOOK_LOCK_TIMEOUT) -> bool:
    """Apply one Claude Code hook payload. Returns True when the activity file changed.

    Waits only `lock_timeout` seconds for the folder lock, then drops the event silently."""
    if not isinstance(payload, dict):
        return False
    folder = find_film(payload.get("cwd"))
    if folder is None:
        return False
    event = payload.get("hook_event_name")
    tool = payload.get("tool_name") if isinstance(payload.get("tool_name"), str) else ""
    tool_input = payload.get("tool_input") if isinstance(payload.get("tool_input"), dict) else {}
    use_id = payload.get("tool_use_id") if isinstance(payload.get("tool_use_id"), str) else None
    try:
        guard = store.locked(folder).acquire(timeout=lock_timeout)
    except Timeout:
        return False
    with guard:
        data = _load(folder)
        if event in ("Stop", "UserPromptSubmit"):  # Esc sends no Stop: a new prompt closes the old turn too
            turn = data["turn"]
            if not turn or turn.get("ended"):
                return False
            _end_turn(turn, _iso())
        elif event == "PreToolUse":
            label = label_for(folder, tool, tool_input)
            if label is None:
                return False
            turn = _current_turn(folder, data)
            stamp = _iso()
            step = {"id": turn["steps"][-1]["id"] + 1 if turn["steps"] else 1, "label": label, "state": "running", "started": stamp,
                    "ended": None, "tool_use_id": use_id}
            target = scene_of(folder, tool, tool_input)
            if target:
                step["scene"] = target
                step["action"] = "read" if tool == "Read" else "edit"
            turn["steps"] = (turn["steps"] + [step])[-MAX_STEPS:]
            turn["updated"] = stamp
        elif event in ("PostToolUse", "PostToolUseFailure"):
            turn = data["turn"]
            if not turn or turn.get("ended") or label_for(folder, tool, tool_input) is None:
                return False
            running = [s for s in turn["steps"] if s["state"] == "running"]
            match = next((s for s in running if use_id and s.get("tool_use_id") == use_id), None)
            if match is None and not use_id and running:
                match = running[-1]
            if match is None:
                return False
            stamp = _iso()
            match["state"] = "failed" if _failed(payload) else "done"
            match["ended"] = stamp
            turn["updated"] = stamp
        else:
            return False
        _save(folder, data)
    return True


def snapshot(folder: Path) -> dict[str, Any]:
    """Current activity for the UI. A turn that went quiet for too long is reported as ended."""
    data = _load(folder)
    turn = data["turn"]
    if turn and not turn.get("ended") and _expired(turn):
        _end_turn(turn, turn.get("updated") or _iso())
    return data


# --------------------------------------------------------------------------- plan


def set_plan(folder: Path, steps: list[str]) -> None:
    with store.locked(folder):
        data = _load(folder)
        data["plan"] = [{"text": s, "done": False} for s in steps if s.strip()]
        _save(folder, data)


def plan_done(folder: Path, number: int) -> None:
    """Tick item `number` (1-based). IndexError when there is no such item."""
    with store.locked(folder):
        data = _load(folder)
        if not 1 <= number <= len(data["plan"]):
            raise IndexError(number)
        data["plan"][number - 1]["done"] = True
        _save(folder, data)


def clear_plan(folder: Path) -> None:
    with store.locked(folder):
        data = _load(folder)
        data["plan"] = []
        _save(folder, data)
