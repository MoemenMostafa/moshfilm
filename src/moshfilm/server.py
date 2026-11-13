"""Local server: the JSON API, live events (SSE), film files and the built UI, all on 127.0.0.1.

The film folder is the single source of truth. The server never keeps film state in memory:
every request reads and writes the folder (under `store.locked`), and a folder watcher turns
file changes into SSE events so the browser and Claude's edits stay in step.
"""
from __future__ import annotations

import asyncio
import functools
import json
import math
import re
import socket
import subprocess
import sys
import threading
import time
import webbrowser
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Callable
from urllib.parse import urlsplit

import uvicorn
from fastapi import FastAPI, File, Form, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from watchfiles import awatch

from . import activity, aspects, edits, history, narrate, proposals, queue, store, timing
from .sound import cache as soundcache, music as soundmusic, sfx as soundsfx
from .export_progress import ExportProgress
from .film import Film, FilmError, SfxClip, load_film, save_film

HOST = "127.0.0.1"
DEFAULT_PORT = 5717
PORT_TRIES = 11            # 5717 .. 5727
QUEUE_TICK = 5.0           # seconds between `queue` events, so `connected` flips when the watcher dies
STATIC = Path(__file__).parent / "static"
ALLOWED_HOSTNAMES = {"127.0.0.1", "localhost"}
_KEY = re.compile(r"[0-9a-f]{16}")

# --------------------------------------------------------------------------- paths


def classify_change(path: Path, folder: Path) -> str | None:
    """What a changed file means for the UI: film, proposals, queue, scene, voice, or None (ignore)."""
    try:
        rel = Path(path).resolve().relative_to(Path(folder).resolve())
    except ValueError:
        return None
    parts, name = rel.parts, rel.name
    if not parts or name.endswith((".tmp", ".part", ".swp")):
        return None
    if parts == ("film.json",):
        return "film"
    if parts == ("proposals.json",):
        return "proposals"
    if parts == ("comments.json",):
        return "queue"
    if parts[0] == ".moshfilm":
        if parts[1:] in (("heartbeat",), ("status.json",)):
            return "queue"
        if parts[1:] == ("activity.json",):
            return "activity"
        if len(parts) >= 3 and parts[1] == "voice":
            return "voice"
        if len(parts) >= 3 and parts[1] == "history":
            return "history"
        return None
    if parts[0] == "scenes" and len(parts) == 2 and name.endswith(".js") and not name.startswith("."):
        return "scene"
    return None


def resolve_film_path(folder: Path, rel: str) -> Path | None:
    """The real file for a URL path inside the film folder, or None.

    Refuses anything that resolves outside the folder (`..`, absolute paths, symlinks out),
    any dotfile or dot-folder (`.moshfilm`, `.claude`, `.env`, ...) and anything that is not a file.
    """
    if not rel or "\0" in rel:
        return None
    root = Path(folder).resolve()
    try:
        target = (root / rel).resolve()
        inside = target.relative_to(root)
    except (ValueError, OSError):
        return None
    if any(part.startswith(".") for part in inside.parts) or not target.is_file():
        return None
    return target


def _inside(folder: Path, rel: str) -> bool:
    """True when `rel` (a path stored in film.json) stays inside the film folder."""
    root = Path(folder).resolve()
    try:
        (root / rel).resolve().relative_to(root)
    except (ValueError, OSError):
        return False
    return not Path(rel).is_absolute()


def _safe_name(filename: str | None) -> str:
    name = Path((filename or "").replace("\\", "/")).name
    name = re.sub(r"[^A-Za-z0-9._-]", "_", name).lstrip(".")
    return name or "upload"


def _save_upload(folder: Path, subdir: str, upload: UploadFile) -> str:
    """Save under `<subdir>/<safe name>` without overwriting; return the relative path."""
    target_dir = Path(folder) / subdir
    target_dir.mkdir(parents=True, exist_ok=True)
    name = _safe_name(upload.filename)
    stem, suffix = Path(name).stem, Path(name).suffix
    n = 1
    while True:
        candidate = target_dir / name
        try:
            with open(candidate, "xb") as out:
                while chunk := upload.file.read(1 << 20):
                    out.write(chunk)
            break
        except FileExistsError:
            n += 1
            name = f"{stem}-{n}{suffix}"
    return f"{subdir}/{name}"


# --------------------------------------------------------------------------- host check


def _hostname(value: str) -> str | None:
    try:
        return urlsplit("//" + value).hostname
    except ValueError:
        return None


class _LocalOnly:
    """Reject requests whose Host (or Origin) is not this machine: blocks DNS rebinding and
    cross-site posts. Any port is fine; the hostname is what a rebinding attack cannot fake."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] in ("http", "websocket"):
            headers = dict(scope["headers"])
            host = _hostname(headers.get(b"host", b"").decode("latin-1"))
            origin = headers.get(b"origin")
            ok = host in ALLOWED_HOSTNAMES
            if ok and origin is not None:
                o = origin.decode("latin-1")
                ok = (_hostname(o.split("://", 1)[1]) if "://" in o else None) in ALLOWED_HOSTNAMES
            if not ok:
                if scope["type"] == "http":
                    await JSONResponse({"error": "forbidden host"}, status_code=403)(scope, receive, send)
                else:
                    await send({"type": "websocket.close", "code": 1008})
                return
        await self.app(scope, receive, send)


# --------------------------------------------------------------------------- events


class _Hub:
    """Fan-out of SSE events to every connected browser. Loop-thread only except `emit`."""

    def __init__(self) -> None:
        self.loop: asyncio.AbstractEventLoop | None = None
        self.closed = False
        self._subs: set[asyncio.Queue] = set()

    def subscribe(self) -> asyncio.Queue:
        q: asyncio.Queue = asyncio.Queue()
        self._subs.add(q)
        return q

    def unsubscribe(self, q: asyncio.Queue) -> None:
        self._subs.discard(q)

    def publish(self, name: str, data: dict) -> None:
        for q in list(self._subs):
            q.put_nowait((name, data))

    def emit(self, name: str, data: dict | None = None) -> None:
        """Thread-safe publish (for worker threads); dropped when no loop is running."""
        if self.loop is not None and not self.closed:
            self.loop.call_soon_threadsafe(self.publish, name, data or {})

    def close(self) -> None:
        self.closed = True
        for q in list(self._subs):
            q.put_nowait(None)


NO_CACHE = {"Cache-Control": "no-cache"}  # revalidate: scenes and pages change while the editor is open


def _sse(name: str, data: dict) -> str:
    return f"event: {name}\ndata: {json.dumps(data)}\n\n"


def _scene_version(folder: Path, rel: str) -> int:
    try:
        return (folder / rel).stat().st_mtime_ns
    except OSError:
        return 0


async def _process_pending(folder: Path) -> bool:
    """Handle pending proposals off the event loop; False when the film is broken."""
    try:
        await asyncio.to_thread(
            proposals.process_pending, folder, functools.partial(queue.add_event, folder))
    except Exception:  # broken film.json etc.
        return False
    return True


async def _watch(folder: Path, hub: _Hub, stop: asyncio.Event) -> None:
    async for changes in awatch(folder, stop_event=stop, debounce=200, step=50):
        kinds: set[str] = set()
        scenes: set[str] = set()
        for _, raw in changes:
            kind = classify_change(Path(raw), folder)
            if kind == "scene":
                scenes.add(Path(raw).resolve().relative_to(folder.resolve()).as_posix())
            if kind:
                kinds.add(kind)
        if "proposals" in kinds:
            if not await _process_pending(folder):  # the film event below tells the UI
                kinds.add("film")
        if kinds & {"film", "scene", "proposals"}:  # changes nobody recorded (Claude's) become a history step
            try:
                await asyncio.to_thread(history.sync, folder, functools.partial(queue.add_event, folder))
            except Exception:  # noqa: BLE001 - history must never break the live view
                pass
        for kind in ("film", "proposals", "queue", "voice", "activity", "history"):
            if kind in kinds:
                hub.publish(kind, {})
        for rel in sorted(scenes):
            hub.publish("scene", {"file": rel, "version": _scene_version(folder, rel)})


# --------------------------------------------------------------------------- app


class CommentBody(BaseModel):
    time: float
    point: queue.Point | None = None
    text: str
    aspect: str | None = None


class ExportBody(BaseModel):
    format: str = "mp4"


class RevealBody(BaseModel):
    name: str


class ApproveBody(BaseModel):
    include_pinned: bool = False


class EditBody(BaseModel):
    ops: list[dict]


class JumpBody(BaseModel):
    id: int


# how long an export may run before the editor gives up on it: a base plus time per second of film
EXPORT_TIMEOUT_BASE = 20 * 60.0
EXPORT_TIMEOUT_PER_SECOND = 30.0
EXPORT_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,120}\.(mp4|gif)")


def _utc() -> str:
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _error(status: int, message: str) -> JSONResponse:
    return JSONResponse({"error": message}, status_code=status)


def create_app(folder: Path) -> FastAPI:
    folder = Path(folder).resolve()
    hub = _Hub()
    voice_guard = threading.Lock()
    voice_state = {"busy": False, "again": False, "note": False}

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        hub.loop = asyncio.get_running_loop()
        stop = asyncio.Event()
        await _process_pending(folder)  # proposals written while the editor was closed
        try:  # first run makes the baseline; changes made while the editor was closed become a Claude step
            await asyncio.to_thread(history.sync, folder, functools.partial(queue.add_event, folder))
        except Exception:  # noqa: BLE001
            pass
        task = asyncio.create_task(_watch(folder, hub, stop))
        try:
            yield
        finally:
            hub.close()
            stop.set()
            try:
                await asyncio.wait_for(task, 3)
            except (asyncio.TimeoutError, asyncio.CancelledError, Exception):
                task.cancel()

    app = FastAPI(title="moshFilm", lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)
    app.state.hub = hub
    app.state.voice_state = voice_state
    app.state.folder = folder
    app.add_middleware(_LocalOnly)

    @app.exception_handler(FilmError)
    async def _film_error(_: Request, exc: FilmError):
        return _error(409, str(exc))

    @app.exception_handler(history.HistoryConflict)
    async def _history_conflict(_: Request, exc: history.HistoryConflict):
        return _error(409, str(exc))

    @app.exception_handler(history.HistoryError)
    async def _history_error(_: Request, exc: history.HistoryError):
        return _error(404, str(exc))

    @app.exception_handler(edits.EditError)
    async def _edit_error(_: Request, exc: edits.EditError):
        return _error(400, str(exc))

    def locate_at(the_film: Film, t: float):
        slots = timing.layout(the_film, narrate.voice_durations(folder, the_film))
        return timing.locate(slots, t)

    # ---- film

    @app.get("/api/film")
    def get_film():
        return {"film": load_film(folder).model_dump(), "folder": str(folder)}

    def history_note(text: str) -> None:
        """Something the person must not miss (redo cleared by Claude, history reset): chat note + live update."""
        queue.add_event(folder, text)
        hub.emit("history")

    def apply_ops(ops: list) -> Film:
        for op in ops:
            if isinstance(op, dict) and op.get("op") == "set_music" and op.get("file") \
                    and not _inside(folder, str(op["file"])):
                raise edits.EditError(f"music file {op['file']} is outside the film folder")
        with store.locked(folder):
            before = load_film(folder)
            result = history.apply_and_record(folder, ops, history_note)  # one request is one undo step
            notes = history.notes_for_ops(before, ops)
            if result.aspect != before.aspect:  # old pins stay on the shape they were made on
                queue.stamp_aspect(folder, before.aspect)
        for note in notes:
            queue.add_event(folder, note)
        if any(isinstance(o, dict) and o.get("op") in ("set_voice_text", "remove_voice") for o in ops):
            start_synthesis(note_overflow=True)  # the new words need their voice, then the fit check reruns
        return result

    @app.post("/api/film/edit")
    def edit_film(body: EditBody):
        return {"film": apply_ops(body.ops).model_dump()}

    # ---- history (undo / redo)

    def history_reply(**extra) -> dict:
        return {**history.info(folder), "film": load_film(folder).model_dump(), **extra}

    def shapes_of() -> tuple[str, str | None] | None:
        try:
            f = load_film(folder)
        except FilmError:
            return None
        return f.aspect, f.second_aspect

    def travelling(call):
        """Run undo, redo or jump; returns (step, note about the shapes if they changed)."""
        before = shapes_of()
        step = call()
        after = shapes_of()
        if step is None or before is None or after is None or before == after:
            return step, ""
        if before[0] != after[0]:
            queue.stamp_aspect(folder, before[0])
        second = f"second shape: {after[1]}" if after[1] else "no second shape"
        return step, (f" The film's shape is now {after[0]} ({second}). "
                      "Check every scene in each shape with `moshfilm check <folder> --layout` and fix what does not fit.")

    def moved(verb: str, step: dict | None, note: str = "") -> dict:
        if step is not None:
            queue.add_event(folder, f"The person {verb}: {step['label']}{note}")
            hub.emit("film")
            hub.emit("history")
            start_synthesis()  # cached lines return at once; an uncached one is made again
        return history_reply(changed=step is not None)

    @app.get("/api/history")
    def get_history():
        info = history.info(folder)  # read-only: a read must never record (or clear redo steps)
        if history.take_reset(folder):  # a damaged index was just reset: say so now, not at the next sync
            history_note(history.RESET_MESSAGE)
        return info

    @app.post("/api/history/undo")
    def undo():
        step, note = travelling(lambda: history.undo(folder, history_note))
        return moved("undid", step, note)

    @app.post("/api/history/redo")
    def redo():
        step, note = travelling(lambda: history.redo(folder, history_note))
        return moved("redid", step, note)

    @app.post("/api/history/jump")
    def jump(body: JumpBody):
        before = history.info(folder)
        step, note = travelling(lambda: history.jump(folder, body.id, history_note))
        ids = [s["id"] for s in before["steps"]]
        back = body.id in ids and ids.index(body.id) < before["cursor"]
        return moved("jumped back to" if back else "jumped forward to", step, note)

    # ---- proposals

    @app.get("/api/proposals")
    def list_proposals():
        return {"proposals": store.read_json(folder / "proposals.json", {}).get("proposals", [])}

    def _proposal_row(pid: str) -> dict | None:
        rows = store.read_json(folder / "proposals.json", {}).get("proposals", [])
        return next((r for r in rows if isinstance(r, dict) and r.get("id") == pid), None)

    def _proposal_failure(exc: proposals.ProposalError) -> JSONResponse:
        return _error(404 if "unknown proposal" in str(exc) else 400, str(exc))

    @app.post("/api/proposals/{pid}/approve")
    def approve_proposal(pid: str, body: ApproveBody):
        with store.locked(folder):
            # Settle pending proposals here, with events, so an invalid one is still reported to Claude.
            proposals.process_pending(folder, functools.partial(queue.add_event, folder))
            row = _proposal_row(pid)
            was_partial = bool(row and row.get("status") == "partial")
            try:
                done = proposals.approve(folder, pid, body.include_pinned)
            except proposals.ProposalError as exc:
                return _proposal_failure(exc)
            if was_partial:
                queue.add_event(folder, f"Proposal {pid} approved (including your pinned values)")
            elif row and row.get("needs_approval"):
                queue.add_event(folder, f"Scene list {pid} approved")
            else:
                queue.add_event(folder, f"Proposal {pid} approved (including your pinned values)")
        return done.model_dump()

    @app.post("/api/proposals/{pid}/reject")
    def reject_proposal(pid: str):
        with store.locked(folder):
            row = _proposal_row(pid)
            was_partial = bool(row and row.get("status") == "partial")
            try:
                done = proposals.reject(folder, pid)
            except proposals.ProposalError as exc:
                return _proposal_failure(exc)
            if was_partial:  # its unpinned changes already went in; only the held ones were declined
                queue.add_event(folder, f"Proposal {pid}: the person kept their pinned values; "
                                        "its other changes were applied")
            else:
                queue.add_event(folder, f"Proposal {pid} rejected")
        return done.model_dump()

    # ---- comments and chat

    @app.get("/api/queue")
    def get_queue():
        return queue.snapshot(folder).model_dump()

    @app.get("/api/activity")
    def get_activity():
        return activity.snapshot(folder)

    @app.post("/api/comments")
    def add_comment(body: CommentBody):
        if not body.text.strip():
            return _error(400, "comment text is empty")
        the_film = load_film(folder)
        aspect = body.aspect or the_film.aspect
        if aspect not in aspects.chosen(the_film):
            return _error(400, f"aspect {aspect} is not one of the film's shapes")
        found = locate_at(the_film, body.time)
        scene, scene_time = found if found else (None, None)
        item = queue.add_item(folder, "comment", body.text, time=body.time, point=body.point,
                              scene=scene, scene_time=scene_time, aspect=aspect)
        return item.model_dump()

    @app.post("/api/chat")
    def add_chat(text: str = Form(""), at: str = Form(""), file: UploadFile | None = File(None)):
        has_file = file is not None and bool(file.filename)
        if not text.strip() and not has_file:
            return _error(400, "message is empty")
        frame = None
        if at.strip():
            try:
                parsed = json.loads(at)
                t = float(parsed["time"])
                wanted = parsed.get("aspect")
            except (ValueError, KeyError, TypeError, AttributeError):
                return _error(400, "at must be JSON like {\"time\": 12.3}")
            if not math.isfinite(t) or t < 0:
                return _error(400, "at.time must be a number of seconds, 0 or more")
            the_film = load_film(folder)
            aspect = wanted  # None means the main shape
            if aspect is not None and aspect not in aspects.chosen(the_film):
                return _error(400, f"aspect {aspect} is not one of the film's shapes")
            found = locate_at(the_film, t)
            scene = found[0] if found else None
            title = next((s.title for s in the_film.scenes if s.id == scene), None)
            frame = queue.At(time=t, scene=scene, sceneTitle=title, aspect=aspect)
        attachment = _save_upload(folder, "sources", file) if has_file else None
        item = queue.add_item(folder, "chat", text, attachment=attachment, at=frame)
        return item.model_dump()

    # ---- export (the top bar's "Export movie")

    exports_dir = folder / "exports"
    export_guard = threading.Lock()
    export_state: dict = {"state": "idle", "format": None, "files": [], "warnings": [], "current": None,
                          "progress": None, "error": None, "started_at": None, "finished_at": None, "token": 0}

    def export_status() -> dict:
        with export_guard:
            return {k: json.loads(json.dumps(v)) for k, v in export_state.items() if k != "token"}

    @app.get("/api/export")
    def get_export():
        return export_status()

    @app.post("/api/export")
    def start_export(body: ExportBody):
        from . import export as exportlib
        from . import layout_check

        if body.format not in ("mp4", "gif"):
            return _error(400, "format must be mp4 or gif")
        with export_guard:
            if export_state["state"] == "running":
                return _error(409, "an export is already running")
            token = export_state["token"] + 1  # a result that arrives after a give-up is ignored
            export_state.update(state="running", format=body.format, files=[], warnings=[], current=None,
                                progress=None, error=None, started_at=_utc(), finished_at=None, token=token)
            tracker = ExportProgress(body.format)

        def render(result: dict) -> None:
            """The slow part, on its own thread so a hang can be given up on. Writes only into `result`."""
            try:
                try:  # warnings only, like the command line: a failed pre-check never stops the export
                    result["warnings"] = [f"{i.where}: {i.message}" for i in layout_check.check_layout(folder)
                                          if i.level == "warning"]
                except Exception as exc:  # noqa: BLE001
                    result["warnings"] = [f"layout check skipped: {exc}"]
                with export_guard:
                    if export_state["token"] == token:
                        export_state["warnings"] = result["warnings"]
                the_film = load_film(folder)
                out = exports_dir / f"{exportlib._slug(the_film.title)}.{body.format}"

                def on_shape(aspect: str) -> None:
                    with export_guard:
                        if export_state["token"] == token:
                            export_state["current"] = aspect

                def on_progress(event: dict) -> None:
                    with export_guard:
                        if export_state["token"] == token:
                            tracker.update(event)
                            export_state["progress"] = tracker.snapshot()

                # the shapes come back with the paths, so names and labels always agree
                paths = exportlib.export_aspects(folder, body.format, out=out, progress=on_shape,
                                                 on_progress=on_progress)
                result["files"] = [{"name": p.name, "aspect": a, "bytes": p.stat().st_size} for a, p in paths.items()]
            except BaseException as exc:  # ExportError, FilmError, anything: the UI shows the text
                result["error"] = str(exc) or type(exc).__name__

        def work() -> None:
            result: dict = {}
            inner = threading.Thread(target=render, args=(result,), name="moshfilm-export-render", daemon=True)
            try:
                inner.start()
                try:
                    length = timing.total_length(timing.layout(load_film(folder), {}))
                except Exception:  # noqa: BLE001
                    length = 0.0
                limit = EXPORT_TIMEOUT_BASE + EXPORT_TIMEOUT_PER_SECOND * length
                inner.join(limit)
                with export_guard:
                    if export_state["token"] != token:
                        return
                    if inner.is_alive():
                        minutes = max(1, round(limit / 60))
                        export_state.update(state="error", current=None, progress=None, finished_at=_utc(),
                                            error=f"The export took longer than {minutes} minutes and was given up on "
                                                  "(ffmpeg or Chromium may be stuck). Try again.")
                    elif "error" in result:
                        export_state.update(state="error", error=result["error"], current=None, progress=None,
                                            finished_at=_utc())
                    else:
                        export_state.update(state="done", files=result.get("files", []), current=None,
                                            progress=None, finished_at=_utc())
            except BaseException as exc:  # the worker itself failed: never stay at "running"
                with export_guard:
                    if export_state["token"] == token:
                        export_state.update(state="error", error=str(exc) or type(exc).__name__, current=None,
                                            progress=None, finished_at=_utc())

        try:
            threading.Thread(target=work, name="moshfilm-export", daemon=True).start()
        except BaseException as exc:  # e.g. the system cannot start another thread
            with export_guard:
                export_state.update(state="error", error=f"could not start the export: {exc}", current=None,
                                    finished_at=_utc())
            return _error(500, f"could not start the export: {exc}")
        return export_status()

    def export_file(name: str) -> Path | JSONResponse:
        if not EXPORT_NAME.fullmatch(name) or ".." in name:
            return _error(400, "not an export file name")
        target = (exports_dir / name).resolve()
        if target.parent != exports_dir.resolve() or not target.is_file():
            return _error(404, "no such export file")
        return target

    @app.get("/api/export/file/{name}")
    def download_export(name: str):
        target = export_file(name)
        if isinstance(target, JSONResponse):
            return target
        return FileResponse(target, filename=target.name,
                            media_type="video/mp4" if target.suffix == ".mp4" else "image/gif")

    @app.post("/api/export/reveal")
    def reveal_export(body: RevealBody):
        target = export_file(body.name)
        if isinstance(target, JSONResponse):
            return target
        if sys.platform != "darwin":
            return _error(501, "Show in folder is only available on macOS")
        subprocess.Popen(["open", "-R", str(target)])
        return {"ok": True}

    # ---- voice

    @app.get("/api/voice")
    def get_voice():
        the_film = load_film(folder)
        out = {}
        for scene_id, duration in narrate.voice_durations(folder, the_film).items():
            scene = next(s for s in the_film.scenes if s.id == scene_id)
            key = narrate.voice_key(scene.voice.text.strip(), the_film.voice.name, the_film.voice.rate)
            out[scene_id] = {"url": f"/api/voice/{key}.mp3", "duration": duration}
        return out

    @app.get("/api/voice/{key}.mp3")
    def get_voice_file(key: str):
        path = narrate.voice_file(folder, key) if _KEY.fullmatch(key) else None
        if path is None or not path.is_file():
            return _error(404, "no such voice file")
        return FileResponse(path, media_type="audio/mpeg")

    def start_synthesis(note_overflow: bool = False) -> dict:
        """Make every missing voice line in a worker thread. A request that arrives while a run is
        busy makes the run go round once more, so a line edited mid-run is not left without audio.
        A request for the overflow note is remembered across passes and answered once, from the last."""
        with voice_guard:
            voice_state["note"] = voice_state["note"] or note_overflow
            if voice_state["busy"]:
                voice_state["again"] = True
                return {"started": False, "running": True}
            voice_state["busy"] = True

        def work() -> None:
            try:
                while True:
                    late: list[str] = []
                    try:
                        the_film = load_film(folder)
                        durations = narrate.ensure_voice(
                            folder, the_film,
                            on_progress=lambda m: hub.emit("voice", {"state": "progress", "message": m}))
                        # the fit check: which scenes are too short for their (new) voice line
                        late = [s.id for s in timing.layout(the_film, durations) if s.overflow]
                        hub.emit("voice", {"state": "done", "overflow": late})
                    except Exception as exc:  # NarrationError, network, ffprobe: the UI shows the text
                        hub.emit("voice", {"state": "error", "message": str(exc)})
                    with voice_guard:
                        if voice_state["again"]:
                            voice_state["again"] = False
                            continue
                        note, voice_state["note"] = voice_state["note"], False
                        voice_state["busy"] = False
                    if late and note:  # the final pass, on the film as it was loaded for that pass
                        queue.add_event(folder, "After the person's text edit, the voice does not fit scene "
                                        + ", ".join(late) + ": " + timing.OVERFLOW_COPY
                                        + ". Their pinned length stays; do not change it.")
                    return
            except BaseException:
                with voice_guard:
                    voice_state["busy"] = False
                raise

        threading.Thread(target=work, name="moshfilm-voice", daemon=True).start()
        return {"started": True, "running": True}

    @app.post("/api/voice/synthesize")
    def synthesize():
        load_film(folder)  # a broken film answers 409 here, as before
        return start_synthesis()

    # ---- generated sound (music bed + sound effects), rendered on demand into .moshfilm/sound

    _SOUND_NAME = re.compile(r"(bed|sfx)-[0-9a-f]{16}")

    @app.get("/api/sound")
    def get_sound():
        the_film = load_film(folder)
        total = soundcache.film_total(folder, the_film)
        music = None
        if the_film.music is not None and the_film.music.bed is not None and total > 0:
            try:
                path = soundcache.ensure_bed(folder, the_film, total, only_if_current=True)
            except soundcache.StaleBed:
                return _error(409, "the film changed while its music was being made")
            music = {"url": f"/api/sound/{path.name}", "duration": total}
        clips = {}
        for clip in the_film.sfx:
            path = soundcache.ensure_sfx(folder, clip)
            clips[clip.id] = {"url": f"/api/sound/{path.name}",
                              "duration": round(clip.seconds, 3)}
        return {"music": music, "sfx": clips}

    @app.get("/api/sound/presets")
    def get_sound_presets():
        return {
            "sfx": [{"name": n, "label": p.label, "description": p.description, "duration": p.base_seconds}
                    for n, p in soundsfx.PRESETS.items()],
            "moods": [{"name": n, "label": m.label, "tempo": m.tempo, "scale": m.scale, "palette": m.palette}
                      for n, m in soundmusic.MOODS.items()],
            "palettes": list(soundmusic.PALETTES),
            "keys": list(soundmusic.KEYS),
            "scales": list(soundmusic.SCALES),
            "tempo": list(soundmusic.TEMPO_RANGE),
        }

    @app.get("/api/sound/preset/{name}.wav")
    def get_sound_preset(name: str):
        if name not in soundsfx.PRESETS:
            return _error(404, "no such sound preset")
        path = soundcache.ensure_sfx(folder, SfxClip(id="preset", scene="-", preset=name))
        return FileResponse(path, media_type="audio/wav")

    @app.get("/api/sound/{name}.wav")
    def get_sound_file(name: str):
        path = soundcache.sound_dir(folder) / f"{name}.wav" if _SOUND_NAME.fullmatch(name) else None
        if path is None or not path.is_file():
            return _error(404, "no such sound file")
        return FileResponse(path, media_type="audio/wav")

    # ---- music

    @app.post("/api/music")
    def upload_music(file: UploadFile = File(...)):
        rel = _save_upload(folder, "music", file)
        with store.locked(folder):
            current = load_film(folder).music
            volume = current.volume if current else 0.6
            result = apply_ops([{"op": "set_music", "file": rel, "volume": volume}])
        return {"film": result.model_dump()}

    # ---- events and files

    @app.get("/api/events")
    async def events():
        q = hub.subscribe()

        async def stream():
            try:
                yield ": connected\n\n"
                while not hub.closed:
                    try:
                        item = await asyncio.wait_for(q.get(), QUEUE_TICK)
                    except asyncio.TimeoutError:
                        item = ("queue", {})
                    if item is None:
                        break
                    yield _sse(*item)
            finally:
                hub.unsubscribe(q)

        return StreamingResponse(stream(), media_type="text/event-stream",
                                 headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})

    @app.get("/film/{path:path}")
    def film_file(path: str):
        target = resolve_film_path(folder, path)
        if target is None:
            return _error(404, "not found")
        headers = {**NO_CACHE, "X-Content-Type-Options": "nosniff"}
        if (Path(folder).resolve() / "sources") in target.parents:
            # Uploads are the person's documents, not pages: never let them run as part of this origin.
            return FileResponse(target, headers=headers, filename=target.name,
                                content_disposition_type="attachment")
        return FileResponse(target, headers=headers)

    @app.get("/")
    def index():
        return FileResponse(STATIC / "index.html", headers=NO_CACHE)

    @app.get("/render.html")
    def render_page():
        page = STATIC / "render.html"
        if not page.is_file():
            return _error(404, "not found")
        return FileResponse(page, headers=NO_CACHE)

    if (STATIC / "assets").is_dir():  # the built UI (Task 7); the placeholder page has none
        app.mount("/assets", StaticFiles(directory=STATIC / "assets"), name="assets")
    return app


# --------------------------------------------------------------------------- running


def _bind(port: int, tries: int = 1) -> socket.socket:
    last: OSError | None = None
    for p in range(port, port + tries) if port else [0]:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            sock.bind((HOST, p))
        except OSError as exc:
            sock.close()
            last = exc
            continue
        return sock
    raise OSError(f"no free port in {port}-{port + tries - 1}: {last}")


def _server(folder: Path) -> uvicorn.Server:
    config = uvicorn.Config(create_app(folder), host=HOST, log_level="warning",
                            timeout_graceful_shutdown=2, ws="none")
    return uvicorn.Server(config)


def serve(folder: Path, port: int = DEFAULT_PORT, open_browser: bool = True) -> None:
    sock = _bind(port, PORT_TRIES)
    url = f"http://{HOST}:{sock.getsockname()[1]}"
    print(f"moshFilm: {url}", flush=True)
    if open_browser:
        threading.Timer(0.5, webbrowser.open, args=(url,)).start()
    _server(Path(folder)).run(sockets=[sock])


def serve_in_thread(folder: Path, port: int = 0) -> tuple[str, Callable[[], None]]:
    """Start the server in a background thread (port 0 = any free port); returns (base URL, stop)."""
    sock = _bind(port)
    base = f"http://{HOST}:{sock.getsockname()[1]}"
    server = _server(Path(folder))
    thread = threading.Thread(target=lambda: asyncio.run(server.serve(sockets=[sock])),
                              name="moshfilm-server", daemon=True)
    thread.start()
    deadline = time.time() + 10
    while not server.started and thread.is_alive() and time.time() < deadline:
        time.sleep(0.02)
    if not server.started:
        sock.close()
        raise RuntimeError("moshFilm server did not start")

    def stop() -> None:
        hub: _Hub = server.config.app.state.hub
        if hub.loop is not None:
            hub.loop.call_soon_threadsafe(hub.close)
        server.should_exit = True
        thread.join(10)
        sock.close()

    return base, stop
