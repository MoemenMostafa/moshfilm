"""Timing edits made from the UI. Each edit that sets a value also pins it."""
from __future__ import annotations

import re
from pathlib import Path
from typing import Annotated, Literal

from pydantic import Field, TypeAdapter, ValidationError

from datetime import datetime, timezone

from . import aspects
from .film import Film, Key, Mood, Music, MusicBed, Palette, SfxClip, SfxPreset, Tombstone, _Model
from .aspects import Aspect
from .timing import MIN_SCENE, PACE_MAX, PACE_MIN

MAX_SCENE = 600.0


class EditError(Exception):
    """An edit names something that does not exist or a value out of range."""


class SetLength(_Model):
    op: Literal["set_length"] = "set_length"
    scene: str
    length: float


class MoveScene(_Model):
    op: Literal["move_scene"] = "move_scene"
    scene: str
    index: int  # final position in the new order


class SetTextTime(_Model):
    op: Literal["set_text_time"] = "set_text_time"
    text: str
    start: float
    end: float | None = None


class SetVoiceOffset(_Model):
    op: Literal["set_voice_offset"] = "set_voice_offset"
    scene: str
    offset: float


class Unpin(_Model):
    op: Literal["unpin"] = "unpin"
    target: str  # "scene:<id>" | "text:<id>" | "voice:<id>" | "order"


class SetPace(_Model):
    op: Literal["set_pace"] = "set_pace"
    pace: float


class SetVoiceSettings(_Model):
    op: Literal["set_voice_settings"] = "set_voice_settings"
    name: str
    rate: str


class SetMusic(_Model):
    op: Literal["set_music"] = "set_music"
    file: str | None = None
    volume: float = 0.6


class RemoveScene(_Model):
    op: Literal["remove_scene"] = "remove_scene"
    scene: str


class RemoveText(_Model):
    op: Literal["remove_text"] = "remove_text"
    text: str


class RemoveVoice(_Model):
    op: Literal["remove_voice"] = "remove_voice"
    scene: str


class SetVoiceText(_Model):
    op: Literal["set_voice_text"] = "set_voice_text"
    scene: str
    text: str


class SetTextContent(_Model):
    op: Literal["set_text_content"] = "set_text_content"
    text: str      # the clip id
    content: str   # the new words


class SetAspects(_Model):
    op: Literal["set_aspects"] = "set_aspects"
    aspect: Aspect
    second_aspect: Aspect | None = None


class AddSfx(_Model):
    op: Literal["add_sfx"] = "add_sfx"
    preset: SfxPreset
    scene: str
    at: float = 0
    volume: float = 0.7
    pitch: float = 0
    stretch: float = 1
    seed: int = 0


class SetSfxTime(_Model):
    op: Literal["set_sfx_time"] = "set_sfx_time"
    sfx: str
    scene: str
    at: float


class SetSfx(_Model):
    op: Literal["set_sfx"] = "set_sfx"
    sfx: str
    preset: SfxPreset | None = None
    volume: float | None = None
    pitch: float | None = None
    stretch: float | None = None
    seed: int | None = None


class RemoveSfx(_Model):
    op: Literal["remove_sfx"] = "remove_sfx"
    sfx: str


class SetMusicBed(_Model):
    op: Literal["set_music_bed"] = "set_music_bed"
    mood: Mood
    tempo: int
    key: Key = "C"
    scale: Literal["major", "minor"] = "major"
    palette: Palette = "keys"
    seed: int = 1
    volume: float = 0.5


EditOp = Annotated[
    SetLength | MoveScene | SetTextTime | SetVoiceOffset | Unpin | SetPace | SetVoiceSettings | SetMusic
    | RemoveScene | RemoveText | RemoveVoice | SetVoiceText | SetTextContent | SetAspects
    | AddSfx | SetSfxTime | SetSfx | RemoveSfx | SetMusicBed,
    Field(discriminator="op"),
]
_op_adapter: TypeAdapter = TypeAdapter(EditOp)


def check_length(length: float) -> None:
    if not MIN_SCENE <= length <= MAX_SCENE:
        raise EditError(f"length {length} is outside {MIN_SCENE}-{MAX_SCENE} seconds")


def check_text_time(start: float, end: float | None) -> None:
    if start < 0:
        raise EditError(f"text start {start} is negative")
    if end is not None and end <= start:
        raise EditError(f"text end {end} must be after its start {start}")


def check_offset(offset: float) -> None:
    if offset < 0:
        raise EditError(f"voice offset {offset} is negative")


def find_scene(film: Film, scene_id: str):
    for s in film.scenes:
        if s.id == scene_id:
            return s
    raise EditError(f"unknown scene {scene_id}")


def find_text(film: Film, text_id: str):
    for t in film.texts:
        if t.id == text_id:
            return t
    raise EditError(f"unknown text {text_id}")


def find_sfx(film: Film, sfx_id: str):
    for c in film.sfx:
        if c.id == sfx_id:
            return c
    raise EditError(f"unknown sound {sfx_id}")


def next_sfx_id(film: Film) -> str:
    """`fx<N>` with the smallest N >= 1 not used by a clip or by a removed sound."""
    used = {c.id for c in film.sfx} | {t.id for t in film.removed_by_person if t.kind == "sfx"}
    n = 1
    while f"fx{n}" in used:
        n += 1
    return f"fx{n}"


def _valid_sfx(**fields) -> SfxClip:
    try:
        return SfxClip(**fields)
    except ValidationError as exc:
        raise EditError("; ".join(f"sound {'.'.join(map(str, e['loc']))}: {e['msg']}" for e in exc.errors())) from None


def move_scene_to(film: Film, scene_id: str, index: int) -> None:
    scene = find_scene(film, scene_id)
    if not 0 <= index < len(film.scenes):
        raise EditError(f"index {index} is outside 0-{len(film.scenes) - 1}")
    film.scenes.remove(scene)
    film.scenes.insert(index, scene)


MAX_TOMBSTONES = 1000  # only text tombstones are ever evicted (oldest first)


def find_tombstone(film: Film, kind: str, ident: str) -> Tombstone | None:
    return next((t for t in film.removed_by_person if t.kind == kind and t.id == ident), None)


def add_tombstone(film: Film, kind: str, ident: str, scene: str | None = None, text: str = "") -> None:
    keep = [t for t in film.removed_by_person if not (t.kind == kind and t.id == ident)]
    stamp = datetime.now(timezone.utc).isoformat(timespec="seconds")
    keep.append(Tombstone(kind=kind, id=ident, scene=scene, text=text, at=stamp))
    while len(keep) > MAX_TOMBSTONES:
        old = next((i for i, t in enumerate(keep) if t.kind == "text"), None)
        if old is None:
            break  # scene and voice tombstones are never dropped
        del keep[old]
    film.removed_by_person = keep


def clear_tombstone(film: Film, kind: str, ident: str) -> None:
    film.removed_by_person = [t for t in film.removed_by_person if not (t.kind == kind and t.id == ident)]


def _norm(text: str) -> str:
    return " ".join(text.split()).casefold()


def scene_removed(film: Film, scene_id: str, title: str | None = None) -> Tombstone | None:
    """The tombstone that stops a scene (by id, or by the same title under a new id) coming back."""
    for t in film.removed_by_person:
        if t.kind == "scene" and (t.id == scene_id or (title and t.text and _norm(t.text) == _norm(title))):
            return t
    return None


def text_removed(film: Film, text_id: str, scene: str, words: str) -> Tombstone | None:
    for t in film.removed_by_person:
        if t.kind == "text" and (t.id == text_id or (t.scene == scene and _norm(t.text) == _norm(words))):
            return t
    return None


def _apply(film: Film, op) -> None:
    if isinstance(op, SetLength):
        scene = find_scene(film, op.scene)
        check_length(op.length)
        scene.length, scene.pinned = op.length, True
    elif isinstance(op, MoveScene):
        move_scene_to(film, op.scene, op.index)
        film.order_pinned = True
    elif isinstance(op, SetTextTime):
        text = find_text(film, op.text)
        check_text_time(op.start, op.end)
        text.start, text.end, text.pinned = op.start, op.end, True
    elif isinstance(op, SetVoiceOffset):
        scene = find_scene(film, op.scene)
        check_offset(op.offset)
        scene.voice.offset, scene.voice.pinned = op.offset, True
    elif isinstance(op, Unpin):
        kind, _, ident = op.target.partition(":")
        if op.target == "order":
            film.order_pinned = False
        elif kind == "scene":
            find_scene(film, ident).pinned = False
        elif kind == "voice":
            find_scene(film, ident).voice.pinned = False
        elif kind == "text":
            find_text(film, ident).pinned = False
        elif kind == "sfx":
            find_sfx(film, ident).pinned = False
        else:
            raise EditError(f"unknown unpin target {op.target}")
    elif isinstance(op, SetPace):
        if not PACE_MIN <= op.pace <= PACE_MAX:
            raise EditError(f"pace {op.pace} is outside {PACE_MIN}-{PACE_MAX}")
        film.pace = op.pace
    elif isinstance(op, SetVoiceSettings):
        if not op.name.strip():
            raise EditError("voice name is empty")
        if not re.fullmatch(r"[+-]\d{1,3}%", op.rate):
            raise EditError(f"voice rate {op.rate!r} must look like +8% or -10%")
        film.voice.name, film.voice.rate = op.name, op.rate
    elif isinstance(op, RemoveScene):
        scene = find_scene(film, op.scene)
        for c in [c for c in film.sfx if c.scene == op.scene]:
            add_tombstone(film, "sfx", c.id, scene=op.scene, text=c.preset)
        film.sfx = [c for c in film.sfx if c.scene != op.scene]
        for clip in [t for t in film.texts if t.scene == op.scene]:
            add_tombstone(film, "text", clip.id, scene=op.scene, text=clip.text)
        add_tombstone(film, "scene", op.scene, text=scene.title)
        film.scenes.remove(scene)  # the voice line lives on the scene, so it goes with it
        film.texts = [t for t in film.texts if t.scene != op.scene]
    elif isinstance(op, RemoveText):
        clip = find_text(film, op.text)
        add_tombstone(film, "text", clip.id, scene=clip.scene, text=clip.text)
        film.texts.remove(clip)
    elif isinstance(op, RemoveVoice):
        scene = find_scene(film, op.scene)
        if not scene.voice.text.strip():
            raise EditError(f"scene {op.scene} has no voice line")
        add_tombstone(film, "voice", op.scene, text=scene.voice.text)
        scene.voice.text, scene.voice.text_pinned = "", False
    elif isinstance(op, SetVoiceText):
        scene = find_scene(film, op.scene)
        if not op.text.strip():
            raise EditError("narration text is empty; remove the voice line instead")
        scene.voice.text, scene.voice.text_pinned = op.text.strip(), True
        clear_tombstone(film, "voice", op.scene)
    elif isinstance(op, SetTextContent):
        clip = find_text(film, op.text)
        if not op.content.strip():
            raise EditError("caption text is empty; remove the caption instead")
        clip.text, clip.text_pinned = op.content.strip(), True
    elif isinstance(op, SetAspects):
        if op.second_aspect == op.aspect:
            raise EditError("the second shape must differ from the main one")
        if op.aspect != film.aspect:
            # computed before the field changes, so the short side is kept
            film.width, film.height = aspects.canvas_size(film, op.aspect)
        film.aspect, film.second_aspect = op.aspect, op.second_aspect
    elif isinstance(op, SetMusic):
        if not 0 <= op.volume <= 1:
            raise EditError(f"music volume {op.volume} is outside 0-1")
        if op.file is None:
            if film.music is not None:
                label = film.music.file or f"{film.music.bed.mood} bed"
                add_tombstone(film, "music", "music", text=Path(label).name)
            film.music = None
        else:
            film.music = Music(file=op.file, volume=op.volume, pinned=True)
            clear_tombstone(film, "music", "music")
    elif isinstance(op, SetMusicBed):
        if not 0 <= op.volume <= 1:
            raise EditError(f"music volume {op.volume} is outside 0-1")
        try:
            bed = MusicBed(mood=op.mood, tempo=op.tempo, key=op.key, scale=op.scale,
                           palette=op.palette, seed=op.seed)
        except ValidationError as exc:
            raise EditError("; ".join(f"music {'.'.join(map(str, e['loc']))}: {e['msg']}"
                                      for e in exc.errors())) from None
        film.music = Music(bed=bed, volume=op.volume, pinned=True)
        clear_tombstone(film, "music", "music")
    elif isinstance(op, AddSfx):
        find_scene(film, op.scene)
        film.sfx.append(_valid_sfx(id=next_sfx_id(film), scene=op.scene, preset=op.preset, at=op.at,
                                   volume=op.volume, pitch=op.pitch, stretch=op.stretch, seed=op.seed,
                                   pinned=True))
    elif isinstance(op, SetSfxTime):
        clip = find_sfx(film, op.sfx)
        find_scene(film, op.scene)
        if op.at < 0:
            raise EditError(f"sound time {op.at} is negative")
        clip.scene, clip.at, clip.pinned = op.scene, op.at, True
    elif isinstance(op, SetSfx):
        clip = find_sfx(film, op.sfx)
        fields = {k: getattr(op, k) for k in ("preset", "volume", "pitch", "stretch", "seed")
                  if getattr(op, k) is not None}
        checked = _valid_sfx(**{**clip.model_dump(), **fields})
        for k in fields:
            setattr(clip, k, getattr(checked, k))
        clip.pinned = True
    elif isinstance(op, RemoveSfx):
        clip = find_sfx(film, op.sfx)
        add_tombstone(film, "sfx", clip.id, scene=clip.scene, text=clip.preset)
        film.sfx.remove(clip)


def apply_edits(film: Film, ops: list) -> Film:
    """Return a new Film with the edits applied in order; the input is untouched."""
    result = film.model_copy(deep=True)
    for raw in ops:
        try:
            op = raw if not isinstance(raw, dict) else _op_adapter.validate_python(raw)
        except ValidationError as exc:
            raise EditError(str(exc)) from None
        _apply(result, op)
    return result
