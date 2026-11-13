"""Layout check: draw every ready scene in each chosen shape and warn about content that does not fit.

Chromium opens the render page once per shape (`/render.html?aspect=9x16`), seeks to a few moments of every
scene and asks the page's overflow detector (`window.moshfilm.overflow()`, ui/src/runtime/overflow.ts) what
sticks out of the frame or is clipped inside its box. The result is a list of `Issue`s Claude can act on.
"""
from __future__ import annotations

import re
from pathlib import Path

from . import aspects as aspectlib
from . import film as filmlib
from . import narrate, server, timing
from .film import Issue

SETUP_HINT = "run scripts/setup.sh"
SAMPLE_POINTS = (0.05, 0.25, 0.5, 0.75, 0.95)  # fractions of a scene's length


class LayoutCheckUnavailable(Exception):
    """Playwright or Chromium is missing, so the layout cannot be checked."""


def _sample_times(the_film: filmlib.Film, slots: list[timing.SceneSlot]) -> dict[str, list[float]]:
    """Film times to look at, per ready scene: the fixed points plus the middle of each caption's window."""
    ready = {s.id for s in the_film.scenes if s.status == "ready" and s.file}
    times: dict[str, list[float]] = {}
    for slot in slots:
        if slot.id in ready:
            times[slot.id] = [slot.start + f * slot.length for f in SAMPLE_POINTS]
    for clip in the_film.texts:
        if clip.scene not in times:
            continue
        try:
            start, end = timing.text_window(clip, slots)
        except Exception:  # noqa: BLE001 - a clip pointing nowhere is the film check's business
            continue
        times[clip.scene].append((start + end) / 2)
    return {k: sorted(set(round(t, 3) for t in v)) for k, v in times.items()}


def _hit_issue(shape: str, t: float, hit: dict) -> Issue:
    where = hit["target"].removeprefix("text:")
    if hit["kind"] == "clipped":
        what = f"{hit['text']} is clipped inside its box"
    else:
        what = f"{hit['text']} sticks out of the frame ({hit['side']}, {hit['by']} px)"
    return Issue(level="warning", where=where, message=f"[{shape}] at {t:.1f} s: {what}")


def check_layout(folder: Path, aspects: list[str] | None = None) -> list[Issue]:
    """Warnings (and scene errors) for each shape; `aspects=None` means the film's chosen shapes."""
    folder = Path(folder)
    the_film = filmlib.load_film(folder)
    shapes = list(aspects) if aspects is not None else aspectlib.chosen(the_film)
    slots = timing.layout(the_film, narrate.voice_durations(folder, the_film))
    samples = _sample_times(the_film, slots)
    if not samples:
        return []
    try:
        from playwright.sync_api import Error as PlaywrightError
        from playwright.sync_api import sync_playwright
    except ImportError:
        raise LayoutCheckUnavailable(f"the playwright package is missing: {SETUP_HINT}") from None

    issues: list[Issue] = []
    base, stop = server.serve_in_thread(folder)
    try:
        with sync_playwright() as p:
            try:
                browser = p.chromium.launch()
            except PlaywrightError as exc:
                first = str(exc).strip().splitlines()[0] if str(exc).strip() else "launch failed"
                raise LayoutCheckUnavailable(f"Chromium is not available ({first}); {SETUP_HINT}") from None
            try:
                for shape in shapes:
                    issues.extend(_check_shape(browser, base, the_film, shape, samples))
            finally:
                browser.close()
    finally:
        stop()
    return issues


def _check_shape(browser, base: str, the_film: filmlib.Film, shape: str,
                 samples: dict[str, list[float]]) -> list[Issue]:
    width, height = aspectlib.canvas_size(the_film, shape)
    page = browser.new_page(viewport={"width": width, "height": height}, device_scale_factor=1)
    issues: list[Issue] = []
    failed: set[str] = set()
    seen: set[tuple] = set()
    try:
        page.goto(f"{base}/render.html?aspect={aspectlib.slug(shape)}")
        page.evaluate("window.moshfilm.ready")

        def scene_errors() -> None:
            for message in page.evaluate("window.moshfilm.errors"):
                m = re.match(r"Scene (\S+) failed: (.*)", message, re.S)
                if not m:
                    key = ("page", message)
                    if key not in seen:
                        seen.add(key)
                        issues.append(Issue(level="error", where=shape, message=f"[{shape}] {message}"))
                    continue
                if m.group(1) not in failed:
                    failed.add(m.group(1))
                    issues.append(Issue(level="error", where=m.group(1),
                                        message=f"[{shape}] scene failed: {m.group(2)}"))

        scene_errors()
        for scene_id, times in samples.items():
            for t in times:
                if scene_id in failed:
                    break
                page.evaluate("t => window.moshfilm.seek(t)", t)
                scene_errors()
                if scene_id in failed:
                    break
                for hit in page.evaluate("window.moshfilm.overflow()"):
                    key = (hit["target"], hit["text"], hit["kind"])
                    if key in seen:
                        continue
                    seen.add(key)
                    issues.append(_hit_issue(shape, t, hit))
    finally:
        page.close()
    return issues
