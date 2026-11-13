import json
from pathlib import Path

import pytest

from moshfilm import film, store
from moshfilm.cli import build_parser, main


def test_new_film_creates_layout(tmp_path: Path):
    folder = tmp_path / "f"
    created = film.new_film(folder, "My film")
    assert (folder / "film.json").is_file()
    assert json.loads((folder / "proposals.json").read_text()) == {"proposals": []}
    assert json.loads((folder / "comments.json").read_text()) == {"items": [], "messages": []}
    assert (folder / "scenes").is_dir()
    assert (folder / ".moshfilm").is_dir()
    loaded = film.load_film(folder)
    assert loaded == created
    assert loaded.title == "My film"
    assert loaded.pace == 1.0
    assert loaded.fps == 30
    assert loaded.voice.name == "en-US-AndrewNeural"
    assert loaded.voice.rate == "+8%"


def test_new_film_refuses_existing(tmp_path: Path):
    film.new_film(tmp_path, "a")
    with pytest.raises(FileExistsError):
        film.new_film(tmp_path, "b")


def test_load_film_reports_schema_error(tmp_path: Path):
    film.new_film(tmp_path, "a")
    data = json.loads((tmp_path / "film.json").read_text())
    data["bogus"] = 1
    (tmp_path / "film.json").write_text(json.dumps(data))
    with pytest.raises(film.FilmError) as exc:
        film.load_film(tmp_path)
    assert "film.json" in str(exc.value)
    assert "bogus" in str(exc.value)


def test_load_film_reports_invalid_json(tmp_path: Path):
    film.new_film(tmp_path, "a")
    (tmp_path / "film.json").write_text("{nope")
    with pytest.raises(film.FilmError, match="film.json"):
        film.load_film(tmp_path)


def test_save_is_atomic(tmp_path: Path):
    f = film.new_film(tmp_path, "a")
    f.title = "changed"
    film.save_film(tmp_path, f)
    assert list(tmp_path.rglob("*.tmp")) == []
    assert film.load_film(tmp_path).title == "changed"
    raw = (tmp_path / "film.json").read_text()
    assert raw.endswith("\n") and '\n  "title"' in raw


def test_locked_is_reentrant_and_cached(tmp_path: Path):
    assert store.locked(tmp_path) is store.locked(tmp_path / ".")
    with store.locked(tmp_path):
        with store.locked(tmp_path):
            f = film.new_film(tmp_path, "a")
            film.save_film(tmp_path, f)  # takes the lock itself, must not deadlock


def test_read_json_default(tmp_path: Path):
    assert store.read_json(tmp_path / "missing.json", {"x": 1}) == {"x": 1}


def _two_scene_film(tmp_path: Path, **scene_kw):
    f = film.new_film(tmp_path, "a")
    f.scenes.append(film.Scene(id="s1", title="One", length=3, **scene_kw))
    film.save_film(tmp_path, f)
    return f


def test_check_flags_missing_scene_file_and_nondeterminism(tmp_path: Path):
    _two_scene_film(tmp_path, file="scenes/s1.js", status="ready")
    issues = film.check_film(tmp_path)
    assert [(i.level, i.where) for i in issues] == [("error", "s1")]

    (tmp_path / "scenes" / "s1.js").write_text("export function render(t){ return Math.random(); }")
    issues = film.check_film(tmp_path)
    assert [i.level for i in issues] == ["warning"]
    assert "Math.random" in issues[0].message


def test_check_flags_all_nondeterministic_calls(tmp_path: Path):
    _two_scene_film(tmp_path, file="scenes/s1.js", status="ready")
    body = "Date.now() new Date() performance.now() setTimeout() setInterval() requestAnimationFrame()"
    (tmp_path / "scenes" / "s1.js").write_text(body)
    messages = " ".join(i.message for i in film.check_film(tmp_path))
    for term in ("Date.now", "new Date", "performance.now", "setTimeout", "setInterval", "requestAnimationFrame"):
        assert term in messages


@pytest.mark.parametrize("snippet,term", [
    ("window.setTimeout(f, 1)", "setTimeout"),
    ("globalThis.setInterval(f, 1)", "setInterval"),
    ("window.requestAnimationFrame(f)", "requestAnimationFrame"),
    ("new  Date()", "new Date"),
    ("new\nDate()", "new Date"),
])
def test_check_flags_receiver_prefixed_and_spaced_calls(tmp_path: Path, snippet, term):
    _two_scene_film(tmp_path, file="scenes/s1.js", status="ready")
    (tmp_path / "scenes" / "s1.js").write_text(snippet)
    issues = film.check_film(tmp_path)
    assert [i.level for i in issues] == ["warning"] and term in issues[0].message


def test_check_flags_duplicates_and_unknown_scene(tmp_path: Path):
    f = _two_scene_film(tmp_path)
    f.scenes.append(film.Scene(id="s1", title="Dup", length=2))
    f.texts.append(film.TextClip(id="t1", scene="nope", text="hi"))
    f.texts.append(film.TextClip(id="t1", scene="s1", text="hi"))
    film.save_film(tmp_path, f)
    msgs = [i.message for i in film.check_film(tmp_path) if i.level == "error"]
    assert any("duplicate" in m and "s1" in m for m in msgs)
    assert any("duplicate" in m and "t1" in m for m in msgs)
    assert any("unknown scene" in m for m in msgs)


def test_check_reports_broken_film_json(tmp_path: Path):
    film.new_film(tmp_path, "a")
    (tmp_path / "film.json").write_text("[]")
    issues = film.check_film(tmp_path)
    assert len(issues) == 1 and issues[0].level == "error" and issues[0].where == "film.json"


def test_optional_fields_default_to_none():
    t = film.TextClip(id="t", scene="s", text="x")
    assert t.x is None and t.y is None and t.end is None
    s = film.Scene(id="s", title="S", length=1)
    assert s.file is None and s.status == "planned" and s.pinned is False


def test_cli_new_and_check(tmp_path: Path, capsys):
    d = str(tmp_path / "x")
    assert main(["new", d, "--title", "X"]) == 0
    assert film.load_film(Path(d)).title == "X"
    assert main(["check", d]) == 0
    assert main(["new", d]) == 1


def test_cli_check_exit_1_on_error(tmp_path: Path, capsys):
    _two_scene_film(tmp_path, file="scenes/s1.js", status="ready")
    assert main(["check", str(tmp_path)]) == 1
    assert capsys.readouterr().out.startswith("error s1:")


def test_cli_version(capsys):
    with pytest.raises(SystemExit) as exc:
        main(["--version"])
    assert exc.value.code == 0
    assert "1.0.0" in capsys.readouterr().out


def test_build_parser_exists():
    assert build_parser().parse_args(["check", "x"]).command == "check"
