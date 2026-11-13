import json
from pathlib import Path

import pytest

from moshfilm.film import Film
from moshfilm.timing import layout, locate, text_window, total_length

CASES = json.loads((Path(__file__).parent / "fixtures" / "timing_cases.json").read_text())


@pytest.mark.parametrize("case", CASES, ids=[c["name"] for c in CASES])
def test_fixture_cases(case):
    film = Film.model_validate(case["film"])
    slots = layout(film, case["voice"])
    assert [s.id for s in slots] == [e["id"] for e in case["slots"]]
    for slot, want in zip(slots, case["slots"]):
        assert slot.start == pytest.approx(want["start"], abs=1e-3)
        assert slot.length == pytest.approx(want["length"], abs=1e-3)
        assert slot.voice_start == pytest.approx(want["voice_start"], abs=1e-3)
        assert slot.voice_speed == pytest.approx(want["voice_speed"], abs=1e-3)
        assert slot.overflow is want["overflow"]
    assert total_length(slots) == case["expected_total"]
    for clip, want in zip(film.texts, case["texts"]):
        start, end = text_window(clip, slots)
        assert clip.id == want["id"]
        assert start == pytest.approx(want["start"], abs=1e-3)
        assert end == pytest.approx(want["end"], abs=1e-3)


def _two_scene_slots():
    film = Film.model_validate({"title": "t", "scenes": [
        {"id": "s1", "title": "a", "length": 5.0},
        {"id": "s2", "title": "b", "length": 3.0},
    ]})
    return layout(film, {})


def test_locate_boundaries():
    slots = _two_scene_slots()
    assert locate(slots, 0.0) == ("s1", 0.0)
    assert locate(slots, 4.999) == ("s1", pytest.approx(4.999))
    assert locate(slots, 5.0) == ("s2", 0.0)
    assert locate(slots, 8.0) == ("s2", 3.0)
    assert locate(slots, 99) == ("s2", 3.0)
    assert locate(slots, -1) == ("s1", 0.0)
    assert locate([], 1.0) is None
    assert locate(layout(Film(title="empty"), {}), 0.0) is None


def test_empty_film_total_is_zero():
    assert total_length(layout(Film(title="empty"), {})) == 0.0
