"""Comment/chat queue in comments.json, Claude's status line, and the watcher heartbeat.

Items are stored the moment they are made (state `queued`), handed to a watching
Claude session oldest-first (`delivered`), and closed by a reply or `resolve`
(`resolved`). Every read-modify-write of comments.json runs inside `store.locked`.
"""
from __future__ import annotations

import os
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, model_serializer

from . import store

HEARTBEAT_INTERVAL = 5.0
HEARTBEAT_TTL = 30.0


class _Model(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Point(_Model):
    x: float
    y: float


class At(_Model):
    """The frame a chat message points at: seconds in the whole film, plus the scene there."""
    time: float
    scene: str | None = None
    sceneTitle: str | None = None
    aspect: str | None = None  # the shape the preview showed (None: the main shape)

    @model_serializer(mode="wrap")
    def _omit_missing_aspect(self, handler):
        data = handler(self)
        if data.get("aspect") is None:
            data.pop("aspect", None)
        return data


class QueueItem(_Model):
    id: str
    kind: Literal["comment", "chat", "event"]
    text: str
    created: str
    state: Literal["queued", "delivered", "resolved"] = "queued"
    time: float | None = None
    scene: str | None = None
    scene_time: float | None = None
    point: Point | None = None
    aspect: str | None = None  # the shape the comment was made on; `point` is measured on that frame
    attachment: str | None = None
    at: At | None = None
    delivered_at: str | None = None
    resolved_at: str | None = None


class Message(_Model):
    id: str
    role: Literal["claude"] = "claude"
    text: str
    reply_to: str | None = None
    created: str


class QueueSnapshot(_Model):
    items: list[QueueItem]
    messages: list[Message]
    status: str | None
    connected: bool


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(moment: datetime | None = None) -> str:
    return (moment or _now()).isoformat(timespec="milliseconds")


def _comments_path(folder: Path) -> Path:
    return Path(folder) / "comments.json"


def _state_path(folder: Path, name: str) -> Path:
    return Path(folder) / ".moshfilm" / name


def _load(folder: Path) -> tuple[list[QueueItem], list[Message]]:
    data = store.read_json(_comments_path(folder), {})
    return (
        [QueueItem(**i) for i in data.get("items", [])],
        [Message(**m) for m in data.get("messages", [])],
    )


def _save(folder: Path, items: list[QueueItem], messages: list[Message]) -> None:
    store.write_json_atomic(
        _comments_path(folder),
        {"items": [i.model_dump() for i in items], "messages": [m.model_dump() for m in messages]},
    )


def _next_id(prefix: str, existing: list[Any]) -> str:
    used = [int(x.id[len(prefix):]) for x in existing if x.id[len(prefix):].isdigit()]
    return f"{prefix}{max(used, default=0) + 1}"


def add_item(folder: Path, kind: str, text: str, **fields: Any) -> QueueItem:
    with store.locked(folder):
        items, messages = _load(folder)
        item = QueueItem(id=_next_id("q", items), kind=kind, text=text, created=_iso(), **fields)
        items.append(item)
        _save(folder, items, messages)
        return item


def add_event(folder: Path, text: str) -> QueueItem:
    """An event line for Claude (e.g. an invalid proposal); fits `process_pending(on_event=...)`."""
    return add_item(folder, "event", text)


def stamp_aspect(folder: Path, aspect: str) -> int:
    """Give every comment or chat pointer that has no shape the shape it was made on (the main one at the time).

    Called when the main shape changes, so old pins stay on the shape they were placed on."""
    with store.locked(folder):
        items, messages = _load(folder)
        n = 0
        for item in items:
            if item.kind == "comment" and item.aspect is None:
                item.aspect, n = aspect, n + 1
            elif item.at is not None and item.at.aspect is None:
                item.at.aspect, n = aspect, n + 1
        if n:
            _save(folder, items, messages)
        return n


def take_queued(folder: Path) -> list[QueueItem]:
    """Mark every queued item delivered and return them, oldest first."""
    with store.locked(folder):
        items, messages = _load(folder)
        taken = [i for i in items if i.state == "queued"]
        if taken:
            stamp = _iso()
            for i in taken:
                i.state = "delivered"
                i.delivered_at = stamp
            _save(folder, items, messages)
        return taken


def _find(items: list[QueueItem], item_id: str) -> QueueItem:
    for i in items:
        if i.id == item_id:
            return i
    raise KeyError(item_id)


def reply(folder: Path, item_id: str | None, text: str, resolve: bool = True) -> Message:
    with store.locked(folder):
        items, messages = _load(folder)
        item = _find(items, item_id) if item_id is not None else None
        msg = Message(id=_next_id("r", messages), text=text, reply_to=item_id, created=_iso())
        messages.append(msg)
        if item is not None and resolve:
            item.state = "resolved"
            item.resolved_at = _iso()
        _save(folder, items, messages)
        return msg


def resolve(folder: Path, item_id: str) -> None:
    with store.locked(folder):
        items, messages = _load(folder)
        item = _find(items, item_id)
        item.state = "resolved"
        item.resolved_at = _iso()
        _save(folder, items, messages)


def set_status(folder: Path, text: str | None) -> None:
    with store.locked(folder):
        store.write_json_atomic(_state_path(folder, "status.json"), {"text": text})


def heartbeat(folder: Path, alive: bool = True) -> None:
    """Written only by `watch`: the time of the last sign of life, or empty once it stops."""
    path = _state_path(folder, "heartbeat")
    path.parent.mkdir(parents=True, exist_ok=True)
    # temp file + replace: the server polls this file, so a reader must never see it half-written
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix="heartbeat.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(_iso() if alive else "")
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except FileNotFoundError:
            pass
        raise


def is_connected(folder: Path, now: datetime | None = None) -> bool:
    try:
        raw = _state_path(folder, "heartbeat").read_text(encoding="utf-8").strip()
        beat = datetime.fromisoformat(raw)
    except (FileNotFoundError, ValueError):
        return False
    if beat.tzinfo is None:
        beat = beat.replace(tzinfo=timezone.utc)
    return (now or _now()) - beat <= timedelta(seconds=HEARTBEAT_TTL)


def snapshot(folder: Path) -> QueueSnapshot:
    with store.locked(folder):
        items, messages = _load(folder)
        status = store.read_json(_state_path(folder, "status.json"), {}).get("text")
    return QueueSnapshot(items=items, messages=messages, status=status, connected=is_connected(folder))
