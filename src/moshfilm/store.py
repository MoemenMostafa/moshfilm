"""JSON read, atomic write, and one re-enterable lock per film folder."""
from __future__ import annotations

import json
import os
import tempfile
import threading
from pathlib import Path
from typing import Any

from filelock import FileLock

LOCK_TIMEOUT = 10.0
_locks: dict[Path, FileLock] = {}
_locks_guard = threading.Lock()


def read_json(path: Path, default: Any) -> Any:
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except FileNotFoundError:
        return default


def write_json_atomic(path: Path, data: Any) -> None:
    """Write to a temp file in the same folder, then os.replace it into place."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=path.name + ".", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(data, fh, indent=2, ensure_ascii=False)
            fh.write("\n")
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except FileNotFoundError:
            pass
        raise


def locked(folder: Path) -> FileLock:
    """The lock for a film folder: one cached FileLock per resolved folder.

    The same object is returned every time, so `with locked(f):` can nest in one
    thread (the lock counts its holders) while other threads and processes wait.
    """
    key = Path(folder).resolve()
    with _locks_guard:
        lock = _locks.get(key)
        if lock is None:
            state = key / ".moshfilm"
            state.mkdir(parents=True, exist_ok=True)
            lock = _locks[key] = FileLock(str(state / "lock"), timeout=LOCK_TIMEOUT)
        return lock
