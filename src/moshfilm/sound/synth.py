"""Small additive-synthesis toolkit: oscillators, envelopes, noise, FFT filters, WAV I/O.

Vectorised numpy only. Randomness only from a `numpy.random.Generator` passed in.
"""
from __future__ import annotations

import wave
from pathlib import Path

import numpy as np

from . import SAMPLE_RATE

SR = SAMPLE_RATE


def _count(seconds: float) -> int:
    return max(0, int(round(seconds * SR)))


def _phase(freq, seconds: float) -> np.ndarray:
    """Phase in cycles. A scalar frequency is constant; an array is the per-sample frequency."""
    if np.ndim(freq) == 0:
        n = _count(seconds)
        return np.arange(n, dtype=np.float64) * (float(freq) / SR)
    f = np.asarray(freq, dtype=np.float64)
    return np.cumsum(f) / SR - f[0] / SR


def sine(freq, seconds: float) -> np.ndarray:
    return np.sin(2 * np.pi * _phase(freq, seconds))


def square(freq, seconds: float, duty: float = 0.5) -> np.ndarray:
    ph = _phase(freq, seconds) % 1.0
    return np.where(ph < duty, 1.0, -1.0)


def saw(freq, seconds: float) -> np.ndarray:
    return 2.0 * (_phase(freq, seconds) % 1.0) - 1.0


def noise(rng: np.random.Generator, seconds: float) -> np.ndarray:
    return rng.uniform(-1.0, 1.0, _count(seconds))


def adsr(n: int, attack: float, decay: float, sustain: float, release: float) -> np.ndarray:
    """Envelope of n samples; the release is the last `release` seconds."""
    a, d, r = _count(attack), _count(decay), min(_count(release), n)
    env = np.full(n, sustain, dtype=np.float64)
    a = min(a, n)
    if a:
        env[:a] = np.linspace(0.0, 1.0, a, endpoint=False)
    d = min(d, max(0, n - a))
    if d:
        env[a:a + d] = np.linspace(1.0, sustain, d, endpoint=False)
    if r:
        start = n - r
        level = env[start - 1] if start > 0 else sustain
        env[start:] = level * np.linspace(1.0, 0.0, r, endpoint=True)
    return env


def exp_decay(n: int, seconds_to_minus_60db: float) -> np.ndarray:
    t = np.arange(n, dtype=np.float64) / SR
    return 10.0 ** (-3.0 * t / max(seconds_to_minus_60db, 1e-4))


def _mask(n: int, lo: float | None, hi: float | None) -> np.ndarray:
    """Band mask over rfft bins with 10 % cosine skirts."""
    f = np.fft.rfftfreq(n, 1.0 / SR)
    m = np.ones_like(f)
    if lo is not None and lo > 0:
        s = lo * 0.1
        x = np.clip((f - (lo - s)) / (2 * s), 0.0, 1.0)
        m *= 0.5 - 0.5 * np.cos(np.pi * x)
    if hi is not None:
        s = hi * 0.1
        x = np.clip((f - (hi - s)) / (2 * s), 0.0, 1.0)
        m *= 0.5 + 0.5 * np.cos(np.pi * x)
    return m


def _filter(x: np.ndarray, lo, hi) -> np.ndarray:
    n = len(x)
    if n == 0:
        return x
    spec = np.fft.rfft(x)
    return np.fft.irfft(spec * _mask(n, lo, hi), n)


def bandpass(x, lo: float, hi: float) -> np.ndarray:
    return _filter(np.asarray(x, dtype=np.float64), lo, hi)


def lowpass(x, hi: float) -> np.ndarray:
    return _filter(np.asarray(x, dtype=np.float64), None, hi)


def highpass(x, lo: float) -> np.ndarray:
    return _filter(np.asarray(x, dtype=np.float64), lo, None)


def sweep_bandpass(x, centers: np.ndarray, q: float = 2.0) -> np.ndarray:
    """Band-pass whose centre follows `centers` (Hz, per sample): 20 ms Hann overlap-add frames,
    each FFT-filtered around its own centre."""
    x = np.asarray(x, dtype=np.float64)
    n = len(x)
    frame = max(16, _count(0.02))
    hop = frame // 2
    win = np.hanning(frame + 1)[:frame]  # periodic Hann: sums to 1 at 50 % overlap
    out = np.zeros(n + frame)
    padded = np.concatenate([x, np.zeros(frame)])
    f = np.fft.rfftfreq(frame, 1.0 / SR)
    for start in range(0, n, hop):
        c = float(centers[min(start + hop, n - 1)])
        bw = max(c / q, 50.0)
        mask = np.exp(-0.5 * ((f - c) / (bw / 2.0)) ** 2)
        seg = padded[start:start + frame] * win
        out[start:start + frame] += np.fft.irfft(np.fft.rfft(seg) * mask, frame)
    return out[:n]


def normalize(x: np.ndarray, peak: float) -> np.ndarray:
    m = float(np.max(np.abs(x))) if len(x) else 0.0
    if m < 1e-12:
        return np.zeros_like(x)
    return x * (peak / m)


def fade(x: np.ndarray, fade_in: float = 0.0, fade_out: float = 0.0) -> np.ndarray:
    """Linear fades (in seconds) on the first and last samples of a mono or (n, 2) array."""
    x = np.array(x, dtype=np.float64, copy=True)
    n = len(x)
    shape = (-1,) + (1,) * (x.ndim - 1)
    fi = min(_count(fade_in), n)
    fo = min(_count(fade_out), n)
    if fi:
        x[:fi] *= np.linspace(0.0, 1.0, fi, endpoint=False).reshape(shape)
    if fo:
        x[n - fo:] *= np.linspace(1.0, 0.0, fo, endpoint=True).reshape(shape)
    return x


def to_stereo(mono: np.ndarray) -> np.ndarray:
    return np.stack([mono, mono], axis=1)


def write_wav(path: Path, stereo: np.ndarray) -> None:
    """16-bit stereo WAV, clipped to +-1; written to `.part` then renamed."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    arr = np.asarray(stereo)
    tmp = path.with_name(path.name + ".part")
    with wave.open(str(tmp), "wb") as w:
        w.setnchannels(2)
        w.setsampwidth(2)
        w.setframerate(SR)
        step = 1 << 20  # chunked: a 10-minute bed must not need several copies in memory
        for i in range(0, len(arr), step):
            chunk = np.clip(arr[i:i + step].astype(np.float64), -1.0, 1.0)
            w.writeframes(np.round(chunk * 32767.0).astype("<i2").tobytes())
    tmp.replace(path)


def read_wav(path: Path) -> np.ndarray:
    """Float32 (n, 2); mono files are duplicated to both channels."""
    with wave.open(str(path), "rb") as w:
        ch, width, n = w.getnchannels(), w.getsampwidth(), w.getnframes()
        raw = w.readframes(n)
    if width != 2:
        raise ValueError(f"{path}: only 16-bit WAV is supported")
    pcm = np.frombuffer(raw, dtype="<i2").astype(np.float32) / 32767.0
    if ch == 1:
        return np.stack([pcm, pcm], axis=1)
    return pcm.reshape(-1, ch)[:, :2]
