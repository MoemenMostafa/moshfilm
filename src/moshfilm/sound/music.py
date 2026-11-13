"""Music bed: a mood-driven 4-bar phrase (bass, chords, arpeggio, drums) tiled to the film length."""
from __future__ import annotations

import math
from typing import NamedTuple

import numpy as np

from . import BED_PEAK, SAMPLE_RATE
from . import synth

SR = SAMPLE_RATE
PALETTES = ("keys", "pluck", "pad", "chip")
KEYS = ("C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B")
SCALES = ("major", "minor")
TEMPO_RANGE = (60, 160)
FADE_IN = 0.01
TAIL = 1.5  # seconds a note may ring past the phrase end (wrapped onto its start)

_STEPS = {"major": (0, 2, 4, 5, 7, 9, 11), "minor": (0, 2, 3, 5, 7, 8, 10)}


class Mood(NamedTuple):
    tempo: int
    scale: str
    palette: str
    progression: tuple[int, ...]
    drums: str       # "none" | "soft" | "pulse" | "kick13"
    density: float   # chance of an arpeggio note per eighth
    label: str


MOODS: dict[str, Mood] = {
    "calm": Mood(80, "major", "pad", (1, 6, 4, 5), "none", 0.35, "Calm"),
    "bright": Mood(112, "major", "pluck", (1, 5, 6, 4), "soft", 0.6, "Bright"),
    "playful": Mood(120, "major", "chip", (1, 4, 5, 4), "none", 0.75, "Playful"),
    "tense": Mood(92, "minor", "pad", (1, 6, 3, 7), "pulse", 0.5, "Tense"),
    "inspiring": Mood(100, "major", "keys", (6, 4, 1, 5), "kick13", 0.55, "Inspiring"),
}


def fade_out_seconds(total: float) -> float:
    return min(3.0, 0.25 * total)


def _hz(midi: float) -> float:
    return 440.0 * 2.0 ** ((midi - 69) / 12.0)


def _step(scale: str, degree: int) -> int:
    steps = _STEPS[scale]
    return steps[(degree - 1) % 7] + 12 * ((degree - 1) // 7)


def _taper(x: np.ndarray, seconds: float = 0.02) -> np.ndarray:
    """Attack of 2 ms and a short taper at the end so no note starts or stops with a step."""
    n = len(x)
    a = min(n, int(0.002 * SR))
    if a:
        x[:a] *= np.linspace(0.0, 1.0, a, endpoint=False)
    r = min(n, int(seconds * SR))
    if r:
        x[n - r:] *= np.linspace(1.0, 0.0, r)
    return x


def _tone(palette: str, midi: float, dur: float, rng: np.random.Generator) -> np.ndarray:
    """One note of `dur` seconds plus its release, in the timbre of a palette."""
    f = _hz(midi)
    if palette == "pad":
        total = dur + 0.5
        n = int(round(total * SR))
        x = sum(synth.saw(f * d, total) for d in (0.996, 1.0, 1.004)) / 3.0
        x = synth.lowpass(x, 2000)
        return _taper(x * synth.adsr(n, 0.3, 0.0, 1.0, 0.5))
    if palette == "pluck":
        total = dur + 0.15
        n = int(round(total * SR))
        x = sum(synth.sine(f * k, total) / k for k in range(1, 7) if f * k < SR / 2.2)
        return _taper(x * synth.exp_decay(n, 0.35))
    if palette == "chip":
        total = dur + 0.03
        n = int(round(total * SR))
        x = synth.square(f, total, duty=0.25) * 0.5
        env = np.minimum(1.0, synth.exp_decay(n, 0.5) * 1.5)
        return _taper(x * env)
    total = dur + 0.4  # keys
    n = int(round(total * SR))
    x = synth.sine(f, total) + 0.3 * synth.sine(2 * f, total) * synth.exp_decay(n, 0.5)
    return _taper(x * synth.exp_decay(n, 1.2))


def _bass(midi: float, dur: float) -> np.ndarray:
    total = dur + 0.1
    f = _hz(midi)
    x = synth.sine(f, total) + 0.25 * synth.sine(2 * f, total)
    return _taper(x * synth.adsr(int(round(total * SR)), 0.01, 0.3, 0.8, 0.1))


def _kick(amp: float) -> np.ndarray:
    dur = 0.25
    f = np.exp(np.interp(np.arange(int(dur * SR)) / (dur * SR), [0, 0.15, 1], np.log([140, 50, 42])))
    return _taper(synth.sine(f, dur) * synth.exp_decay(len(f), 0.18), 0.01) * amp


def _hat(rng: np.random.Generator, amp: float) -> np.ndarray:
    x = synth.highpass(synth.noise(rng, 0.06), 7000)
    return _taper(x * synth.exp_decay(len(x), 0.025), 0.005) * amp


def _add(buf: np.ndarray, sound: np.ndarray, at: int, gain: float = 1.0) -> None:
    if at >= len(buf):
        return
    j = min(len(buf), at + len(sound))
    buf[at:j] += sound[:j - at] * gain


def render_phrase(spec) -> np.ndarray:
    """Stereo (n, 2) of exactly 4 bars of 4/4 at `spec.tempo`, circular: ringing notes wrap onto the start."""
    mood = MOODS[spec.mood]
    scale = spec.scale
    key = KEYS.index(spec.key)
    beat = 60.0 / spec.tempo * SR
    n = int(round(16 * beat))
    tail = int(TAIL * SR)
    buf = np.zeros(n + tail)
    rng = np.random.default_rng(spec.seed)
    chord_base = 48 + key - (12 if key >= 7 else 0)
    inversion = spec.seed % 3
    pal = spec.palette
    arp_pal = "keys" if pal == "pad" else pal

    for bar in range(4):
        degree = mood.progression[bar]
        t0 = bar * 4 * beat
        bar_s = 4 * beat / SR
        # bass: the chord root in octave 2
        _add(buf, _bass(36 + (key + _step(scale, degree)) % 12, bar_s * 0.95), int(round(t0)), 0.9)
        # chord: triad, voicing inversion from the seed
        tones = [chord_base + _step(scale, degree + k) for k in (0, 2, 4)]
        for _ in range(inversion):
            tones = tones[1:] + [tones[0] + 12]
        hits = {"pad": 1, "keys": 1, "pluck": 2, "chip": 4}[pal]
        hit_s = bar_s / hits
        for h in range(hits):
            at = int(round(t0 + h * 4 * beat / hits))
            for m in tones:
                _add(buf, _tone(pal, m, hit_s * (0.9 if pal != "chip" else 0.45), rng), at, 0.5 / 3 * 1.6)
        # arpeggio / melody: chord tones per eighth, kept with probability `density`
        pool = [m + 12 for m in tones] + [tones[0] + 24]
        eighth = beat / 2
        for e in range(8):
            keep, pick = rng.random() < mood.density, int(rng.integers(0, len(pool)))
            if keep:
                length = eighth / SR * (1.5 if arp_pal == "keys" else 0.9)
                _add(buf, _tone(arp_pal, pool[pick], length, rng), int(round(t0 + e * eighth)), 0.3)
        # drums
        if mood.drums == "soft":
            for b in (0, 2):
                _add(buf, _kick(0.5), int(round(t0 + b * beat)))
            for e in range(8):
                if e % 2 == 1:
                    _add(buf, _hat(rng, 0.12), int(round(t0 + e * eighth)))
        elif mood.drums == "pulse":
            for b in range(4):
                _add(buf, _kick(0.35 if b else 0.5), int(round(t0 + b * beat)))
        elif mood.drums == "kick13":
            for b in (0, 2):
                _add(buf, _kick(0.7), int(round(t0 + b * beat)))

    over = buf[n:]
    buf = buf[:n]
    buf[:len(over)] += over  # circular wrap: the tail of the last bar rings into the first
    buf = synth.normalize(buf, BED_PEAK)
    return synth.to_stereo(buf).astype(np.float32)


def render_bed(spec, total: float) -> np.ndarray:
    """Stereo float32 bed of exactly round(total * 48000) frames: tiled phrase, faded, peak BED_PEAK."""
    if total <= 0:
        raise ValueError("the film has no length")
    n = int(round(total * SR))
    phrase = render_phrase(spec)
    reps = math.ceil(n / len(phrase))
    bed = np.tile(phrase, (reps, 1))[:n] if reps > 1 else phrase[:n].copy()
    if n < len(phrase):
        bed = synth.normalize(bed, BED_PEAK).astype(np.float32)
    fi = min(n, int(FADE_IN * SR))
    if fi:
        bed[:fi] *= np.linspace(0.0, 1.0, fi, endpoint=False, dtype=np.float32)[:, None]
    fo = min(n, int(round(fade_out_seconds(total) * SR)))
    if fo:
        x = np.linspace(0.0, 1.0, fo, dtype=np.float32)
        bed[n - fo:] *= ((1.0 - x) ** 2)[:, None]  # a squared ramp: the last ms are nearly silent
    return bed
