"""Film model (pydantic), new/load/save, and the `check` rules."""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from . import store
from .aspects import Aspect, nearest


class FilmError(Exception):
    """A film file is missing, unreadable or does not match the schema."""


class _Model(BaseModel):
    model_config = ConfigDict(extra="forbid")


class VoiceLine(_Model):
    text: str = ""
    offset: float = 0.3
    pinned: bool = False
    text_pinned: bool = False  # the person wrote or edited the words: proposals must not overwrite them


class Scene(_Model):
    id: str
    title: str
    file: str | None = None
    length: float
    pinned: bool = False
    status: Literal["planned", "building", "ready"] = "planned"
    voice: VoiceLine = VoiceLine()


class TextClip(_Model):
    id: str
    scene: str
    text: str
    start: float = 0
    end: float | None = None
    pinned: bool = False
    text_pinned: bool = False  # the person edited the words: proposals must not overwrite them
    style: Literal["caption", "title"] = "caption"
    x: float | None = None
    y: float | None = None


class VoiceSettings(_Model):
    name: str = "en-US-AndrewNeural"
    rate: str = "+8%"


Mood = Literal["calm", "bright", "playful", "tense", "inspiring"]
Key = Literal["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]
Palette = Literal["keys", "pluck", "pad", "chip"]
SfxPreset = Literal["whoosh", "swoosh-up", "door", "ding", "pop", "tick", "click", "success", "error",
                    "typewriter", "riser", "thud"]


# Length in seconds of every preset as rendered (numpy-free copy of sound.sfx.PRESETS; a test renders each
# preset at several stretches and pitches and checks the rendered length); a clip lasts this times `stretch`.
SFX_SECONDS: dict[str, float] = {
    "whoosh": 0.55, "swoosh-up": 0.4, "door": 0.7, "ding": 1.2, "pop": 0.08, "tick": 0.02, "click": 0.06,
    "success": 0.9, "error": 0.45, "typewriter": 1.0, "riser": 1.5, "thud": 0.3,
}


class MusicBed(_Model):
    """Parameters of a generated music bed (the audio is re-derived from them, never stored)."""
    mood: Mood
    tempo: int = Field(ge=60, le=160)
    key: Key = "C"
    scale: Literal["major", "minor"] = "major"
    palette: Palette = "keys"
    seed: int = 1


class Music(_Model):
    file: str | None = None
    bed: MusicBed | None = None
    volume: float = 0.6
    pinned: bool = False  # the person picked or supplied it: proposals must not replace it

    @model_validator(mode="before")
    @classmethod
    def _old_files_are_the_persons(cls, data):
        if isinstance(data, dict) and data.get("file") is not None and "pinned" not in data:
            return {**data, "pinned": True}
        return data

    @model_validator(mode="after")
    def _one_source(self) -> "Music":
        if (self.file is None) == (self.bed is None):
            raise ValueError("music needs a file or a generated bed, not both")
        return self


class SfxClip(_Model):
    """A generated sound effect pinned to a moment of a scene (`at` seconds after the scene starts)."""
    id: str
    scene: str
    preset: SfxPreset
    at: float = Field(default=0, ge=0)
    volume: float = Field(default=0.7, ge=0, le=1)
    pitch: float = Field(default=0, ge=-12, le=12)
    stretch: float = Field(default=1, ge=0.25, le=4)
    seed: int = 0
    pinned: bool = False

    @property
    def seconds(self) -> float:
        """How long the sound lasts."""
        return SFX_SECONDS[self.preset] * self.stretch


class Tombstone(_Model):
    """Something the person removed. Proposals may not bring it back without their approval."""
    kind: Literal["scene", "text", "voice", "sfx", "music"]
    id: str                 # scene id, text id, or (for a voice line) its scene id
    scene: str | None = None  # for a text: the scene it belonged to
    text: str = ""          # a scene's title or a text's words, to recognise it under a new id
    at: str = ""


class Film(_Model):
    version: int = 2
    title: str
    width: int = 1280
    height: int = 720
    aspect: Aspect = "16:9"
    second_aspect: Aspect | None = None
    fps: int = 30
    pace: float = 1.0
    order_pinned: bool = False
    voice: VoiceSettings = VoiceSettings()
    music: Music | None = None
    scenes: list[Scene] = []
    texts: list[TextClip] = []
    sfx: list[SfxClip] = []
    removed_by_person: list[Tombstone] = []

    @model_validator(mode="after")
    def _second_differs(self) -> "Film":
        if self.second_aspect is not None and self.second_aspect == self.aspect:
            raise ValueError("the second shape must differ from the main one")
        return self


class Issue(BaseModel):
    level: Literal["error", "warning"]
    where: str
    message: str


NONDETERMINISTIC = (
    "Math.random", "Date.now", "new Date", "performance.now",
    "setTimeout", "setInterval", "requestAnimationFrame",
)


def new_film(folder: Path, title: str) -> Film:
    folder = Path(folder)
    if (folder / "film.json").exists():
        raise FileExistsError(f"{folder / 'film.json'} already exists")
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "scenes").mkdir(exist_ok=True)
    (folder / ".moshfilm").mkdir(exist_ok=True)
    created = Film(title=title)
    with store.locked(folder):
        store.write_json_atomic(folder / "proposals.json", {"proposals": []})
        store.write_json_atomic(folder / "comments.json", {"items": [], "messages": []})
        store.write_json_atomic(folder / "film.json", created.model_dump())
    return created


def migrate(data: dict) -> dict:
    """Bring older film.json data to the current version (in memory; saved on the next save).

    Version 1 had no shape: pick the nearest of the four ratios and keep width/height as they are."""
    if not isinstance(data, dict):
        return data
    version = data.get("version", 1)
    if not isinstance(version, int) or isinstance(version, bool):
        raise FilmError(f"version must be a whole number, not {version!r}")
    if version >= 2 and "aspect" in data:
        return data
    out = dict(data)
    w, h = out.get("width", 1280), out.get("height", 720)
    try:
        out.setdefault("aspect", nearest(w, h))
    except (TypeError, ValueError, ZeroDivisionError):
        pass  # a nonsense size: let validation report it
    out.setdefault("second_aspect", None)
    out["version"] = 2
    return out


def load_film(folder: Path) -> Film:
    path = Path(folder) / "film.json"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise FilmError(f"{path}: file not found") from None
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise FilmError(f"{path}: invalid JSON: {exc}") from None
    try:
        return Film.model_validate(migrate(data))
    except FilmError as exc:
        raise FilmError(f"{path}: {exc}") from None
    except ValidationError as exc:
        raise FilmError(f"{path}: {exc}") from None


def save_film(folder: Path, film: Film) -> None:
    with store.locked(folder):
        store.write_json_atomic(Path(folder) / "film.json", film.model_dump())


def _duplicates(ids: list[str]) -> list[str]:
    return sorted({i for i in ids if ids.count(i) > 1})


def check_film(folder: Path) -> list[Issue]:
    folder = Path(folder)
    try:
        film = load_film(folder)
    except FilmError as exc:
        return [Issue(level="error", where="film.json", message=str(exc))]

    issues: list[Issue] = []
    for dup in _duplicates([s.id for s in film.scenes]):
        issues.append(Issue(level="error", where=dup, message=f"duplicate scene id {dup}"))
    for dup in _duplicates([t.id for t in film.texts]):
        issues.append(Issue(level="error", where=dup, message=f"duplicate text id {dup}"))
    for dup in _duplicates([c.id for c in film.sfx]):
        issues.append(Issue(level="error", where=dup, message=f"duplicate sound id {dup}"))
    scene_ids = {s.id for s in film.scenes}
    for c in film.sfx:
        if c.scene not in scene_ids:
            issues.append(Issue(level="error", where=c.id, message=f"sound points to unknown scene {c.scene}"))
    for t in film.texts:
        if t.scene not in scene_ids:
            issues.append(Issue(level="error", where=t.id, message=f"text points to unknown scene {t.scene}"))
    for s in film.scenes:
        path = folder / s.file if s.file else None
        if path is None or not path.is_file():
            if s.status == "ready":
                issues.append(Issue(level="error", where=s.id,
                                    message=f"scene is ready but file is missing: {s.file}"))
            continue
        source = path.read_text(encoding="utf-8", errors="replace")
        for term in NONDETERMINISTIC:
            if re.search(r"(?<!\w)" + r"\s+".join(map(re.escape, term.split())) + r"\b", source):
                issues.append(Issue(level="warning", where=s.id,
                                    message=f"{s.file} uses {term}; scenes must be deterministic"))
    return issues
