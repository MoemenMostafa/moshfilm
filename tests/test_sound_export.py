import shutil
import subprocess
from pathlib import Path

import numpy as np
import pytest

from moshfilm import export, film, narrate, timing
from moshfilm.film import Music, MusicBed, SfxClip
from moshfilm.sound import cache, mix, synth

COLORS = Path(__file__).parent / "fixtures" / "films" / "colors"
SR = 48000
HAVE_FFMPEG = bool(shutil.which("ffmpeg") and shutil.which("ffprobe"))


def _have_chromium() -> bool:
    try:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            return Path(p.chromium.executable_path).exists()
    except Exception:
        return False


needs_ffmpeg = pytest.mark.skipif(not HAVE_FFMPEG, reason="ffmpeg/ffprobe not installed")
needs_chromium = pytest.mark.skipif(not HAVE_FFMPEG or not _have_chromium(),
                                    reason="ffmpeg or Playwright Chromium not installed")


@pytest.fixture
def colors(tmp_path):
    folder = tmp_path / "colors"
    shutil.copytree(COLORS, folder)
    return folder


def _edit(folder, fn):
    f = film.load_film(folder)
    fn(f)
    film.save_film(folder, f)


def _decode(path: Path) -> np.ndarray:
    raw = subprocess.run(["ffmpeg", "-v", "error", "-i", str(path), "-f", "s16le", "-ac", "1",
                          "-ar", str(SR), "-"], capture_output=True, check=True).stdout
    return np.frombuffer(raw, dtype="<i2").astype(np.float64) / 32768.0


def _rms(x):
    return float(np.sqrt(np.mean(x ** 2))) if len(x) else 0.0


def test_limit_curve():
    x = np.linspace(-0.9, 0.9, 101)
    assert np.array_equal(mix.limit(x), x)
    assert mix.limit(np.array([5.0]))[0] <= 0.95 and mix.limit(np.array([-5.0]))[0] >= -0.95
    ramp = mix.limit(np.linspace(0, 6, 1000))
    assert np.all(np.diff(ramp) >= 0) and ramp.max() <= 0.95


def test_placed_sfx_uses_scene_anchor(colors):
    def setup(f):
        f.sfx = [SfxClip(id="fx1", scene="blue", preset="ding", at=0.5, volume=0.4),
                 SfxClip(id="fx2", scene="red", preset="pop", at=0.25)]
    _edit(colors, setup)
    the_film = film.load_film(colors)
    slots = timing.layout(the_film, {})
    placed = mix.placed_sfx(colors, the_film, slots)
    # exactly on its cue (scene start 1 s + 0.5 s); the end is where its scene ends, where it will be cut
    assert [(p.start, p.volume, p.end) for p in placed] == [(1.5, 0.4, 2.0), (0.25, 0.7, 1.0)]
    assert all(p.path.is_file() for p in placed)


def test_add_sfx_cuts_tail_and_limits(tmp_path):
    base = tmp_path / "base.wav"
    synth.write_wav(base, np.zeros((SR, 2)))
    clip = tmp_path / "c.wav"
    synth.write_wav(clip, np.ones((SR // 2, 2)) * 0.9)
    mix.add_sfx_to_wav(base, [mix.PlacedSfx(clip, 0.75, 1.0), mix.PlacedSfx(clip, 0.75, 1.0)], 1.0,
                       tmp_path / "o.wav")
    out = synth.read_wav(tmp_path / "o.wav")
    assert len(out) == SR and np.abs(out).max() <= 0.95 + 1e-4 and np.abs(out[SR // 2]).max() == 0


def test_sfx_cut_at_the_film_end_fades_out(tmp_path):
    base = tmp_path / "base.wav"
    synth.write_wav(base, np.zeros((SR, 2)))
    clip = tmp_path / "c.wav"
    synth.write_wav(clip, np.ones((SR, 2)) * 0.5)  # 1 s of a flat tone starting 0.5 s before the end
    mix.add_sfx_to_wav(base, [mix.PlacedSfx(clip, 0.5, 1.0)], 1.0, tmp_path / "o.wav")
    out = synth.read_wav(tmp_path / "o.wav")[:, 0]
    assert out[-1] == pytest.approx(0, abs=1e-3)           # without the fade this is 0.5: a click
    assert out[-480 - 50] == pytest.approx(0.5, abs=1e-3)  # the fade is only the last 10 ms
    assert np.abs(np.diff(out[SR // 2 + 10:])).max() < 0.01  # after the onset: no step at the cut


def test_mix_in_blocks_matches_one_pass(tmp_path, monkeypatch):
    rng = np.random.default_rng(0)
    base = tmp_path / "base.wav"
    synth.write_wav(base, rng.uniform(-0.6, 0.6, (SR * 3, 2)))
    clip = tmp_path / "c.wav"
    synth.write_wav(clip, rng.uniform(-0.6, 0.6, (SR // 2, 2)))
    clips = [mix.PlacedSfx(clip, 1.9, 1.0)]  # straddles the block boundary used below
    mix.add_sfx_to_wav(base, clips, 3.0, tmp_path / "one.wav")
    monkeypatch.setattr(mix, "BLOCK", 2 * SR)
    mix.add_sfx_to_wav(base, clips, 3.0, tmp_path / "blocks.wav")
    assert (tmp_path / "one.wav").read_bytes() == (tmp_path / "blocks.wav").read_bytes()


@pytest.mark.slow
@needs_ffmpeg
def test_final_mix_never_clips(tmp_path):
    t = np.arange(2 * SR) / SR
    voice = np.sin(2 * np.pi * 440 * t) * 0.9
    base = tmp_path / "voice.wav"
    synth.write_wav(base, np.stack([voice, voice], axis=1))
    clips = []
    for name in ("riser", "ding", "thud"):
        p = tmp_path / f"{name}.wav"
        from moshfilm.sound import sfx
        synth.write_wav(p, sfx.render_sfx(name))
        clips.append(mix.PlacedSfx(p, 0.2, 1.0))
    mixed = tmp_path / "mixed.wav"
    music = tmp_path / "music.wav"
    synth.write_wav(music, np.stack([voice, voice], axis=1))
    narrate.mix_music(base, music, 1.0, 2.0, mixed)
    mix.add_sfx_to_wav(mixed, clips, 2.0, tmp_path / "out.wav")
    pre = synth.read_wav(mixed)
    for c in clips:
        i = int(c.start * SR)
        sound = synth.read_wav(c.path)
        pre[i:i + len(sound)] += sound
    assert np.abs(pre).max() > 0.95, "the test mix must really be too loud before the limiter"
    out = synth.read_wav(tmp_path / "out.wav")
    assert np.isfinite(out).all()
    assert np.abs(out).max() <= 0.95 + 1e-4
    assert np.abs(out).max() > 0.9  # limited, not flattened to silence


@pytest.mark.slow
@needs_ffmpeg
def test_generated_bed_is_ducked(colors, tmp_path, fake_tts_audio, monkeypatch):
    def setup(f):
        f.scenes[0].length, f.scenes[0].pinned = 5.0, True
        f.scenes[1].length, f.scenes[1].pinned = 3.0, True
        f.scenes[0].voice.text = " ".join(["word"] * 20)  # 2.0 s, spoken 0.3-2.3 s
        f.music = Music(bed=MusicBed(mood="bright", tempo=112), volume=0.8)
    _edit(colors, setup)
    the_film = film.load_film(colors)
    durations = narrate.ensure_voice(colors, the_film)
    slots = timing.layout(the_film, durations)
    total = timing.total_length(slots)
    seen = {}
    real = narrate.mix_music

    def spy(voice_wav, music, volume, total_, out_wav):
        seen["music"] = music
        real(voice_wav, music, volume, total_, out_wav)
        seen["voice"], seen["out"] = voice_wav, out_wav

    monkeypatch.setattr(narrate, "mix_music", spy)
    work = tmp_path / "work"
    work.mkdir()
    out = export._build_audio(colors, the_film, slots, total, True, work)
    assert seen["music"] == cache.ensure_bed(colors, the_film, total)
    ducked = synth.read_wav(out)[:, 0] - synth.read_wav(seen["voice"])[:, 0]  # the music alone, as mixed
    inside = _rms(ducked[int(0.8 * SR):int(2.2 * SR)])
    outside = _rms(ducked[int(3.0 * SR):int(5.5 * SR)])
    assert inside < 0.6 * outside


@pytest.mark.slow
@needs_chromium
def test_export_has_sfx_at_its_moment(colors, tmp_path):
    def setup(f):
        f.scenes[1].length, f.scenes[1].pinned = 3.0, True  # room for the 1.2 s ding to start at 0.5 s
        f.sfx = [SfxClip(id="fx1", scene="blue", preset="ding", at=0.5)]
    _edit(colors, setup)
    out = export.export_film(colors, "mp4", out=tmp_path / "o.mp4", voice=False)
    audio = _decode(out)
    start = int(1.5 * SR)
    assert _rms(audio[start:start + int(0.3 * SR)]) > 0.02
    assert _rms(audio[start - SR:start - int(0.02 * SR)]) < 0.002


@pytest.mark.slow
@needs_chromium
def test_export_two_shapes_same_audio(colors, tmp_path):
    def setup(f):
        f.second_aspect = "9:16"
        f.music = Music(bed=MusicBed(mood="calm", tempo=80))
        f.sfx = [SfxClip(id="fx1", scene="red", preset="pop", at=0.4)]
    _edit(colors, setup)
    paths = export.export_aspects(colors, "mp4", out=tmp_path / "o.mp4", voice=False)
    assert len(paths) == 2
    a, b = (_decode(p) for p in paths.values())
    assert len(a) == len(b) and np.array_equal(a, b) and _rms(a) > 0.001


@pytest.mark.slow
@needs_ffmpeg
def test_old_music_file_still_mixes_and_missing_file_errors(colors, tmp_path):
    (colors / "music").mkdir()
    synth.write_wav(colors / "music" / "a.wav", np.ones((2 * SR, 2)) * 0.3)
    _edit(colors, lambda f: setattr(f, "music", Music.model_validate({"file": "music/a.wav", "volume": 0.6})))
    the_film = film.load_film(colors)
    slots = timing.layout(the_film, {})
    work = tmp_path / "w"
    work.mkdir()
    out = export._build_audio(colors, the_film, slots, 2.0, True, work)
    assert _rms(synth.read_wav(out)[:, 0]) > 0.1
    (colors / "music" / "a.wav").unlink()
    with pytest.raises(export.ExportError, match="music file not found: music/a.wav"):
        export._build_audio(colors, the_film, slots, 2.0, True, work)


@pytest.mark.slow
@needs_ffmpeg
def test_export_limits_even_without_sound_effects(colors, tmp_path, monkeypatch):
    (colors / "music").mkdir()
    synth.write_wav(colors / "music" / "hot.wav", np.ones((2 * SR, 2)) * 0.99)
    _edit(colors, lambda f: setattr(f, "music", Music.model_validate({"file": "music/hot.wav", "volume": 1.0})))
    the_film = film.load_film(colors)
    assert the_film.sfx == []
    slots = timing.layout(the_film, {})
    seen = {}
    real = narrate.mix_music
    def spy(voice_wav, music, volume, total, out_wav):
        real(voice_wav, music, volume, total, out_wav)
        seen["pre"] = np.abs(synth.read_wav(out_wav)).max()
    monkeypatch.setattr(narrate, "mix_music", spy)
    work = tmp_path / "w"
    work.mkdir()
    out = export._build_audio(colors, the_film, slots, 2.0, True, work)
    assert seen["pre"] > 0.95  # the ducked music alone is hotter than the ceiling
    assert np.abs(synth.read_wav(out)).max() <= 0.95 + 1e-4


def test_sfx_crossing_the_scene_end_fades_over_80_ms_and_is_cut(tmp_path):
    base = tmp_path / "base.wav"
    synth.write_wav(base, np.zeros((3 * SR, 2)))
    clip = tmp_path / "c.wav"
    synth.write_wav(clip, np.ones((2 * SR, 2)) * 0.5)  # 2 s of flat tone, scene ends 1 s after it starts
    mix.add_sfx_to_wav(base, [mix.PlacedSfx(clip, 0.5, 1.0, end=1.5)], 3.0, tmp_path / "o.wav")
    out = synth.read_wav(tmp_path / "o.wav")[:, 0]
    assert out[int(1.5 * SR) - 1] == pytest.approx(0, abs=2e-3)       # faded to nothing at the scene end
    assert np.abs(out[int(1.5 * SR):]).max() == 0                    # nothing rings into the next scene
    assert out[int(1.5 * SR) - int(0.08 * SR) - 100] == pytest.approx(0.5, abs=1e-3)  # fade is the last 80 ms
    assert out[int(1.5 * SR) - int(0.04 * SR)] == pytest.approx(0.25, abs=0.02)       # halfway down halfway through
    assert out[int(0.5 * SR) + 100] == pytest.approx(0.5, abs=1e-3)  # the start is exactly on the cue


def test_sfx_at_the_scene_end_plays_nothing(tmp_path):
    base = tmp_path / "base.wav"
    synth.write_wav(base, np.zeros((SR, 2)))
    clip = tmp_path / "c.wav"
    synth.write_wav(clip, np.ones((SR // 2, 2)) * 0.5)
    mix.add_sfx_to_wav(base, [mix.PlacedSfx(clip, 0.5, 1.0, end=0.5)], 1.0, tmp_path / "o.wav")
    assert np.abs(synth.read_wav(tmp_path / "o.wav")).max() == 0
