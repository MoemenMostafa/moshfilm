import time
from dataclasses import dataclass

import numpy as np
import pytest

from moshfilm.sound import music
from moshfilm.sound.music import MOODS, PALETTES, render_bed, render_phrase

SR = 48000


@dataclass
class Spec:
    mood: str = "calm"
    tempo: int = 120
    key: str = "C"
    scale: str = "major"
    palette: str = "keys"
    seed: int = 1


def test_phrase_length_follows_tempo():
    assert render_phrase(Spec(tempo=120)).shape == (8 * SR, 2)
    assert render_phrase(Spec(tempo=80)).shape == (12 * SR, 2)


@pytest.mark.parametrize("mood", list(MOODS))
@pytest.mark.parametrize("palette", PALETTES)
def test_phrase_loops_without_a_click(mood, palette):
    p = render_phrase(Spec(mood=mood, palette=palette, tempo=MOODS[mood].tempo))
    seam = np.abs(np.diff(np.concatenate([p[-64:], p[:64]]), axis=0)).max()
    assert seam <= np.abs(np.diff(p, axis=0)).max()


def test_bed_length_exact_for_short_and_long():
    short = render_bed(Spec(), 0.4)
    assert len(short) == round(0.4 * SR)
    last = short[-480:]
    assert 20 * np.log10(max(np.abs(last).max(), 1e-9)) < -40
    t = time.time()
    long = render_bed(Spec(), 600.0)
    assert len(long) == 600 * SR
    assert time.time() - t < 20
    with pytest.raises(ValueError):
        render_bed(Spec(), 0)


def _rms(x):
    return float(np.sqrt(np.mean(x.astype(np.float64) ** 2)))


def test_bed_fades_out():
    bed = render_bed(Spec(), 20.0)
    assert _rms(bed[-int(0.2 * SR):]) < 0.1 * _rms(bed[10 * SR:12 * SR])
    assert np.abs(bed).max() == pytest.approx(0.5, abs=1e-3)


def _bass_hz(spec):
    p = render_phrase(spec)[:, 0].astype(np.float64)
    first = synth_lowpass(p[int(0.3 * SR):int(1.8 * SR)])
    spectrum = np.abs(np.fft.rfft(first, 1 << 19))
    return np.argmax(spectrum) * SR / (1 << 19)


def synth_lowpass(x):
    from moshfilm.sound import synth
    return synth.lowpass(x, 110)


def test_same_spec_same_audio_seed_changes_it():
    a, b = render_bed(Spec(), 5.0), render_bed(Spec(), 5.0)
    assert np.array_equal(a, b)
    assert not np.array_equal(a, render_bed(Spec(seed=2), 5.0))
    assert _bass_hz(Spec(key="D")) == pytest.approx(_bass_hz(Spec(key="C")) * 2 ** (2 / 12), rel=0.03)


def _onsets(x):
    mono = np.abs(x[:, 0].astype(np.float64))
    frame = 480
    env = mono[: len(mono) // frame * frame].reshape(-1, frame).mean(axis=1)
    rise = np.diff(env)
    return int(np.sum(rise > 0.3 * rise.max()))


def test_moods_differ():
    calm = render_bed(Spec(mood="calm", tempo=MOODS["calm"].tempo, palette="pad"), 24.0)
    playful = render_bed(Spec(mood="playful", tempo=MOODS["playful"].tempo, palette="chip"), 24.0)
    assert _onsets(playful) > _onsets(calm)


def test_constants():
    assert music.fade_out_seconds(20) == 3.0 and music.fade_out_seconds(4) == 1.0
    assert music.TEMPO_RANGE == (60, 160) and len(music.KEYS) == 12
