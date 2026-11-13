"""Rendered sound cache: `<film>/.moshfilm/sound/{bed,sfx}-<key>.wav`.

The key is a hash of every input (the parameters in film.json, the film length for a bed, the sample rate
and SYNTH_VERSION), so a changed length or parameter is simply a new file and nothing is ever stale.
"""
from __future__ import annotations

import contextlib
import hashlib
import json
import os
import threading
import time
import wave
from pathlib import Path

from .. import narrate, timing
from ..film import Film, MusicBed, SfxClip, load_film
from . import SAMPLE_RATE, SYNTH_VERSION
from . import music, sfx, synth

MAX_BEDS = 6
PRUNE_GRACE = 90.0  # seconds: a bed used more recently than this is never pruned (exports use the in-use set)
MIN_WAV_BYTES = 44   # a WAV header alone

# One bed render at a time: a 10-minute bed needs a few hundred MB, so renders queue instead of piling up.
_render_slot = threading.Semaphore(1)
_dir_lock = threading.Lock()   # prune and in-use bookkeeping
_in_use: dict[str, int] = {}   # paths an export is reading right now

_locks: dict[str, threading.Lock] = {}
_guard = threading.Lock()


def sound_dir(folder: Path) -> Path:
    return Path(folder) / ".moshfilm" / "sound"


def _hash(parts: dict) -> str:
    blob = json.dumps({**parts, "rate": SAMPLE_RATE, "synth": SYNTH_VERSION}, sort_keys=True)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:16]


def bed_key(bed: MusicBed, total: float) -> str:
    return _hash({"kind": "bed", "bed": bed.model_dump(), "total": round(total, 3)})


def sfx_key(clip: SfxClip) -> str:
    return _hash({"kind": "sfx", "preset": clip.preset, "pitch": clip.pitch,
                  "stretch": clip.stretch, "seed": clip.seed})


def _lock(path: Path) -> threading.Lock:
    with _guard:
        return _locks.setdefault(str(path), threading.Lock())


def ensure_sfx(folder: Path, clip: SfxClip) -> Path:
    path = sound_dir(folder) / f"sfx-{sfx_key(clip)}.wav"
    with _lock(path):
        if not path.is_file():
            synth.write_wav(path, sfx.render_sfx(clip.preset, clip.pitch, clip.stretch, clip.seed))
    return path


def _valid(path: Path) -> bool:
    """A usable WAV: present, longer than a bare header, and its header parses."""
    try:
        if path.stat().st_size < MIN_WAV_BYTES:
            return False
        with wave.open(str(path), "rb") as w:
            return w.getnframes() > 0
    except (OSError, EOFError, wave.Error):
        return False


class StaleBed(Exception):
    """The bed asked for is no longer the film's current one (it changed while the request waited)."""


def _is_current(folder: Path, key: str) -> bool:
    try:
        f = load_film(folder)
        return f.music is None or f.music.bed is None or bed_key(f.music.bed, film_total(folder, f)) == key
    except Exception:  # noqa: BLE001 - an unreadable film is not a reason to refuse
        return True


def ensure_bed(folder: Path, film: Film, total: float, only_if_current: bool = False) -> Path:
    """The bed's WAV, rendered when missing or unusable. With `only_if_current`, a render that has been
    waiting for its turn is skipped (StaleBed) when the film moved on: obsolete renders never pile up."""
    if film.music is None or film.music.bed is None:
        raise ValueError("the film has no generated music bed")
    bed = film.music.bed
    key = bed_key(bed, total)
    path = sound_dir(folder) / f"bed-{key}.wav"
    with _lock(path):
        fresh = False
        if _valid(path):
            try:
                os.utime(path)  # most recently used survives the pruning; never creates the file
                fresh = True
            except OSError:
                pass  # pruned under us: render it again
        if not fresh:
            with _render_slot:
                if only_if_current and not _is_current(folder, key):
                    raise StaleBed(key)
                synth.write_wav(path, music.render_bed(bed, total))
        _prune_beds(path.parent, keep=path)
    return path


def _prune_beds(directory: Path, keep: Path) -> None:
    now = time.time()
    with _dir_lock:
        held = set(_in_use)
        candidates = []
        for p in directory.glob("bed-*.wav"):
            if p == keep:
                continue
            try:
                candidates.append((p.stat().st_mtime, p))
            except OSError:
                pass  # vanished
        candidates.sort(key=lambda c: (c[0], c[1].name), reverse=True)
        for mtime, p in candidates[MAX_BEDS - 1:]:
            if str(p) in held or now - mtime < PRUNE_GRACE:
                continue
            p.unlink(missing_ok=True)


@contextlib.contextmanager
def use_bed(folder: Path, film: Film, total: float):
    """The bed's path, held so pruning cannot delete it while an export reads it."""
    path = ensure_bed(folder, film, total)
    with _dir_lock:
        _in_use[str(path)] = _in_use.get(str(path), 0) + 1
    try:
        yield path
    finally:
        with _dir_lock:
            n = _in_use.get(str(path), 1) - 1
            if n <= 0:
                _in_use.pop(str(path), None)
            else:
                _in_use[str(path)] = n


def film_total(folder: Path, film: Film) -> float:
    """Film length from the layout with the cached voice lines (never touches the network)."""
    return timing.total_length(timing.layout(film, narrate.voice_durations(folder, film)))
