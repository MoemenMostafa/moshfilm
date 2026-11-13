import io
import os
import wave
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from moshfilm import film as filmmod
from moshfilm import narrate, server
from moshfilm.cli import main
from moshfilm.film import Music, MusicBed, Scene, SfxClip, VoiceLine
from moshfilm.sound import cache, check

BASE = "http://127.0.0.1:5717"
BED = MusicBed(mood="calm", tempo=80)
LINE = " ".join(["word"] * 20)  # 2.0 s with the fake voice: narration window 0.3-2.3 s in scene s1


@pytest.fixture
def folder(tmp_path: Path) -> Path:
    filmmod.new_film(tmp_path, "t")
    f = filmmod.load_film(tmp_path)
    f.scenes = [
        Scene(id="s1", title="one", file="scenes/s1.js", length=5, pinned=True, status="ready",
              voice=VoiceLine(text=LINE, offset=0.3)),
        Scene(id="s2", title="two", file="scenes/s2.js", length=3, pinned=True, status="ready"),
    ]
    f.music = Music(bed=BED)
    f.sfx = [SfxClip(id="fx1", scene="s1", preset="ding", at=3.0), SfxClip(id="fx2", scene="s2", preset="pop")]
    filmmod.save_film(tmp_path, f)
    for name in ("s1", "s2"):
        (tmp_path / "scenes" / f"{name}.js").write_text("export default {}\n")
    return tmp_path


@pytest.fixture
def client(folder):
    return TestClient(server.create_app(folder), base_url=BASE)


def _frames(content: bytes) -> int:
    with wave.open(io.BytesIO(content)) as w:
        assert w.getframerate() == 48000 and w.getnchannels() == 2
        return w.getnframes()


def _edit(folder, fn):
    f = filmmod.load_film(folder)
    fn(f)
    filmmod.save_film(folder, f)


def test_sound_info_lists_bed_and_sfx(client):
    info = client.get("/api/sound").json()
    assert info["music"]["duration"] == 8.0
    r = client.get(info["music"]["url"])
    assert r.headers["content-type"] == "audio/wav" and _frames(r.content) == 8 * 48000
    assert set(info["sfx"]) == {"fx1", "fx2"}
    assert info["sfx"]["fx1"]["duration"] == 1.2
    r = client.get(info["sfx"]["fx1"]["url"])
    assert r.headers["content-type"] == "audio/wav" and _frames(r.content) == round(1.2 * 48000)


def test_sound_info_key_follows_film_length(client):
    first = client.get("/api/sound").json()["music"]
    client.post("/api/film/edit", json={"ops": [{"op": "set_length", "scene": "s2", "length": 4.5}]})
    second = client.get("/api/sound").json()["music"]
    assert second["url"] != first["url"] and second["duration"] == 9.5
    assert _frames(client.get(second["url"]).content) == round(9.5 * 48000)


def test_sound_info_without_scenes(client, folder):
    _edit(folder, lambda f: (setattr(f, "scenes", []), setattr(f, "sfx", [])))
    assert client.get("/api/sound").json() == {"music": None, "sfx": {}}


def test_file_music_has_no_generated_bed(client, folder):
    _edit(folder, lambda f: setattr(f, "music", Music(file="music/a.mp3")))
    assert client.get("/api/sound").json()["music"] is None


def test_sound_file_names_are_checked(client):
    assert client.get("/api/sound/..%2Ffilm.json.wav").status_code == 404
    assert client.get("/api/sound/bed-xyz.wav").status_code == 404
    assert client.get("/api/sound/bed-0123456789abcdef.wav").status_code == 404


def test_presets_endpoint_and_audition(client):
    body = client.get("/api/sound/presets").json()
    assert len(body["sfx"]) == 12 and len(body["moods"]) == 5
    assert body["tempo"] == [60, 160] and len(body["keys"]) == 12
    assert body["moods"][0] == {"name": "calm", "label": "Calm", "tempo": 80, "scale": "major", "palette": "pad"}
    r = client.get("/api/sound/preset/pop.wav")
    assert r.status_code == 200 and _frames(r.content) == round(0.08 * 48000)
    assert client.get("/api/sound/preset/boom.wav").status_code == 404


def _make_beds(folder, count=8):
    the_film = filmmod.load_film(folder)
    paths = []
    for i in range(count):
        paths.append(cache.ensure_bed(folder, the_film, 1.0 + i / 10))
        os.utime(paths[-1], (1000 + i, 1000 + i))  # make every bed look old, oldest first
    return the_film, paths


def test_recent_beds_are_not_pruned(folder):
    the_film = filmmod.load_film(folder)
    for i in range(8):
        cache.ensure_bed(folder, the_film, 1.0 + i / 10)
    assert len(list(cache.sound_dir(folder).glob("bed-*.wav"))) == 8  # all used within the grace period


def test_bed_cache_is_pruned(folder):
    the_film, paths = _make_beds(folder)
    cache.ensure_bed(folder, the_film, 9.0)  # triggers a prune of the old ones
    left = sorted(cache.sound_dir(folder).glob("bed-*.wav"))
    assert len(left) == cache.MAX_BEDS and paths[0] not in left and paths[-1] in left


def test_prune_keeps_a_bed_an_export_holds(folder):
    the_film, paths = _make_beds(folder)
    with cache.use_bed(folder, the_film, 1.0) as held:  # the oldest, held like an export would
        assert held == paths[0]
        cache.ensure_bed(folder, the_film, 9.0)
        assert paths[0].is_file()
    os.utime(paths[0], (1000, 1000))  # using it refreshed its time; age it again
    cache.ensure_bed(folder, the_film, 9.5)  # released: now it can go
    assert not paths[0].exists()


def test_corrupt_cached_bed_is_rendered_again(folder):
    the_film = filmmod.load_film(folder)
    path = cache.ensure_bed(folder, the_film, 1.0)
    good = path.stat().st_size
    path.write_bytes(b"")  # what a racing touch() used to leave behind
    assert cache.ensure_bed(folder, the_film, 1.0) == path and path.stat().st_size == good
    path.write_bytes(b"RIFF" + b"x" * 100)  # truncated nonsense
    cache.ensure_bed(folder, the_film, 1.0)
    assert path.stat().st_size == good


def test_ensure_bed_returns_an_existing_file_when_the_touch_fails(folder, monkeypatch):
    the_film = filmmod.load_film(folder)
    path = cache.ensure_bed(folder, the_film, 1.0)
    real = os.utime
    def vanish(p, *a, **k):  # another thread pruned it between the check and the touch
        path.unlink()
        return real(p, *a, **k)
    monkeypatch.setattr(os, "utime", vanish)
    again = cache.ensure_bed(folder, the_film, 1.0)
    monkeypatch.setattr(os, "utime", real)
    assert again == path and path.is_file() and cache._valid(path)  # rendered again, never an empty or missing file


def test_a_render_that_waited_is_skipped_when_the_film_moved_on(folder):
    import threading

    the_film = filmmod.load_film(folder)
    total = cache.film_total(folder, the_film)
    key = cache.bed_key(the_film.music.bed, total)
    result = {}
    cache._render_slot.acquire()  # a long render is running: the next request has to wait for its turn
    try:
        t = threading.Thread(target=lambda: result.update(
            err=_try(lambda: cache.ensure_bed(folder, the_film, total, only_if_current=True))))
        t.start()
        _edit(folder, lambda f: setattr(f.scenes[1], "length", 4.0))  # the film length (and so the bed) changes
    finally:
        cache._render_slot.release()
    t.join(10)
    assert isinstance(result["err"], cache.StaleBed)
    assert not (cache.sound_dir(folder) / f"bed-{key}.wav").exists()  # the obsolete bed was never rendered


def _try(fn):
    try:
        fn()
    except Exception as exc:  # noqa: BLE001
        return exc


def test_sound_endpoint_answers_409_for_a_stale_bed(client, monkeypatch):
    def stale(*a, **k):
        raise cache.StaleBed("x")
    monkeypatch.setattr(cache, "ensure_bed", stale)
    assert client.get("/api/sound").status_code == 409


def test_prune_grace_is_short():
    assert cache.PRUNE_GRACE == 90


def _issues(folder, fake=True):
    the_film = filmmod.load_film(folder)
    narrate.ensure_voice(folder, the_film)
    return [i.message for i in check.sfx_issues(folder, filmmod.load_film(folder))]


def test_sfx_issues(folder, fake_tts):
    def setup(f):
        f.sfx = [SfxClip(id="fx1", scene="s1", preset="ding", at=1.0, volume=0.7)]
    _edit(folder, setup)
    assert _issues(folder) == ["sound fx1 (ding) at 1 s plays over the narration of scene 01; "
                               "move it before or after the line or turn it down to 35 %"]
    _edit(folder, lambda f: setattr(f.sfx[0], "volume", 0.3))
    assert _issues(folder) == []
    _edit(folder, lambda f: (setattr(f.sfx[0], "volume", 0.7), setattr(f.sfx[0], "at", 3.0)))
    assert _issues(folder) == []

    _edit(folder, lambda f: f.sfx.append(SfxClip(id="fx2", scene="s1", preset="pop", at=3.2, volume=0.3)))
    assert _issues(folder) == ["sounds fx1 and fx2 start 0.2 s apart; keep at least 0.4 s between sounds"]

    def many(f):
        f.sfx = [SfxClip(id=f"fx{i}", scene="s2", preset="tick", at=i * 0.5, volume=0.3) for i in range(1, 5)]
    _edit(folder, many)
    assert _issues(folder) == ["scene 02 has 4 sounds; use at most 3 per scene"]


def test_sfx_issues_warn_only_when_a_clip_is_cut_by_more_than_30_percent(folder):
    def setup(f):
        f.sfx = [SfxClip(id="fx1", scene="s2", preset="ding", at=2.0, volume=0.3),        # 1.0 of 1.2 s: cut 17 %
                 SfxClip(id="fx2", scene="s2", preset="success", at=2.4, volume=0.3),    # 0.6 of 0.9 s: cut 33 %
                 SfxClip(id="fx3", scene="s2", preset="riser", at=0.0, stretch=4, volume=0.3)]  # 3 of 6 s
    _edit(folder, setup)
    msgs = [i.message for i in check.sfx_issues(folder, filmmod.load_film(folder)) if "runs past" in i.message]
    assert msgs == [
        "sound fx2 (success) at 2.4 s runs past the end of scene 02 and is cut to 0.6 s of 0.9 s; "
        "move it earlier or use a shorter sound",
        "sound fx3 (riser) at 0 s runs past the end of scene 02 and is cut to 3 s of 6 s; "
        "move it earlier or use a shorter sound"]


def test_sfx_issues_ignore_unknown_scene(folder):
    _edit(folder, lambda f: f.sfx.append(SfxClip(id="fx9", scene="gone", preset="pop")))
    assert check.sfx_issues(folder, filmmod.load_film(folder)) == []


def test_cli_sounds_lists_presets(capsys):
    assert main(["sounds"]) == 0
    out = capsys.readouterr().out
    assert "ding" in out and "1.2 s  bell, for a correct answer or a found item" in out
    assert "calm" in out and "80 bpm" in out and "typewriter" in out


def test_cli_check_prints_sound_warnings(folder, fake_tts, capsys):
    _edit(folder, lambda f: setattr(f.sfx[0], "at", 1.0))
    narrate.ensure_voice(folder, filmmod.load_film(folder))
    assert main(["check", str(folder)]) == 0
    out = capsys.readouterr().out
    assert "warning fx1: sound fx1 (ding) at 1 s plays over the narration of scene 01" in out
