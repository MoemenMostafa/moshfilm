"""Command line: `moshfilm <command>`. Later tasks register more subcommands in build_parser."""
from __future__ import annotations

import argparse
import json
import shutil
import signal
import sys
import threading
from pathlib import Path

from . import __version__, activity, aspects, film, hooks, narrate, proposals, queue, timing


def _cmd_new(args: argparse.Namespace) -> int:
    folder = Path(args.folder)
    try:
        film.new_film(folder, args.title or folder.resolve().name)
    except FileExistsError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    print(f"created {folder}")
    return _install_hooks_unless(args, folder)


def _install_hooks_unless(args: argparse.Namespace, folder: Path) -> int:
    if args.no_hooks:
        return 0
    try:
        hooks.install(folder)
    except (hooks.HooksError, OSError) as exc:
        print(f"warning: hooks not installed: {exc}", file=sys.stderr)
    return 0


def _cmd_hooks(args: argparse.Namespace) -> int:
    folder = Path(args.folder)
    try:
        if args.uninstall:
            changed = hooks.uninstall(folder)
            print("hooks removed" if changed else "no moshfilm hooks found")
        else:
            changed = hooks.install(folder)
            print("hooks installed; restart Claude Code in this folder to pick them up" if changed
                  else "hooks already installed")
    except (hooks.HooksError, OSError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    return 0


def _cmd_check(args: argparse.Namespace) -> int:
    folder = Path(args.folder)
    issues = film.check_film(folder)
    if (args.layout or args.aspect) and not any(i.where == "film.json" for i in issues):
        from . import layout_check

        try:
            shapes = aspects.chosen(film.load_film(folder))
            shapes += [a for a in dict.fromkeys(args.aspect or []) if a not in shapes]
            issues += layout_check.check_layout(folder, shapes)
        except layout_check.LayoutCheckUnavailable as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 2
    if not any(i.where == "film.json" for i in issues):
        from .sound import check as soundcheck

        issues += soundcheck.sfx_issues(folder, film.load_film(folder))
    for i in issues:
        print(f"{i.level} {i.where}: {i.message}")
    return 1 if any(i.level == "error" for i in issues) else 0


def _cmd_sounds(args: argparse.Namespace) -> int:
    from .sound import music, sfx

    print("sound effects (add_sfx preset):")
    for name, p in sfx.PRESETS.items():
        print(f"  {name:<11} {p.base_seconds:g} s  {p.description}")
    print("music moods (set_music bed.mood; tempo, key, scale and palette can be changed):")
    for name, m in music.MOODS.items():
        print(f"  {name:<10} {m.tempo} bpm, {m.scale}, {m.palette}")
    print(f"palettes: {', '.join(music.PALETTES)}; keys: {', '.join(music.KEYS)}; "
          f"tempo {music.TEMPO_RANGE[0]}-{music.TEMPO_RANGE[1]}")
    return 0


def _cmd_propose(args: argparse.Namespace) -> int:
    try:
        text = sys.stdin.read() if args.file == "-" else Path(args.file).read_text(encoding="utf-8")
        data = json.loads(text)
        proposal = proposals.add_proposal(Path(args.folder), data)
    except (OSError, json.JSONDecodeError, proposals.ProposalError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    print(proposal.id)
    return 0


def _item_line(item: queue.QueueItem, the_film: film.Film | None = None) -> str:
    out: dict = {"id": item.id, "kind": item.kind, "text": item.text}
    if item.kind == "comment":
        out["time"] = None if item.time is None else round(item.time, 1)
        out["scene"] = item.scene
        out["scene_time"] = None if item.scene_time is None else round(item.scene_time, 1)
        out["point"] = None if item.point is None else {"x": round(item.point.x, 2), "y": round(item.point.y, 2)}
        shape = item.aspect or (the_film.aspect if the_film else None)
        if shape:  # `point` is a fraction of this shape's frame; an old comment was made on the main shape
            out["aspect"] = shape
            if the_film:  # still worked out from the ratio when the shape has since been removed
                w, h = aspects.canvas_size(the_film, shape)
                out["frame"] = {"width": w, "height": h}
    if item.attachment:
        out["attachment"] = item.attachment
    if item.kind == "chat" and item.at is not None:
        out["at"] = {"time": round(item.at.time, 1), "scene": item.at.scene, "sceneTitle": item.at.sceneTitle}
        if item.at.aspect:
            out["at"]["aspect"] = item.at.aspect
    return json.dumps(out, ensure_ascii=False)


def _cmd_watch(args: argparse.Namespace) -> int:
    folder = Path(args.folder)
    stop = threading.Event()
    for sig in (signal.SIGINT, signal.SIGTERM):
        signal.signal(sig, lambda *_: stop.set())
    try:
        while not stop.is_set():
            queue.heartbeat(folder)
            batch = queue.take_queued(folder)
            try:
                the_film = film.load_film(folder) if batch else None
            except film.FilmError:
                the_film = None
            for item in batch:
                print(_item_line(item, the_film), flush=True)
            if batch and args.once:
                break
            stop.wait(queue.HEARTBEAT_INTERVAL)
    finally:
        queue.heartbeat(folder, alive=False)
    return 0


def _cmd_voice(args: argparse.Namespace) -> int:
    folder = Path(args.folder)
    try:
        the_film = film.load_film(folder)
        durations = narrate.ensure_voice(
            folder, the_film, on_progress=lambda m: print(m, file=sys.stderr))
    except (film.FilmError, narrate.NarrationError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    bad = False
    for scene, slot in zip(the_film.scenes, timing.layout(the_film, durations)):
        d = durations.get(scene.id)
        if d is None:
            print(f"{scene.id}  no voice line")
            continue
        if slot.overflow:
            note, bad = timing.OVERFLOW_COPY, True
        elif slot.voice_speed > 1:
            note = f"sped up {slot.voice_speed:.2f}x"
        else:
            note = "ok"
        print(f"{scene.id}  {d:.1f}s / {slot.length:.1f}s  {note}")
    return 1 if bad else 0


def _cmd_open(args: argparse.Namespace) -> int:
    from . import server

    folder = Path(args.folder)
    if not (folder / "film.json").exists():
        film.new_film(folder, folder.resolve().name)
        print(f"created {folder}")
    try:
        server.serve(folder, port=args.port, open_browser=not args.no_browser)
    except OSError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        pass
    return 0


SAMPLE_DIR = Path(__file__).resolve().parent / "samples" / "binary-search"


def _cmd_sample(args: argparse.Namespace) -> int:
    if not (SAMPLE_DIR / "film.json").is_file():
        print("error: sample not bundled", file=sys.stderr)
        return 1
    folder = Path(args.folder)
    if folder.exists() and not folder.is_dir():
        print(f"error: {folder} already exists and is not a folder", file=sys.stderr)
        return 1
    if folder.exists() and any(folder.iterdir()):
        print(f"error: {folder} already exists and is not empty", file=sys.stderr)
        return 1
    shutil.copytree(SAMPLE_DIR, folder, dirs_exist_ok=True)
    print(f"created {folder}")
    return _install_hooks_unless(args, folder)


def _unknown_item(item_id: str) -> int:
    print(f"no item {item_id}", file=sys.stderr)
    return 2


def _cmd_reply(args: argparse.Namespace) -> int:
    try:
        queue.reply(Path(args.folder), args.item_id, args.text, resolve=not args.keep_open)
    except KeyError:
        return _unknown_item(args.item_id)
    return 0


def _cmd_say(args: argparse.Namespace) -> int:
    queue.reply(Path(args.folder), None, args.text)
    return 0


def _cmd_status(args: argparse.Namespace) -> int:
    queue.set_status(Path(args.folder), None if args.clear else args.text)
    return 0


def _cmd_resolve(args: argparse.Namespace) -> int:
    try:
        queue.resolve(Path(args.folder), args.item_id)
    except KeyError:
        return _unknown_item(args.item_id)
    return 0


def _cmd_activity(args: argparse.Namespace) -> int:
    """Claude Code hook: JSON on stdin in, nothing out. Never fails, never blocks, no network."""
    try:
        activity.handle_hook(json.loads(sys.stdin.read()))
    except Exception:  # a hook must never get in Claude's way
        pass
    return 0


def _cmd_plan(args: argparse.Namespace) -> int:
    folder = Path(args.folder)
    if not (folder / "film.json").is_file():
        print(f"error: {folder} is not a film folder (no film.json)", file=sys.stderr)
        return 1
    if args.set is not None:
        activity.set_plan(folder, args.set)
    elif args.done is not None:
        try:
            activity.plan_done(folder, args.done)
        except IndexError:
            print(f"no plan step {args.done}", file=sys.stderr)
            return 2
    else:
        activity.clear_plan(folder)
    return 0


class _ProgressLine:
    """The export's progress on stderr: one line rewritten with \r on a terminal, plain lines (every 10%
    and at each stage change) otherwise, e.g. `16:9  frames 412/1380  30%`."""

    def __init__(self, stream=None) -> None:
        self.stream = stream or sys.stderr
        self.tty = bool(getattr(self.stream, "isatty", lambda: False)())
        self.shown = ""
        self.key: tuple | None = None

    def __call__(self, e: dict) -> None:
        total = e["total"]
        pct = int(100 * e["done"] / total) if total else 0
        if e["stage"] == "audio":
            text, key = "building audio" + ("" if pct >= 100 else "..."), ("audio", pct >= 100)
        elif e["stage"] == "frames":
            text = f"{e['aspect']}  frames {int(e['done'])}/{int(total)}  {pct}%"
            key = ("frames", e["aspect"], pct // 10)
        else:
            text, key = f"{e['aspect']}  encode  {pct}%", ("encode", e["aspect"], pct // 10)
        if self.tty:
            self.stream.write("\r" + text.ljust(len(self.shown)))
            self.shown = text
        elif key != self.key:
            self.stream.write(text + "\n")
        self.key = key
        self.stream.flush()

    def finish(self) -> None:
        if self.tty and self.shown:
            self.stream.write("\n")
            self.stream.flush()


def _cmd_export(args: argparse.Namespace) -> int:
    from . import export, layout_check

    folder = Path(args.folder)
    try:  # warn first, never refuse: the person decides whether the overflow matters
        for i in layout_check.check_layout(folder):
            if i.level == "warning":
                print(f"warning: {i.where}: {i.message}", file=sys.stderr)
    except Exception as exc:  # noqa: BLE001 - the pre-check must never stop an export that would work
        print(f"layout check skipped: {exc}", file=sys.stderr)
    line = _ProgressLine()
    try:
        outs = export.export_aspects(
            folder, args.format, out=Path(args.output) if args.output else None,
            fps=args.fps, width=args.width, voice=not args.no_voice, on_progress=line)
    except export.ExportError as exc:
        line.finish()
        print(f"error: {exc}", file=sys.stderr)
        return 1
    line.finish()
    for out in outs.values():
        print(out)
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="moshfilm")
    parser.add_argument("--version", action="version", version=f"moshfilm {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("new", help="create a film folder")
    p.add_argument("folder")
    p.add_argument("--title")
    p.add_argument("--no-hooks", action="store_true", help="do not install the Claude Code activity hooks")
    p.set_defaults(func=_cmd_new)

    p = sub.add_parser("open", help="open the film in the browser editor (starts the local server)")
    p.add_argument("folder")
    p.add_argument("--port", type=int, default=5717)
    p.add_argument("--no-browser", action="store_true")
    p.set_defaults(func=_cmd_open)

    p = sub.add_parser("sample", help="copy the bundled sample film (Binary search) into a new folder")
    p.add_argument("folder")
    p.add_argument("--no-hooks", action="store_true", help="do not install the Claude Code activity hooks")
    p.set_defaults(func=_cmd_sample)

    p = sub.add_parser("check", help="validate a film folder")
    p.add_argument("folder")
    p.add_argument("--layout", action="store_true",
                   help="also draw every ready scene in each chosen shape and warn about overflow (starts Chromium)")
    p.add_argument("--aspect", action="append", choices=aspects.ALL, metavar="ASPECT",
                   help="also check this shape (16:9, 9:16, 1:1, 4:5); repeatable; implies --layout")
    p.set_defaults(func=_cmd_check)

    p = sub.add_parser("sounds", help="list the sound-effect presets and music moods Claude can use")
    p.set_defaults(func=_cmd_sounds)

    p = sub.add_parser("voice", help="make the narration for every scene and report how it fits")
    p.add_argument("folder")
    p.set_defaults(func=_cmd_voice)

    p = sub.add_parser("export", help="render the film to MP4 or GIF (needs ffmpeg and Chromium)")
    p.add_argument("folder")
    p.add_argument("--format", choices=["mp4", "gif"], default="mp4")
    p.add_argument("-o", "--output")
    p.add_argument("--fps", type=int)
    p.add_argument("--width", type=int)
    p.add_argument("--no-voice", action="store_true", help="mute the narration (scene lengths stay as in the preview)")
    p.set_defaults(func=_cmd_export)

    p = sub.add_parser("propose", help="add a proposal from a JSON file or - for stdin")
    p.add_argument("folder")
    p.add_argument("file")
    p.set_defaults(func=_cmd_propose)

    p = sub.add_parser("watch", help="print new comments/chat as JSON lines; keeps the panel 'connected'")
    p.add_argument("folder")
    p.add_argument("--once", action="store_true", help="exit after the first non-empty batch")
    p.set_defaults(func=_cmd_watch)

    p = sub.add_parser("reply", help="answer a comment or chat item (resolves it unless --keep-open)")
    p.add_argument("folder")
    p.add_argument("item_id")
    p.add_argument("text")
    p.add_argument("--keep-open", action="store_true")
    p.set_defaults(func=_cmd_reply)

    p = sub.add_parser("say", help="send a chat message not tied to an item")
    p.add_argument("folder")
    p.add_argument("text")
    p.set_defaults(func=_cmd_say)

    p = sub.add_parser("status", help="set or clear Claude's status line")
    p.add_argument("folder")
    p.add_argument("text", nargs="?")
    p.add_argument("--clear", action="store_true")
    p.set_defaults(func=_cmd_status)

    p = sub.add_parser("resolve", help="mark an item resolved without a reply")
    p.add_argument("folder")
    p.add_argument("item_id")
    p.set_defaults(func=_cmd_resolve)

    p = sub.add_parser("hooks", help="install or remove the Claude Code hooks that feed the working card")
    p.add_argument("action", choices=["install"], help="install (add --uninstall to remove)")
    p.add_argument("folder")
    p.add_argument("--uninstall", action="store_true")
    p.set_defaults(func=_cmd_hooks)

    p = sub.add_parser("activity", help="Claude Code hook: read a hook payload (JSON on stdin) and record a step")
    p.set_defaults(func=_cmd_activity)

    p = sub.add_parser("plan", help="set, tick off or clear the plan checklist shown in the panel")
    p.add_argument("folder")
    group = p.add_mutually_exclusive_group(required=True)
    group.add_argument("--set", nargs="+", metavar="STEP", help="replace the plan with these steps")
    group.add_argument("--done", type=int, metavar="N", help="tick step N (1-based)")
    group.add_argument("--clear", action="store_true", help="remove the plan")
    p.set_defaults(func=_cmd_plan)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command == "status" and not args.clear and args.text is None:
        parser.error("status needs <text> or --clear")
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
