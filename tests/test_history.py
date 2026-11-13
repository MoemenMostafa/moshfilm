"""Undo/redo history: snapshots of film.json and scene files in .moshfilm/history/."""
import json
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from moshfilm import activity, edits, history, store
from moshfilm import film as filmmod
from moshfilm.film import Scene, TextClip, VoiceLine


@pytest.fixture
def folder(tmp_path: Path) -> Path:
    filmmod.new_film(tmp_path, "t")
    f = filmmod.load_film(tmp_path)
    f.scenes = [
        Scene(id=f"s{i}", title=f"scene {i}", file=f"scenes/s{i}.js", length=4, status="ready",
              voice=VoiceLine(text=f"line {i}"))
        for i in (1, 2, 3)
    ]
    f.texts = [TextClip(id="t1", scene="s2", text="Hello", start=0.5, end=2)]
    filmmod.save_film(tmp_path, f)
    for i in (1, 2, 3):
        (tmp_path / "scenes" / f"s{i}.js").write_text(f"export default {{ n: {i} }}\n")
    history.sync(tmp_path)  # baseline
    return tmp_path


def film(folder: Path):
    return filmmod.load_film(folder)


def person(folder: Path, ops: list[dict]):
    return history.apply_and_record(folder, ops)


def set_clock(monkeypatch, start=None):
    clock = {"now": start or datetime(2026, 11, 11, 12, 0, 0, tzinfo=timezone.utc)}
    monkeypatch.setattr(history, "_now", lambda: clock["now"])
    monkeypatch.setattr(activity, "_now", lambda: clock["now"])
    return clock


# ------------------------------------------------------------------ basics


def test_baseline_is_created_once_and_nothing_to_undo(folder):
    info = history.info(folder)
    assert len(info["steps"]) == 1 and info["steps"][0]["kind"] == "base"
    assert not info["can_undo"] and not info["can_redo"]
    history.sync(folder)
    assert len(history.info(folder)["steps"]) == 1


def test_each_person_edit_is_one_step_and_undo_redo_roundtrip(folder):
    person(folder, [{"op": "set_length", "scene": "s1", "length": 6}])
    person(folder, [{"op": "set_length", "scene": "s2", "length": 7}])
    assert len(history.info(folder)["steps"]) == 3
    undone = history.undo(folder)
    assert undone["label"] == "Changed length of scene 02"
    assert film(folder).scenes[1].length == 4 and film(folder).scenes[1].pinned is False
    assert film(folder).scenes[0].length == 6
    history.undo(folder)
    assert film(folder).scenes[0].length == 4 and film(folder).scenes[0].pinned is False
    assert history.undo(folder) is None  # at the start
    redone = history.redo(folder)
    assert redone["label"] == "Changed length of scene 01"
    assert film(folder).scenes[0].length == 6 and film(folder).scenes[0].pinned is True
    history.redo(folder)
    assert film(folder).scenes[1].length == 7
    assert history.redo(folder) is None


def test_new_edit_clears_the_redo_stack(folder):
    person(folder, [{"op": "set_length", "scene": "s1", "length": 6}])
    history.undo(folder)
    assert history.info(folder)["can_redo"]
    person(folder, [{"op": "set_pace", "pace": 1.5}])
    info = history.info(folder)
    assert not info["can_redo"] and len(info["steps"]) == 2
    assert not any(p.name.endswith("None") for p in (folder / ".moshfilm" / "history").iterdir())


def test_a_noop_edit_records_nothing(folder):
    person(folder, [{"op": "set_pace", "pace": 1.0}])
    assert len(history.info(folder)["steps"]) == 1


@pytest.mark.parametrize("ops,check", [
    ([{"op": "set_length", "scene": "s1", "length": 9}], lambda f: f.scenes[0].length == 4 and not f.scenes[0].pinned),
    ([{"op": "move_scene", "scene": "s1", "index": 2}],
     lambda f: [s.id for s in f.scenes] == ["s1", "s2", "s3"] and not f.order_pinned),
    ([{"op": "set_text_time", "text": "t1", "start": 1, "end": 3}],
     lambda f: f.texts[0].start == 0.5 and f.texts[0].end == 2 and not f.texts[0].pinned),
    ([{"op": "set_voice_offset", "scene": "s1", "offset": 1.1}],
     lambda f: f.scenes[0].voice.offset == 0.3 and not f.scenes[0].voice.pinned),
    ([{"op": "set_pace", "pace": 1.5}], lambda f: f.pace == 1.0),
    ([{"op": "set_voice_settings", "name": "en-GB-RyanNeural", "rate": "+0%"}],
     lambda f: f.voice.name == "en-US-AndrewNeural"),
    ([{"op": "set_music", "file": "music/a.mp3", "volume": 0.4}], lambda f: f.music is None),
    ([{"op": "remove_scene", "scene": "s2"}],
     lambda f: [s.id for s in f.scenes] == ["s1", "s2", "s3"] and len(f.texts) == 1 and not f.removed_by_person),
    ([{"op": "remove_text", "text": "t1"}], lambda f: len(f.texts) == 1 and not f.removed_by_person),
    ([{"op": "remove_voice", "scene": "s1"}],
     lambda f: f.scenes[0].voice.text == "line 1" and not f.removed_by_person),
    ([{"op": "set_voice_text", "scene": "s1", "text": "new"}],
     lambda f: f.scenes[0].voice.text == "line 1" and not f.scenes[0].voice.text_pinned),
    ([{"op": "set_text_content", "text": "t1", "content": "Bye"}],
     lambda f: f.texts[0].text == "Hello" and not f.texts[0].text_pinned),
])
def test_undo_restores_every_edit_kind(folder, ops, check):
    (folder / "music").mkdir(exist_ok=True)
    before = film(folder).model_dump()
    person(folder, ops)
    assert film(folder).model_dump() != before
    history.undo(folder)
    assert check(film(folder))
    assert film(folder).model_dump() == before
    history.redo(folder)
    assert film(folder).model_dump() != before


def test_unpin_is_undoable_and_restores_the_pinned_flag(folder):
    person(folder, [{"op": "set_length", "scene": "s1", "length": 6}])
    person(folder, [{"op": "unpin", "target": "scene:s1"}])
    assert film(folder).scenes[0].pinned is False
    history.undo(folder)
    assert film(folder).scenes[0].pinned is True


def test_scene_files_are_restored_too(folder):
    p = folder / "scenes" / "s1.js"
    person(folder, [{"op": "set_pace", "pace": 1.2}])
    p.write_text("export default { n: 'claude' }\n")
    (folder / "scenes" / "s9.js").write_text("export default {}\n")
    history.sync(folder)
    history.undo(folder)  # the Claude step: its edit and its new file both go
    assert p.read_text() == "export default { n: 1 }\n"
    assert not (folder / "scenes" / "s9.js").exists()
    history.redo(folder)
    assert "claude" in p.read_text() and (folder / "scenes" / "s9.js").exists()


def test_jump_goes_to_any_step_and_back(folder):
    for n in (5, 6, 7):
        person(folder, [{"op": "set_length", "scene": "s1", "length": n}])
    steps = history.info(folder)["steps"]
    assert len(steps) == 4
    history.jump(folder, steps[1]["id"])
    assert film(folder).scenes[0].length == 5
    assert history.info(folder)["cursor"] == 1
    history.jump(folder, steps[3]["id"])
    assert film(folder).scenes[0].length == 7
    with pytest.raises(history.HistoryError):
        history.jump(folder, 9999)


def test_history_survives_a_restart(folder):
    person(folder, [{"op": "set_length", "scene": "s1", "length": 6}])
    person(folder, [{"op": "set_length", "scene": "s2", "length": 6}])
    history.undo(folder)
    # a "restart" is a fresh process: nothing is cached in memory
    info = history.info(folder)
    assert info["cursor"] == 1 and info["can_redo"]
    history.redo(folder)
    assert film(folder).scenes[1].length == 6
    assert (folder / ".moshfilm" / "history" / "index.json").is_file()


def test_changes_made_while_the_server_was_down_are_recorded_on_sync(folder):
    f = film(folder)
    f.scenes[0].length = 9
    filmmod.save_film(folder, f)
    history.sync(folder)
    steps = history.info(folder)["steps"]
    assert len(steps) == 2 and steps[1]["kind"] == "claude"


def test_a_damaged_index_starts_a_fresh_history(folder):
    (folder / ".moshfilm" / "history" / "index.json").write_text("{ nope")
    history.sync(folder)
    assert len(history.info(folder)["steps"]) == 1


def test_undo_does_not_record_a_step_by_itself(folder):
    person(folder, [{"op": "set_length", "scene": "s1", "length": 6}])
    history.undo(folder)
    history.sync(folder)  # what the folder watcher does after the undo wrote the files
    info = history.info(folder)
    assert len(info["steps"]) == 2 and info["cursor"] == 0 and info["can_redo"]


# ------------------------------------------------------------------ bounds


def test_history_is_bounded_by_step_count(folder, monkeypatch):
    monkeypatch.setattr(history, "MAX_STEPS", 5)
    for n in range(1, 13):
        person(folder, [{"op": "set_length", "scene": "s1", "length": n + 0.5}])
    info = history.info(folder)
    assert len(info["steps"]) == 5
    assert film(folder).scenes[0].length == 12.5
    files = [p for p in (folder / ".moshfilm" / "history").iterdir() if p.name != "index.json"]
    assert len(files) == 5  # dropped steps leave no snapshot behind
    for _ in range(10):
        history.undo(folder)
    assert film(folder).scenes[0].length == 8.5  # the oldest kept step


def test_history_is_bounded_by_size(folder, monkeypatch):
    big = "x" * 5000
    (folder / "scenes" / "s1.js").write_text(f"// {big}\nexport default {{}}\n")
    history.sync(folder)
    monkeypatch.setattr(history, "MAX_BYTES", 30_000)
    for n in range(1, 21):
        person(folder, [{"op": "set_length", "scene": "s1", "length": n + 0.5}])
    info = history.info(folder)
    total = sum(p.stat().st_size for p in (folder / ".moshfilm" / "history").iterdir() if p.name != "index.json")
    assert total <= 30_000 + 8_000  # the newest step always stays, even if it alone is large
    assert 2 <= len(info["steps"]) < 21
    assert film(folder).scenes[0].length == 20.5


# ------------------------------------------------------------------ Claude turns


def claude_edit(folder, n, scene="s1"):
    (folder / "scenes" / f"{scene}.js").write_text(f"export default {{ v: {n} }}\n")
    history.sync(folder)


def test_one_claude_turn_is_one_labelled_step(folder, monkeypatch):
    clock = set_clock(monkeypatch)
    turn = {"id": "turn1", "started": "x", "updated": clock["now"].isoformat(), "ended": None, "item": None, "steps": []}
    store.write_json_atomic(folder / ".moshfilm" / "activity.json", {"turn": turn, "plan": []})
    claude_edit(folder, 1, "s3")
    clock["now"] += timedelta(minutes=2)  # well past the quiet period, but still the same turn
    claude_edit(folder, 2, "s3")
    claude_edit(folder, 3, "s3")
    steps = history.info(folder)["steps"]
    assert [s["kind"] for s in steps] == ["base", "claude"]
    assert steps[1]["label"] == "Claude: edited scene 03"
    history.undo(folder)  # one undo reverts the whole turn
    assert (folder / "scenes" / "s3.js").read_text() == "export default { n: 3 }\n"


def test_two_turns_are_two_steps(folder, monkeypatch):
    clock = set_clock(monkeypatch)
    for tid, scene in (("turn1", "s1"), ("turn2", "s2")):
        turn = {"id": tid, "started": "x", "updated": clock["now"].isoformat(), "ended": None, "item": None, "steps": []}
        store.write_json_atomic(folder / ".moshfilm" / "activity.json", {"turn": turn, "plan": []})
        claude_edit(folder, 1, scene)
        clock["now"] += timedelta(seconds=1)
    steps = history.info(folder)["steps"]
    assert [s["label"] for s in steps] == ["Start", "Claude: edited scene 01", "Claude: edited scene 02"]


def test_without_a_turn_a_quiet_period_groups_changes(folder, monkeypatch):
    clock = set_clock(monkeypatch)
    claude_edit(folder, 1, "s1")
    clock["now"] += timedelta(seconds=history.QUIET_SECONDS - 1)
    claude_edit(folder, 2, "s2")
    assert len(history.info(folder)["steps"]) == 2
    assert history.info(folder)["steps"][1]["label"] == "Claude: edited scenes 01, 02"
    clock["now"] += timedelta(seconds=history.QUIET_SECONDS + 1)
    claude_edit(folder, 3, "s3")
    assert len(history.info(folder)["steps"]) == 3


def test_an_old_ended_turn_does_not_swallow_later_changes(folder, monkeypatch):
    clock = set_clock(monkeypatch)
    turn = {"id": "old", "started": "x", "updated": clock["now"].isoformat(),
            "ended": clock["now"].isoformat(), "item": None, "steps": []}
    store.write_json_atomic(folder / ".moshfilm" / "activity.json", {"turn": turn, "plan": []})
    claude_edit(folder, 1, "s1")
    clock["now"] += timedelta(minutes=10)
    claude_edit(folder, 2, "s2")
    assert len(history.info(folder)["steps"]) == 3


def test_a_person_edit_ends_the_claude_group(folder, monkeypatch):
    clock = set_clock(monkeypatch)
    claude_edit(folder, 1, "s1")
    person(folder, [{"op": "set_pace", "pace": 1.5}])
    clock["now"] += timedelta(seconds=1)
    claude_edit(folder, 2, "s1")
    assert [s["kind"] for s in history.info(folder)["steps"]] == ["base", "claude", "person", "claude"]


def test_pending_claude_changes_are_recorded_before_a_person_edit(folder):
    (folder / "scenes" / "s2.js").write_text("export default { v: 'claude' }\n")  # watcher has not synced yet
    person(folder, [{"op": "set_pace", "pace": 1.5}])
    kinds = [s["kind"] for s in history.info(folder)["steps"]]
    assert kinds == ["base", "claude", "person"]
    history.undo(folder)  # undoes only the person's edit; Claude's file stays
    assert "claude" in (folder / "scenes" / "s2.js").read_text()
    assert film(folder).pace == 1.0


def test_claude_film_changes_get_readable_labels(folder, monkeypatch):
    set_clock(monkeypatch)
    f = film(folder)
    f.scenes.append(Scene(id="s4", title="four", length=3))
    filmmod.save_film(folder, f)
    history.sync(folder)
    assert history.info(folder)["steps"][-1]["label"] == "Claude: added scene 04"


# ------------------------------------------------------------------ concurrency


def test_concurrent_person_edits_all_land_and_history_stays_consistent(folder):
    errors: list[Exception] = []

    def work(i: int) -> None:
        try:
            person(folder, [{"op": "set_length", "scene": f"s{i % 3 + 1}", "length": 5 + i * 0.5}])
        except Exception as exc:  # noqa: BLE001
            errors.append(exc)

    threads = [threading.Thread(target=work, args=(i,)) for i in range(12)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert errors == []
    info = history.info(folder)
    assert len(info["steps"]) == 13
    ids = [s["id"] for s in info["steps"]]
    assert len(set(ids)) == 13
    final = film(folder).model_dump()
    for _ in range(12):
        history.undo(folder)
    for _ in range(12):
        history.redo(folder)
    assert film(folder).model_dump() == final


def test_undo_runs_under_the_folder_lock(folder, monkeypatch):
    person(folder, [{"op": "set_length", "scene": "s1", "length": 6}])
    held = []
    real = history._restore_state

    def spy(*a, **k):
        held.append(store.locked(folder).is_locked)
        return real(*a, **k)

    monkeypatch.setattr(history, "_restore_state", spy)
    history.undo(folder)
    assert held == [True]


def test_label_for_ops_uses_scene_numbers(folder):
    f = film(folder)
    assert history.label_for_ops(f, [{"op": "remove_scene", "scene": "s3"}]) == 'Removed scene 03 "scene 3"'
    assert history.label_for_ops(f, [{"op": "set_pace", "pace": 1.1}, {"op": "set_pace", "pace": 1.2}]) \
        == "Changed pace (+1 more)"
    assert json.dumps(history.label_for_ops(f, []))


# ------------------------------------------------------------------ review fix round 1


def test_undo_records_a_claude_write_that_lands_just_before_the_restore(folder, monkeypatch):
    person(folder, [{"op": "set_pace", "pace": 1.5}])
    real_ready = history._ready

    def ready_then_claude_writes(f, notify=None):
        idx = real_ready(f, notify)  # the sync is done ...
        (f / "scenes" / "s2.js").write_text("export default { v: 'late claude write' }\n")  # ... then Claude writes
        return idx

    monkeypatch.setattr(history, "_ready", ready_then_claude_writes)
    history.undo(folder)
    monkeypatch.undo()
    steps = history.info(folder)["steps"]
    assert [s["kind"] for s in steps] == ["base", "person", "claude"]
    assert any(s["label"] == "Claude: edited scene 02" for s in steps)  # recorded, not lost
    history.redo(folder)
    history.redo(folder)  # base -> the person's step -> Claude's late write: it can be brought back
    assert "late claude write" in (folder / "scenes" / "s2.js").read_text()


def test_scene_files_are_written_atomically_and_film_json_last(folder, monkeypatch):
    person(folder, [{"op": "set_pace", "pace": 1.5}])
    (folder / "scenes" / "s1.js").write_text("export default { v: 'x' }\n")
    history.sync(folder)
    order = []
    real_replace = history.os.replace
    monkeypatch.setattr(history.os, "replace", lambda a, b: (order.append(Path(b).name), real_replace(a, b))[1])
    real_json = store.write_json_atomic
    monkeypatch.setattr(store, "write_json_atomic", lambda p, d: (order.append(Path(p).name), real_json(p, d))[1])
    history.jump(folder, history.info(folder)["steps"][0]["id"])
    writes = [n for i, n in enumerate(order) if n in ("s1.js", "film.json") and (i == 0 or order[i - 1] != n)]
    assert writes == ["s1.js", "film.json"]  # the scene first, film.json last
    assert not list((folder / "scenes").glob("*.tmp"))


def test_history_info_is_read_only_and_does_not_sync(folder):
    (folder / "scenes" / "s1.js").write_text("export default { v: 'unrecorded' }\n")
    assert len(history.info(folder)["steps"]) == 1


def test_claude_write_after_an_undo_is_recorded_with_a_notice_that_redo_was_cleared(folder):
    person(folder, [{"op": "set_pace", "pace": 1.5}])
    history.undo(folder)
    assert history.info(folder)["can_redo"]
    notes: list[str] = []
    (folder / "scenes" / "s1.js").write_text("export default { v: 'claude' }\n")
    history.sync(folder, notes.append)
    assert not history.info(folder)["can_redo"]
    assert len(notes) == 1 and "after your undo" in notes[0] and "1 redo step was cleared" in notes[0]
    history.sync(folder, notes.append)
    assert len(notes) == 1  # nothing new, nothing said


def test_a_symlinked_scene_file_is_never_tracked_or_followed(folder, tmp_path):
    outside = tmp_path.parent / "outside-secret.js"
    outside.write_text("SECRET")
    (folder / "scenes" / "link.js").symlink_to(outside)
    history.sync(folder)
    person(folder, [{"op": "set_pace", "pace": 1.5}])
    snap = json.loads((folder / ".moshfilm" / "history" / history.info(folder)["steps"][-1]["file"]
                       if False else next((folder / ".moshfilm" / "history").glob("0000*.json"))).read_text())
    assert "scenes/link.js" not in snap["files"]
    history.undo(folder)
    assert outside.read_text() == "SECRET"


def test_only_top_level_scene_files_are_tracked(folder):
    (folder / "scenes" / "sub").mkdir()
    (folder / "scenes" / "sub" / "deep.js").write_text("x")
    (folder / "scenes" / ".hidden.js").write_text("x")
    assert sorted(history._tracked_files(folder)) == ["scenes/s1.js", "scenes/s2.js", "scenes/s3.js"]


def test_restore_refuses_snapshot_files_outside_the_scenes_folder(folder):
    person(folder, [{"op": "set_pace", "pace": 1.5}])
    idx_path = folder / ".moshfilm" / "history"
    first = json.loads((idx_path / "index.json").read_text())["steps"][0]["file"]
    snap = json.loads((idx_path / first).read_text())
    snap["files"]["scenes/../../evil.js"] = "boom"
    (idx_path / first).write_text(json.dumps(snap))
    with pytest.raises(history.HistoryError):
        history.undo(folder)
    assert not (folder.parent / "evil.js").exists()


@pytest.mark.parametrize("bad", ["../../etc/x.json", "abc.json", "000001.json/../x", "", None])
def test_a_step_file_name_that_is_not_six_digits_resets_the_history(folder, bad):
    person(folder, [{"op": "set_pace", "pace": 1.5}])
    p = folder / ".moshfilm" / "history" / "index.json"
    data = json.loads(p.read_text())
    data["steps"][1]["file"] = bad
    p.write_text(json.dumps(data))
    history.sync(folder)
    assert len(history.info(folder)["steps"]) == 1


def test_a_step_without_a_file_resets_the_history_and_says_so_once(folder):
    person(folder, [{"op": "set_pace", "pace": 1.5}])
    p = folder / ".moshfilm" / "history" / "index.json"
    data = json.loads(p.read_text())
    del data["steps"][1]["file"]
    p.write_text(json.dumps(data))
    notes: list[str] = []
    history.sync(folder, notes.append)
    history.sync(folder, notes.append)
    assert notes == ["History was reset (its files were damaged): earlier steps can no longer be undone."]


def test_the_index_is_saved_before_redo_snapshots_are_deleted(folder, monkeypatch):
    person(folder, [{"op": "set_pace", "pace": 1.5}])
    history.undo(folder)
    events = []
    real_save, real_drop = history._save, history._drop
    monkeypatch.setattr(history, "_save", lambda f, i: (events.append("save"), real_save(f, i))[1])
    monkeypatch.setattr(history, "_drop", lambda f, s: (events.append("drop"), real_drop(f, s))[1])
    person(folder, [{"op": "set_pace", "pace": 1.2}])
    assert events.index("save") < events.index("drop")
    idx = json.loads((folder / ".moshfilm" / "history" / "index.json").read_text())
    assert all((folder / ".moshfilm" / "history" / s["file"]).is_file() for s in idx["steps"])
