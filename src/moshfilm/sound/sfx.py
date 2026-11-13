"""Twelve generated sound-effect presets, rendered deterministically with numpy."""
from __future__ import annotations

from typing import Callable, NamedTuple

import numpy as np

from . import SAMPLE_RATE, SFX_PEAK
from . import synth

SR = SAMPLE_RATE
Fn = Callable[[np.random.Generator, float, float], np.ndarray]


class Preset(NamedTuple):
    base_seconds: float
    label: str
    description: str
    fn: Fn


def _t(dur: float) -> np.ndarray:
    return np.arange(int(round(dur * SR)), dtype=np.float64) / SR


def _place(out: np.ndarray, sound: np.ndarray, at: float) -> None:
    i = int(round(at * SR))
    if i >= len(out):
        return
    j = min(len(out), i + len(sound))
    out[i:j] += sound[:j - i]


def _glide(dur: float, points: list[tuple[float, float]]) -> np.ndarray:
    """Per-sample frequency following (fraction of the length, Hz) points, geometrically."""
    t = _t(dur) / max(dur, 1e-9)
    xs = [p[0] for p in points]
    ys = np.log([p[1] for p in points])
    return np.exp(np.interp(t, xs, ys))


def _bell(freq: float, dur: float, decay: float, amp: float = 1.0) -> np.ndarray:
    n = int(round(dur * SR))
    out = np.zeros(n)
    for ratio, a, d in ((1.0, 1.0, 1.0), (2.76, 0.5, 0.6), (5.4, 0.25, 0.35)):
        f = freq * ratio
        if f < SR / 2.2:
            out += a * synth.sine(f, dur) * synth.exp_decay(n, decay * d)
    out *= np.minimum(1.0, np.arange(n) / (0.002 * SR))
    return out * amp


def whoosh(rng, r, s):
    dur = 0.55 * s
    centers = _glide(dur, [(0, 300 * r), (0.4, 2500 * r), (1, 600 * r)])
    x = synth.sweep_bandpass(synth.noise(rng, dur), centers, q=1.5)
    t = _t(dur) / dur
    return x * np.sin(np.pi * t) ** 2


def swoosh_up(rng, r, s):
    dur = 0.4 * s
    centers = _glide(dur, [(0, 400 * r), (1, 5000 * r)])
    x = synth.sweep_bandpass(synth.noise(rng, dur), centers, q=1.5)
    t = _t(dur) / dur
    return x * t ** 1.5 * np.clip((1 - t) * 8, 0, 1)


def door(rng, r, s):
    dur = 0.7 * s
    out = np.zeros(int(round(dur * SR)))
    n = len(out)
    out += 1.2 * synth.sine(60 * r, dur) * synth.exp_decay(n, 0.25 * s)
    for at in (0.0, 0.12):
        k = synth.bandpass(synth.noise(rng, 0.1 * s), 200 * r, 900 * r)
        k *= synth.exp_decay(len(k), 0.06 * s)
        _place(out, k, at * s)
    latch = synth.highpass(synth.noise(rng, 0.03 * s), 2000 * r)
    latch *= synth.exp_decay(len(latch), 0.012 * s)
    _place(out, 0.6 * latch / max(1e-9, np.abs(latch).max()), 0.45 * s)
    return out


def ding(rng, r, s):
    return _bell(1320 * r, 1.2 * s, 0.9 * s)


def pop(rng, r, s):
    dur = 0.08 * s
    f = _glide(dur, [(0, 900 * r), (1, 180 * r)])
    return synth.sine(f, dur) * synth.exp_decay(len(f), 0.06 * s)


def tick(rng, r, s):
    dur = 0.02 * s
    x = synth.highpass(synth.noise(rng, dur), 4000 * r)
    return x * synth.exp_decay(len(x), 0.006 * s)


def click(rng, r, s):
    dur = 0.06 * s
    out = np.zeros(int(round(dur * SR)))
    for at in (0.0, 0.015):
        k = synth.bandpass(synth.noise(rng, 0.02 * s), 1000 * r, 3200 * r)
        _place(out, k * synth.exp_decay(len(k), 0.008 * s), at * s)
    return out


def success(rng, r, s):
    dur = 0.9 * s
    out = np.zeros(int(round(dur * SR)))
    for i, f in enumerate((1046.5, 1318.5, 1568.0)):
        last = i == 2
        length = (dur - 0.3 * s) if last else 0.5 * s
        _place(out, _bell(f * r, length, 0.35 * s * (2 if last else 1)), 0.15 * s * i)
    return out


def error(rng, r, s):
    dur = 0.45 * s
    n = int(round(dur * SR))
    x = synth.square(110 * r, dur) + synth.square(116 * r, dur)
    x = synth.lowpass(x, 800 * r)
    t = _t(dur) / dur
    gate = (((t < 0.4) | ((t > 0.53) & (t < 0.93))).astype(np.float64))
    gate = synth.lowpass(gate, 200)  # soften the edges so the pulses do not click
    return x[:n] * np.clip(gate, 0, 1)


def typewriter(rng, r, s):
    dur = 1.0 * s
    out = np.zeros(int(round(dur * SR)))
    t = 0.02
    while t < dur - 0.03:
        k = synth.bandpass(synth.noise(rng, 0.03), 1000 * r, 5000 * r)
        k *= synth.exp_decay(len(k), 0.008) * rng.uniform(0.6, 1.0)
        th = synth.sine(180 * r, 0.03) * synth.exp_decay(int(0.03 * SR), 0.01) * 0.5
        _place(out, k + th, t)
        t += rng.uniform(0.07, 0.15)
    return out


def riser(rng, r, s):
    dur = 1.5 * s
    centers = _glide(dur, [(0, 200 * r), (1, 6000 * r)])
    x = synth.sweep_bandpass(synth.noise(rng, dur), centers, q=1.0)
    x = x / max(1e-9, np.abs(x).max())
    tone = synth.saw(_glide(dur, [(0, 150 * r), (1, 1200 * r)]), dur)
    tone = synth.lowpass(tone, 4000)
    t = _t(dur) / dur
    return (x + 0.5 * tone) * t ** 2


def thud(rng, r, s):
    dur = 0.3 * s
    f = _glide(dur, [(0, 70 * r), (1, 45 * r)])
    x = synth.sine(f, dur) * synth.exp_decay(len(f), 0.12 * s)
    n = synth.lowpass(synth.noise(rng, 0.03 * s), 300) * 0.3
    x[:len(n)] += n * synth.exp_decay(len(n), 0.01)
    return x


PRESETS: dict[str, Preset] = {
    "whoosh": Preset(0.55, "Whoosh", "air sweep, for something sliding in or a scene change", whoosh),
    "swoosh-up": Preset(0.4, "Swoosh up", "rising sweep, for something lifting or appearing", swoosh_up),
    "door": Preset(0.7, "Door", "a knock and a latch click, for an entrance or a closing", door),
    "ding": Preset(1.2, "Ding", "bell, for a correct answer or a found item", ding),
    "pop": Preset(0.08, "Pop", "soft pop, for a bubble or a small item appearing", pop),
    "tick": Preset(0.02, "Tick", "tiny click, for a counter or a step", tick),
    "click": Preset(0.06, "Click", "double click, for a button press", click),
    "success": Preset(0.9, "Success", "rising chime, for a finished task or a win", success),
    "error": Preset(0.45, "Error", "low double buzz, for a failure or a warning", error),
    "typewriter": Preset(1.0, "Typewriter", "key clicks, for text being typed", typewriter),
    "riser": Preset(1.5, "Riser", "building sweep, for tension before a reveal", riser),
    "thud": Preset(0.3, "Thud", "low hit, for something heavy landing", thud),
}


def render_sfx(preset: str, pitch: float = 0, stretch: float = 1, seed: int = 0) -> np.ndarray:
    """Stereo float32 (n, 2) of `round(base * stretch * 48000)` frames with peak SFX_PEAK."""
    p = PRESETS[preset]  # KeyError for an unknown name
    rng = np.random.default_rng(seed)
    mono = np.asarray(p.fn(rng, 2.0 ** (pitch / 12.0), float(stretch)), dtype=np.float64)
    n = int(round(p.base_seconds * stretch * SR))
    if len(mono) < n:
        mono = np.concatenate([mono, np.zeros(n - len(mono))])
    mono = synth.fade(mono[:n], 0.002, 0.002)
    mono = synth.normalize(mono, SFX_PEAK)
    return synth.to_stereo(mono).astype(np.float32)
