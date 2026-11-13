import pytest

from moshfilm.edits import EditError, apply_edits
from moshfilm.film import Film, Scene, TextClip


def make() -> Film:
    return Film(
        title="t",
        scenes=[Scene(id="s1", title="a", length=5), Scene(id="s2", title="b", length=5)],
        texts=[TextClip(id="t1", scene="s1", text="hi")],
    )


def test_set_length_pins_scene():
    film = make()
    out = apply_edits(film, [{"op": "set_length", "scene": "s1", "length": 9}])
    assert out.scenes[0].length == 9 and out.scenes[0].pinned
    assert film.scenes[0].length == 5 and not film.scenes[0].pinned  # input untouched


def test_move_scene_pins_order():
    out = apply_edits(make(), [{"op": "move_scene", "scene": "s1", "index": 1}])
    assert [s.id for s in out.scenes] == ["s2", "s1"]
    assert out.order_pinned


def test_unpin_clears_flag():
    film = apply_edits(make(), [
        {"op": "set_length", "scene": "s1", "length": 9},
        {"op": "set_voice_offset", "scene": "s1", "offset": 1},
        {"op": "set_text_time", "text": "t1", "start": 1, "end": 2},
        {"op": "move_scene", "scene": "s1", "index": 1},
    ])
    assert film.scenes[1].pinned and film.scenes[1].voice.pinned and film.texts[0].pinned
    out = apply_edits(film, [{"op": "unpin", "target": t}
                             for t in ("scene:s1", "voice:s1", "text:t1", "order")])
    assert not (out.scenes[1].pinned or out.scenes[1].voice.pinned or out.texts[0].pinned
                or out.order_pinned)


def test_pace_bounds():
    for bad in (0.7, 2.1):
        with pytest.raises(EditError):
            apply_edits(make(), [{"op": "set_pace", "pace": bad}])
    assert apply_edits(make(), [{"op": "set_pace", "pace": 1.5}]).pace == 1.5


def test_length_minimum():
    for bad in (0.4, 601):
        with pytest.raises(EditError):
            apply_edits(make(), [{"op": "set_length", "scene": "s1", "length": bad}])


def test_unknown_ids_and_negative_offset():
    for op in ({"op": "set_length", "scene": "nope", "length": 3},
               {"op": "set_text_time", "text": "nope", "start": 0},
               {"op": "unpin", "target": "scene:nope"},
               {"op": "set_voice_offset", "scene": "s1", "offset": -1}):
        with pytest.raises(EditError):
            apply_edits(make(), [op])


def test_voice_settings_and_music():
    out = apply_edits(make(), [{"op": "set_voice_settings", "name": "en-GB-RyanNeural", "rate": "-5%"},
                               {"op": "set_music", "file": "music/bed.mp3", "volume": 0.4}])
    assert out.voice.name == "en-GB-RyanNeural" and out.voice.rate == "-5%"
    assert out.music.file == "music/bed.mp3" and out.music.volume == 0.4
    assert apply_edits(out, [{"op": "set_music", "file": None}]).music is None
