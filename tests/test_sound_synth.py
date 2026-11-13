import itertools

import numpy as np
import pytest

from moshfilm.sound import SAMPLE_RATE, sfx, synth
from moshfilm.sound.sfx import PRESETS, render_sfx


@pytest.mark.parametrize("name", list(PRESETS))
def test_every_preset_renders(name):
    x = render_sfx(name)
    assert x.shape == (round(PRESETS[name].base_seconds * SAMPLE_RATE), 2)
    assert np.abs(x).max() == pytest.approx(0.5, abs=1e-3)
    assert np.sqrt(np.mean(x ** 2)) > 0.005
    assert abs(x[0, 0]) < 0.01 and abs(x[-1, 0]) < 0.01


def test_presets_are_reproducible():
    a, b = render_sfx("typewriter", seed=3), render_sfx("typewriter", seed=3)
    assert np.array_equal(a, b)
    assert not np.array_equal(a, render_sfx("typewriter", seed=4))


def _peak_hz(x):
    mono = x[:, 0].astype(np.float64)
    spec = np.abs(np.fft.rfft(mono, 1 << 18))
    return np.argmax(spec) * SAMPLE_RATE / (1 << 18)


def test_pitch_and_stretch():
    assert len(render_sfx("pop", stretch=2)) == 2 * len(render_sfx("pop"))
    assert _peak_hz(render_sfx("ding", pitch=12)) == pytest.approx(2 * _peak_hz(render_sfx("ding")), rel=0.03)


def _bands(x):
    spec = np.abs(np.fft.rfft(x[:, 0].astype(np.float64), 1 << 15))
    f = np.fft.rfftfreq(1 << 15, 1 / SAMPLE_RATE)
    edges = np.geomspace(40, 20000, 49)
    v = np.array([spec[(f >= lo) & (f < hi)].mean() for lo, hi in zip(edges, edges[1:])])
    return v / np.linalg.norm(v)


def test_presets_sound_different():
    spectra = {n: _bands(render_sfx(n)) for n in PRESETS}
    for a, b in itertools.combinations(PRESETS, 2):
        assert float(spectra[a] @ spectra[b]) < 0.98, (a, b)


def test_wav_round_trip_is_byte_identical(tmp_path):
    x = render_sfx("ding")
    synth.write_wav(tmp_path / "a.wav", x)
    synth.write_wav(tmp_path / "b.wav", render_sfx("ding"))
    assert (tmp_path / "a.wav").read_bytes() == (tmp_path / "b.wav").read_bytes()
    assert not list(tmp_path.glob("*.part"))
    back = synth.read_wav(tmp_path / "a.wav")
    assert back.shape == x.shape
    assert np.abs(back - x).max() <= 1 / 32767 + 1e-6


def test_unknown_preset():
    with pytest.raises(KeyError):
        render_sfx("boom")
    assert sfx.PRESETS["ding"].base_seconds == 1.2
