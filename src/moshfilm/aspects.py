"""Film shapes (aspect ratios) and the canvas size of each one.

Mirrored in ui/src/runtime/aspect.ts and pinned by tests/fixtures/aspect_cases.json.
"""
from __future__ import annotations

import math
from typing import TYPE_CHECKING, Literal

if TYPE_CHECKING:
    from .film import Film

Aspect = Literal["16:9", "9:16", "1:1", "4:5"]
ALL: tuple[str, ...] = ("16:9", "9:16", "1:1", "4:5")


def ratio(aspect: str) -> tuple[int, int]:
    a, b = aspect.split(":")
    return int(a), int(b)


def canvas_size(film: "Film", aspect: str) -> tuple[int, int]:
    """The main shape keeps the stored size; any other keeps the short side and derives the long one."""
    if aspect == film.aspect:
        return film.width, film.height
    a, b = ratio(aspect)
    short = min(film.width, film.height)
    # floor(x + 0.5) rounds halves up, like JS Math.round (Python's round() goes to even)
    long = 2 * math.floor(short * max(a, b) / min(a, b) / 2 + 0.5)
    if a == b:
        return short, short
    return (long, short) if a > b else (short, long)


def chosen(film: "Film") -> list[str]:
    return [film.aspect] + ([film.second_aspect] if film.second_aspect else [])


def slug(aspect: str) -> str:
    return aspect.replace(":", "x")


def from_slug(s: str) -> str:
    for a in ALL:
        if slug(a) == s:
            return a
    raise ValueError(f"unknown aspect {s!r}")


def nearest(width: int, height: int) -> str:
    """The shape whose ratio is closest to width/height in log space; ties go to the earlier one."""
    target = math.log(width / height)
    best, best_d = ALL[0], None
    for a in ALL:
        x, y = ratio(a)
        d = abs(math.log(x / y) - target)
        if best_d is None or d < best_d - 1e-12:
            best, best_d = a, d
    return best
