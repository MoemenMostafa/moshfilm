import json
import shutil
from pathlib import Path
from typing import get_args

import pytest
from pydantic import ValidationError

from moshfilm import film as filmlib
from moshfilm.film import Film, Key, Mood, Music, MusicBed, Palette, SfxClip, SfxPreset, check_film
from moshfilm.sound import music, sfx
from moshfilm.timing import layout, sfx_audible, sfx_start

HERE = Path(__file__).parent
CASES = json.loads((HERE / "fixtures" / "sfx_cases.json").read_text())
BED = {"mood": "calm", "tempo": 80}


@pytest.mark.parametrize("case", CASES, ids=[c["name"] for c in CASES])
def test_sfx_start_matches_fixture(case):
    f = Film.model_validate(case["film"])
    slots = layout(f, case["voice"])
    for clip in f.sfx:
        assert sfx_start(clip, slots) == pytest.approx(case["starts"][clip.id], abs=1e-3)
        assert sfx_audible(clip, slots) == pytest.approx(case["audible"][clip.id], abs=1e-3)


def test_sfx_start_unknown_scene():
    f = Film.model_validate({"title": "t", "scenes": [{"id": "s1", "title": "a", "length": 2}]})
    with pytest.raises(ValueError):
        sfx_start(SfxClip(id="x", scene="nope", preset="pop"), layout(f, {}))


def test_music_needs_file_or_bed():
    with pytest.raises(ValidationError):
        Music(file="music/a.mp3", bed=MusicBed(**BED))
    with pytest.raises(ValidationError):
        Music()


def test_old_music_file_loads_pinned():
    base = {"title": "t"}
    assert Film.model_validate({**base, "music": {"file": "music/a.mp3", "volume": 0.6}}).music.pinned is True
    assert Film.model_validate({**base, "music": {"file": "music/a.mp3", "pinned": False}}).music.pinned is False
    assert Film.model_validate({**base, "music": {"bed": BED}}).music.pinned is False


@pytest.mark.parametrize("field,value", [("pitch", 13), ("stretch", 5), ("volume", 1.2), ("at", -1),
                                         ("preset", "boom")])
def test_sfx_ranges(field, value):
    with pytest.raises(ValidationError):
        SfxClip(**{"id": "a", "scene": "s", "preset": "pop", field: value})


def test_check_flags_sfx_refs(tmp_path):
    f = Film.model_validate({"title": "t", "scenes": [{"id": "s1", "title": "a", "length": 2}],
                             "sfx": [{"id": "fx1", "scene": "s1", "preset": "pop"},
                                     {"id": "fx1", "scene": "gone", "preset": "pop"}]})
    filmlib.save_film(tmp_path, f)
    messages = [i.message for i in check_film(tmp_path) if i.level == "error"]
    assert "duplicate sound id fx1" in messages
    assert "sound points to unknown scene gone" in messages


def test_film_literals_match_sound_engine():
    assert get_args(SfxPreset) == tuple(sfx.PRESETS)
    assert get_args(Mood) == tuple(music.MOODS)
    assert get_args(Palette) == music.PALETTES
    assert get_args(Key) == music.KEYS


def test_old_film_without_sfx_round_trips(tmp_path):
    folder = tmp_path / "colors"
    shutil.copytree(HERE / "fixtures" / "films" / "colors", folder)
    f = filmlib.load_film(folder)
    assert f.sfx == []
    filmlib.save_film(folder, f)
    saved = json.loads((folder / "film.json").read_text())
    old = json.loads((HERE / "fixtures" / "films" / "colors" / "film.json").read_text())
    assert saved["sfx"] == []
    assert saved["music"] is None and saved["scenes"][0]["id"] == "red"
    assert saved["texts"] == old["texts"] and saved["title"] == old["title"]


# ------------------------------------------------------------------ person edits (Task 4)

from moshfilm import edits, history  # noqa: E402
from moshfilm.edits import EditError  # noqa: E402
from moshfilm.film import Scene, VoiceLine  # noqa: E402


@pytest.fixture
def folder(tmp_path):
    filmlib.new_film(tmp_path, "t")
    f = filmlib.load_film(tmp_path)
    f.scenes = [Scene(id=f"s{i}", title=f"scene {i}", file=f"scenes/s{i}.js", length=4, pinned=True,
                      status="ready", voice=VoiceLine(text="")) for i in (1, 2, 3)]
    filmlib.save_film(tmp_path, f)
    for i in (1, 2, 3):
        (tmp_path / "scenes" / f"s{i}.js").write_text("export default {}\n")
    history.sync(tmp_path)
    return tmp_path


def _film(folder):
    return filmlib.load_film(folder)


def _add(folder, scene="s1", preset="ding", at=0.5):
    return history.apply_and_record(folder, [{"op": "add_sfx", "preset": preset, "scene": scene, "at": at}])


def test_add_sfx_assigns_free_id_and_pins(folder):
    _add(folder)
    f = _add(folder, "s2", "pop")
    assert [(c.id, c.pinned) for c in f.sfx] == [("fx1", True), ("fx2", True)]
    history.apply_and_record(folder, [{"op": "remove_sfx", "sfx": "fx1"}])
    assert _add(folder).sfx[-1].id == "fx3"  # a tombstoned id is not reused
    with pytest.raises(EditError, match="unknown scene nope"):
        _add(folder, "nope")


def test_set_sfx_time_reanchors(folder):
    _add(folder)
    f = history.apply_and_record(folder, [{"op": "set_sfx_time", "sfx": "fx1", "scene": "s2", "at": 0.7}])
    assert (f.sfx[0].scene, f.sfx[0].at, f.sfx[0].pinned) == ("s2", 0.7, True)
    f = history.apply_and_record(folder, [{"op": "unpin", "target": "sfx:fx1"}])
    assert f.sfx[0].pinned is False
    with pytest.raises(EditError, match="unknown sound nope"):
        history.apply_and_record(folder, [{"op": "unpin", "target": "sfx:nope"}])
    with pytest.raises(EditError):
        history.apply_and_record(folder, [{"op": "set_sfx_time", "sfx": "fx1", "scene": "s1", "at": -1}])


def test_set_sfx_changes_only_given_fields(folder):
    _add(folder)
    f = history.apply_and_record(folder, [{"op": "set_sfx", "sfx": "fx1", "volume": 0.3}])
    c = f.sfx[0]
    assert (c.volume, c.preset, c.at, c.pinned) == (0.3, "ding", 0.5, True)
    with pytest.raises(EditError):
        history.apply_and_record(folder, [{"op": "set_sfx", "sfx": "fx1", "pitch": 40}])


def test_remove_scene_takes_its_sfx(folder):
    _add(folder, "s1")
    _add(folder, "s1", "pop")
    _add(folder, "s2", "tick")
    f = history.apply_and_record(folder, [{"op": "remove_scene", "scene": "s1"}])
    assert [c.id for c in f.sfx] == ["fx3"]
    assert sorted(t.id for t in f.removed_by_person if t.kind == "sfx") == ["fx1", "fx2"]


def test_sfx_follow_moved_scene(folder):
    f = _add(folder, "s1", at=1.0)
    before = sfx_start(f.sfx[0], layout(f, {}))
    f = history.apply_and_record(folder, [{"op": "move_scene", "scene": "s1", "index": 2}])
    assert sfx_start(f.sfx[0], layout(f, {})) == pytest.approx(before + 8.0)


def test_undo_restores_sfx(folder):
    original = _film(folder).sfx
    _add(folder)
    history.apply_and_record(folder, [{"op": "set_sfx_time", "sfx": "fx1", "scene": "s2", "at": 1}])
    history.apply_and_record(folder, [{"op": "remove_sfx", "sfx": "fx1"}])
    labels = [s["label"] for s in history.info(folder)["steps"]][-3:]
    assert labels == ["Added sound ding", "Moved sound ding", "Removed sound ding"]
    for _ in range(3):
        history.undo(folder)
    assert _film(folder).sfx == original


def test_set_music_bed_replaces_file_and_pins(folder):
    history.apply_and_record(folder, [{"op": "set_music", "file": "music/a.mp3"}])
    f = _film(folder)
    assert f.music.file == "music/a.mp3" and f.music.pinned is True
    f = history.apply_and_record(folder, [{"op": "set_music_bed", "mood": "calm", "tempo": 80, "volume": 0.4}])
    assert f.music.file is None and f.music.bed.mood == "calm" and f.music.pinned is True
    assert f.music.volume == 0.4
    f = history.apply_and_record(folder, [{"op": "set_music", "file": None}])
    assert f.music is None
    assert [(t.kind, t.text) for t in f.removed_by_person if t.kind == "music"] == [("music", "calm bed")]
    f = history.apply_and_record(folder, [{"op": "set_music_bed", "mood": "tense", "tempo": 92}])
    assert not [t for t in f.removed_by_person if t.kind == "music"]
    with pytest.raises(EditError):
        history.apply_and_record(folder, [{"op": "set_music_bed", "mood": "calm", "tempo": 400}])


def test_diff_label_counts_sounds_and_music(folder):
    prev = history._capture(folder)
    f = _film(folder)
    f.sfx = [SfxClip(id="fx1", scene="s1", preset="pop")]
    f.music = Music(bed=MusicBed(**BED))
    filmlib.save_film(folder, f)
    label = history._diff_label(prev, history._capture(folder))
    assert "added 1 sound" in label and "changed music" in label and "film settings" not in label


def test_sfx_seconds_match_the_presets():
    assert filmlib.SFX_SECONDS == {n: p.base_seconds for n, p in sfx.PRESETS.items()}
    assert SfxClip(id="a", scene="s", preset="ding", stretch=2).seconds == pytest.approx(2.4)


@pytest.mark.parametrize("name", list(sfx.PRESETS))
def test_sfx_seconds_are_the_rendered_lengths(name):
    for stretch in (0.25, 1, 4):
        for pitch in (-12, 0, 12):
            clip = SfxClip(id="a", scene="s", preset=name, stretch=stretch, pitch=pitch)
            rendered = len(sfx.render_sfx(name, pitch, stretch)) / 48000
            assert rendered == pytest.approx(clip.seconds, abs=1 / 48000), (name, stretch, pitch)


def test_a_clip_starts_exactly_at_its_cue_even_near_the_scene_end():
    f = Film.model_validate({"title": "t", "scenes": [{"id": "s1", "title": "a", "length": 5, "pinned": True}],
                             "sfx": [{"id": "fx1", "scene": "s1", "preset": "success", "at": 4.8}]})
    slots = layout(f, {})
    assert sfx_start(f.sfx[0], slots) == 4.8  # not pulled back to 4.1
    assert sfx_audible(f.sfx[0], slots) == pytest.approx(0.2)
