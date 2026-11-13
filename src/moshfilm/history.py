"""Undo/redo history: snapshots of film.json and the scene files, in `<film>/.moshfilm/history/`.

Each step is one snapshot of the whole tracked state (film.json parsed, plus every `scenes/**/*.js` file as text),
so undoing restores pinned flags, texts, voice text and scene code together. The folder holds `index.json`
(cursor, steps) and one `<id>.json` per step; it survives reloads and server restarts because nothing is kept in
memory. Everything here runs inside `store.locked`.

Two writers feed it:
- the person's edits call `apply_and_record` (one request, one step);
- changes nobody recorded (Claude writing scene files, applied proposals) are noticed by `sync`, which the server
  calls whenever the folder changes. One Claude turn is one step: changes in the same activity turn merge, and
  without a turn changes merge while the folder stays busy (a quiet period of `QUIET_SECONDS`).
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import tempfile
from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from . import activity, edits, store
from .film import Film, load_film, save_film

MAX_STEPS = 100
MAX_BYTES = 20 * 1024 * 1024
QUIET_SECONDS = 20.0   # no activity turn: changes closer together than this are one Claude step
TURN_GRACE = 5.0       # seconds after an activity turn ended that its id still claims new changes
LABEL_PARTS = 3
_STEP_FILE = re.compile(r"\d{6}\.json")
_SCENE_FILE = re.compile(r"scenes/[^/\\]+\.js")
_reset_pending: set[Path] = set()  # folders whose damaged history was just reset (told to the person once)
Notify = Callable[[str], None]


class HistoryError(Exception):
    """An unknown history step."""


class HistoryConflict(HistoryError):
    """The step exists no more or cannot be restored here; the message says what to do."""


RESET_MESSAGE = "History was reset (its files were damaged): earlier steps can no longer be undone."


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(moment: datetime) -> str:
    return moment.isoformat(timespec="milliseconds")


def _dir(folder: Path) -> Path:
    return Path(folder) / ".moshfilm" / "history"


def _index_path(folder: Path) -> Path:
    return _dir(folder) / "index.json"


# --------------------------------------------------------------------------- state


def _tracked_files(folder: Path) -> dict[str, str]:
    """Top-level `scenes/*.js` (what the folder watcher treats as scenes); symlinks are never followed."""
    out: dict[str, str] = {}
    base = Path(folder) / "scenes"
    if not base.is_dir():
        return out
    for path in sorted(base.glob("*.js")):
        if path.name.startswith(".") or path.is_symlink() or not path.is_file():
            continue
        try:
            out[f"scenes/{path.name}"] = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
    return out


def _capture(folder: Path) -> dict[str, Any] | None:
    try:
        film = json.loads((Path(folder) / "film.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None  # missing or half-written: nothing to record now
    return {"film": film, "files": _tracked_files(folder)}


def _hash(state: dict[str, Any]) -> str:
    return hashlib.sha256(json.dumps(state, sort_keys=True).encode("utf-8")).hexdigest()[:20]


def _write_atomic_text(path: Path, text: str) -> None:
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=path.name + ".", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(text)
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except FileNotFoundError:
            pass
        raise


def _restore_state(folder: Path, state: dict[str, Any]) -> None:
    """Make the folder match `state`; files that already match are left alone (no needless reloads).

    Scene files are written atomically and film.json last, so a watcher never sees a film that names a
    half-written scene. Only top-level scenes/*.js inside the folder are ever touched."""
    folder = Path(folder)
    scenes = (folder / "scenes").resolve()
    for rel in state["files"]:
        ok = isinstance(rel, str) and _SCENE_FILE.fullmatch(rel) and not (folder / rel).is_symlink() \
            and (folder / rel).resolve().parent == scenes
        if not ok:
            if isinstance(rel, str) and rel.startswith("scenes/") and rel.endswith(".js") and ".." not in rel.split("/"):
                raise HistoryConflict("This step was saved by an older version and can't be restored.")
            raise HistoryError(f"history snapshot names a file outside the scenes folder: {rel!r}")
    current = _tracked_files(folder)
    for rel, text in state["files"].items():
        if current.get(rel) != text:
            target = folder / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            _write_atomic_text(target, text)
    for rel in current:
        if rel not in state["files"]:
            (folder / rel).unlink(missing_ok=True)
    store.write_json_atomic(folder / "film.json", state["film"])


# --------------------------------------------------------------------------- index


def _blank() -> dict[str, Any]:
    return {"version": 1, "cursor": -1, "next_id": 1, "steps": []}


def _load(folder: Path) -> dict[str, Any] | None:
    try:
        data = json.loads(_index_path(folder).read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None
    except (OSError, ValueError):
        data = None
    ok = (isinstance(data, dict) and isinstance(data.get("steps"), list) and data["steps"]
          and isinstance(data.get("cursor"), int) and 0 <= data["cursor"] < len(data["steps"])
          and all(isinstance(s, dict) and "id" in s and "hash" in s and isinstance(s.get("file"), str)
                  and _STEP_FILE.fullmatch(s["file"]) for s in data["steps"]))
    if not ok:  # damaged: start again from the current state, and say so once
        shutil.rmtree(_dir(folder), ignore_errors=True)
        _reset_pending.add(Path(folder).resolve())
        return None
    return data


def _save(folder: Path, idx: dict[str, Any]) -> None:
    store.write_json_atomic(_index_path(folder), idx)


def _snap_path(folder: Path, step: dict) -> Path:
    return _dir(folder) / step["file"]


def _read_snap(folder: Path, step: dict) -> dict[str, Any] | None:
    try:
        return json.loads(_snap_path(folder, step).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _write_snap(folder: Path, step: dict, state: dict[str, Any]) -> None:
    path = _snap_path(folder, step)
    store.write_json_atomic(path, state)
    step["size"] = path.stat().st_size
    step["hash"] = _hash(state)


def _new_step(idx: dict, label: str, kind: str, turn: str | None) -> dict:
    n = idx["next_id"]
    idx["next_id"] = n + 1
    stamp = _iso(_now())
    return {"id": n, "label": label, "kind": kind, "ts": stamp, "updated": stamp, "turn": turn,
            "hash": "", "size": 0, "file": f"{n:06d}.json"}


def _drop(folder: Path, step: dict) -> None:
    _snap_path(folder, step).unlink(missing_ok=True)


def _append(folder: Path, idx: dict, step: dict, state: dict) -> int:
    """Add a step after the cursor; returns how many redo steps that cleared."""
    gone = idx["steps"][idx["cursor"] + 1:]  # a new edit clears the redo stack
    idx["steps"] = idx["steps"][:idx["cursor"] + 1]
    _write_snap(folder, step, state)
    idx["steps"].append(step)
    idx["cursor"] = len(idx["steps"]) - 1
    dropped = _enforce_bounds(folder, idx)
    _save(folder, idx)  # the index first: a crash must never leave it naming deleted snapshots
    for old in gone + dropped:
        _drop(folder, old)
    return len(gone)


def _enforce_bounds(folder: Path, idx: dict) -> list[dict]:
    dropped: list[dict] = []

    def drop_oldest() -> None:
        dropped.append(idx["steps"].pop(0))
        idx["cursor"] -= 1

    while len(idx["steps"]) > max(MAX_STEPS, 2):
        drop_oldest()
    while len(idx["steps"]) > 2 and sum(s.get("size", 0) for s in idx["steps"]) > MAX_BYTES:
        drop_oldest()
    return dropped


def _public(idx: dict, step: dict) -> dict:
    pos = idx["steps"].index(step)
    return {"id": step["id"], "label": step["label"], "kind": step["kind"], "time": step["ts"],
            "current": pos == idx["cursor"], "future": pos > idx["cursor"]}


def _baseline(folder: Path, state: dict) -> dict:
    idx = _blank()
    step = _new_step(idx, "Start", "base", None)
    _write_snap(folder, step, state)
    idx["steps"].append(step)
    idx["cursor"] = 0
    _save(folder, idx)
    return idx


# --------------------------------------------------------------------------- labels


def _num(film: Film, scene_id: str) -> str:
    for i, s in enumerate(film.scenes):
        if s.id == scene_id:
            return f"{i + 1:02d}"
    return scene_id


def _short(text: str, n: int = 30) -> str:
    text = " ".join(text.split())
    return text if len(text) <= n else text[: n - 1] + "…"


def _label_one(film: Film, op: Any) -> str:
    kind = op.op
    if kind == "set_length":
        return f"Changed length of scene {_num(film, op.scene)}"
    if kind == "move_scene":
        return f"Moved scene {_num(film, op.scene)}"
    if kind == "set_text_time":
        return "Moved caption"
    if kind == "set_voice_offset":
        return f"Moved voice of scene {_num(film, op.scene)}"
    if kind == "unpin":
        what, _, ident = op.target.partition(":")
        return "Unpinned scene order" if op.target == "order" else f"Unpinned {what} {_num(film, ident) if what != 'text' else ident}"
    if kind == "set_pace":
        return "Changed pace"
    if kind == "set_voice_settings":
        return "Changed voice"
    if kind == "set_aspects":
        return f"Changed shape to {op.aspect}" + (f" + {op.second_aspect}" if op.second_aspect else "")
    if kind == "set_music":
        return "Removed music" if op.file is None else "Changed music"
    if kind in ("add_sfx", "set_sfx_time", "set_sfx", "remove_sfx"):
        if kind == "add_sfx":
            return f"Added sound {op.preset}"
        clip = next((c for c in film.sfx if c.id == op.sfx), None)
        name = clip.preset if clip else op.sfx
        verb = {"set_sfx_time": "Moved", "set_sfx": "Changed", "remove_sfx": "Removed"}[kind]
        return f"{verb} sound {name}"
    if kind == "set_music_bed":
        return f"Picked music: {op.mood}"
    if kind == "remove_scene":
        title = next((s.title for s in film.scenes if s.id == op.scene), op.scene)
        return f'Removed scene {_num(film, op.scene)} "{_short(title)}"'
    if kind == "remove_text":
        text = next((t.text for t in film.texts if t.id == op.text), op.text)
        return f'Removed caption "{_short(text)}"'
    if kind == "remove_voice":
        return f"Removed voice of scene {_num(film, op.scene)}"
    if kind == "set_voice_text":
        return f"Edited narration of scene {_num(film, op.scene)}"
    if kind == "set_text_content":
        return f'Edited caption "{_short(op.content)}"'
    return "Edited the film"  # pragma: no cover


def label_for_ops(film: Film, ops: list) -> str:
    """A short name for one person edit (one request), from the film as it was before."""
    parsed = []
    for raw in ops:
        try:
            parsed.append(edits._op_adapter.validate_python(raw) if isinstance(raw, dict) else raw)
        except Exception:  # noqa: BLE001 - an invalid op fails later with its own message
            return "Edited the film"
    if not parsed:
        return "Edited the film"
    label = _label_one(film, parsed[0])
    return label if len(parsed) == 1 else f"{label} (+{len(parsed) - 1} more)"


def notes_for_ops(film: Film, ops: list) -> list[str]:
    """Chat notes for Claude about a person edit that it must know about (removals, text edits).

    `film` is the film before the edit. Timing drags need no note: pinned flags already protect them."""
    notes: list[str] = []
    for raw in ops:
        try:
            op = edits._op_adapter.validate_python(raw) if isinstance(raw, dict) else raw
        except Exception:  # noqa: BLE001
            continue
        kind = op.op
        if kind == "remove_scene":
            scene = next((s for s in film.scenes if s.id == op.scene), None)
            if scene is None:
                continue
            clips = sum(1 for t in film.texts if t.scene == op.scene)
            extra = []
            if scene.voice.text.strip():
                extra.append("its voice line")
            if clips:
                extra.append(f"{clips} caption" + ("s" if clips > 1 else ""))
            sounds = sum(1 for c in film.sfx if c.scene == op.scene)
            if sounds:
                extra.append(f"{sounds} sound" + ("s" if sounds > 1 else ""))
            tail = f" (with {' and '.join(extra)})" if extra else ""
            notes.append(f'The person removed scene {_num(film, op.scene)} "{scene.title}" ({op.scene}){tail}. '
                         "Do not add it back unless they ask.")
        elif kind == "remove_text":
            clip = next((t for t in film.texts if t.id == op.text), None)
            if clip is not None:
                notes.append(f'The person removed the caption "{clip.text}" ({clip.id}) from scene '
                             f"{_num(film, clip.scene)}. Do not add it back unless they ask.")
        elif kind == "remove_voice":
            scene = next((s for s in film.scenes if s.id == op.scene), None)
            if scene is not None:
                notes.append(f'The person removed the voice line of scene {_num(film, op.scene)}: '
                             f'"{scene.voice.text}". Do not write it again unless they ask.')
        elif kind == "set_voice_text":
            scene = next((s for s in film.scenes if s.id == op.scene), None)
            if scene is not None and scene.voice.text.strip() != op.text.strip():
                notes.append(f'The person edited the narration of scene {_num(film, op.scene)} ({op.scene}): '
                             f'"{scene.voice.text}" is now "{op.text.strip()}". The words are theirs (pinned): '
                             "do not overwrite them unless they ask.")
        elif kind == "set_text_content":
            clip = next((t for t in film.texts if t.id == op.text), None)
            if clip is not None and clip.text.strip() != op.content.strip():
                notes.append(f'The person edited the caption {clip.id}: "{clip.text}" is now "{op.content.strip()}". '
                             "The words are theirs (pinned): do not overwrite them unless they ask.")
        elif kind == "set_aspects" and (op.aspect, op.second_aspect) != (film.aspect, film.second_aspect):
            second = f"second shape: {op.second_aspect}" if op.second_aspect else "no second shape"
            notes.append(f"The person changed the film's shape to {op.aspect} ({second}). "
                         "Check every scene in each shape with `moshfilm check <folder> --layout` "
                         "and fix what does not fit.")
        elif kind == "remove_sfx":
            clip = next((c for c in film.sfx if c.id == op.sfx), None)
            if clip is not None:
                notes.append(f'The person removed the sound "{clip.preset}" ({clip.id}) from scene '
                             f"{_num(film, clip.scene)}. Do not add it back unless they ask.")
        elif kind == "set_music_bed":
            old = film.music.bed if film.music else None
            fields = ("mood", "tempo", "key", "scale", "palette", "seed")
            if old is None or any(getattr(old, f) != getattr(op, f) for f in fields):
                notes.append(f"The person picked the music: {op.mood}, {op.tempo} bpm, {op.key} {op.scale}, "
                             f"{op.palette}. It is theirs (pinned): do not change it unless they ask.")
        elif kind == "set_music" and op.file is None and film.music is not None:
            notes.append("The person removed the music. Do not add it back unless they ask.")
    return notes


def _plural(nums: list[str], one: str, many: str) -> str:
    return f"{one} {nums[0]}" if len(nums) == 1 else f"{many} {', '.join(nums)}"


def _diff_label(prev: dict, new: dict) -> str:
    """What changed between two states, in Claude's voice ("Claude: edited scene 03")."""
    pf, nf = prev["film"], new["film"]
    pscenes = {s["id"]: s for s in pf.get("scenes", [])}
    nscenes = {s["id"]: s for s in nf.get("scenes", [])}
    order = {s["id"]: f"{i + 1:02d}" for i, s in enumerate(nf.get("scenes", []))}
    parts: list[str] = []
    added = [i for i in nscenes if i not in pscenes]
    removed = [i for i in pscenes if i not in nscenes]
    if added:
        parts.append("added " + _plural([order[i] for i in added], "scene", "scenes"))
    if removed:
        parts.append("removed " + ", ".join(f'scene "{pscenes[i]["title"]}"' for i in removed))
    edited: set[str] = set()
    other: list[str] = []
    by_file = {s.get("file"): i for i, s in nscenes.items() if s.get("file")}
    for rel in sorted(set(prev["files"]) | set(new["files"])):
        if prev["files"].get(rel) == new["files"].get(rel):
            continue
        sid = by_file.get(rel)
        if sid is None:
            if rel in new["files"]:
                other.append(f"edited {Path(rel).name}")
        elif sid not in added:
            edited.add(order[sid])
    if edited:
        parts.append("edited " + _plural(sorted(edited), "scene", "scenes"))
    parts.extend(other)
    narr, props = [], []
    for sid, s in nscenes.items():
        old = pscenes.get(sid)
        if old is None:
            continue
        if old.get("voice", {}).get("text") != s.get("voice", {}).get("text"):
            narr.append(order[sid])
        strip = lambda d: {k: v for k, v in d.items() if k != "voice"} | {  # noqa: E731
            "voice": {k: v for k, v in d.get("voice", {}).items() if k != "text"}}
        if strip(old) != strip(s):
            props.append(order[sid])
    if narr:
        parts.append("changed narration of " + _plural(narr, "scene", "scenes"))
    if props:
        parts.append("changed " + _plural(props, "scene", "scenes"))
    ptexts = {t["id"]: t for t in pf.get("texts", [])}
    ntexts = {t["id"]: t for t in nf.get("texts", [])}
    for word, ids in (("added", [i for i in ntexts if i not in ptexts]),
                      ("removed", [i for i in ptexts if i not in ntexts]),
                      ("changed", [i for i in ntexts if i in ptexts and ntexts[i] != ptexts[i]])):
        if ids:
            parts.append(f"{word} {len(ids)} caption" + ("s" if len(ids) > 1 else ""))
    psfx = {c["id"]: c for c in pf.get("sfx", [])}
    nsfx = {c["id"]: c for c in nf.get("sfx", [])}
    for word, ids in (("added", [i for i in nsfx if i not in psfx]),
                      ("removed", [i for i in psfx if i not in nsfx]),
                      ("changed", [i for i in nsfx if i in psfx and nsfx[i] != psfx[i]])):
        if ids:
            parts.append(f"{word} {len(ids)} sound" + ("s" if len(ids) > 1 else ""))
    if pf.get("music") != nf.get("music"):
        parts.append("changed music")
    rest = {k for k in set(pf) | set(nf)
            if k not in ("scenes", "texts", "sfx", "music") and pf.get(k) != nf.get(k)}
    if rest:
        parts.append("changed film settings")
    if not parts:
        parts = ["changed the film"]
    if len(parts) > LABEL_PARTS:
        parts = parts[:LABEL_PARTS] + [f"+{len(parts) - LABEL_PARTS} more"]
    return "Claude: " + ", ".join(parts)


# --------------------------------------------------------------------------- Claude turns


def _parse(stamp: Any) -> datetime | None:
    try:
        return datetime.fromisoformat(stamp)
    except (TypeError, ValueError):
        return None


def _turn_key(folder: Path, now: datetime) -> str | None:
    """The activity turn that owns changes made now, if any (a running one, or one that just ended)."""
    try:
        turn = activity.snapshot(folder).get("turn")
    except (OSError, ValueError):
        return None
    if not isinstance(turn, dict) or not isinstance(turn.get("id"), str):
        return None
    ended = turn.get("ended")
    if not ended:
        return turn["id"]
    when = _parse(ended)
    return turn["id"] if when and (now - when).total_seconds() <= TURN_GRACE else None


def _same_group(last: dict, key: str | None, now: datetime) -> bool:
    if key is not None:
        return last.get("turn") == key
    when = _parse(last.get("updated"))
    return bool(when and (now - when).total_seconds() <= QUIET_SECONDS)


# --------------------------------------------------------------------------- public API


def info(folder: Path) -> dict[str, Any]:
    idx = _load(folder)
    if idx is None:
        return {"steps": [], "cursor": -1, "can_undo": False, "can_redo": False}
    return {"steps": [_public(idx, s) for s in idx["steps"]], "cursor": idx["cursor"],
            "can_undo": idx["cursor"] > 0, "can_redo": idx["cursor"] < len(idx["steps"]) - 1}


def _tell_reset(folder: Path, notify: Notify | None) -> None:
    if Path(folder).resolve() in _reset_pending:
        _reset_pending.discard(Path(folder).resolve())
        if notify:
            notify(RESET_MESSAGE)


def take_reset(folder: Path) -> bool:
    """True once after a damaged history was reset (e.g. by a read), so the caller can tell the person."""
    key = Path(folder).resolve()
    if key in _reset_pending:
        _reset_pending.discard(key)
        return True
    return False


def sync(folder: Path, notify: Notify | None = None) -> bool:
    """Record changes nobody recorded (Claude's) as a Claude step. True when the history changed.

    `notify` gets a plain sentence when something happened that the person must not miss: the history
    was reset, or Claude's change cleared their redo steps."""
    folder = Path(folder)
    with store.locked(folder):
        state = _capture(folder)
        if state is None:
            return False
        idx = _load(folder)
        if idx is None:
            _baseline(folder, state)
            _tell_reset(folder, notify)
            return False
        if _hash(state) == idx["steps"][idx["cursor"]]["hash"]:
            return False
        now = _now()
        key = _turn_key(folder, now)
        last = idx["steps"][-1]
        if idx["cursor"] == len(idx["steps"]) - 1 and last["kind"] == "claude" and len(idx["steps"]) > 1 \
                and _same_group(last, key, now):
            before = _read_snap(folder, idx["steps"][-2])
            if before is not None and _hash(before) == _hash(state):  # Claude undid its own change
                _drop(folder, idx["steps"].pop())
                idx["cursor"] -= 1
            else:
                last["label"] = _diff_label(before, state) if before is not None else last["label"]
                last["updated"] = _iso(now)
                last["turn"] = key or last.get("turn")
                _write_snap(folder, last, state)
            _save(folder, idx)
            return True
        prev = _read_snap(folder, idx["steps"][idx["cursor"]])
        step = _new_step(idx, _diff_label(prev, state) if prev is not None else "Claude: changed the film",
                         "claude", key)
        cleared = _append(folder, idx, step, state)
        if cleared and notify:
            notify(f"Claude changed the film after your undo: {cleared} redo step"
                   f"{'s were' if cleared > 1 else ' was'} cleared.")
        return True


def record(folder: Path, label: str, kind: str = "person") -> dict | None:
    """Record the folder's current state as a new step (the caller just changed it)."""
    folder = Path(folder)
    with store.locked(folder):
        state = _capture(folder)
        if state is None:
            return None
        idx = _load(folder)
        if idx is None:
            _baseline(folder, state)
            return None
        if _hash(state) == idx["steps"][idx["cursor"]]["hash"]:
            return None
        step = _new_step(idx, label, kind, None)
        _append(folder, idx, step, state)
        return _public(idx, step)


def apply_and_record(folder: Path, ops: list, notify: Notify | None = None) -> Film:
    """Apply the person's edits to film.json and record them as one step.

    Changes Claude made that are still unrecorded become their own step first, so one undo never
    swallows them."""
    folder = Path(folder)
    with store.locked(folder):
        sync(folder, notify)
        before = load_film(folder)
        result = edits.apply_edits(before, ops)
        save_film(folder, result)
        record(folder, label_for_ops(before, ops))
    return result


def _move(folder: Path, idx: dict, step_id: int, notify: Notify | None = None) -> dict:
    """Restore the state after step `step_id`. Returns the index as saved.

    Just before writing, the folder is captured again: if Claude wrote something since the caller's
    sync, that is recorded first, so the restore can never overwrite it unrecorded."""
    for _ in range(3):
        now = _capture(folder)
        if now is not None and _hash(now) != idx["steps"][idx["cursor"]]["hash"]:
            sync(folder, notify)
            idx = _load(folder) or idx
            continue
        break
    pos = next((i for i, s in enumerate(idx["steps"]) if s["id"] == step_id), None)
    if pos is None:  # a Claude write cleared the redo steps between the person's click and now
        raise HistoryConflict("Nothing to redo — Claude changed the film after your undo")
    state = _read_snap(folder, idx["steps"][pos])
    if state is None:
        raise HistoryError("that history step's snapshot is missing")
    _restore_state(folder, state)
    idx["cursor"] = pos
    _save(folder, idx)
    return idx


def _ready(folder: Path, notify: Notify | None = None) -> dict | None:
    sync(folder, notify)  # whatever is on disk now becomes a step first, so redo can bring it back
    return _load(folder)


def undo(folder: Path, notify: Notify | None = None) -> dict | None:
    """Step back one step; returns the step that was undone, or None at the start."""
    folder = Path(folder)
    with store.locked(folder):
        idx = _ready(folder, notify)
        if idx is None or idx["cursor"] <= 0:
            return None
        undone = _public(idx, idx["steps"][idx["cursor"]])
        _move(folder, idx, idx["steps"][idx["cursor"] - 1]["id"], notify)
        return undone


def redo(folder: Path, notify: Notify | None = None) -> dict | None:
    """Step forward one step; returns the step that was redone, or None at the end."""
    folder = Path(folder)
    with store.locked(folder):
        idx = _ready(folder, notify)
        if idx is None or idx["cursor"] >= len(idx["steps"]) - 1:
            return None
        idx = _move(folder, idx, idx["steps"][idx["cursor"] + 1]["id"], notify)
        return _public(idx, idx["steps"][idx["cursor"]])


def jump(folder: Path, step_id: int, notify: Notify | None = None) -> dict:
    """Go to the state after step `step_id`; returns that step."""
    folder = Path(folder)
    with store.locked(folder):
        idx = _ready(folder, notify)
        if idx is None or not any(s["id"] == step_id for s in idx["steps"]):
            raise HistoryError(f"unknown history step {step_id}")
        idx = _move(folder, idx, step_id, notify)
        return _public(idx, idx["steps"][idx["cursor"]])
