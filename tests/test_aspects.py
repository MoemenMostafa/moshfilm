"""Shapes: canvas sizes, migration, the set_aspects edit."""
import json
import shutil
from pathlib import Path

import pytest
from pydantic import ValidationError

from moshfilm import aspects, film

FIXTURES = Path(__file__).parent / "fixtures"
CASES = json.loads((FIXTURES / "aspect_cases.json").read_text())


@pytest.mark.parametrize("case", CASES, ids=lambda c: f"{c['film']['width']}x{c['film']['height']}-{c['aspect']}")
def test_canvas_sizes_match_fixture(case):
    f = film.Film(title="t", **case["film"])
    assert aspects.canvas_size(f, case["aspect"]) == tuple(case["size"])


def test_default_sizes():
    f = film.Film(title="t")
    assert aspects.canvas_size(f, "16:9") == (1280, 720)
    assert aspects.canvas_size(f, "9:16") == (720, 1280)
    assert aspects.canvas_size(f, "1:1") == (720, 720)
    assert aspects.canvas_size(f, "4:5") == (720, 900)


def test_chosen_and_slug():
    assert aspects.chosen(film.Film(title="t")) == ["16:9"]
    assert aspects.chosen(film.Film(title="t", second_aspect="9:16")) == ["16:9", "9:16"]
    assert aspects.slug("4:5") == "4x5"
    assert aspects.from_slug("1x1") == "1:1"
    with pytest.raises(ValueError):
        aspects.from_slug("2x3")


def test_second_must_differ():
    with pytest.raises(ValidationError):
        film.Film(title="t", aspect="1:1", second_aspect="1:1")


def test_old_film_json_loads_as_16_9(tmp_path):
    folder = tmp_path / "colors"
    shutil.copytree(FIXTURES / "films" / "colors", folder)
    before = (folder / "film.json").read_text()
    f = film.load_film(folder)
    assert (f.aspect, f.second_aspect, f.version, f.width, f.height) == ("16:9", None, 2, 320, 180)
    assert (folder / "film.json").read_text() == before
    film.save_film(folder, f)
    assert json.loads((folder / "film.json").read_text())["aspect"] == "16:9"


def test_migrate_odd_sizes_keep_canvas():
    m = film.migrate({"version": 1, "title": "t", "width": 1000, "height": 1000})
    assert (m["aspect"], m["width"], m["height"]) == ("1:1", 1000, 1000)
    assert film.migrate({"version": 1, "title": "t", "width": 1080, "height": 1350})["aspect"] == "4:5"
    assert film.migrate({"version": 1, "title": "t", "width": 720, "height": 1280})["aspect"] == "9:16"
    v2 = {"version": 2, "title": "t", "aspect": "4:5", "second_aspect": None}
    assert film.migrate(v2) == v2


def test_new_film_has_default_shape(tmp_path):
    film.new_film(tmp_path / "f", "F")
    data = json.loads((tmp_path / "f" / "film.json").read_text())
    assert (data["aspect"], data["second_aspect"], data["version"]) == ("16:9", None, 2)


# ---- the set_aspects edit

from moshfilm import edits, history  # noqa: E402


def test_set_aspects_changes_main_and_keeps_short_side():
    f = film.Film(title="t")
    out = edits.apply_edits(f, [{"op": "set_aspects", "aspect": "9:16", "second_aspect": "16:9"}])
    assert (out.aspect, out.second_aspect, out.width, out.height) == ("9:16", "16:9", 720, 1280)
    back = edits.apply_edits(out, [{"op": "set_aspects", "aspect": "16:9", "second_aspect": None}])
    assert (back.width, back.height, back.second_aspect) == (1280, 720, None)


def test_set_aspects_rejects_same_twice():
    with pytest.raises(edits.EditError, match="the second shape must differ from the main one"):
        edits.apply_edits(film.Film(title="t"), [{"op": "set_aspects", "aspect": "1:1", "second_aspect": "1:1"}])


def test_set_aspects_is_one_undo_step(tmp_path):
    film.new_film(tmp_path, "t")
    history.apply_and_record(tmp_path, [{"op": "set_aspects", "aspect": "9:16", "second_aspect": "1:1"}])
    assert film.load_film(tmp_path).aspect == "9:16"
    history.undo(tmp_path)
    f = film.load_film(tmp_path)
    assert (f.aspect, f.width, f.height) == ("16:9", 1280, 720)


def test_set_aspects_note_copy():
    f = film.Film(title="t")
    note = history.notes_for_ops(f, [{"op": "set_aspects", "aspect": "9:16", "second_aspect": "1:1"}])
    assert note == ["The person changed the film's shape to 9:16 (second shape: 1:1). "
                    "Check every scene in each shape with `moshfilm check <folder> --layout` and fix what does not fit."]
    none = history.notes_for_ops(f, [{"op": "set_aspects", "aspect": "4:5", "second_aspect": None}])
    assert "(no second shape)" in none[0]
    assert history.notes_for_ops(f, [{"op": "set_aspects", "aspect": "16:9", "second_aspect": None}]) == []


@pytest.mark.parametrize("bad", ['"1"', "null", "1.5", "true"])
def test_bad_version_is_a_film_error(tmp_path, bad):
    (tmp_path / "film.json").write_text('{"version": %s, "title": "t"}' % bad)
    with pytest.raises(film.FilmError, match="version"):
        film.load_film(tmp_path)
    assert film.check_film(tmp_path)[0].level == "error"
