"""Export a film to MP4 or GIF: Chromium renders each frame, ffmpeg encodes.

The frames come from the same render page and scene code as the browser preview
(`/render.html`, `window.moshfilm.seek(t)`), at the same layout times, so what you
see in the editor is what you get. The voice track is built from the same layout.
"""
from __future__ import annotations

import contextlib
import math
import re
import shutil
import subprocess
import tempfile
import threading
import time
from pathlib import Path
from typing import Callable, Literal

from . import aspects as aspectlib
from . import film as filmlib
from . import narrate, server, timing
from .sound import cache as soundcache, mix as soundmix

SETUP_HINT = "run scripts/setup.sh"
GIF_FPS = 12
GIF_SHORT_SIDE = 360  # a 16:9 GIF is 640 wide, a 9:16 one 360 wide


class ExportError(Exception):
    """The film cannot be exported; the message says why and what to fix."""


def _slug(title: str) -> str:
    # capped so a long title still gives a file name the editor's download link accepts
    return re.sub(r"[^a-z0-9]+", "-", title.lower())[:80].strip("-") or "film"


def _check_scenes(the_film: filmlib.Film, slots: list[timing.SceneSlot]) -> None:
    not_ready = [s for s in the_film.scenes if s.status != "ready" or not s.file]
    if not_ready:
        names = ", ".join(f'"{s.title}" ({s.status})' for s in not_ready)
        raise ExportError(f"scenes not ready: {names}")
    titles = {s.id: s.title for s in the_film.scenes}
    over = [titles[s.id] for s in slots if s.overflow]
    if over:
        names = ", ".join(f'"{t}"' for t in over)
        raise ExportError(f"{timing.OVERFLOW_COPY}: {names}")


def _page_errors(page, the_film: filmlib.Film) -> None:
    errors = page.evaluate("window.moshfilm.errors")
    if not errors:
        return
    titles = {s.id: s.title for s in the_film.scenes}
    shown = []
    for e in errors:
        m = re.match(r"Scene (\S+) failed: (.*)", e, re.S)
        shown.append(f'scene "{titles.get(m.group(1), m.group(1))}" ({m.group(1)}) failed: {m.group(2)}'
                     if m else e)
    raise ExportError("; ".join(shown))


def _even(x: float) -> int:
    return max(2, 2 * round(x / 2))


def _target_size(canvas: tuple[int, int], main: tuple[int, int], fmt: str, width: int | None) -> tuple[int, int]:
    """Pixel size of one shape's file. `width` scales every shape by width / main width; a GIF without it
    gets a short side of GIF_SHORT_SIDE; an MP4 keeps the canvas. Always even (H.264 needs it)."""
    if width:
        k = width / main[0]
    elif fmt == "gif":
        k = GIF_SHORT_SIDE / min(canvas)
    else:
        k = 1.0
    return _even(canvas[0] * k), _even(canvas[1] * k)


def _video_filter(fmt: str, canvas: tuple[int, int], size: tuple[int, int]) -> list[str]:
    scale = f"scale={size[0]}:{size[1]}" + (":flags=lanczos" if fmt == "gif" else "")
    if fmt == "gif":
        return ["-vf", f"{scale},split[a][b];[a]palettegen=stats_mode=diff[p];"
                       f"[b][p]paletteuse=dither=bayer:bayer_scale=5"]
    return ["-vf", scale] if size != canvas else []


PROGRESS_INTERVAL = 0.25  # seconds between frame updates: about 4 a second


class _Reporter:
    """Sends `{stage, aspect, aspect_index, aspect_count, done, total}` events to the caller's callback.
    Calls are serialised, because ffmpeg's output is read on its own thread."""

    def __init__(self, callback: Callable[[dict], None] | None, count: int) -> None:
        self.callback, self.count, self._lock = callback, count, threading.Lock()

    def __call__(self, stage: str, aspect: str | None, index: int, done: float, total: float) -> None:
        if self.callback is None:
            return
        with self._lock:
            self.callback({"stage": stage, "aspect": aspect, "aspect_index": index,
                           "aspect_count": self.count, "done": done, "total": total})


def _run_frames(n: int, fps: int, render_frame: Callable[[int], bytes], stdin, report: Callable[[int], None],
                clock: Callable[[], float] = time.monotonic) -> None:
    """Render frames 0..n-1 into `stdin`; `report(done)` runs at the start and at most every
    PROGRESS_INTERVAL seconds after, and always after the last frame."""
    report(0)
    last = clock()
    for i in range(n):
        stdin.write(render_frame(i))
        now = clock()
        if i + 1 == n or now - last >= PROGRESS_INTERVAL:
            report(i + 1)
            last = now


def _encode_cmd(fmt: str, fps: int, canvas: tuple[int, int], size: tuple[int, int],
                audio: Path | None, out: Path) -> list:
    cmd = ["ffmpeg", "-y", "-v", "error", "-f", "image2pipe", "-framerate", str(fps), "-i", "-"]
    if fmt == "gif":
        return [*cmd, *_video_filter(fmt, canvas, size), "-loop", "0", out]
    return [*cmd, "-i", audio, *_video_filter(fmt, canvas, size), "-map", "0:v", "-map", "1:a",
            "-c:v", "libx264", "-pix_fmt", "yuv420p", "-crf", "18", "-preset", "medium",
            "-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart", out]


def _build_audio(folder: Path, the_film: filmlib.Film, slots, total: float, voice: bool,
                 tmp: Path) -> Path:
    voice_wav = tmp / "voice.wav"
    # voice=False mutes the track only; the layout still uses cached voice lengths, like the preview
    clips = narrate.voice_clips(folder, the_film, slots) if voice else []
    narrate.build_voice_track(clips, total, voice_wav)
    mixed = voice_wav
    music = the_film.music
    with contextlib.ExitStack() as stack:
        if music is not None:
            if music.bed is not None:
                # generated: exactly as long as the film; held so it cannot be pruned mid-export
                source = stack.enter_context(soundcache.use_bed(folder, the_film, total))
            else:
                source = folder / music.file
                if not source.is_file():
                    raise ExportError(f"music file not found: {music.file}")
            mixed = tmp / "mixed.wav"
            narrate.mix_music(voice_wav, source, music.volume, total, mixed)
        # the final step always runs the limiter, with or without sound effects
        final = tmp / "final.wav"
        soundmix.add_sfx_to_wav(mixed, soundmix.placed_sfx(folder, the_film, slots), total, final)
    return final


def _render_frames(base: str, the_film: filmlib.Film, aspect: str, slots, n: int, fps: int, stdin,
                   report: Callable[[int], None] = lambda done: None) -> None:
    try:
        from playwright.sync_api import Error as PlaywrightError
        from playwright.sync_api import sync_playwright
    except ImportError:
        raise ExportError(f"the playwright package is missing: {SETUP_HINT}") from None
    width, height = aspectlib.canvas_size(the_film, aspect)
    with sync_playwright() as p:
        try:
            browser = p.chromium.launch()
        except PlaywrightError as exc:
            raise ExportError(f"Chromium is not available ({SETUP_HINT}): {exc}") from None
        try:
            page = browser.new_page(viewport={"width": width, "height": height}, device_scale_factor=1)
            page.goto(f"{base}/render.html?aspect={aspectlib.slug(aspect)}")
            page.evaluate("window.moshfilm.ready")
            _page_errors(page, the_film)
            for slot in slots:  # fail before encoding: one frame inside every scene
                page.evaluate("t => window.moshfilm.seek(t)", slot.start + slot.length / 2)
            _page_errors(page, the_film)

            def render_frame(i: int) -> bytes:
                page.evaluate("t => window.moshfilm.seek(t)", i / fps)
                _page_errors(page, the_film)
                return page.screenshot(type="png")

            _run_frames(n, fps, render_frame, stdin, report)
        finally:
            browser.close()


def output_paths(the_film: filmlib.Film, fmt: str, out: Path | None, folder: Path) -> dict[str, Path]:
    """Where each chosen shape's file goes, keyed by shape. One shape keeps the plain name; two shapes
    add the shape (`-16x9`, `-9x16`) before the extension."""
    shapes = aspectlib.chosen(the_film)
    base = Path(out) if out else Path(folder) / "exports" / f"{_slug(the_film.title)}.{fmt}"
    if len(shapes) == 1:
        return {shapes[0]: base}
    return {a: base.with_name(f"{base.stem}-{aspectlib.slug(a)}{base.suffix}") for a in shapes}


def _read_encode_progress(stream, frames_done: threading.Event, seconds: float,
                          report: Callable[[float], None]) -> None:
    """Read ffmpeg's `-progress pipe:1` lines; once every frame is sent, report how much film it has encoded."""
    last = 0.0
    for line in stream:
        key, _, value = line.strip().partition("=")
        if key not in ("out_time_us", "out_time_ms") or not frames_done.is_set():
            continue  # (out_time_ms is in microseconds too, a long-standing ffmpeg quirk)
        try:
            done = int(value) / 1e6
        except ValueError:
            continue  # "N/A" before the first output
        now = time.monotonic()
        if now - last >= PROGRESS_INTERVAL:
            last = now
            report(min(done, seconds))


def _export_one(base: str, the_film: filmlib.Film, aspect: str, fmt: str, fps: int, size: tuple[int, int],
                audio: Path | None, slots, n: int, tmp: Path, out: Path,
                report: Callable[[str, str | None, int, float, float], None] | None = None,
                index: int = 0) -> None:
    canvas = aspectlib.canvas_size(the_film, aspect)
    part = tmp / f"out-{aspectlib.slug(aspect)}.{fmt}"
    log_path = tmp / f"ffmpeg-{aspectlib.slug(aspect)}.log"
    seconds = n / fps
    report = report or (lambda *a: None)
    cmd = _encode_cmd(fmt, fps, canvas, size, audio, part)
    cmd[2:2] = ["-progress", "pipe:1", "-nostats"]  # machine-readable progress on stdout
    frames_done = threading.Event()
    with open(log_path, "wb") as log:
        enc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=log, text=False)
        reader = threading.Thread(
            target=_read_encode_progress, daemon=True, name="moshfilm-ffmpeg-progress",
            args=(_lines(enc.stdout), frames_done, seconds, lambda d: report("encode", aspect, index, d, seconds)))
        reader.start()
        try:
            _render_frames(base, the_film, aspect, slots, n, fps, enc.stdin,
                           lambda done: report("frames", aspect, index, done, n))
            frames_done.set()
            report("encode", aspect, index, 0, seconds)  # the frames are all sent: ffmpeg is finishing
        except BrokenPipeError:
            pass  # ffmpeg died; its log below says why
        finally:
            try:
                enc.stdin.close()
            except BrokenPipeError:
                pass
            code = enc.wait()
            reader.join(5)
    if code != 0 or not part.exists():
        raise ExportError(f"ffmpeg failed: {log_path.read_text(errors='replace')[-500:]}")
    report("encode", aspect, index, seconds, seconds)
    out.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(part, out)


def _lines(stream):
    """Text lines from a binary pipe (or from an already-text stream)."""
    for raw in stream:
        yield raw.decode("utf-8", "replace") if isinstance(raw, bytes) else raw


def _export(folder: Path, fmt: str, out: Path | None, fps: int | None, width: int | None, voice: bool,
            main_only: bool, progress: Callable[[str], None] | None = None,
            on_progress: Callable[[dict], None] | None = None) -> dict[str, Path]:
    folder = Path(folder)
    if not (shutil.which("ffmpeg") and shutil.which("ffprobe")):
        raise ExportError(f"ffmpeg is not installed ({SETUP_HINT})")
    try:
        the_film = filmlib.load_film(folder)
        durations = (narrate.ensure_voice(folder, the_film) if voice
                     else narrate.voice_durations(folder, the_film))
    except (filmlib.FilmError, narrate.NarrationError) as exc:
        raise ExportError(str(exc)) from None
    slots = timing.layout(the_film, durations)
    _check_scenes(the_film, slots)
    total = timing.total_length(slots)
    if total <= 0:
        raise ExportError("the film has no scenes")
    fps = fps or (GIF_FPS if fmt == "gif" else the_film.fps)
    n = math.ceil(total * fps)
    paths = output_paths(the_film, fmt, Path(out) if out else None, folder)
    if main_only:
        paths = {the_film.aspect: paths[the_film.aspect]}
    main_canvas = (the_film.width, the_film.height)

    base, stop = server.serve_in_thread(folder)
    try:
        with tempfile.TemporaryDirectory(prefix="moshfilm-export-") as tmpdir:
            tmp = Path(tmpdir)
            # one audio track for every shape: the timeline and the narration are shared
            report = _Reporter(on_progress, len(paths))
            if fmt == "mp4":
                report("audio", None, 0, 0, 1)
                audio = _build_audio(folder, the_film, slots, total, voice, tmp)
                report("audio", None, 0, 1, 1)
            else:
                audio = None
            for index, (aspect, path) in enumerate(paths.items()):
                canvas = aspectlib.canvas_size(the_film, aspect)
                size = _target_size(canvas, main_canvas, fmt, width)
                if progress:
                    progress(aspect)
                _export_one(base, the_film, aspect, fmt, fps, size, audio, slots, n, tmp, path, report, index)
    finally:
        stop()
    return paths


def export_aspects(folder: Path, fmt: Literal["mp4", "gif"], out: Path | None = None,
                   fps: int | None = None, width: int | None = None, voice: bool = True,
                   progress: Callable[[str], None] | None = None,
                   on_progress: Callable[[dict], None] | None = None) -> dict[str, Path]:
    """Export one file per chosen shape (main first); returns shape -> path.

    `progress(aspect)` is called as each shape starts. `on_progress(event)` is called as work moves along
    with `{stage: "audio"|"frames"|"encode", aspect, aspect_index, aspect_count, done, total}`: audio
    0/1 then 1/1 (MP4 only, aspect None); frames done/total at the start, about 4 times a second and after
    the last frame; encode done/total in seconds of film (from ffmpeg), 0 first and total last. It runs on
    the exporting thread or on the ffmpeg reader thread, one call at a time."""
    return _export(folder, fmt, out, fps, width, voice, main_only=False, progress=progress,
                   on_progress=on_progress)


def export_film(folder: Path, fmt: Literal["mp4", "gif"], out: Path | None = None,
                fps: int | None = None, width: int | None = None, voice: bool = True) -> Path:
    """Export the main shape only and return its file (see `export_aspects` for every shape)."""
    return next(iter(_export(folder, fmt, out, fps, width, voice, main_only=True).values()))
