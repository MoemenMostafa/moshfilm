"""Remove elements, edit narration and captions, and the server endpoints behind undo/redo."""
import contextlib
import threading
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from moshfilm import edits, history, narrate, proposals, queue, server, timing
from moshfilm import film as filmmod
from moshfilm.film import Scene, TextClip, VoiceLine

BASE = "http://127.0.0.1:5717"


@pytest.fixture
def folder(tmp_path: Path) -> Path:
    filmmod.new_film(tmp_path, "t")
    f = filmmod.load_film(tmp_path)
    f.scenes = [
        Scene(id="s1", title="Intro", file="scenes/s1.js", length=6, status="ready", voice=VoiceLine(text="hello there")),
        Scene(id="s2", title="Middle", file="scenes/s2.js", length=5, status="ready", voice=VoiceLine(text="the middle")),
        Scene(id="s3", title="End", file="scenes/s3.js", length=4, status="ready", voice=VoiceLine(text="bye now")),
    ]
    f.texts = [TextClip(id="t1", scene="s2", text="Hello", start=0.5, end=2),
               TextClip(id="t2", scene="s2", text="World", start=2, end=3),
               TextClip(id="t3", scene="s1", text="Intro caption", start=0, end=2)]
    filmmod.save_film(tmp_path, f)
    for i in (1, 2, 3):
        (tmp_path / "scenes" / f"s{i}.js").write_text("export default {}\n")
    history.sync(tmp_path)
    return tmp_path


@pytest.fixture(autouse=True)
def no_stray_voice_workers(request, monkeypatch):
    """Edits that start voice synthesis must not reach the network, nor leak a worker into a later test's fake."""
    if "fake_tts" in request.fixturenames:
        return

    async def refuse(*_a, **_k):
        raise narrate.NarrationError("no network in this test")

    monkeypatch.setattr(narrate, "synthesize", refuse)


@pytest.fixture
def client(folder: Path):
    return TestClient(server.create_app(folder), base_url=BASE)


@contextlib.contextmanager
def running(folder):
    """A client with the lifespan running; on exit waits for the voice worker so it cannot leak into the next test."""
    app = server.create_app(folder)
    with TestClient(app, base_url=BASE) as client:
        try:
            yield client
        finally:
            wait_for(lambda: not app.state.voice_state["busy"], tries=200)


def film(folder):
    return filmmod.load_film(folder)


def edit(client, *ops):
    r = client.post("/api/film/edit", json={"ops": list(ops)})
    assert r.status_code == 200, r.text
    return r.json()["film"]


def propose(folder, *changes, needs_approval=False):
    proposals.add_proposal(folder, {"summary": "p", "needs_approval": needs_approval, "changes": list(changes)})
    return proposals.process_pending(folder)


def events(folder):
    return [i.text for i in queue.snapshot(folder).items if i.kind == "event"]


def wait_for(fn, tries=100):
    for _ in range(tries):
        got = fn()
        if got:
            return got
        time.sleep(0.05)
    return fn()


# ------------------------------------------------------------------ remove elements


def test_removing_a_scene_closes_the_gap_and_takes_its_voice_and_texts(client, folder):
    out = edit(client, {"op": "remove_scene", "scene": "s2"})
    assert [s["id"] for s in out["scenes"]] == ["s1", "s3"]
    assert [t["id"] for t in out["texts"]] == ["t3"]  # t1 and t2 belonged to s2
    slots = timing.layout(film(folder), {})
    assert slots[1].start == slots[0].length  # s3 now starts right where s1 ends: no gap


def test_removing_a_text_and_a_voice_line(client, folder):
    out = edit(client, {"op": "remove_text", "text": "t1"}, {"op": "remove_voice", "scene": "s1"})
    assert [t["id"] for t in out["texts"]] == ["t2", "t3"]
    assert out["scenes"][0]["voice"]["text"] == ""
    kinds = {(t["kind"], t["id"]) for t in out["removed_by_person"]}
    assert kinds == {("text", "t1"), ("voice", "s1")}
    assert client.post("/api/film/edit", json={"ops": [{"op": "remove_voice", "scene": "s1"}]}).status_code == 400


def test_removing_music_is_one_edit(client, folder):
    (folder / "music").mkdir()
    edit(client, {"op": "set_music", "file": "music/a.mp3", "volume": 0.5})
    out = edit(client, {"op": "set_music", "file": None, "volume": 0.5})
    assert out["music"] is None
    assert any("removed the music" in e for e in events(folder))


def test_unknown_targets_are_rejected(client):
    for op in ({"op": "remove_scene", "scene": "nope"}, {"op": "remove_text", "text": "nope"}):
        assert client.post("/api/film/edit", json={"ops": [op]}).status_code == 400


def test_a_removal_is_undoable_and_redoable_through_the_api(client, folder):
    edit(client, {"op": "remove_scene", "scene": "s2"})
    r = client.post("/api/history/undo").json()
    assert r["changed"] and [s["id"] for s in r["film"]["scenes"]] == ["s1", "s2", "s3"]
    assert len(r["film"]["texts"]) == 3 and r["film"]["removed_by_person"] == []
    r = client.post("/api/history/redo").json()
    assert [s["id"] for s in r["film"]["scenes"]] == ["s1", "s3"]
    assert [t["kind"] for t in r["film"]["removed_by_person"]].count("scene") == 1


def test_claude_gets_a_chat_note_about_each_removal(client, folder):
    edit(client, {"op": "remove_scene", "scene": "s2"})
    edit(client, {"op": "remove_text", "text": "t3"})
    notes = events(folder)
    assert any('removed scene 02 "Middle"' in n and "voice line" in n and "2 captions" in n
               and "Do not add it back" in n for n in notes)
    assert any('removed the caption "Intro caption"' in n for n in notes)


# ------------------------------------------------------------------ tombstones vs proposals


def add_scene_change(sid="s2", title="Middle"):
    return {"op": "add_scene", "scene": {"id": sid, "title": title, "length": 5}}


def test_proposal_cannot_re_add_a_removed_scene(client, folder):
    edit(client, {"op": "remove_scene", "scene": "s2"})
    done = propose(folder, add_scene_change())
    assert done[0].status == "partial" and done[0].held == [0]
    assert [s.id for s in film(folder).scenes] == ["s1", "s3"]


def test_removed_scene_is_recognised_under_a_new_id_by_its_title(client, folder):
    edit(client, {"op": "remove_scene", "scene": "s2"})
    done = propose(folder, add_scene_change("s9", "  middle "))
    assert done[0].held == [0] and "s9" not in [s.id for s in film(folder).scenes]


def test_a_different_new_scene_is_fine(client, folder):
    edit(client, {"op": "remove_scene", "scene": "s2"})
    done = propose(folder, add_scene_change("s4", "Something else"))
    assert done[0].status == "applied" and [s.id for s in film(folder).scenes] == ["s1", "s3", "s4"]


def test_proposal_cannot_re_add_a_removed_text_or_texts_of_a_removed_scene(client, folder):
    edit(client, {"op": "remove_text", "text": "t3"})
    edit(client, {"op": "remove_scene", "scene": "s2"})
    done = propose(
        folder,
        {"op": "add_text", "text": {"id": "t3", "scene": "s1", "text": "something"}},          # same id
        {"op": "add_text", "text": {"id": "t7", "scene": "s1", "text": "Intro caption"}},      # same words
        {"op": "add_text", "text": {"id": "t8", "scene": "s2", "text": "brand new"}},          # removed scene
        {"op": "add_text", "text": {"id": "t9", "scene": "s1", "text": "Different"}},          # fine
    )
    assert done[0].held == [0, 1, 2] and done[0].status == "partial"
    assert [t.id for t in film(folder).texts] == ["t9"]


def test_changes_to_removed_things_are_ignored_not_errors(client, folder):
    edit(client, {"op": "remove_scene", "scene": "s2"})
    edit(client, {"op": "remove_text", "text": "t3"})
    done = propose(folder, {"op": "set_scene", "id": "s2", "title": "back!"},
                   {"op": "set_voice", "id": "s2", "text": "again"},
                   {"op": "set_text", "id": "t3", "text": "again"},
                   {"op": "remove_text", "id": "t3"},
                   {"op": "move_scene", "id": "s2", "index": 0})
    assert done[0].status == "applied" and done[0].held == []
    assert [s.id for s in film(folder).scenes] == ["s1", "s3"]


def test_removed_voice_line_stays_removed_for_proposals(client, folder):
    edit(client, {"op": "remove_voice", "scene": "s1"})
    done = propose(folder, {"op": "set_voice", "id": "s1", "text": "new words"})
    assert done[0].held == [0] and film(folder).scenes[0].voice.text == ""


def test_the_person_can_approve_a_held_comeback_and_the_tombstone_goes(client, folder):
    edit(client, {"op": "remove_scene", "scene": "s2"})
    done = propose(folder, add_scene_change())
    proposals.approve(folder, done[0].id, include_pinned=True)
    f = film(folder)
    assert "s2" in [s.id for s in f.scenes]
    assert not [t for t in f.removed_by_person if t.kind == "scene" and t.id == "s2"]


def test_a_scene_list_proposal_waits_and_still_respects_the_tombstone(client, folder):
    edit(client, {"op": "remove_scene", "scene": "s2"})
    done = propose(folder, add_scene_change(), needs_approval=True)
    assert done[0].status == "awaiting_approval"
    res = proposals.approve(folder, done[0].id, include_pinned=False)
    assert res.status == "partial" and "s2" not in [s.id for s in film(folder).scenes]


def test_undoing_a_removal_removes_the_tombstone_too(client, folder):
    edit(client, {"op": "remove_scene", "scene": "s2"})
    client.post("/api/history/undo")
    done = propose(folder, {"op": "set_scene", "id": "s2", "title": "renamed"})
    assert done[0].status == "applied" and film(folder).scenes[1].title == "renamed"


# ------------------------------------------------------------------ narration and captions


def test_narration_edit_pins_the_text_and_proposals_cannot_overwrite_it(client, folder):
    out = edit(client, {"op": "set_voice_text", "scene": "s1", "text": "my own words"})
    assert out["scenes"][0]["voice"]["text"] == "my own words" and out["scenes"][0]["voice"]["text_pinned"]
    done = propose(folder, {"op": "set_voice", "id": "s1", "text": "claude words", "offset": 0.5})
    assert done[0].status == "partial"
    assert film(folder).scenes[0].voice.text == "my own words"
    assert film(folder).scenes[0].voice.offset == 0.5  # only the pinned words were held
    proposals.approve(folder, done[0].id, include_pinned=True)
    assert film(folder).scenes[0].voice.text == "claude words"
    assert not film(folder).scenes[0].voice.text_pinned


def test_caption_edit_pins_the_text_and_proposals_cannot_overwrite_it(client, folder):
    edit(client, {"op": "set_text_content", "text": "t1", "content": "Mine"})
    done = propose(folder, {"op": "set_text", "id": "t1", "text": "Theirs", "style": "title"},
                   {"op": "remove_text", "id": "t1"})
    assert done[0].held == [0, 1]
    clip = film(folder).texts[0]
    assert clip.text == "Mine" and clip.text_pinned and clip.style == "title"  # style is not text: applied


def test_removing_a_scene_with_edited_text_is_held_from_claude(client, folder):
    edit(client, {"op": "set_text_content", "text": "t1", "content": "Mine"})
    done = propose(folder, {"op": "remove_scene", "id": "s2"})
    assert done[0].held == [0] and "s2" in [s.id for s in film(folder).scenes]


def test_empty_text_is_refused(client):
    for op in ({"op": "set_voice_text", "scene": "s1", "text": "  "},
               {"op": "set_text_content", "text": "t1", "content": ""}):
        assert client.post("/api/film/edit", json={"ops": [op]}).status_code == 400


def test_chat_note_for_edited_narration_and_caption(client, folder):
    edit(client, {"op": "set_voice_text", "scene": "s1", "text": "my own words"})
    edit(client, {"op": "set_text_content", "text": "t1", "content": "Mine"})
    notes = events(folder)
    assert any('narration of scene 01' in n and '"hello there" is now "my own words"' in n and "pinned" in n
               for n in notes)
    assert any('caption t1: "Hello" is now "Mine"' in n for n in notes)
    n = len(notes)
    edit(client, {"op": "set_text_content", "text": "t1", "content": "Mine"})  # same words: no new note
    assert len(events(folder)) == n


def test_narration_edit_resynthesises_automatically_and_reruns_the_fit_check(folder, fake_tts):
    f = film(folder)
    f.scenes[0].length, f.scenes[0].pinned = 3, True   # pinned: a long line cannot stretch it
    filmmod.save_film(folder, f)
    long_line = " ".join(["word"] * 40)  # 4.0 s with the fake voice: too long for 3 s even sped up 1.25x
    with running(folder) as client:
        narrate.ensure_voice(folder, film(folder))
        assert "s1" in client.get("/api/voice").json()
        edit(client, {"op": "set_voice_text", "scene": "s1",
                      "text": long_line})
        assert wait_for(lambda: any(c[0] == long_line for c in fake_tts.calls))
        voice = wait_for(lambda: (v := client.get("/api/voice").json()).get("s1", {}).get("duration", 0) > 1.0 and v)
        assert voice["s1"]["duration"] == pytest.approx(4.0, abs=0.01)  # 40 words at 0.1 s each
        the_film = film(folder)
        slots = timing.layout(the_film, narrate.voice_durations(folder, the_film))
        assert slots[0].overflow  # the scene turns red, with the existing hint
        assert any("voice does not fit scene s1" in e and timing.OVERFLOW_COPY in e
                   for e in wait_for(lambda: [x for x in events(folder) if "does not fit" in x]))


def test_a_text_edited_while_synthesis_runs_still_gets_its_voice(folder, fake_tts):
    with running(folder) as client:
        edit(client, {"op": "set_voice_text", "scene": "s1", "text": "first version"})
        edit(client, {"op": "set_voice_text", "scene": "s1", "text": "second version"})
        assert wait_for(lambda: any(c[0] == "second version" for c in fake_tts.calls))


def test_narration_edit_is_undoable_and_old_audio_is_reused(folder, fake_tts):
    with running(folder) as client:
        narrate.ensure_voice(folder, film(folder))
        calls = len(fake_tts.calls)
        edit(client, {"op": "set_voice_text", "scene": "s1", "text": "changed words here now"})
        wait_for(lambda: client.get("/api/voice").json().get("s1", {}).get("duration") == pytest.approx(0.4))
        r = client.post("/api/history/undo").json()
        assert r["film"]["scenes"][0]["voice"]["text"] == "hello there"
        assert not r["film"]["scenes"][0]["voice"]["text_pinned"]
        time.sleep(0.3)
        assert [c for c in fake_tts.calls[calls:] if c[0] == "hello there"] == []  # cached: no new synthesis


# ------------------------------------------------------------------ history endpoints


def test_history_endpoints_and_chat_notes(client, folder):
    edit(client, {"op": "set_length", "scene": "s1", "length": 7})
    edit(client, {"op": "set_pace", "pace": 1.5})
    h = client.get("/api/history").json()
    assert [s["label"] for s in h["steps"]] == ["Start", "Changed length of scene 01", "Changed pace"]
    assert h["can_undo"] and not h["can_redo"]
    r = client.post("/api/history/undo").json()
    assert r["film"]["pace"] == 1.0 and r["can_redo"] and r["changed"]
    assert "The person undid: Changed pace" in events(folder)
    client.post("/api/history/redo")
    assert "The person redid: Changed pace" in events(folder)
    first = h["steps"][1]["id"]
    r = client.post("/api/history/jump", json={"id": first}).json()
    assert r["film"]["pace"] == 1.0 and r["film"]["scenes"][0]["length"] == 7
    assert "The person jumped back to: Changed length of scene 01" in events(folder)
    assert client.post("/api/history/jump", json={"id": 999}).status_code == 404


def test_undo_at_the_start_changes_nothing_and_adds_no_note(client, folder):
    before = len(events(folder))
    r = client.post("/api/history/undo").json()
    assert r["changed"] is False and len(events(folder)) == before


def test_undo_picks_up_claude_scene_edits_first(client, folder):
    (folder / "scenes" / "s3.js").write_text("export default { v: 2 }\n")
    client.post("/api/history/undo")  # the unrecorded edit becomes a Claude step, then is undone
    labels = [s["label"] for s in client.get("/api/history").json()["steps"]]
    assert labels[-1] == "Claude: edited scene 03"
    assert (folder / "scenes" / "s3.js").read_text() == "export default {}\n"
    client.post("/api/history/redo")
    assert "v: 2" in (folder / "scenes" / "s3.js").read_text()


def test_undo_survives_a_server_restart(folder):
    c1 = TestClient(server.create_app(folder), base_url=BASE)
    edit(c1, {"op": "set_pace", "pace": 1.5})
    c2 = TestClient(server.create_app(folder), base_url=BASE)  # a new process would start like this
    h = c2.get("/api/history").json()
    assert h["can_undo"]
    assert c2.post("/api/history/undo").json()["film"]["pace"] == 1.0


def test_classify_history_files(folder):
    assert server.classify_change(folder / ".moshfilm/history/index.json", folder) == "history"
    assert server.classify_change(folder / ".moshfilm/history/000002.json.abc.tmp", folder) is None


def test_edit_error_leaves_history_untouched(client, folder):
    n = len(client.get("/api/history").json()["steps"])
    assert client.post("/api/film/edit", json={"ops": [{"op": "set_length", "scene": "s1", "length": 1000}]}).status_code == 400
    assert len(client.get("/api/history").json()["steps"]) == n


# ------------------------------------------------------------------ review fix round 1


def test_tombstone_cap_never_evicts_scene_or_voice_tombstones(folder, monkeypatch):
    monkeypatch.setattr(edits, "MAX_TOMBSTONES", 5)
    f = film(folder)
    edits.add_tombstone(f, "scene", "sA", text="A")
    edits.add_tombstone(f, "voice", "s1", text="v")
    for i in range(10):
        edits.add_tombstone(f, "text", f"t{i}", scene="s1", text=f"w{i}")
    kinds = [(t.kind, t.id) for t in f.removed_by_person]
    assert ("scene", "sA") in kinds and ("voice", "s1") in kinds
    assert len(kinds) == 5
    assert [i for k, i in kinds if k == "text"] == ["t7", "t8", "t9"]  # the oldest texts went first
    assert edits.MAX_TOMBSTONES == 5


def test_default_tombstone_cap_is_1000():
    assert edits.MAX_TOMBSTONES == 1000


def test_approving_a_removed_scene_also_clears_its_text_tombstones(client, folder):
    edit(client, {"op": "remove_scene", "scene": "s2"})  # t1, t2 are tombstoned with it
    done = propose(folder, add_scene_change())
    proposals.approve(folder, done[0].id, include_pinned=True)
    f = film(folder)
    assert not [t for t in f.removed_by_person if t.scene == "s2" or t.id == "s2"]
    done = propose(folder, {"op": "add_text", "text": {"id": "t1", "scene": "s2", "text": "Hello"}})
    assert done[0].status == "applied"


def test_held_reason_says_same_title_as_a_scene_you_removed(client, folder):
    edit(client, {"op": "remove_scene", "scene": "s2"})
    done = propose(folder, add_scene_change("s9", "middle"))
    assert "same title as a scene you removed" in done[0].held_reasons["0"]
    done = propose(folder, add_scene_change("s2", "Whatever"))
    assert "you removed this scene" in done[0].held_reasons["0"]


def test_overflow_note_is_sticky_and_sent_once_from_the_final_pass(folder, fake_tts):
    f = film(folder)
    f.scenes[0].length, f.scenes[0].pinned = 3, True
    filmmod.save_film(folder, f)
    long_line = " ".join(["word"] * 40)
    with running(folder) as client:
        # an edit whose run is already busy (plain synthesize) must still carry the note request
        gate = threading.Event()
        real = narrate.ensure_voice

        def slow(*a, **k):
            gate.wait(5)
            return real(*a, **k)

        narrate_ensure = narrate.ensure_voice
        narrate.ensure_voice = slow
        try:
            client.post("/api/voice/synthesize")
            edit(client, {"op": "set_voice_text", "scene": "s1", "text": long_line})  # arrives while busy
            gate.set()
            notes = wait_for(lambda: [e for e in events(folder) if "does not fit" in e])
            time.sleep(0.5)
        finally:
            narrate.ensure_voice = narrate_ensure
        notes = [e for e in events(folder) if "does not fit" in e]
        assert len(notes) == 1 and "scene s1" in notes[0]


def test_get_history_is_read_only(client, folder):
    (folder / "scenes" / "s3.js").write_text("export default { v: 2 }\n")
    assert len(client.get("/api/history").json()["steps"]) == 1


def test_claude_change_after_an_undo_tells_the_person_in_chat(client, folder):
    edit(client, {"op": "set_pace", "pace": 1.5})
    client.post("/api/history/undo")
    (folder / "scenes" / "s3.js").write_text("export default { v: 2 }\n")
    server_notes = []
    history.sync(folder, lambda t: (server_notes.append(t), queue.add_event(folder, t)))
    assert any("redo step was cleared" in e for e in events(folder))


# ------------------------------------------------------------------ review fix round 2


def test_get_history_tells_the_person_at_once_when_it_resets_a_damaged_index(client, folder):
    edit(client, {"op": "set_pace", "pace": 1.5})
    (folder / ".moshfilm" / "history" / "index.json").write_text("{ nope")
    r = client.get("/api/history").json()
    assert r["steps"] == []
    assert sum("History was reset" in e for e in events(folder)) == 1
    client.get("/api/history")
    history.sync(folder)
    assert sum("History was reset" in e for e in events(folder)) == 1  # once, not again at the next sync


def test_redo_after_claude_cleared_it_is_a_409_with_a_clear_message(client, folder, monkeypatch):
    edit(client, {"op": "set_pace", "pace": 1.5})
    client.post("/api/history/undo")
    real_ready = history._ready

    def ready_then_claude_writes(f, notify=None):
        idx = real_ready(f, notify)  # the redo target was chosen from this index ...
        (f / "scenes" / "s3.js").write_text("export default { v: 'claude' }\n")  # ... then Claude writes
        return idx

    monkeypatch.setattr(history, "_ready", ready_then_claude_writes)
    r = client.post("/api/history/redo")
    assert r.status_code == 409
    assert r.json()["error"] == "Nothing to redo — Claude changed the film after your undo"


def test_unknown_jump_target_is_still_404(client):
    assert client.post("/api/history/jump", json={"id": 999}).status_code == 404


def test_a_snapshot_with_nested_scene_files_is_refused_with_a_409(client, folder):
    edit(client, {"op": "set_pace", "pace": 1.5})
    hist = folder / ".moshfilm" / "history"
    import json as _json
    first = _json.loads((hist / "index.json").read_text())["steps"][0]["file"]
    snap = _json.loads((hist / first).read_text())
    snap["files"]["scenes/sub/deep.js"] = "x"
    (hist / first).write_text(_json.dumps(snap))
    r = client.post("/api/history/undo")
    assert r.status_code == 409
    assert r.json()["error"] == "This step was saved by an older version and can't be restored."
    assert film(folder).pace == 1.5  # nothing was restored
