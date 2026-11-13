"""Place sound effects on the film timeline and add them to the voice+music track."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import wave

import numpy as np

from .. import timing
from ..film import Film
from . import LIMIT, SAMPLE_RATE
from . import cache, synth


@dataclass
class PlacedSfx:
    path: Path
    start: float
    volume: float
    end: float | None = None  # absolute second the sound is cut at (its scene's end); None: play it all


def placed_sfx(folder: Path, film: Film, slots: list[timing.SceneSlot]) -> list[PlacedSfx]:
    """Every clip of a scene that exists, rendered (cached) and placed by its scene's anchor."""
    known = {s.id for s in slots}
    ends = {s.id: round(s.start + s.length, 3) for s in slots}
    return [PlacedSfx(cache.ensure_sfx(folder, c), timing.sfx_start(c, slots), c.volume, ends[c.scene])
            for c in film.sfx if c.scene in known]


def limit(x: np.ndarray, knee: float = 0.9, ceiling: float = LIMIT) -> np.ndarray:
    """Soft limiter: identity below `knee`, a smooth tanh curve above it, never beyond `ceiling`."""
    x = np.asarray(x)
    mag = np.abs(x)
    room = ceiling - knee
    over = knee + room * np.tanh((mag - knee) / room)
    return np.where(mag <= knee, x, np.sign(x) * np.minimum(over, ceiling)).astype(x.dtype, copy=False)


BLOCK = 10 * SAMPLE_RATE  # frames per block: the mix is processed 10 s at a time
TAIL_FADE = int(0.010 * SAMPLE_RATE)
SCENE_FADE = int(timing.SFX_SCENE_FADE * SAMPLE_RATE)


def add_sfx_to_wav(base_wav: Path, clips: list[PlacedSfx], total: float, out_wav: Path) -> None:
    """`base_wav` plus every clip (x its volume) at its start, then limited; written in blocks.

    A clip is cut at its scene end (80 ms fade-out) and at the film end (10 ms fade-out), so a cut never clicks.
    With no clips it still applies `limit` and writes."""
    with wave.open(str(base_wav), "rb") as src:
        channels, width, frames = src.getnchannels(), src.getsampwidth(), src.getnframes()
        if width != 2:
            raise ValueError(f"{base_wav}: only 16-bit WAV is supported")
        n = min(frames, int(round(total * SAMPLE_RATE))) if total > 0 else frames
        placed = []  # (start frame, samples x volume)
        for clip in clips:
            i = int(round(clip.start * SAMPLE_RATE))
            if i >= n:
                continue
            sound = synth.read_wav(clip.path) * np.float32(clip.volume)
            keep, fade = len(sound), 0
            if clip.end is not None and i + keep > int(round(clip.end * SAMPLE_RATE)):
                keep, fade = max(0, int(round(clip.end * SAMPLE_RATE)) - i), SCENE_FADE  # cut at the scene end
            if i + keep > n:
                keep, fade = n - i, TAIL_FADE  # cut at the film end
            if keep < len(sound):
                sound = sound[:keep].copy()
                f = min(fade, len(sound))
                if f:
                    sound[len(sound) - f:] *= np.linspace(1.0, 0.0, f, dtype=np.float32)[:, None]
            if len(sound):
                placed.append((i, sound))
        out_wav = Path(out_wav)
        out_wav.parent.mkdir(parents=True, exist_ok=True)
        tmp = out_wav.with_name(out_wav.name + ".part")
        with wave.open(str(tmp), "wb") as dst:
            dst.setnchannels(2)
            dst.setsampwidth(2)
            dst.setframerate(SAMPLE_RATE)
            for start in range(0, n, BLOCK):
                count = min(BLOCK, n - start)
                raw = np.frombuffer(src.readframes(count), dtype="<i2")
                block = raw.reshape(-1, channels)[:, :2].astype(np.float32) / 32767.0
                if channels == 1:
                    block = np.repeat(block[:, :1], 2, axis=1)
                if len(block) < count:  # a base shorter than `total`: pad with silence
                    block = np.concatenate([block, np.zeros((count - len(block), 2), np.float32)])
                for i, sound in placed:
                    lo, hi = max(i, start), min(i + len(sound), start + count)
                    if lo < hi:
                        block[lo - start:hi - start] += sound[lo - i:hi - i]
                limited = limit(block)
                dst.writeframes(np.round(np.clip(limited, -1.0, 1.0) * 32767.0).astype("<i2").tobytes())
    tmp.replace(out_wav)
