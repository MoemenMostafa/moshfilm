import json
import re
import time
import urllib.request
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from moshfilm import film as filmmod
from moshfilm import narrate, queue, server
from moshfilm.film import Scene, VoiceLine

BASE = "http://127.0.0.1:5717"


@pytest.fixture
def folder(tmp_path: Path) -> Path:
    filmmod.new_film(tmp_path, "t")
    f = filmmod.load_film(tmp_path)
    f.scenes = [
        Scene(id="s1", title="one", file="scenes/s1.js", length=5, pinned=True, status="ready",
              voice=VoiceLine(text="hello there", offset=0.3)),
        Scene(id="s2", title="two", file="scenes/s2.js", length=3, pinned=True, status="ready"),
    ]
    filmmod.save_film(tmp_path, f)
    (tmp_path / "scenes").mkdir(exist_ok=True)
    (tmp_path / "scenes" / "s1.js").write_text("export default {}\n")
    return tmp_path


@pytest.fixture
def client(folder: Path):
    return TestClient(server.create_app(folder), base_url=BASE)


def test_get_film(client, folder):
    r = client.get("/api/film")
    assert r.status_code == 200
    body = r.json()
    assert body["film"]["title"] == "t" and body["folder"] == str(folder.resolve())


def test_broken_film_json_returns_409(client, folder):
    (folder / "film.json").write_text("{ not json")
    r = client.get("/api/film")
    assert r.status_code == 409
    assert "invalid JSON" in r.json()["error"]
    assert client.post("/api/film/edit", json={"ops": []}).status_code == 409


def test_edit_sets_pinned(client, folder):
    r = client.post("/api/film/edit", json={"ops": [{"op": "set_length", "scene": "s2", "length": 4.5}]})
    assert r.status_code == 200
    s2 = r.json()["film"]["scenes"][1]
    assert s2["length"] == 4.5 and s2["pinned"] is True
    assert filmmod.load_film(folder).scenes[1].length == 4.5


def test_edit_bad_length_400(client):
    r = client.post("/api/film/edit", json={"ops": [{"op": "set_length", "scene": "s1", "length": 9999}]})
    assert r.status_code == 400 and "outside" in r.json()["error"]
    r = client.post("/api/film/edit", json={"ops": [{"op": "nonsense"}]})
    assert r.status_code == 400


def test_edit_music_outside_folder_400(client):
    r = client.post("/api/film/edit", json={"ops": [{"op": "set_music", "file": "../../etc/passwd"}]})
    assert r.status_code == 400


def test_comment_gets_scene_and_scene_time(client):
    r = client.post("/api/comments", json={"time": 6.0, "point": {"x": 0.5, "y": 0.25}, "text": "bigger"})
    assert r.status_code == 200
    item = r.json()
    assert (item["scene"], item["scene_time"], item["time"], item["kind"]) == ("s2", 1.0, 6.0, "comment")
    snap = client.get("/api/queue").json()
    assert snap["items"][0]["id"] == item["id"] and snap["connected"] is False


def test_comment_at_boundary_and_after_end(client):
    a = client.post("/api/comments", json={"time": 5.0, "text": "edge"}).json()
    b = client.post("/api/comments", json={"time": 99.0, "text": "late"}).json()
    assert (a["scene"], a["scene_time"]) == ("s2", 0.0)
    assert (b["scene"], b["scene_time"]) == ("s2", 3.0)


def test_chat_with_attachment_saved_in_sources(client, folder):
    r = client.post("/api/chat", data={"text": "use this"},
                    files={"file": ("../my pic?.png", b"PNGDATA", "image/png")})
    assert r.status_code == 200
    item = r.json()
    assert item["kind"] == "chat" and item["text"] == "use this"
    assert item["attachment"] == "sources/my_pic_.png"
    assert (folder / item["attachment"]).read_bytes() == b"PNGDATA"
    again = client.post("/api/chat", data={"text": "x"}, files={"file": ("my pic?.png", b"2")}).json()
    assert again["attachment"] != item["attachment"]
    assert (folder / item["attachment"]).read_bytes() == b"PNGDATA"


def test_chat_text_only(client):
    item = client.post("/api/chat", data={"text": "hi"}).json()
    assert item["attachment"] is None
    assert client.post("/api/chat", data={"text": ""}).status_code == 400


def test_music_upload_sets_music(client, folder):
    r = client.post("/api/music", files={"file": ("bed.mp3", b"ID3", "audio/mpeg")})
    assert r.status_code == 200
    assert r.json()["film"]["music"] == {"file": "music/bed.mp3", "bed": None, "volume": 0.6, "pinned": True}
    assert (folder / "music" / "bed.mp3").read_bytes() == b"ID3"


def _proposal(folder: Path, data: list[dict]) -> None:
    (folder / "proposals.json").write_text(json.dumps({"proposals": data}))


def _events(folder: Path) -> list[str]:
    return [i.text for i in queue.snapshot(folder).items if i.kind == "event"]


def test_approve_adds_event_item(client, folder):
    from moshfilm import proposals
    pid = proposals.add_proposal(folder, {"summary": "new list", "needs_approval": True, "changes": [
        {"op": "add_scene", "scene": {"id": "s3", "title": "three", "length": 3}, "after": None}]}).id
    assert client.get("/api/proposals").json()["proposals"][0]["id"] == pid
    r = client.post(f"/api/proposals/{pid}/approve", json={"include_pinned": False})
    assert r.status_code == 200, r.text
    assert [s.id for s in filmmod.load_film(folder).scenes][-1] == "s3"
    assert _events(folder) == [f"Scene list {pid} approved"]


def test_approve_pinned_values_event_wording(client, folder):
    from moshfilm import proposals
    pid = proposals.add_proposal(folder, {"summary": "shorter", "changes": [
        {"op": "set_scene", "id": "s1", "length": 2}]}).id
    proposals.process_pending(folder)
    r = client.post(f"/api/proposals/{pid}/approve", json={"include_pinned": True})
    assert r.status_code == 200, r.text
    assert _events(folder) == [f"Proposal {pid} approved (including your pinned values)"]


def test_approve_reports_other_invalid_proposals(client, folder):
    from moshfilm import proposals
    good = proposals.add_proposal(folder, {"summary": "g", "needs_approval": True, "changes": [
        {"op": "add_scene", "scene": {"id": "s3", "title": "three", "length": 3}, "after": None}]}).id
    raw = json.loads((folder / "proposals.json").read_text())
    raw["proposals"].append({"id": "p9", "created": "x", "status": "pending", "changes": [{"op": "bogus"}]})
    (folder / "proposals.json").write_text(json.dumps(raw))
    assert client.post(f"/api/proposals/{good}/approve", json={"include_pinned": False}).status_code == 200
    events = _events(folder)
    assert any(e.startswith("Proposal p9 is invalid") for e in events)
    assert f"Scene list {good} approved" in events


def test_reject_adds_event_and_unknown_is_404(client, folder):
    from moshfilm import proposals
    pid = proposals.add_proposal(folder, {"summary": "x", "needs_approval": True, "changes": []}).id
    assert client.post(f"/api/proposals/{pid}/reject").status_code == 200
    assert _events(folder) == [f"Proposal {pid} rejected"]
    assert client.post("/api/proposals/p99/reject").status_code == 404
    assert client.post("/api/proposals/p99/approve", json={"include_pinned": False}).status_code == 404


def test_host_header_rejected(client):
    assert client.get("/api/film", headers={"Host": "evil.example"}).status_code == 403
    assert client.get("/api/film", headers={"Host": "evil.example:5717"}).status_code == 403
    assert client.get("/api/film", headers={"Host": "localhost:5173"}).status_code == 200
    assert client.get("/api/film", headers={"Host": "127.0.0.1:9"}).status_code == 200


def test_foreign_origin_rejected(client):
    assert client.post("/api/chat", data={"text": "x"}, headers={"Origin": "https://evil.example"}).status_code == 403
    assert client.post("/api/chat", data={"text": "x"}, headers={"Origin": "http://localhost:5173"}).status_code == 200


def test_film_files_served(client, folder):
    r = client.get("/film/scenes/s1.js")
    assert r.status_code == 200 and "export default" in r.text
    assert client.get("/film/scenes/missing.js").status_code == 404


def test_film_files_no_traversal(client, folder):
    (folder.parent / "secret.txt").write_text("secret")
    (folder / ".moshfilm").mkdir(exist_ok=True)
    (folder / ".moshfilm" / "heartbeat").write_text("x")
    for url in ("/film/.moshfilm/heartbeat", "/film/%2e%2e/secret.txt", "/film/scenes/%2e%2e/%2e%2e/secret.txt",
                "/film/..%2fsecret.txt", "/film/scenes/..%2f..%2fsecret.txt"):
        r = client.get(url)
        assert r.status_code == 404, url
        assert "secret" not in r.text


def test_film_sources_served_as_attachment_with_nosniff(client, folder):
    (folder / "sources").mkdir(exist_ok=True)
    (folder / "sources" / "page.html").write_text("<script>alert(1)</script>")
    r = client.get("/film/sources/page.html")
    assert r.status_code == 200
    assert r.headers["content-disposition"].startswith("attachment")
    assert r.headers["x-content-type-options"] == "nosniff"
    ok = client.get("/film/scenes/s1.js")  # scenes are code the page needs: inline, but still nosniff
    assert "attachment" not in ok.headers.get("content-disposition", "")
    assert ok.headers["x-content-type-options"] == "nosniff"


def test_film_never_serves_dotfiles(client, folder):
    (folder / ".claude").mkdir(exist_ok=True)
    (folder / ".claude" / "settings.local.json").write_text('{"secret": 1}')
    (folder / ".env").write_text("TOKEN=1")
    (folder / "scenes" / ".hidden.js").write_text("export default 1")
    for url in ("/film/.claude/settings.local.json", "/film/.env", "/film/scenes/.hidden.js"):
        assert client.get(url).status_code == 404, url
    for bad in (".claude/settings.local.json", ".env", "scenes/.hidden.js"):
        assert server.resolve_film_path(folder, bad) is None, bad


def test_resolve_film_path(folder):
    (folder.parent / "secret.txt").write_text("secret")
    (folder / "link").symlink_to(folder.parent)
    assert server.resolve_film_path(folder, "scenes/s1.js") == (folder / "scenes" / "s1.js").resolve()
    for bad in ("../secret.txt", "scenes/../../secret.txt", "/etc/passwd", ".moshfilm/lock",
                "scenes/../.moshfilm/lock", "link/secret.txt", "scenes", "nope.js", "a\0b"):
        assert server.resolve_film_path(folder, bad) is None, bad


def test_static_index_and_missing_assets(client):
    r = client.get("/")
    assert r.status_code == 200 and "moshFilm" in r.text
    assert client.get("/assets/nothing.js").status_code == 404


def test_voice_listing_and_file(client, folder, fake_tts):
    assert client.get("/api/voice").json() == {}
    f = filmmod.load_film(folder)
    narrate.ensure_voice(folder, f)
    body = client.get("/api/voice").json()
    assert list(body) == ["s1"] and body["s1"]["duration"] == pytest.approx(0.2)
    url = body["s1"]["url"]
    assert re.fullmatch(r"/api/voice/[0-9a-f]{16}\.mp3", url)
    assert client.get(url).content == b"stub"
    assert client.get("/api/voice/..%2f..%2flock.mp3").status_code == 404
    assert client.get("/api/voice/XYZ.mp3").status_code == 404
    assert client.get("/api/voice/0123456789abcdef.mp3").status_code == 404


def test_voice_synthesize_runs_in_worker(client, folder, fake_tts):
    assert client.post("/api/voice/synthesize").status_code == 200
    for _ in range(100):
        body = client.get("/api/voice").json()
        if "s1" in body:
            break
        time.sleep(0.05)
    assert "s1" in body


@pytest.mark.parametrize("rel,expected", [
    ("film.json", "film"), ("proposals.json", "proposals"), ("comments.json", "queue"),
    (".moshfilm/heartbeat", "queue"), (".moshfilm/status.json", "queue"),
    ("scenes/s2.js", "scene"), (".moshfilm/voice/0123456789abcdef.mp3", "voice"),
    (".moshfilm/voice/index.json", "voice"),
    (".moshfilm/lock", None), ("film.json.abc123.tmp", None), (".moshfilm/heartbeat.x1.tmp", None),
    (".moshfilm/voice/0123456789abcdef.mp3.part", None), ("sources/pic.png", None),
    ("scenes/.s2.js.swp", None), ("notes.txt", None),
])
def test_classify_change(folder, rel, expected):
    assert server.classify_change(folder / rel, folder) == expected


def test_classify_change_outside_folder(folder):
    assert server.classify_change(folder.parent / "film.json", folder) is None


def _get(url: str) -> str:
    with urllib.request.urlopen(url, timeout=5) as r:
        return r.read().decode()


def test_serve_in_thread_serves_film(folder):
    base, stop = server.serve_in_thread(folder)
    try:
        assert re.fullmatch(r"http://127\.0\.0\.1:\d+", base)
        assert json.loads(_get(base + "/api/film"))["film"]["title"] == "t"
        assert "export default" in _get(base + "/film/scenes/s1.js")
    finally:
        stop()
    with pytest.raises(OSError):
        _get(base + "/api/film")


def test_events_stream_reports_changes_and_invalid_proposals(folder):
    base, stop = server.serve_in_thread(folder)
    try:
        resp = urllib.request.urlopen(base + "/api/events", timeout=10)
        time.sleep(0.5)  # let the watcher start
        (folder / "scenes" / "s1.js").write_text("export default { v: 2 }\n")
        _proposal(folder, [{"id": "p1", "created": "x", "status": "pending", "changes": [{"op": "bogus"}]}])
        seen: dict[str, str] = {}
        deadline = time.time() + 10
        while time.time() < deadline and not {"scene", "proposals", "queue"} <= set(seen):
            line = resp.readline().decode().strip()
            if line.startswith("event:"):
                name = line.split(":", 1)[1].strip()
                seen[name] = resp.readline().decode().strip()
        resp.close()
        assert {"scene", "proposals", "queue"} <= set(seen), seen
        data = json.loads(seen["scene"].removeprefix("data:"))
        assert data["file"] == "scenes/s1.js" and data["version"] > 0
        assert any(e.startswith("Proposal p1 is invalid") for e in _events(folder))
        assert json.loads((folder / "proposals.json").read_text())["proposals"][0]["status"] == "invalid"
    finally:
        stop()


def test_cli_open_creates_film_and_serves(tmp_path, monkeypatch):
    from moshfilm import cli

    calls = []
    monkeypatch.setattr(server, "serve", lambda folder, port=5717, open_browser=True: calls.append((folder, port, open_browser)))
    target = tmp_path / "newfilm"
    assert cli.main(["open", str(target), "--port", "5000", "--no-browser"]) == 0
    assert (target / "film.json").exists()
    assert calls == [(target, 5000, False)]


def test_default_port_avoids_reserved_range():
    from moshfilm import cli

    assert server.DEFAULT_PORT == 5717
    tried = range(server.DEFAULT_PORT, server.DEFAULT_PORT + server.PORT_TRIES)
    assert list(tried) == list(range(5717, 5728))
    assert not set(tried) & set(range(4747, 4758))
    assert cli.build_parser().parse_args(["open", "x"]).port == server.DEFAULT_PORT


def test_bind_skips_port_held_by_a_wildcard_listener():
    import socket

    other = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    other.bind(("0.0.0.0", 0))
    other.listen()
    port = other.getsockname()[1]
    got = None
    try:
        try:
            got = server._bind(port, 2)
        except OSError:
            pytest.skip(f"port {port + 1} is taken too")
        assert got.getsockname()[1] == port + 1
    finally:
        if got:
            got.close()
        other.close()


def test_proposal_written_before_server_start_is_processed(folder):
    from moshfilm import proposals
    pid = proposals.add_proposal(folder, {"summary": "shorter", "changes": [
        {"op": "set_scene", "id": "s2", "title": "renamed"}]}).id
    assert json.loads((folder / "proposals.json").read_text())["proposals"][0]["status"] == "pending"
    with TestClient(server.create_app(folder), base_url=BASE) as c:
        deadline = time.time() + 5
        status = "pending"
        while time.time() < deadline and status == "pending":
            status = c.get("/api/proposals").json()["proposals"][0]["status"]
            time.sleep(0.05)
    assert status == "applied", pid
    assert filmmod.load_film(folder).scenes[1].title == "renamed"


def test_film_files_and_pages_are_not_cached(client):
    for url in ("/film/scenes/s1.js", "/"):
        assert client.get(url).headers["cache-control"] == "no-cache", url
    r = client.get("/render.html")
    if r.status_code == 200:
        assert r.headers["cache-control"] == "no-cache"


def test_keep_mine_on_partial_proposal_says_other_changes_were_applied(client, folder):
    from moshfilm import proposals
    pid = proposals.add_proposal(folder, {"summary": "mixed", "changes": [
        {"op": "set_scene", "id": "s1", "length": 2},
        {"op": "set_scene", "id": "s2", "title": "renamed"}]}).id
    proposals.process_pending(folder)
    assert client.post(f"/api/proposals/{pid}/reject").status_code == 200
    assert _events(folder) == [
        f"Proposal {pid}: the person kept their pinned values; its other changes were applied"]


def test_reject_of_untouched_proposal_still_says_rejected(client, folder):
    from moshfilm import proposals
    pid = proposals.add_proposal(folder, {"summary": "x", "needs_approval": True, "changes": []}).id
    client.post(f"/api/proposals/{pid}/reject")
    assert _events(folder) == [f"Proposal {pid} rejected"]


def test_second_approve_of_scene_list_uses_pinned_wording(client, folder):
    from moshfilm import proposals
    pid = proposals.add_proposal(folder, {"summary": "list", "needs_approval": True, "changes": [
        {"op": "add_scene", "scene": {"id": "s3", "title": "three", "length": 3}, "after": None},
        {"op": "set_scene", "id": "s1", "length": 2}]}).id
    assert client.post(f"/api/proposals/{pid}/approve", json={"include_pinned": False}).status_code == 200
    assert client.post(f"/api/proposals/{pid}/approve", json={"include_pinned": True}).status_code == 200
    assert _events(folder) == [f"Scene list {pid} approved",
                               f"Proposal {pid} approved (including your pinned values)"]


def test_activity_endpoint_and_sse_classification(client, folder):
    from moshfilm import activity
    assert client.get("/api/activity").json() == {"turn": None, "plan": []}
    activity.set_plan(folder, ["a"])
    assert client.get("/api/activity").json()["plan"] == [{"text": "a", "done": False}]
    assert server.classify_change(folder / ".moshfilm" / "activity.json", folder) == "activity"


def test_chat_with_frame_reference(client):
    item = client.post("/api/chat", data={"text": "this part", "at": json.dumps({"time": 6.0})}).json()
    assert item["at"] == {"time": 6.0, "scene": "s2", "sceneTitle": "two"}
    plain = client.post("/api/chat", data={"text": "no frame"}).json()
    assert plain["at"] is None
    assert client.post("/api/chat", data={"text": "x", "at": "garbage"}).status_code == 400
    assert client.post("/api/chat", data={"text": "x", "at": json.dumps({"time": -1})}).status_code == 400


def test_set_aspects_sends_chat_note(client, folder):
    r = client.post("/api/film/edit", json={"ops": [{"op": "set_aspects", "aspect": "9:16", "second_aspect": "1:1"}]})
    assert r.status_code == 200 and r.json()["film"]["aspect"] == "9:16"
    items = client.get("/api/queue").json()["items"]
    events = [i for i in items if i["kind"] == "event"]
    assert len(events) == 1 and events[0]["text"].startswith("The person changed the film's shape to 9:16")
    client.post("/api/film/edit", json={"ops": [{"op": "set_aspects", "aspect": "9:16", "second_aspect": "1:1"}]})
    items = client.get("/api/queue").json()["items"]
    assert len([i for i in items if i["kind"] == "event"]) == 1


def _second(client, aspect="9:16"):
    client.post("/api/film/edit", json={"ops": [{"op": "set_aspects", "aspect": "16:9", "second_aspect": aspect}]})


def test_comment_stores_aspect_and_defaults_to_main(client):
    first = client.post("/api/comments", json={"time": 1.0, "text": "a"}).json()
    assert first["aspect"] == "16:9"
    _second(client)
    second = client.post("/api/comments", json={"time": 1.0, "text": "b", "aspect": "9:16"}).json()
    assert second["aspect"] == "9:16"
    bad = client.post("/api/comments", json={"time": 1.0, "text": "c", "aspect": "4:5"})
    assert bad.status_code == 400 and "aspect 4:5 is not one of the film's shapes" in bad.json()["error"]
    assert client.post("/api/comments", json={"time": 1.0, "text": "c", "aspect": "7:3"}).status_code == 400


def test_chat_at_carries_aspect(client):
    _second(client)
    r = client.post("/api/chat", data={"text": "here", "at": json.dumps({"time": 1.0, "aspect": "9:16"})})
    assert r.json()["at"]["aspect"] == "9:16"
    r = client.post("/api/chat", data={"text": "here", "at": json.dumps({"time": 1.0})})
    assert "aspect" not in r.json()["at"]  # no shape given: it means the main one
    r = client.post("/api/chat", data={"text": "here", "at": json.dumps({"time": 1.0, "aspect": "4:5"})})
    assert r.status_code == 400


def test_comment_on_removed_shape_still_listed(client, folder):
    from moshfilm import cli
    _second(client)
    made = client.post("/api/comments", json={"time": 1.0, "text": "b", "aspect": "9:16",
                                              "point": {"x": 0.5, "y": 0.5}}).json()
    client.post("/api/film/edit", json={"ops": [{"op": "set_aspects", "aspect": "16:9", "second_aspect": None}]})
    items = client.get("/api/queue").json()["items"]
    mine = next(i for i in items if i["id"] == made["id"])
    assert mine["aspect"] == "9:16"
    line = json.loads(cli._item_line(queue.QueueItem(**mine), filmmod_load(folder)))
    assert line["frame"] == {"width": 720, "height": 1280}


def filmmod_load(folder):
    return filmmod.load_film(folder)


def test_main_shape_change_stamps_old_pins(client):
    old = client.post("/api/comments", json={"time": 1.0, "text": "a", "point": {"x": 0.5, "y": 0.5}}).json()
    # a comment from before shapes existed has no shape of its own
    queue.add_item(Path(client.get("/api/film").json()["folder"]), "comment", "legacy", time=1.0)
    client.post("/api/film/edit", json={"ops": [{"op": "set_aspects", "aspect": "9:16", "second_aspect": "16:9"}]})
    items = {i["text"]: i for i in client.get("/api/queue").json()["items"]}
    assert items["a"]["aspect"] == "16:9" and items["legacy"]["aspect"] == "16:9"
    assert old["id"] == items["a"]["id"]


def test_undoing_a_shape_change_names_the_shapes_and_asks_for_the_check(client):
    client.post("/api/film/edit", json={"ops": [{"op": "set_aspects", "aspect": "9:16", "second_aspect": "1:1"}]})
    assert client.post("/api/history/undo").status_code == 200
    texts = [i["text"] for i in client.get("/api/queue").json()["items"] if i["kind"] == "event"]
    undo_note = next(t for t in texts if t.startswith("The person undid"))
    assert "Changed shape to 9:16 + 1:1" in undo_note
    assert "The film's shape is now 16:9 (no second shape)" in undo_note
    assert "moshfilm check <folder> --layout" in undo_note


# ---- export endpoints

def _wait_export(client, states=("done", "error"), timeout=10):
    end = time.time() + timeout
    while time.time() < end:
        st = client.get("/api/export").json()
        if st["state"] in states:
            return st
        time.sleep(0.02)
    raise AssertionError(client.get("/api/export").json())


@pytest.fixture
def fake_export(monkeypatch):
    """export_aspects writes small files named like the real one; a gate keeps it 'running' on demand."""
    import threading
    from moshfilm import export, layout_check
    gate = threading.Event()
    gate.set()
    calls = []

    def fake(folder, fmt, out=None, fps=None, width=None, voice=True, progress=None, on_progress=None):
        calls.append((fmt, out))
        the_film = filmmod.load_film(folder)
        paths = export.output_paths(the_film, fmt, out, folder)
        for aspect, p in paths.items():
            if progress:
                progress(aspect)
            gate.wait(5)
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_bytes(b"MOVIE" + aspect.encode())
        return paths

    monkeypatch.setattr(export, "export_aspects", fake)
    monkeypatch.setattr(layout_check, "check_layout", lambda f: [
        filmmod.Issue(level="warning", where="s1", message="[16:9] at 1.0 s: <text> sticks out")])
    return gate, calls


def test_export_starts_reports_and_serves_the_file(client, folder, fake_export):
    assert client.get("/api/export").json()["state"] == "idle"
    r = client.post("/api/export", json={"format": "mp4"})
    assert r.status_code == 200
    st = _wait_export(client)
    assert st["state"] == "done" and st["format"] == "mp4"
    assert [f["name"] for f in st["files"]] == ["t.mp4"] and st["files"][0]["aspect"] == "16:9"
    assert st["files"][0]["bytes"] == len(b"MOVIE16:9")
    assert st["warnings"] == ["s1: [16:9] at 1.0 s: <text> sticks out"]
    assert (folder / "exports" / "t.mp4").is_file()
    got = client.get("/api/export/file/t.mp4")
    assert got.status_code == 200 and got.content == b"MOVIE16:9"


def test_export_two_shapes_names(client, folder, fake_export):
    client.post("/api/film/edit", json={"ops": [{"op": "set_aspects", "aspect": "16:9", "second_aspect": "9:16"}]})
    client.post("/api/export", json={"format": "gif"})
    st = _wait_export(client)
    assert [f["name"] for f in st["files"]] == ["t-16x9.gif", "t-9x16.gif"]


def test_export_409_while_running(client, fake_export):
    gate, _ = fake_export
    gate.clear()
    assert client.post("/api/export", json={"format": "mp4"}).status_code == 200
    assert _wait_export(client, ("running",))["current"] in (None, "16:9")
    assert client.post("/api/export", json={"format": "gif"}).status_code == 409
    gate.set()
    assert _wait_export(client)["state"] == "done"


def test_export_error_is_reported(client, monkeypatch):
    from moshfilm import export, layout_check
    monkeypatch.setattr(layout_check, "check_layout", lambda f: [])

    def boom(*a, **k):
        raise export.ExportError("scenes not ready: \"Two\"")

    monkeypatch.setattr(export, "export_aspects", boom)
    client.post("/api/export", json={"format": "mp4"})
    st = _wait_export(client)
    assert st["state"] == "error" and "scenes not ready" in st["error"]
    assert client.post("/api/export", json={"format": "pdf"}).status_code == 400


@pytest.mark.parametrize("name", ["..%2F..%2Ffilm.json", "%2e%2e%2ffilm.json", "a..b.mp4", "x/y.mp4", "film.json",
                                  ".hidden.mp4", "t.mp4%00.gif", "t.MP4x"])
def test_export_file_refuses_traversal_and_odd_names(client, folder, fake_export, name):
    (folder / "exports").mkdir(exist_ok=True)
    (folder / "exports" / "t.mp4").write_bytes(b"x")
    r = client.get(f"/api/export/file/{name}")
    assert r.status_code in (400, 404) and r.content != b"x"


def test_export_file_missing_and_symlink_escape(client, folder, tmp_path):
    (folder / "exports").mkdir()
    assert client.get("/api/export/file/nope.mp4").status_code == 404
    outside = tmp_path / "secret.mp4"
    outside.write_bytes(b"secret")
    (folder / "exports" / "link.mp4").symlink_to(outside)
    assert client.get("/api/export/file/link.mp4").status_code == 404


def test_export_reveal_only_inside_exports(client, folder, monkeypatch):
    import subprocess as sp
    seen = []
    monkeypatch.setattr(sp, "Popen", lambda cmd, *a, **k: seen.append(cmd))
    monkeypatch.setattr("sys.platform", "darwin")
    (folder / "exports").mkdir()
    (folder / "exports" / "t.mp4").write_bytes(b"x")
    assert client.post("/api/export/reveal", json={"name": "../film.json"}).status_code == 400
    assert client.post("/api/export/reveal", json={"name": "t.mp4"}).status_code == 200
    assert seen == [["open", "-R", str((folder / "exports" / "t.mp4").resolve())]]


def test_export_worker_crash_with_a_plain_exception_ends_in_error(client, monkeypatch):
    from moshfilm import export, layout_check
    monkeypatch.setattr(layout_check, "check_layout", lambda f: [])

    def boom(*a, **k):
        raise ZeroDivisionError("division by zero in the encoder")

    monkeypatch.setattr(export, "export_aspects", boom)
    client.post("/api/export", json={"format": "mp4"})
    st = _wait_export(client)
    assert st["state"] == "error" and "division by zero" in st["error"]
    # and a new export can start afterwards
    monkeypatch.setattr(export, "export_aspects", lambda *a, **k: {})
    assert client.post("/api/export", json={"format": "mp4"}).status_code == 200
    assert _wait_export(client)["state"] == "done"


def test_export_that_cannot_start_a_thread_resets_the_state(client, monkeypatch):
    import threading
    real = threading.Thread

    class Broken(real):
        def start(self):
            if self.name == "moshfilm-export":
                raise RuntimeError("can't start new thread")
            super().start()

    monkeypatch.setattr(threading, "Thread", Broken)
    r = client.post("/api/export", json={"format": "mp4"})
    assert r.status_code == 500 and "can't start new thread" in r.json()["error"]
    assert client.get("/api/export").json()["state"] == "error"
    monkeypatch.setattr(threading, "Thread", real)
    assert client.post("/api/export", json={"format": "bogus"}).status_code == 400  # not 409: it is not stuck


def test_a_hung_export_is_given_up_on(client, monkeypatch):
    import threading
    from moshfilm import export, layout_check
    monkeypatch.setattr(layout_check, "check_layout", lambda f: [])
    monkeypatch.setattr(server, "EXPORT_TIMEOUT_BASE", 0.3)
    monkeypatch.setattr(server, "EXPORT_TIMEOUT_PER_SECOND", 0.0)
    hang = threading.Event()
    monkeypatch.setattr(export, "export_aspects", lambda *a, **k: (hang.wait(10), {})[1])
    client.post("/api/export", json={"format": "mp4"})
    st = _wait_export(client)
    assert st["state"] == "error" and "given up" in st["error"]
    hang.set()  # the stuck render finishing late must not overwrite the error
    time.sleep(0.2)
    assert client.get("/api/export").json()["state"] == "error"


def test_export_files_come_from_the_exporter_mapping(client, folder, monkeypatch):
    from moshfilm import export, layout_check
    monkeypatch.setattr(layout_check, "check_layout", lambda f: [])

    def fake(folder_, fmt, out=None, fps=None, width=None, voice=True, progress=None, on_progress=None):
        p = out.with_name("custom-9x16.mp4")
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(b"x")
        return {"9:16": p}  # the exporter's own idea of the shapes, not the film's at the time

    monkeypatch.setattr(export, "export_aspects", fake)
    client.post("/api/export", json={"format": "mp4"})
    st = _wait_export(client)
    assert st["files"] == [{"name": "custom-9x16.mp4", "aspect": "9:16", "bytes": 1}]


def test_sound_edits_send_notes(client, folder):
    client.post("/api/film/edit", json={"ops": [{"op": "add_sfx", "preset": "ding", "scene": "s2", "at": 1}]})
    client.post("/api/film/edit", json={"ops": [{"op": "remove_sfx", "sfx": "fx1"}]})
    bed = {"op": "set_music_bed", "mood": "calm", "tempo": 80, "key": "C", "scale": "major",
           "palette": "keys", "seed": 1, "volume": 0.5}
    client.post("/api/film/edit", json={"ops": [bed]})
    assert _events(folder) == [
        'The person removed the sound "ding" (fx1) from scene 02. Do not add it back unless they ask.',
        "The person picked the music: calm, 80 bpm, C major, keys. It is theirs (pinned): "
        "do not change it unless they ask.",
    ]
    client.post("/api/film/edit", json={"ops": [{**bed, "volume": 0.3}]})  # volume only: no new note
    assert len(_events(folder)) == 2


def test_music_upload_is_pinned(client, folder):
    r = client.post("/api/music", files={"file": ("bed.mp3", b"ID3", "audio/mpeg")})
    assert r.json()["film"]["music"]["pinned"] is True
    assert filmmod.load_film(folder).music.pinned is True
