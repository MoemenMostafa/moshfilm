"""Sound warnings for `moshfilm check`: sounds over the narration, too close together, too many."""
from __future__ import annotations

from pathlib import Path

from .. import narrate, timing
from ..film import Film, Issue
SFX_MAX_CUT = 0.3  # a sound cut by more than this share of its length is warned about
from . import SFX_MAX_PER_SCENE, SFX_MIN_GAP, SFX_OVER_VOICE_MAX


def _g(x: float) -> str:
    return f"{round(x, 3):g}"


def sfx_issues(folder: Path, film: Film) -> list[Issue]:
    if not film.sfx:
        return []
    durations = narrate.voice_durations(folder, film)
    slots = timing.layout(film, durations)
    by_scene = {s.id: s for s in slots}
    number = {s.id: f"{i + 1:02d}" for i, s in enumerate(film.scenes)}
    clips = [c for c in film.sfx if c.scene in by_scene]
    issues: list[Issue] = []

    for c in clips:
        heard = timing.sfx_audible(c, slots)
        if heard < c.seconds * (1 - SFX_MAX_CUT):
            issues.append(Issue(level="warning", where=c.id, message=(
                f"sound {c.id} ({c.preset}) at {_g(c.at)} s runs past the end of scene {number[c.scene]} and is "
                f"cut to {_g(heard)} s of {_g(c.seconds)} s; move it earlier or use a shorter sound")))

    windows = []  # (scene number, start, end) of every narration line
    for scene in film.scenes:
        d = durations.get(scene.id)
        if d is not None and scene.id in by_scene:
            slot = by_scene[scene.id]
            windows.append((number[scene.id], slot.voice_start, slot.voice_start + d / slot.voice_speed))

    starts = {c.id: timing.sfx_start(c, slots) for c in clips}
    for c in clips:
        if c.volume <= SFX_OVER_VOICE_MAX:
            continue
        s, e = starts[c.id], starts[c.id] + timing.sfx_audible(c, slots)
        hit = next((n for n, vs, ve in windows if s < ve and e > vs), None)
        if hit is not None:
            issues.append(Issue(level="warning", where=c.id, message=(
                f"sound {c.id} ({c.preset}) at {_g(s)} s plays over the narration of scene {hit}; "
                f"move it before or after the line or turn it down to {round(SFX_OVER_VOICE_MAX * 100)} %")))

    ordered = sorted(clips, key=lambda c: (starts[c.id], c.id))
    for a, b in zip(ordered, ordered[1:]):
        gap = round(starts[b.id] - starts[a.id], 3)
        if gap < SFX_MIN_GAP:
            issues.append(Issue(level="warning", where=b.id, message=(
                f"sounds {a.id} and {b.id} start {_g(gap)} s apart; "
                f"keep at least {_g(SFX_MIN_GAP)} s between sounds")))

    for scene in film.scenes:
        n = sum(1 for c in clips if c.scene == scene.id)
        if n > SFX_MAX_PER_SCENE:
            issues.append(Issue(level="warning", where=scene.id, message=(
                f"scene {number[scene.id]} has {n} sounds; use at most {SFX_MAX_PER_SCENE} per scene")))
    return issues
