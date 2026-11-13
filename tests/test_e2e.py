"""End-to-end: the whole Claude loop without a browser, against a real server thread."""
import json
import shutil
import time
import urllib.parse
import urllib.request
from pathlib import Path

import pytest

from moshfilm import cli, film, server

pytestmark = pytest.mark.slow

SCENE_JS = """export default {
  setup(root) { root.style.background = "#336699"; },
  render() {},
};
"""


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


def _get(base: str, path: str):
    with urllib.request.urlopen(base + path, timeout=10) as r:
        return json.load(r)


def _post(base: str, path: str, body: dict | None = None, form: dict | None = None):
    if form is not None:
        data, headers = urllib.parse.urlencode(form).encode(), {}
    else:
        data, headers = json.dumps(body or {}).encode(), {"Content-Type": "application/json"}
    req = urllib.request.Request(base + path, data=data, headers=headers, method="POST")
    with urllib.request.urlopen(req, timeout=10) as r:
        return json.load(r)


def _wait(check, what: str, seconds: float = 8.0):
    deadline = time.time() + seconds
    while time.time() < deadline:
        value = check()
        if value:
            return value
        time.sleep(0.1)
    raise AssertionError(f"timed out waiting for {what}")


def _watch_once(folder: Path, capsys) -> list[dict]:
    capsys.readouterr()
    assert cli.main(["watch", str(folder), "--once"]) == 0
    return [json.loads(line) for line in capsys.readouterr().out.splitlines() if line.strip()]


def _propose(folder: Path, data: dict, capsys) -> str:
    src = folder / "_proposal.json"
    src.write_text(json.dumps(data))
    capsys.readouterr()
    assert cli.main(["propose", str(folder), str(src)]) == 0
    return capsys.readouterr().out.strip()


def _proposal(base: str, pid: str) -> dict:
    return next(p for p in _get(base, "/api/proposals")["proposals"] if p["id"] == pid)


def test_claude_loop_without_ui(tmp_path, capsys):
    folder = tmp_path / "loop"
    film.new_film(folder, "Loop")
    base, stop = server.serve_in_thread(folder)
    try:
        # chat from the browser side reaches Claude's watcher
        chat = _post(base, "/api/chat", form={"text": "Make a film about lockers"})
        lines = _watch_once(folder, capsys)
        assert [(l["kind"], l["text"]) for l in lines] == [("chat", "Make a film about lockers")]

        # Claude proposes a scene list that needs approval; it waits until the user approves
        pid = _propose(folder, {
            "summary": "one scene", "needs_approval": True,
            "changes": [{"op": "add_scene", "scene": {"id": "s1", "title": "Lockers", "length": 3}}],
        }, capsys)
        _wait(lambda: _proposal(base, pid)["status"] == "awaiting_approval", "awaiting approval")
        assert film.load_film(folder).scenes == []
        _post(base, f"/api/proposals/{pid}/approve", {})
        lines = _watch_once(folder, capsys)
        assert [l["kind"] for l in lines] == ["event"] and "approved" in lines[0]["text"]
        assert [s.id for s in film.load_film(folder).scenes] == ["s1"]

        # Claude writes the scene file and marks it ready, then answers the chat item
        (folder / "scenes").mkdir(exist_ok=True)
        (folder / "scenes" / "s1.js").write_text(SCENE_JS)
        ready = _propose(folder, {"changes": [
            {"op": "set_scene", "id": "s1", "file": "scenes/s1.js", "status": "ready"}]}, capsys)
        _wait(lambda: _proposal(base, ready)["status"] == "applied", "ready proposal applied")
        assert cli.main(["reply", str(folder), chat["id"], "Scene s1 is ready."]) == 0
        snap = _get(base, "/api/queue")
        item = next(i for i in snap["items"] if i["id"] == chat["id"])
        assert item["state"] == "resolved"
        assert [m["text"] for m in snap["messages"]] == ["Scene s1 is ready."]
        scene = film.load_film(folder).scenes[0]
        assert scene.status == "ready" and scene.file == "scenes/s1.js"
    finally:
        stop()

    from moshfilm import export
    out = export.export_film(folder, "gif", voice=False)
    assert out.exists() and out.stat().st_size > 0 and out.read_bytes()[:3] == b"GIF"
