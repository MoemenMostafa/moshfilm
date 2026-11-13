"""Timing rules: how long each scene runs, where voice and text sit.

The browser preview mirrors this in ui/src/runtime/timing.ts; both are checked
against tests/fixtures/timing_cases.json.
"""
from __future__ import annotations

from dataclasses import dataclass

from .film import Film, SfxClip, TextClip

VOICE_PAUSE = 0.8   # silence after a voice line, seconds
PACE_MIN = 0.75
PACE_MAX = 2.0
MAX_SPEEDUP = 1.25  # fastest a voice line may be played to fit a pinned scene
MIN_SCENE = 0.5     # shortest an automatic scene length can get, seconds
OVERFLOW_COPY = "voice doesn't fit — stretch scene or shorten line"


@dataclass
class SceneSlot:
    id: str
    start: float
    length: float
    voice_start: float
    voice_speed: float
    overflow: bool


def _r(x: float) -> float:
    return round(x, 3)


def layout(film: Film, voice: dict[str, float]) -> list[SceneSlot]:
    """Place every scene on the timeline.

    `voice` maps scene id to the duration of its current synthesised line;
    a missing id means unknown: no minimum length, speed 1, no overflow.
    """
    slots: list[SceneSlot] = []
    start = 0.0
    for scene in film.scenes:
        offset = scene.voice.offset
        d = voice.get(scene.id)
        speed, overflow = 1.0, False
        if scene.pinned:
            length = scene.length
            if d is not None:
                avail = length - offset
                if avail <= 0:
                    speed, overflow = MAX_SPEEDUP, True
                elif d > avail:
                    wanted = d / avail
                    overflow = wanted > MAX_SPEEDUP
                    speed = min(wanted, MAX_SPEEDUP)
        else:
            needed = offset + d + VOICE_PAUSE if d is not None else 0.0
            length = max(max(scene.length, needed) * film.pace, needed, MIN_SCENE)
        slots.append(SceneSlot(scene.id, _r(start), _r(length), _r(start + offset),
                               _r(speed), overflow))
        start += length
    return slots


def total_length(slots: list[SceneSlot]) -> float:
    return _r(slots[-1].start + slots[-1].length) if slots else 0.0


def text_window(clip: TextClip, slots: list[SceneSlot]) -> tuple[float, float]:
    """Absolute (start, end) of a text clip on the film timeline."""
    slot = next((s for s in slots if s.id == clip.scene), None)
    if slot is None:
        raise ValueError(f"text {clip.id} points to unknown scene {clip.scene}")
    start = slot.start + clip.start
    end = slot.start + (clip.end if clip.end is not None else slot.length)
    if not clip.pinned:
        lo, hi = slot.start, slot.start + slot.length
        start = min(max(start, lo), hi)
        end = min(max(end, lo), hi)
    return _r(start), _r(end)


def locate(slots: list[SceneSlot], t: float) -> tuple[str, float] | None:
    """Scene id and time inside it at film time `t` (half-open scene ranges)."""
    if not slots:
        return None
    if t < 0:
        return slots[0].id, 0.0
    for s in slots:
        if t < s.start + s.length:
            return s.id, _r(t - s.start)
    last = slots[-1]
    return last.id, last.length


SFX_SCENE_FADE = 0.08  # seconds: a sound that crosses its scene's end fades out over the last 80 ms and is cut


def _sfx_at(clip: SfxClip, slot: SceneSlot) -> float:
    return min(max(clip.at, 0.0), slot.length)


def _sfx_slot(clip: SfxClip, slots: list[SceneSlot]) -> SceneSlot:
    slot = next((s for s in slots if s.id == clip.scene), None)
    if slot is None:
        raise ValueError(f"sound {clip.id} points to unknown scene {clip.scene}")
    return slot


def sfx_start(clip: SfxClip, slots: list[SceneSlot]) -> float:
    """Absolute start of a sound clip: exactly its scene's start plus `at` (the person's cue), `at` only
    clamped into the scene (0 to the scene length)."""
    slot = _sfx_slot(clip, slots)
    return _r(slot.start + _sfx_at(clip, slot))


def sfx_audible(clip: SfxClip, slots: list[SceneSlot]) -> float:
    """Seconds of the sound that play before its scene ends (the rest is faded out and cut)."""
    slot = _sfx_slot(clip, slots)
    return _r(max(0.0, min(clip.seconds, slot.length - _sfx_at(clip, slot))))
