"""Layout check: every ready scene is drawn in each chosen shape and overflow becomes a warning."""
import shutil
from pathlib import Path

import pytest

from moshfilm import film, layout_check
from moshfilm.cli import main

SHAPES = Path(__file__).parent / "fixtures" / "films" / "shapes"


def _have_chromium() -> bool:
    try:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            return Path(p.chromium.executable_path).exists()
    except Exception:
        return False


slow = pytest.mark.slow
needs_chromium = pytest.mark.skipif(not _have_chromium(), reason="Playwright Chromium not installed (run scripts/setup.sh)")


@pytest.fixture
def shapes(tmp_path):
    folder = tmp_path / "shapes"
    shutil.copytree(SHAPES, folder)
    return folder


def _edit(folder: Path, fn) -> None:
    f = film.load_film(folder)
    fn(f)
    film.save_film(folder, f)


def _ready(folder: Path, scene_id: str) -> None:
    _edit(folder, lambda f: setattr(next(s for s in f.scenes if s.id == scene_id), "status", "ready"))


def test_check_layout_without_ready_scenes_skips_browser(tmp_path, monkeypatch):
    film.new_film(tmp_path, "t")
    f = film.load_film(tmp_path)
    f.scenes = [film.Scene(id="a", title="A", file="scenes/a.js", length=2)]  # planned
    film.save_film(tmp_path, f)

    def boom(*a, **k):
        raise AssertionError("the browser must not start")

    import playwright.sync_api as pw
    monkeypatch.setattr(pw, "sync_playwright", boom)
    assert layout_check.check_layout(tmp_path) == []


@slow
@needs_chromium
def test_layout_check_flags_only_the_shape_that_overflows(shapes):
    issues = layout_check.check_layout(shapes)
    assert not [i for i in issues if i.where == "fits"]
    wide = [i for i in issues if i.where == "wide"]
    assert wide and all(i.level == "warning" for i in wide)
    assert all(i.message.startswith("[9:16]") for i in wide)
    assert any("sticks out of the frame (right" in i.message for i in wide)
    assert not [i for i in issues if i.message.startswith("[16:9]")]


@slow
@needs_chromium
def test_layout_check_extra_aspects(shapes):
    issues = layout_check.check_layout(shapes, ["1:1"])
    wide = [i for i in issues if i.where == "wide"]
    assert wide and all(i.message.startswith("[1:1]") for i in wide)


@slow
@needs_chromium
def test_layout_check_reports_broken_scene_and_continues(shapes):
    _ready(shapes, "throws")
    issues = layout_check.check_layout(shapes)
    errors = [i for i in issues if i.where == "throws"]
    assert [i.level for i in errors] == ["error", "error"]
    assert sorted(i.message.split(" scene failed")[0] for i in errors) == ["[16:9]", "[9:16]"]
    assert all("boom in render" in i.message for i in errors)
    assert any(i.where == "wide" for i in issues)


@slow
@needs_chromium
def test_layout_check_flags_caption_that_cannot_fit(shapes):
    words = " ".join(["unbreakable"] * 60)

    def long_caption(f):
        clip = f.texts[0]
        clip.text, clip.y = words, 0.98
    _edit(shapes, long_caption)
    issues = layout_check.check_layout(shapes)
    hits = [i for i in issues if i.where == "t1"]
    assert hits and any(i.message.startswith("[9:16]") for i in hits)


@slow
@needs_chromium
def test_cli_check_layout(shapes, capsys):
    assert main(["check", str(shapes), "--layout"]) == 0
    out = capsys.readouterr().out
    assert any(line.startswith("warning wide: [9:16]") for line in out.splitlines())
    _ready(shapes, "throws")
    assert main(["check", str(shapes), "--layout"]) == 1


def test_cli_check_layout_unavailable(shapes, monkeypatch, capsys):
    def nope(*a, **k):
        raise layout_check.LayoutCheckUnavailable("Chromium is not available; run scripts/setup.sh")

    monkeypatch.setattr(layout_check, "check_layout", nope)
    assert main(["check", str(shapes), "--layout"]) == 2
    assert "error: Chromium is not available" in capsys.readouterr().err


def test_export_precheck_failure_never_stops_the_export(shapes, monkeypatch, capsys):
    from moshfilm import export

    def boom(*a, **k):
        raise RuntimeError("render page missing")

    monkeypatch.setattr(layout_check, "check_layout", boom)
    monkeypatch.setattr(export, "export_aspects", lambda *a, **k: {"16:9": Path("/x/out.mp4")})
    assert main(["export", str(shapes)]) == 0
    cap = capsys.readouterr()
    assert "layout check skipped: render page missing" in cap.err
    assert "/x/out.mp4" in cap.out
