"""Export tests: real Chromium + real ffmpeg, so all are slow."""
import json
import shutil
import subprocess
from pathlib import Path

import pytest

from moshfilm import export, film, narrate, timing

pytestmark = pytest.mark.slow

COLORS = Path(__file__).parent / "fixtures" / "films" / "colors"


def _have_chromium() -> bool:
    try:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            return Path(p.chromium.executable_path).exists()
    except Exception:
        return False


if not (shutil.which("ffmpeg") and shutil.which("ffprobe")):
    pytest.skip("ffmpeg/ffprobe not installed", allow_module_level=True)
if not _have_chromium():
    pytest.skip("Playwright Chromium not installed (run scripts/setup.sh)", allow_module_level=True)


@pytest.fixture
def colors(tmp_path):
    folder = tmp_path / "colors"
    shutil.copytree(COLORS, folder)
    return folder


def _edit(folder: Path, fn) -> None:
    f = film.load_film(folder)
    fn(f)
    film.save_film(folder, f)


def _probe(path: Path, *args: str) -> str:
    return subprocess.run(["ffprobe", "-v", "error", *args, str(path)],
                          capture_output=True, text=True, check=True).stdout.strip()


def _duration(path: Path, stream: str | None = None) -> float:
    sel = ["-select_streams", stream] if stream else []
    return float(_probe(path, *sel, "-show_entries",
                        "stream=duration" if stream else "format=duration",
                        "-of", "default=nw=1:nk=1"))


def _mean_rgb(video: Path, at: float, tmp: Path) -> tuple[float, float, float]:
    png = tmp / f"frame-{at}.png"
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-ss", str(at), "-i", str(video),
                    "-frames:v", "1", "-vf", "scale=1:1:flags=area", "-pix_fmt", "rgb24",
                    "-f", "rawvideo", str(png)], check=True)
    r, g, b = png.read_bytes()[:3]
    return r, g, b


def test_mp4_timing_matches_layout(colors, tmp_path):
    out = export.export_film(colors, "mp4", out=tmp_path / "o.mp4", voice=False)
    assert _duration(out) == pytest.approx(2.0, abs=0.1)
    r, g, b = _mean_rgb(out, 0.5, tmp_path)
    assert r > 200 and b < 60
    r, g, b = _mean_rgb(out, 1.5, tmp_path)
    assert b > 200 and r < 60
    assert "audio" in _probe(out, "-show_entries", "stream=codec_type", "-of", "csv=p=0")  # silent track


def test_mp4_has_voice_audio(colors, tmp_path, fake_tts_audio):
    _edit(colors, lambda f: setattr(f.scenes[0].voice, "text",
                                    "This is a short line of real narration for the red scene"))
    out = export.export_film(colors, "mp4", out=tmp_path / "o.mp4")
    audio, video = _duration(out, "a:0"), _duration(out, "v:0")
    assert audio == pytest.approx(video, abs=0.15)
    # voice sits in the red scene (0.3 s .. 1.4 s); the blue scene stays silent
    def max_db(start: float, dur: float) -> float:
        res = subprocess.run(["ffmpeg", "-v", "info", "-ss", str(start), "-t", str(dur), "-i", str(out),
                              "-vn", "-af", "volumedetect", "-f", "null", "-"],
                             capture_output=True, text=True)
        line = next(x for x in res.stderr.splitlines() if "max_volume" in x)
        return float(line.split("max_volume:")[1].split("dB")[0])
    f = film.load_film(colors)
    slots = timing.layout(f, narrate.voice_durations(colors, f))
    assert max_db(slots[0].voice_start + 0.1, 0.4) > -30
    assert max_db(slots[1].start + 0.1, 0.5) < -50


def test_gif_defaults(colors, tmp_path):
    out = export.export_film(colors, "gif", out=tmp_path / "o.gif", voice=False)
    assert _probe(out, "-select_streams", "v:0", "-show_entries", "stream=width",
                  "-of", "csv=p=0") == "640"
    frames = int(_probe(out, "-select_streams", "v:0", "-count_frames", "-show_entries",
                        "stream=nb_read_frames", "-of", "csv=p=0"))
    assert 22 <= frames <= 26
    assert _probe(out, "-select_streams", "a", "-show_entries", "stream=codec_type",
                  "-of", "csv=p=0") == ""


def test_default_output_path(colors):
    out = export.export_film(colors, "gif", voice=False, fps=5, width=160)
    assert out == colors / "exports" / "colors.gif" and out.exists()


def test_export_refuses_overflow(colors, fake_tts_audio):
    long_line = " ".join(["word"] * 20)  # 2.0 s of fake speech

    def pin(f):
        f.scenes[0].pinned = True
        f.scenes[0].length = 1.0
        f.scenes[0].voice.text = long_line
    _edit(colors, pin)
    with pytest.raises(export.ExportError) as err:
        export.export_film(colors, "mp4")
    assert timing.OVERFLOW_COPY in str(err.value)
    assert "Red" in str(err.value)


def test_export_has_no_force_option():
    import inspect
    assert "force" not in inspect.signature(export.export_film).parameters


def test_export_refuses_scene_not_ready(colors):
    _edit(colors, lambda f: setattr(f.scenes[1], "status", "building"))
    with pytest.raises(export.ExportError, match="Blue"):
        export.export_film(colors, "mp4", voice=False)


def test_export_refuses_broken_scene(colors):
    def add(f):
        f.scenes.append(film.Scene(id="broken", title="Broken one", file="scenes/broken.js",
                                   length=1.0, status="ready"))
    _edit(colors, add)
    with pytest.raises(export.ExportError) as err:
        export.export_film(colors, "mp4", voice=False)
    assert "Broken one" in str(err.value) and "boom in render" in str(err.value)
    assert not (colors / "exports").exists() or not list((colors / "exports").glob("*.mp4"))


def test_cli_export_reports_error(colors, capsys):
    from moshfilm import cli
    _edit(colors, lambda f: setattr(f.scenes[1], "status", "building"))
    assert cli.main(["export", str(colors), "--no-voice"]) == 1
    assert "Blue" in capsys.readouterr().err


def test_no_voice_keeps_the_voice_aware_layout(colors, tmp_path, fake_tts_audio):
    _edit(colors, lambda f: setattr(f.scenes[0].voice, "text",
                                    "This is a short line of real narration for the red scene"))
    f = film.load_film(colors)
    durations = narrate.ensure_voice(colors, f)  # cache the line, as the preview would have
    slots = timing.layout(f, durations)
    total = timing.total_length(slots)
    assert total > 2.5  # the voice line stretched the red scene past its 1.0 s
    out = export.export_film(colors, "mp4", out=tmp_path / "o.mp4", voice=False)
    assert _duration(out, "v:0") == pytest.approx(total, abs=0.15)
    boundary = slots[1].start
    r, _, b = _mean_rgb(out, boundary - 0.2, tmp_path)
    assert r > 200 and b < 60
    r, _, b = _mean_rgb(out, boundary + 0.2, tmp_path)
    assert b > 200 and r < 60
    res = subprocess.run(["ffmpeg", "-v", "info", "-i", str(out), "-vn", "-af", "volumedetect",
                          "-f", "null", "-"], capture_output=True, text=True)
    line = next(x for x in res.stderr.splitlines() if "max_volume" in x)
    assert float(line.split("max_volume:")[1].split("dB")[0]) < -50  # muted


def test_no_voice_still_refuses_overflow(colors, fake_tts_audio):
    def pin(f):
        f.scenes[0].pinned = True
        f.scenes[0].voice.text = " ".join(["word"] * 20)
    _edit(colors, pin)
    narrate.ensure_voice(colors, film.load_film(colors))
    with pytest.raises(export.ExportError, match="Red"):
        export.export_film(colors, "mp4", voice=False)


# ---- one file per chosen shape

def _two_shapes(f):
    f.second_aspect = "9:16"


def _size(path: Path) -> str:
    return _probe(path, "-select_streams", "v:0", "-show_entries", "stream=width,height", "-of", "csv=p=0:s=x")


def test_output_paths_naming(colors, tmp_path):
    f = film.load_film(colors)
    assert export.output_paths(f, "mp4", None, colors) == {"16:9": colors / "exports" / "colors.mp4"}
    f.second_aspect = "9:16"
    assert export.output_paths(f, "mp4", None, colors) == {
        "16:9": colors / "exports" / "colors-16x9.mp4", "9:16": colors / "exports" / "colors-9x16.mp4"}
    assert export.output_paths(f, "gif", tmp_path / "o.gif", colors) == {
        "16:9": tmp_path / "o-16x9.gif", "9:16": tmp_path / "o-9x16.gif"}


def test_export_writes_one_file_per_shape(colors, tmp_path):
    _edit(colors, _two_shapes)
    mapping = export.export_aspects(colors, "mp4", out=tmp_path / "o.mp4", voice=False)
    assert list(mapping) == ["16:9", "9:16"]  # shape -> path
    outs = list(mapping.values())
    assert [p.name for p in outs] == ["o-16x9.mp4", "o-9x16.mp4"]
    assert [_size(p) for p in outs] == ["320x180", "180x320"]
    f = film.load_film(colors)
    total = timing.total_length(timing.layout(f, {}))
    for p in outs:
        assert _duration(p, "v:0") == pytest.approx(total, abs=0.15)
    assert export.export_film(colors, "mp4", out=tmp_path / "m.mp4", voice=False).name == "m-16x9.mp4"


def test_gif_per_shape_default_size(colors, tmp_path):
    _edit(colors, _two_shapes)
    outs = list(export.export_aspects(colors, "gif", out=tmp_path / "o.gif", voice=False, fps=5).values())
    assert [_size(p) for p in outs] == ["640x360", "360x640"]


def test_width_scales_every_shape_alike(colors, tmp_path):
    _edit(colors, _two_shapes)
    outs = list(export.export_aspects(colors, "mp4", out=tmp_path / "o.mp4", voice=False, width=160).values())
    assert [_size(p) for p in outs] == ["160x90", "90x160"]


def test_cli_export_prints_every_file(colors, capsys):
    from moshfilm import cli
    _edit(colors, _two_shapes)
    assert cli.main(["export", str(colors), "--format", "gif", "--fps", "5", "--no-voice"]) == 0
    lines = capsys.readouterr().out.split()
    assert [Path(x).name for x in lines] == ["colors-16x9.gif", "colors-9x16.gif"]
    assert all(Path(x).exists() for x in lines)


def test_slug_is_capped_so_download_names_stay_valid():
    from moshfilm import server
    title = "A very long film title " * 20
    slug = export._slug(title)
    assert len(slug) <= 80 and not slug.endswith("-")
    assert server.EXPORT_NAME.fullmatch(f"{slug}-16x9.mp4")
    assert export._slug("!!!") == "film"
