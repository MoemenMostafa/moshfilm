"""Claude's proposals: validated, applied automatically unless they touch pinned timing."""
from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path
from typing import Annotated, Literal

from pydantic import BaseModel, Field, ValidationError

from . import edits, store
from .film import (Film, Music, MusicBed, Scene, SfxClip, TextClip, VoiceLine, _Model, load_film,
                   save_film)
from .timing import MIN_SCENE

Length = Annotated[float, Field(ge=MIN_SCENE, le=edits.MAX_SCENE)]
Status = Literal["planned", "building", "ready"]


class ProposalError(Exception):
    """A proposal is malformed, names unknown things, or cannot be approved now."""


class NewVoice(_Model):
    text: str = ""
    offset: Annotated[float, Field(ge=0)] = 0.3


class NewScene(_Model):
    id: str
    title: str
    file: str | None = None
    length: Length
    status: Status = "planned"
    voice: NewVoice = NewVoice()


class AddScene(_Model):
    op: Literal["add_scene"] = "add_scene"
    scene: NewScene
    after: str | None = None  # None = append at the end


class RemoveScene(_Model):
    op: Literal["remove_scene"] = "remove_scene"
    id: str


class MoveScene(_Model):
    op: Literal["move_scene"] = "move_scene"
    id: str
    index: int  # final position in the new order


class SetScene(_Model):
    op: Literal["set_scene"] = "set_scene"
    id: str
    title: str | None = None
    file: str | None = None
    length: Length | None = None
    status: Status | None = None


class SetVoice(_Model):
    op: Literal["set_voice"] = "set_voice"
    id: str  # scene id
    text: str | None = None
    offset: Annotated[float, Field(ge=0)] | None = None


class AddText(_Model):
    op: Literal["add_text"] = "add_text"
    text: TextClip


class SetText(_Model):
    op: Literal["set_text"] = "set_text"
    id: str
    text: str | None = None
    start: Annotated[float, Field(ge=0)] | None = None
    end: float | None = None
    style: Literal["caption", "title"] | None = None
    x: float | None = None
    y: float | None = None


class RemoveText(_Model):
    op: Literal["remove_text"] = "remove_text"
    id: str


class AddSfx(_Model):
    op: Literal["add_sfx"] = "add_sfx"
    sfx: SfxClip


class SetSfx(_Model):
    op: Literal["set_sfx"] = "set_sfx"
    id: str
    scene: str | None = None
    at: Annotated[float, Field(ge=0)] | None = None
    preset: str | None = None
    volume: Annotated[float, Field(ge=0, le=1)] | None = None
    pitch: Annotated[float, Field(ge=-12, le=12)] | None = None
    stretch: Annotated[float, Field(ge=0.25, le=4)] | None = None
    seed: int | None = None


class RemoveSfx(_Model):
    op: Literal["remove_sfx"] = "remove_sfx"
    id: str


class SetMusic(_Model):
    op: Literal["set_music"] = "set_music"
    bed: MusicBed | None = None  # None removes the music
    volume: Annotated[float, Field(ge=0, le=1)] = 0.5


Change = Annotated[
    AddScene | RemoveScene | MoveScene | SetScene | SetVoice | AddText | SetText | RemoveText
    | AddSfx | SetSfx | RemoveSfx | SetMusic,
    Field(discriminator="op"),
]


class Proposal(_Model):
    id: str
    created: str
    summary: str = ""
    needs_approval: bool = False
    status: Literal["pending", "applied", "partial", "awaiting_approval", "rejected", "invalid"] = "pending"
    changes: list[Change]
    held: list[int] = []
    held_reasons: dict[str, str] = {}  # change index -> why it was held, when it is not just a pinned value
    error: str | None = None


class ApplyResult(BaseModel):
    film: Film
    applied: list[int]
    held: list[int]
    reasons: dict[str, str] = {}


def _gone(film: Film, kind: str, ident: str) -> bool:
    """True when the person removed this scene or text and it is not there now."""
    present = {"scene": [s.id for s in film.scenes], "sfx": [c.id for c in film.sfx]}.get(
        kind, [t.id for t in film.texts])
    return ident not in present and edits.find_tombstone(film, kind, ident) is not None


def _apply_change(film: Film, ch, allow_pinned: bool,
                  timing_only: bool = False, why: list[str] | None = None) -> tuple[bool, bool]:
    """Apply one change in place. Returns (applied_something, held_something).

    timing_only re-runs a held change: the non-timing fields went in the first time and may have
    been edited since, so only lengths, offsets, start/end, removals and moves are applied."""
    if isinstance(ch, AddScene):
        spec = ch.scene
        if any(s.id == spec.id for s in film.scenes):
            raise edits.EditError(f"scene {spec.id} already exists")
        removed = edits.scene_removed(film, spec.id, spec.title)
        if removed and not allow_pinned:  # the person removed it: only they can bring it back
            if why is not None:
                why.append("you removed this scene" if removed.id == spec.id
                           else "same title as a scene you removed")
            return False, True
        if removed:
            edits.clear_tombstone(film, "scene", removed.id)
            for gone in {removed.id, spec.id}:  # its captions come back with it
                film.removed_by_person = [t for t in film.removed_by_person
                                          if not (t.kind == "text" and t.scene == gone)]
        scene = Scene(id=spec.id, title=spec.title, file=spec.file, length=spec.length,
                      status=spec.status, voice=VoiceLine(text=spec.voice.text, offset=spec.voice.offset))
        if ch.after is None:
            film.scenes.append(scene)
        else:
            pos = film.scenes.index(edits.find_scene(film, ch.after)) + 1
            film.scenes.insert(pos, scene)
        return True, False

    if isinstance(ch, RemoveScene):
        if _gone(film, "scene", ch.id):
            return False, False  # the person already removed it
        scene = edits.find_scene(film, ch.id)
        pinned = scene.pinned or scene.voice.pinned or scene.voice.text_pinned or any(
            t.pinned or t.text_pinned for t in film.texts if t.scene == ch.id) or any(
            c.pinned for c in film.sfx if c.scene == ch.id)
        if pinned and not allow_pinned:
            return False, True
        film.scenes.remove(scene)
        film.texts = [t for t in film.texts if t.scene != ch.id]
        film.sfx = [c for c in film.sfx if c.scene != ch.id]
        return True, False

    if isinstance(ch, MoveScene):
        if _gone(film, "scene", ch.id):
            return False, False
        edits.find_scene(film, ch.id)
        if film.order_pinned and not allow_pinned:
            return False, True
        edits.move_scene_to(film, ch.id, ch.index)
        return True, False

    if isinstance(ch, SetScene):
        if _gone(film, "scene", ch.id):
            return False, False
        scene = edits.find_scene(film, ch.id)
        applied = held = False
        for name in () if timing_only else ("title", "file", "status"):
            value = getattr(ch, name)
            if value is not None:
                setattr(scene, name, value)
                applied = True
        if ch.length is not None:
            if scene.pinned and not allow_pinned:
                held = True
            else:
                scene.length = ch.length
                applied = True
        return applied, held

    if isinstance(ch, SetVoice):
        if _gone(film, "scene", ch.id):
            return False, False
        scene = edits.find_scene(film, ch.id)
        applied = held = False
        voice_gone = edits.find_tombstone(film, "voice", ch.id) is not None and not scene.voice.text.strip()
        protected = scene.voice.text_pinned or voice_gone  # the person wrote it, or removed it
        if ch.text is not None and (not timing_only or (allow_pinned and protected)):
            if protected and not allow_pinned:
                held = True
            else:
                scene.voice.text = ch.text
                if protected:  # the person approved Claude's words over theirs
                    scene.voice.text_pinned = False
                    edits.clear_tombstone(film, "voice", ch.id)
                applied = True
        if ch.offset is not None:
            if scene.voice.pinned and not allow_pinned:
                held = True
            else:
                scene.voice.offset = ch.offset
                applied = True
        return applied, held

    if isinstance(ch, AddText):
        clip = ch.text
        if any(t.id == clip.id for t in film.texts):
            raise edits.EditError(f"text {clip.id} already exists")
        removed = edits.text_removed(film, clip.id, clip.scene, clip.text)
        scene_gone = edits.find_tombstone(film, "scene", clip.scene)
        if (removed or scene_gone) and not allow_pinned:
            if why is not None:
                why.append("you removed this caption" if removed and removed.id == clip.id else
                           "same words as a caption you removed" if removed else "you removed its scene")
            return False, True
        if removed:
            edits.clear_tombstone(film, "text", removed.id)
        edits.find_scene(film, clip.scene)
        edits.check_text_time(clip.start, clip.end)
        film.texts.append(clip.model_copy(update={"pinned": False}))
        return True, False

    if isinstance(ch, SetText):
        if _gone(film, "text", ch.id):
            return False, False
        clip = edits.find_text(film, ch.id)
        applied = held = False
        for name in () if timing_only else ("style", "x", "y"):
            value = getattr(ch, name)
            if value is not None:
                setattr(clip, name, value)
                applied = True
        if ch.text is not None and (not timing_only or (allow_pinned and clip.text_pinned)):
            if clip.text_pinned and not allow_pinned:  # the person edited these words
                held = True
            else:
                clip.text, clip.text_pinned = ch.text, False
                applied = True
        # Value-based (null means "not supplied"), so it survives the JSON round-trip;
        # a proposal therefore cannot clear a text's end back to "until scene end".
        if ch.start is not None or ch.end is not None:
            if clip.pinned and not allow_pinned:
                held = True
            else:
                start = ch.start if ch.start is not None else clip.start
                end = ch.end if ch.end is not None else clip.end
                edits.check_text_time(start, end)
                clip.start, clip.end = start, end
                applied = True
        return applied, held

    if isinstance(ch, RemoveText):
        if _gone(film, "text", ch.id):
            return False, False
        clip = edits.find_text(film, ch.id)
        if (clip.pinned or clip.text_pinned) and not allow_pinned:
            return False, True
        film.texts.remove(clip)
        return True, False

    if isinstance(ch, AddSfx):
        clip = ch.sfx
        if any(c.id == clip.id for c in film.sfx):
            raise edits.EditError(f"sound {clip.id} already exists")
        same_id = edits.find_tombstone(film, "sfx", clip.id)
        same_sound = next((t for t in film.removed_by_person
                           if t.kind == "sfx" and t.scene == clip.scene and t.text == clip.preset), None)
        scene_gone = edits.find_tombstone(film, "scene", clip.scene)
        if (same_id or same_sound or scene_gone) and not allow_pinned:
            if why is not None:
                why.append("you removed this sound" if same_id else
                           "you removed the same sound in this scene" if same_sound else
                           "you removed its scene")
            return False, True
        for t in (same_id, same_sound):
            if t:
                edits.clear_tombstone(film, "sfx", t.id)
        edits.find_scene(film, clip.scene)
        film.sfx.append(clip.model_copy(update={"pinned": False}))
        return True, False

    if isinstance(ch, SetSfx):
        if _gone(film, "sfx", ch.id):
            return False, False
        clip = edits.find_sfx(film, ch.id)
        if clip.pinned and not allow_pinned:
            return False, True
        fields = {k: getattr(ch, k) for k in ("preset", "volume", "pitch", "stretch", "seed", "at")
                  if getattr(ch, k) is not None}
        if ch.scene is not None:
            edits.find_scene(film, ch.scene)
            fields["scene"] = ch.scene
        if not fields:
            return False, False
        checked = edits._valid_sfx(**{**clip.model_dump(), **fields})
        for k in fields:
            setattr(clip, k, getattr(checked, k))
        return True, False

    if isinstance(ch, RemoveSfx):
        if _gone(film, "sfx", ch.id):
            return False, False
        clip = edits.find_sfx(film, ch.id)
        if clip.pinned and not allow_pinned:
            return False, True
        film.sfx.remove(clip)
        return True, False

    if isinstance(ch, SetMusic):
        current = film.music
        if ch.bed is None:
            if current is None:
                return False, False
            if current.pinned and not allow_pinned:
                return False, True
            film.music = None
            return True, False
        gone = current is None and edits.find_tombstone(film, "music", "music") is not None
        if (current is not None and current.pinned or gone) and not allow_pinned:
            if why is not None and gone:
                why.append("you removed the music")
            return False, True
        edits.clear_tombstone(film, "music", "music")
        film.music = Music(bed=ch.bed, volume=ch.volume, pinned=False)
        return True, False

    raise edits.EditError(f"unsupported change {ch!r}")  # pragma: no cover


def _run(film: Film, changes: list, allow_pinned: bool, only: set[int] | None) -> ApplyResult:
    result = film.model_copy(deep=True)
    applied: list[int] = []
    held: list[int] = []
    reasons: dict[str, str] = {}
    for i, ch in enumerate(changes):
        if only is not None and i not in only:
            continue
        try:
            why: list[str] = []
            did, hold = _apply_change(result, ch, allow_pinned, timing_only=only is not None, why=why)
        except edits.EditError as exc:
            raise ProposalError(f"change {i}: {exc}") from None
        if did:
            applied.append(i)
        if hold:
            held.append(i)
            if why:
                reasons[str(i)] = why[0]
    return ApplyResult(film=result, applied=applied, held=held, reasons=reasons)


def apply_proposal(film: Film, proposal: Proposal, allow_pinned: bool = False) -> ApplyResult:
    """Apply a proposal to a copy of the film. Pinned timing values are held, not changed."""
    return _run(film, proposal.changes, allow_pinned, None)


# --- storage ---------------------------------------------------------------

def _path(folder: Path) -> Path:
    return Path(folder) / "proposals.json"


def _read_raw(folder: Path) -> list[dict]:
    data = store.read_json(_path(folder), {"proposals": []})
    items = data.get("proposals") if isinstance(data, dict) else None
    if not isinstance(items, list):
        raise ProposalError(f"{_path(folder)}: expected {{\"proposals\": [...]}}")
    return items


def _write(folder: Path, items: list[dict]) -> None:
    store.write_json_atomic(_path(folder), {"proposals": items})


def _dump(p: Proposal) -> dict:
    return p.model_dump(exclude_none=False)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _next_id(items: list[dict]) -> str:
    nums = [int(str(i.get("id", ""))[1:]) for i in items
            if isinstance(i, dict) and str(i.get("id", "")).startswith("p") and str(i["id"])[1:].isdigit()]
    return f"p{max(nums, default=0) + 1}"


def add_proposal(folder: Path, data: dict) -> Proposal:
    if not isinstance(data, dict):
        raise ProposalError("a proposal must be a JSON object")
    with store.locked(folder):
        items = _read_raw(folder)
        fields = {k: v for k, v in data.items() if k not in {"id", "created", "status", "held", "error"}}
        try:
            proposal = Proposal.model_validate(
                {**fields, "id": _next_id(items), "created": _now(), "status": "pending"})
        except ValidationError as exc:
            raise ProposalError(str(exc)) from None
        _write(folder, items + [_dump(proposal)])
    return proposal


def _find(items: list[dict], pid: str) -> int:
    for i, raw in enumerate(items):
        if isinstance(raw, dict) and raw.get("id") == pid:
            return i
    raise ProposalError(f"unknown proposal {pid}")


def process_pending(folder: Path, on_event: Callable[[str], None] = lambda _: None) -> list[Proposal]:
    """Handle every pending proposal; returns the ones whose status changed."""
    folder = Path(folder)
    with store.locked(folder):
        items = _read_raw(folder)
        pending = [i for i, raw in enumerate(items) if isinstance(raw, dict) and raw.get("status") == "pending"]
        if not pending:
            return []
        film = load_film(folder)
        done: list[Proposal] = []
        film_changed = False
        for i in pending:
            raw = items[i]
            try:
                proposal = Proposal.model_validate(raw)
                if proposal.needs_approval:
                    proposal.status = "awaiting_approval"
                else:
                    res = apply_proposal(film, proposal)
                    film, film_changed = res.film, True
                    proposal.held = res.held
                    proposal.held_reasons = res.reasons
                    proposal.status = "partial" if res.held else "applied"
            except (ValidationError, ProposalError) as exc:
                pid = raw.get("id", f"#{i}")
                message = str(exc)
                items[i] = {**raw, "status": "invalid", "error": message}
                try:
                    done.append(Proposal.model_validate(items[i]))
                except ValidationError:
                    pass  # too broken to model; the stored entry still says why
                on_event(f"Proposal {pid} is invalid: {message}")
                continue
            items[i] = _dump(proposal)
            done.append(proposal)
        if film_changed:
            save_film(folder, film)
        _write(folder, items)
        return done


def approve(folder: Path, pid: str, include_pinned: bool) -> Proposal:
    """Apply a proposal that waits for approval, or its held timing changes when include_pinned."""
    folder = Path(folder)
    with store.locked(folder):
        items = _read_raw(folder)
        if items[_find(items, pid)].get("status") == "pending":
            process_pending(folder)
            items = _read_raw(folder)
        i = _find(items, pid)
        proposal = Proposal.model_validate(items[i])
        if proposal.status not in ("awaiting_approval", "partial"):
            raise ProposalError(f"proposal {pid} is {proposal.status}; nothing to approve")
        film = load_film(folder)
        only = set(proposal.held) if proposal.status == "partial" else None
        if proposal.status == "partial" and not include_pinned:
            raise ProposalError(f"proposal {pid} only has held pinned changes; approve with include_pinned")
        res = _run(film, proposal.changes, include_pinned, only)
        proposal.held = res.held
        proposal.held_reasons = res.reasons
        proposal.status = "partial" if res.held else "applied"
        save_film(folder, res.film)
        items[i] = _dump(proposal)
        _write(folder, items)
        return proposal


def reject(folder: Path, pid: str) -> Proposal:
    with store.locked(folder):
        items = _read_raw(folder)
        i = _find(items, pid)
        proposal = Proposal.model_validate(items[i])
        if proposal.status in ("applied", "rejected", "invalid"):
            raise ProposalError(f"proposal {pid} is {proposal.status}; cannot reject")
        proposal.status = "rejected"
        items[i] = _dump(proposal)
        _write(folder, items)
        return proposal
