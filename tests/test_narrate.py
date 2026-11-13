import asyncio
import re
import subprocess
from pathlib import Path

import pytest

from moshfilm import cli, film, narrate, timing
from moshfilm.film import Film, Scene, VoiceLine
from moshfilm.narrate import NarrationError, VoiceClip
from moshfilm.store import read_json

from conftest import needs_ffmpeg


def make_film(folder: Path, *scenes: Scene) -> Film:
    f = film.new_film(folder, "t")
    f.scenes = list(scenes)
    film.save_film(folder, f)
    return f


def scene(sid, text, length=4.0, pinned=False, offset=0.3):
    return Scene(id=sid, title=sid, length=length, pinned=pinned,
                 voice=VoiceLine(text=text, offset=offset))


def test_voice_key_changes_with_text_voice_rate():
    base = narrate.voice_key("hello", "v1", "+0%")
    assert re.fullmatch(r"[0-9a-f]{16}", base)
    assert base == narrate.voice_key("hello", "v1", "+0%")
    assert len({base, narrate.voice_key("hello!", "v1", "+0%"),
                narrate.voice_key("hello", "v2", "+0%"),
                narrate.voice_key("hello", "v1", "+8%")}) == 4


def test_retry_then_success(tmp_path, fake_tts, monkeypatch):
    delays = []

    async def fake_sleep(d):
        delays.append(d)

    monkeypatch.setattr(asyncio, "sleep", fake_sleep)
    fake_tts.fail = 2
    out = tmp_path / "a.mp3"
    asyncio.run(narrate.synthesize("one two", "v", "+0%", out))
    assert out.exists() and len(fake_tts.calls) == 3
    assert delays == [1, 2]
    assert not list(tmp_path.glob("*.part"))


def test_network_failure_message(tmp_path, fake_tts, monkeypatch):
    async def no_sleep(d):
        pass

    monkeypatch.setattr(asyncio, "sleep", no_sleep)
    fake_tts.fail = 99
    f = make_film(tmp_path, scene("s1", "one two three"))
    with pytest.raises(NarrationError, match="after 4 tries"):
        narrate.ensure_voice(tmp_path, f)
    assert len(fake_tts.calls) == 4
    voice_dir = tmp_path / ".moshfilm" / "voice"
    assert not list(voice_dir.glob("*.mp3*"))
    assert read_json(voice_dir / "index.json", {}) == {}
    assert narrate.voice_durations(tmp_path, f) == {}


def test_ensure_voice_caches(tmp_path, fake_tts):
    f = make_film(tmp_path, scene("s1", "one two three"), scene("s2", ""))
    progress = []
    d = narrate.ensure_voice(tmp_path, f, on_progress=progress.append)
    assert d == {"s1": pytest.approx(0.3)}
    assert len(fake_tts.calls) == 1 and len(progress) == 1
    assert narrate.ensure_voice(tmp_path, f) == d
    assert len(fake_tts.calls) == 1
    assert narrate.voice_durations(tmp_path, f) == d


def test_edited_line_is_not_cached(tmp_path, fake_tts):
    f = make_film(tmp_path, scene("s1", "one two three"), scene("s2", "four five"))
    narrate.ensure_voice(tmp_path, f)
    f.scenes[0].voice.text = "one two three four five six"
    d = narrate.voice_durations(tmp_path, f)
    assert "s1" not in d and d["s2"] == pytest.approx(0.2)
    f.voice.rate = "+20%"
    assert narrate.voice_durations(tmp_path, f) == {}
    assert narrate.ensure_voice(tmp_path, f)["s1"] == pytest.approx(0.6)


def test_voice_clips_follow_layout(tmp_path, fake_tts):
    f = make_film(tmp_path, scene("s1", "a b c", pinned=True, length=2.0),
                  scene("s2", "d e", pinned=True, length=2.0))
    d = narrate.ensure_voice(tmp_path, f)
    slots = timing.layout(f, d)
    clips = narrate.voice_clips(tmp_path, f, slots)
    assert [c.start for c in clips] == [0.3, 2.3]
    assert all(c.path.exists() and c.speed == 1.0 for c in clips)
    f.scenes[1].voice.text = "changed"
    assert len(narrate.voice_clips(tmp_path, f, slots)) == 1


def duration(path):
    return narrate.probe_duration(path)


def sine(path, seconds):
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i",
                    f"sine=frequency=440:duration={seconds}", str(path)], check=True)
    return path


def silences(path):
    r = subprocess.run(["ffmpeg", "-i", str(path), "-af", "silencedetect=noise=-50dB:d=0.1",
                        "-f", "null", "-"], capture_output=True, text=True)
    return [(k, float(v)) for k, v in re.findall(r"silence_(start|end): ([\d.]+)", r.stderr)]


@pytest.mark.slow
@needs_ffmpeg
def test_voice_track_length_and_placement(tmp_path):
    clip = sine(tmp_path / "c.wav", 1.0)
    out = tmp_path / "v.wav"
    narrate.build_voice_track([VoiceClip(clip, 0.5, 1.0), VoiceClip(clip, 3.0, 1.0)], 5.0, out)
    assert duration(out) == pytest.approx(5.0, abs=0.05)
    s = silences(out)
    assert s[0][0] == "start" and s[0][1] < 0.05
    assert s[1] == ("end", pytest.approx(0.5, abs=0.06))


@pytest.mark.slow
@needs_ffmpeg
def test_empty_track_is_silent_of_total_length(tmp_path):
    out = tmp_path / "v.wav"
    narrate.build_voice_track([], 2.0, out)
    assert duration(out) == pytest.approx(2.0, abs=0.05)


@pytest.mark.slow
@needs_ffmpeg
def test_speedup_applied_for_pinned_short_scene(tmp_path, fake_tts_audio):
    f = make_film(tmp_path, scene("s1", " ".join(["w"] * 24), pinned=True, length=2.0, offset=0.0))
    d = narrate.ensure_voice(tmp_path, f)
    assert d["s1"] == pytest.approx(2.4, abs=0.1)
    slots = timing.layout(f, d)
    assert slots[0].voice_speed == pytest.approx(1.2, abs=0.01)
    out = tmp_path / "v.wav"
    narrate.build_voice_track(narrate.voice_clips(tmp_path, f, slots), 4.0, out)
    starts = [t for k, t in silences(out) if k == "start"]
    assert starts[0] == pytest.approx(d["s1"] / slots[0].voice_speed, abs=0.08)


@pytest.mark.slow
@needs_ffmpeg
def test_mix_music_ducks_under_voice(tmp_path):
    voice = tmp_path / "v.wav"
    narrate.build_voice_track([VoiceClip(sine(tmp_path / "c.wav", 1.0), 1.0, 1.0)], 3.0, voice)
    music = sine(tmp_path / "m.wav", 6.0)
    out = tmp_path / "mix.wav"
    narrate.mix_music(voice, music, 0.6, 3.0, out)
    assert duration(out) == pytest.approx(3.0, abs=0.05)


def test_cli_voice_reports_overflow(tmp_path, fake_tts, capsys):
    make_film(tmp_path,
              scene("s1", "one two three", length=4.0, pinned=True),
              scene("s2", " ".join(["w"] * 20), length=1.0, pinned=True),
              scene("s3", "", length=2.0),
              scene("s4", " ".join(["w"] * 22), length=2.5, pinned=True, offset=0.0))
    code = cli.main(["voice", str(tmp_path)])
    out = capsys.readouterr().out.splitlines()
    assert code == 1
    assert out[0] == "s1  0.3s / 4.0s  ok"
    assert out[1] == "s2  2.0s / 1.0s  voice doesn't fit — stretch scene or shorten line"
    assert out[2] == "s3  no voice line"
    assert out[3] == "s4  2.2s / 2.5s  ok"


def test_cli_voice_ok_exit_zero_and_sped_up(tmp_path, fake_tts, capsys):
    make_film(tmp_path, scene("s1", " ".join(["w"] * 24), length=2.0, pinned=True, offset=0.0))
    assert cli.main(["voice", str(tmp_path)]) == 0
    assert capsys.readouterr().out.strip() == "s1  2.4s / 2.0s  sped up 1.20x"


def test_cli_voice_network_error_exits_1(tmp_path, fake_tts, monkeypatch, capsys):
    async def no_sleep(d):
        pass

    monkeypatch.setattr(asyncio, "sleep", no_sleep)
    fake_tts.fail = 99
    make_film(tmp_path, scene("s1", "hi there"))
    assert cli.main(["voice", str(tmp_path)]) == 1
    assert "after 4 tries" in capsys.readouterr().err


def test_os_trust_store_injected_before_connecting(tmp_path, fake_tts, monkeypatch):
    import sys
    import types

    calls = []
    fake = types.ModuleType("truststore")
    fake.inject_into_ssl = lambda: calls.append("inject")
    monkeypatch.setitem(sys.modules, "truststore", fake)
    monkeypatch.setattr(narrate, "_trust_store_done", False)
    asyncio.run(narrate.synthesize("one two", "v", "+0%", tmp_path / "a.mp3"))
    assert calls == ["inject"]


def test_missing_truststore_falls_back_to_defaults(tmp_path, fake_tts, monkeypatch):
    import sys

    monkeypatch.setitem(sys.modules, "truststore", None)  # import raises ImportError
    monkeypatch.setattr(narrate, "_trust_store_done", False)
    out = tmp_path / "a.mp3"
    asyncio.run(narrate.synthesize("one two", "v", "+0%", out))
    assert out.exists()


@pytest.mark.slow
@needs_ffmpeg
def test_sped_up_first_clip_with_offset_stays_in_sync(tmp_path):
    clip = sine(tmp_path / "c.mp3", 1.0)
    out = tmp_path / "v.wav"
    narrate.build_voice_track([VoiceClip(clip, 0.3, 1.1), VoiceClip(clip, 3.3, 1.0)], 6.0, out)
    assert duration(out) == pytest.approx(6.0, abs=0.02)
    ends = [t for k, t in silences(out) if k == "end"]
    assert ends[0] == pytest.approx(0.3, abs=0.05)
    assert ends[1] == pytest.approx(3.3, abs=0.05)


@pytest.mark.slow
@needs_ffmpeg
def test_mix_music_keeps_track_length_with_sped_up_voice(tmp_path):
    clip = sine(tmp_path / "c.mp3", 1.0)
    voice = tmp_path / "v.wav"
    narrate.build_voice_track([VoiceClip(clip, 0.3, 1.1)], 6.0, voice)
    out = tmp_path / "mix.wav"
    narrate.mix_music(voice, sine(tmp_path / "m.wav", 10.0), 0.6, 6.0, out)
    assert duration(out) == pytest.approx(6.0, abs=0.02)
