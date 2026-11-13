"""The bundled sample film "Binary search": copied by `moshfilm sample`, clean under check, renders."""
import shutil
from pathlib import Path

import pytest

from moshfilm import cli, film

SCENES = [
    ("s1", "The sorted row", 7,
     "Sixteen lockers stand in a row, and the numbers inside rise from left to right. Somewhere in here is 37."),
    ("s2", "One by one", 7,
     "We could open them one by one from the left. It works, but in the worst case we open all sixteen."),
    ("s3", "Open the middle", 8,
     "Instead, open the locker in the middle. It holds 52, which is too big, so every locker to its right is out."),
    ("s4", "Halve what is left", 8,
     "Each look throws away about half of what remains: sixteen lockers, then seven, then three, then one."),
    ("s5", "Found it", 7,
     "Four looks, and 37 is ours. Checking one by one would have taken five here, and up to sixteen."),
    ("s6", "Why it scales", 8,
     "Double the lockers and you need only one more look. A million sorted items take about twenty."),
]
TEXTS = {
    "s1": ("Sorted: smallest → largest", "caption"),
    "s3": ("52 > 37 → drop the right half", "caption"),
    "s4": ("16 → 7 → 3 → 1", "caption"),
    "s6": ("1,000,000 items ≈ 20 looks", "title"),
}


@pytest.fixture
def sample(tmp_path) -> Path:
    folder = tmp_path / "bs"
    assert cli.main(["sample", str(folder)]) == 0
    return folder


def test_sample_checks_clean(sample):
    assert film.check_film(sample) == []
    f = film.load_film(sample)
    assert [s.id for s in f.scenes] == ["s1", "s2", "s3", "s4", "s5", "s6"]
    assert all(s.status == "ready" and (sample / s.file).is_file() for s in f.scenes)


def test_sample_matches_brief(sample):
    f = film.load_film(sample)
    assert (f.title, f.width, f.height, f.fps, f.pace) == ("Binary search", 1280, 720, 30, 1.0)
    assert f.music.bed.mood == "calm" and f.music.file is None
    assert (f.voice.name, f.voice.rate) == ("en-US-AndrewNeural", "+8%")
    assert [(s.id, s.title, s.length, s.voice.text) for s in f.scenes] == SCENES
    assert not any(s.pinned or s.voice.pinned for s in f.scenes)
    assert {t.scene: (t.text, t.style) for t in f.texts} == TEXTS
    assert not list(sample.glob("**/*.mp3")) and not (sample / ".moshfilm").exists()


def test_sample_has_sound_without_warnings(sample, fake_tts):
    from moshfilm import narrate
    from moshfilm.sound import check

    f = film.load_film(sample)
    assert f.music.bed.mood == "calm" and f.music.volume == 0.45 and f.music.pinned is False
    assert len(f.sfx) == 5 and not any(c.pinned for c in f.sfx)
    narrate.ensure_voice(sample, f)  # the fake voice gives every scene a narration window
    assert check.sfx_issues(sample, film.load_film(sample)) == []


def test_sample_voice_lines_short(sample):
    for s in film.load_film(sample).scenes:
        assert len(s.voice.text.split()) <= 22, s.id


def test_sample_refuses_existing_file(tmp_path, capsys):
    target = tmp_path / "taken.txt"
    target.write_text("x", encoding="utf-8")
    assert cli.main(["sample", str(target)]) == 1
    err = capsys.readouterr().err
    assert err.startswith("error: ") and str(target) in err and "Traceback" not in err
    assert target.read_text(encoding="utf-8") == "x"


def _have_chromium() -> bool:
    try:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            return Path(p.chromium.executable_path).exists()
    except Exception:
        return False


@pytest.mark.slow
def test_sample_renders_without_errors(sample):
    if not _have_chromium():
        pytest.skip("Playwright Chromium not installed (run scripts/setup.sh)")
    from playwright.sync_api import sync_playwright

    from moshfilm import server

    f = film.load_film(sample)
    base, stop = server.serve_in_thread(sample)
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch()
            try:
                page = browser.new_page(viewport={"width": f.width, "height": f.height})
                page.goto(f"{base}/render.html")
                page.evaluate("window.moshfilm.ready")
                assert page.evaluate("window.moshfilm.errors") == []
                start = 0.0
                for s in f.scenes:  # no cached voice: every scene runs its base length
                    for t in (start, start + s.length / 2, start + s.length - 0.05):
                        page.evaluate("t => window.moshfilm.seek(t)", t)
                        assert page.evaluate("window.moshfilm.errors") == [], (s.id, t)
                        shown = page.evaluate(
                            "() => [...document.querySelectorAll('[data-scene]')]"
                            ".filter(e => e.style.display === 'block').map(e => e.dataset.scene)")
                        assert shown == [s.id]
                        assert page.evaluate(f"document.querySelector('[data-scene={s.id}] svg') !== null")
                    start += s.length
                # every text clip fits on one line (a centred title must not wrap at half the stage width)
                page.evaluate("t => window.moshfilm.seek(t)", start - 0.05)
                height = page.evaluate("document.querySelector('[data-text=t6]').getBoundingClientRect().height")
                assert 0 < height < 100
            finally:
                browser.close()
    finally:
        stop()


@pytest.mark.slow
def test_sample_exports_through_real_path(sample, tmp_path):
    if not (shutil.which("ffmpeg") and shutil.which("ffprobe")):
        pytest.skip("ffmpeg/ffprobe not installed")
    if not _have_chromium():
        pytest.skip("Playwright Chromium not installed (run scripts/setup.sh)")
    from moshfilm import export

    out = export.export_film(sample, "gif", out=tmp_path / "bs.gif", fps=1, width=320, voice=False)
    assert out.is_file() and out.stat().st_size > 0


@pytest.mark.slow
def test_sample_fits_every_shape(sample):
    if not _have_chromium():
        pytest.skip("Playwright Chromium not installed (run scripts/setup.sh)")
    from moshfilm import aspects, layout_check

    issues = layout_check.check_layout(sample, list(aspects.ALL))
    assert issues == [], "\n".join(f"{i.where}: {i.message}" for i in issues)
