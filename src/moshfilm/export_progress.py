"""Turns the exporter's stage events into the editor's one overall progress figure.

The exporter reports `{stage, aspect, aspect_index, aspect_count, done, total}` events (see
`export.export_aspects`). This tracker keeps the latest one and works out the overall percent
(across every shape) and a time estimate. It has no dependencies, so it is easy to test.
"""
from __future__ import annotations

import time
from typing import Callable

AUDIO_SHARE = 0.03   # the voice/music/effects track is built once, for an MP4 only: a small fixed share
ENCODE_SHARE = 0.10  # inside one shape: the last 10% is ffmpeg finishing; the first 90% is the frames
ETA_AFTER = 3.0      # seconds of rendering needed before an estimate is shown


def _fraction(done: float, total: float) -> float:
    return 0.0 if total <= 0 else min(1.0, max(0.0, done / total))


class ExportProgress:
    def __init__(self, fmt: str, clock: Callable[[], float] = time.monotonic) -> None:
        self.audio_share = AUDIO_SHARE if fmt == "mp4" else 0.0
        self.clock = clock
        self.event: dict | None = None
        self.frames_per_shape = 0
        self._first: tuple[float, int] | None = None  # (time, frames done) at the first frames event
        self._last: tuple[float, int] | None = None   # the same at the latest frames event

    def update(self, event: dict) -> None:
        self.event = dict(event)
        if event["stage"] == "frames":
            self.frames_per_shape = int(event["total"])
            cum = int(event.get("aspect_index", 0)) * self.frames_per_shape + int(event["done"])
            point = (self.clock(), cum)
            if self._first is None:
                self._first = point
            self._last = point

    def _shape_fraction(self) -> float:
        e = self.event or {}
        f = _fraction(e.get("done", 0), e.get("total", 0))
        if e.get("stage") == "frames":
            return (1 - ENCODE_SHARE) * f
        if e.get("stage") == "encode":
            return (1 - ENCODE_SHARE) + ENCODE_SHARE * f
        return 0.0

    def percent(self) -> float:
        e = self.event
        if e is None:
            return 0.0
        if e["stage"] == "audio":
            return 100 * self.audio_share * _fraction(e["done"], e["total"])
        count = max(1, int(e.get("aspect_count", 1)))
        per_shape = (1 - self.audio_share) / count
        return 100 * (self.audio_share + (int(e.get("aspect_index", 0)) + self._shape_fraction()) * per_shape)

    def eta_seconds(self) -> int | None:
        e = self.event
        if e is None or e["stage"] == "audio" or self._first is None or self._last is None:
            return None
        spent = self._last[0] - self._first[0]
        frames = self._last[1] - self._first[1]
        if spent < ETA_AFTER or frames <= 0 or self.frames_per_shape <= 0:
            return None
        count = max(1, int(e.get("aspect_count", 1)))
        # work in "frame equivalents": a shape is its frames plus the encode share on top
        per_shape = self.frames_per_shape / (1 - ENCODE_SHARE)
        left = count * per_shape - (int(e.get("aspect_index", 0)) + self._shape_fraction()) * per_shape
        return max(0, round(left / (frames / spent)))

    def snapshot(self) -> dict | None:
        e = self.event
        if e is None:
            return None
        return {"stage": e["stage"], "aspect": e.get("aspect"), "aspect_index": int(e.get("aspect_index", 0)),
                "aspect_count": int(e.get("aspect_count", 1)), "done": e["done"], "total": e["total"],
                "percent": round(self.percent(), 1), "eta_seconds": self.eta_seconds()}
