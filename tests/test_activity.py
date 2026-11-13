import json

import pytest

from moshfilm import activity, film, queue
from moshfilm.cli import main


@pytest.fixture
def folder(tmp_path):
    film.new_film(tmp_path, "t")
    f = film.load_film(tmp_path)
    f.scenes = [film.Scene(id=f"s{i}", title=f"Scene {i}", file=f"scenes/s{i}.js", length=3) for i in (1, 2, 3)]
    film.save_film(tmp_path, f)
    return tmp_path


def payload(folder, event, tool=None, tool_input=None, **extra):
    out = {"hook_event_name": event, "cwd": str(folder), **extra}
    if tool:
        out["tool_name"] = tool
        out["tool_input"] = tool_input or {}
    return out


@pytest.mark.parametrize("tool,inp,label", [
    ("Read", {"file_path": "scenes/s3.js"}, "Reading scene 03"),
    ("Edit", {"file_path": "scenes/s3.js", "old_string": "SECRET", "new_string": "x"}, "Editing scene 03"),
    ("Write", {"file_path": "{folder}/scenes/s2.js", "content": "SECRET"}, "Editing scene 02"),
    ("Read", {"file_path": "film.json"}, "Reading film.json"),
    ("Read", {"file_path": "/etc/passwd"}, "Reading a file"),
    ("Read", {"file_path": "sources/notes.md"}, "Reading a source document"),
    ("Edit", {"file_path": "scenes/lockers.js"}, "Editing a scene helper"),
    ("Write", {"file_path": "/home/x/.env"}, "Editing a file"),
    ("Bash", {"command": "moshfilm check ."}, "Checking the film"),
    ("Bash", {"command": ".venv/bin/moshfilm voice /f && echo TOKEN=abc"}, "Making narration"),
    ("Bash", {"command": "moshfilm export /f --format gif"}, "Exporting"),
    ("Bash", {"command": "curl -H 'Authorization: Bearer abc' https://x"}, "Running a command"),
    ("Grep", {"pattern": "password"}, "Searching the film"),
    ("WebFetch", {"url": "https://x"}, "Looking something up"),
    ("mcp__x__y", {}, "Using a tool"),
])
def test_labels(folder, tool, inp, label):
    inp = {k: v.replace("{folder}", str(folder)) if isinstance(v, str) else v for k, v in inp.items()}
    assert activity.label_for(folder, tool, inp) == label


@pytest.mark.parametrize("cmd", ["moshfilm plan f --done 1", "moshfilm status f hi", "moshfilm watch f --once",
                                 "moshfilm activity"])
def test_bookkeeping_commands_have_no_label(folder, cmd):
    assert activity.label_for(folder, "Bash", {"command": cmd}) is None


def test_scene_number_falls_back_to_digits(tmp_path):
    film.new_film(tmp_path, "t")
    assert activity.label_for(tmp_path, "Read", {"file_path": "scenes/s7.js"}) == "Reading scene 07"


def test_turn_lifecycle(folder):
    activity.handle_hook(payload(folder, "PreToolUse", "Read", {"file_path": "scenes/s1.js"}, tool_use_id="a"))
    activity.handle_hook(payload(folder, "PostToolUse", "Read", {"file_path": "scenes/s1.js"}, tool_use_id="a"))
    activity.handle_hook(payload(folder, "PreToolUse", "Bash", {"command": "ls"}, tool_use_id="b"))
    activity.handle_hook(payload(folder, "PostToolUseFailure", "Bash", {"command": "ls"}, tool_use_id="b"))
    activity.handle_hook(payload(folder, "PreToolUse", "Bash", {"command": "ls"}, tool_use_id="c"))
    snap = activity.snapshot(folder)
    turn = snap["turn"]
    assert [(s["label"], s["state"]) for s in turn["steps"]] == [
        ("Reading scene 01", "done"), ("Running a command", "failed"), ("Running a command", "running")]
    assert turn["ended"] is None
    activity.handle_hook(payload(folder, "Stop"))
    turn = activity.snapshot(folder)["turn"]
    assert turn["ended"] and all(s["state"] != "running" for s in turn["steps"])


def test_post_with_error_marks_failed(folder):
    activity.handle_hook(payload(folder, "PreToolUse", "Bash", {"command": "ls"}, tool_use_id="a"))
    activity.handle_hook(payload(folder, "PostToolUse", "Bash", {"command": "ls"}, tool_use_id="a",
                                 tool_response={"is_error": True, "stdout": "SECRET"}))
    activity.handle_hook(payload(folder, "PreToolUse", "Bash", {"command": "ls"}, tool_use_id="b"))
    activity.handle_hook(payload(folder, "PostToolUse", "Bash", {"command": "ls"}, tool_use_id="b",
                                 tool_response={"exit_code": 2}))
    steps = activity.snapshot(folder)["turn"]["steps"]
    assert [s["state"] for s in steps] == ["failed", "failed"]
    assert "SECRET" not in json.dumps(activity.snapshot(folder))


def test_new_turn_after_stop_remembers_anchor(folder):
    queue.add_item(folder, "chat", "hi")
    queue.take_queued(folder)
    activity.handle_hook(payload(folder, "PreToolUse", "Read", {"file_path": "film.json"}, tool_use_id="a"))
    first = activity.snapshot(folder)["turn"]
    assert first["item"] == "q1"
    activity.handle_hook(payload(folder, "Stop"))
    activity.handle_hook(payload(folder, "PreToolUse", "Read", {"file_path": "film.json"}, tool_use_id="b"))
    second = activity.snapshot(folder)["turn"]
    assert second["id"] != first["id"] and len(second["steps"]) == 1


def test_stale_turn_is_closed(folder, monkeypatch):
    activity.handle_hook(payload(folder, "PreToolUse", "Read", {"file_path": "film.json"}, tool_use_id="a"))
    data = activity._load(folder)
    data["turn"]["updated"] = "2020-01-01T00:00:00.000+00:00"
    activity._save(folder, data)
    turn = activity.snapshot(folder)["turn"]
    assert turn["ended"] == "2020-01-01T00:00:00.000+00:00"


def test_non_film_cwd_does_nothing(tmp_path):
    activity.handle_hook(payload(tmp_path, "PreToolUse", "Read", {"file_path": "x"}))
    assert not (tmp_path / ".moshfilm").exists()


def test_plan(folder):
    activity.set_plan(folder, ["one", "two"])
    activity.plan_done(folder, 2)
    assert activity.snapshot(folder)["plan"] == [{"text": "one", "done": False}, {"text": "two", "done": True}]
    with pytest.raises(IndexError):
        activity.plan_done(folder, 3)
    activity.clear_plan(folder)
    assert activity.snapshot(folder)["plan"] == []


def test_cli_activity_reads_stdin_and_never_fails(folder, monkeypatch, capsys):
    import io
    body = json.dumps(payload(folder, "PreToolUse", "Bash", {"command": "moshfilm check f"}, tool_use_id="a"))
    monkeypatch.setattr("sys.stdin", io.StringIO(body))
    assert main(["activity"]) == 0
    assert activity.snapshot(folder)["turn"]["steps"][0]["label"] == "Checking the film"
    for junk in ("", "not json", "[]", '{"cwd": 5}'):
        monkeypatch.setattr("sys.stdin", io.StringIO(junk))
        assert main(["activity"]) == 0
    assert capsys.readouterr().out == ""


def test_cli_plan(folder, capsys):
    assert main(["plan", str(folder), "--set", "a", "b"]) == 0
    assert main(["plan", str(folder), "--done", "1"]) == 0
    assert activity.snapshot(folder)["plan"][0]["done"] is True
    assert main(["plan", str(folder), "--done", "9"]) == 2
    assert main(["plan", str(folder), "--clear"]) == 0
    assert activity.snapshot(folder)["plan"] == []


def test_scene_steps_carry_scene_and_action(folder):
    activity.handle_hook(payload(folder, "PreToolUse", "Read", {"file_path": "scenes/s2.js"}, tool_use_id="a"))
    activity.handle_hook(payload(folder, "PreToolUse", "Edit", {"file_path": "scenes/s3.js"}, tool_use_id="b"))
    activity.handle_hook(payload(folder, "PreToolUse", "Edit", {"file_path": "scenes/helper.js"}, tool_use_id="c"))
    steps = activity.snapshot(folder)["turn"]["steps"]
    assert [(s.get("scene"), s.get("action")) for s in steps] == [("s2", "read"), ("s3", "edit"), (None, None)]


def test_step_ids_stay_unique_past_the_cap(folder):
    for i in range(activity.MAX_STEPS + 15):
        activity.handle_hook(payload(folder, "PreToolUse", "Read", {"file_path": "film.json"}, tool_use_id=str(i)))
    ids = [s["id"] for s in activity.snapshot(folder)["turn"]["steps"]]
    assert len(ids) == activity.MAX_STEPS and len(set(ids)) == len(ids) and ids == sorted(ids)
    assert ids[-1] == activity.MAX_STEPS + 15


def test_new_prompt_ends_an_open_turn(folder):
    activity.handle_hook(payload(folder, "PreToolUse", "Bash", {"command": "ls"}, tool_use_id="a"))
    first = activity.snapshot(folder)["turn"]["id"]
    activity.handle_hook(payload(folder, "UserPromptSubmit", prompt="next"))
    turn = activity.snapshot(folder)["turn"]
    assert turn["ended"] and turn["steps"][0]["state"] == "done"
    activity.handle_hook(payload(folder, "PreToolUse", "Bash", {"command": "ls"}, tool_use_id="b"))
    assert activity.snapshot(folder)["turn"]["id"] != first
    assert "next" not in json.dumps(activity.snapshot(folder))


def test_scene_id_comes_from_film_json_not_the_file_name(tmp_path):
    film.new_film(tmp_path, "t")
    f = film.load_film(tmp_path)
    f.scenes = [film.Scene(id="intro", title="I", file="scenes/opening.js", length=3),
                film.Scene(id="outro", title="O", file="scenes/closing.js", length=3)]
    film.save_film(tmp_path, f)
    assert activity.scene_of(tmp_path, "Edit", {"file_path": "scenes/closing.js"}) == "outro"
    assert activity.label_for(tmp_path, "Edit", {"file_path": "scenes/closing.js"}) == "Editing scene 02"
    activity.handle_hook(payload(tmp_path, "PreToolUse", "Edit", {"file_path": "scenes/closing.js"}, tool_use_id="a"))
    assert activity.snapshot(tmp_path)["turn"]["steps"][0]["scene"] == "outro"
    assert activity.scene_of(tmp_path, "Edit", {"file_path": "scenes/unknown.js"}) is None


def test_hook_gives_up_quickly_when_the_lock_is_held(folder):
    import time

    from moshfilm import store
    lock = store.locked(folder)
    import threading
    got = threading.Event()
    release = threading.Event()

    def hold():
        with lock:
            got.set()
            release.wait(5)

    t = threading.Thread(target=hold)
    t.start()
    got.wait(2)
    try:
        start = time.time()
        assert activity.handle_hook(payload(folder, "PreToolUse", "Bash", {"command": "ls"}), lock_timeout=0.2) is False
        assert time.time() - start < 2
    finally:
        release.set()
        t.join()
    assert activity.snapshot(folder)["turn"] is None


def test_hook_module_runs_without_the_cli(folder, monkeypatch):
    import io

    from moshfilm import hook
    body = json.dumps(payload(folder, "PreToolUse", "Bash", {"command": "moshfilm export f"}, tool_use_id="a"))
    monkeypatch.setattr("sys.stdin", io.StringIO(body))
    assert hook.main() == 0
    assert activity.snapshot(folder)["turn"]["steps"][0]["label"] == "Exporting"
    monkeypatch.setattr("sys.stdin", io.StringIO("junk"))
    assert hook.main() == 0


def test_activity_module_does_not_pull_in_pydantic():
    import subprocess
    import sys
    code = "import sys, moshfilm.activity, moshfilm.hook; sys.exit(1 if 'pydantic' in sys.modules else 0)"
    assert subprocess.run([sys.executable, "-c", code]).returncode == 0


def test_plan_refuses_a_folder_without_a_film(tmp_path, capsys):
    assert main(["plan", str(tmp_path), "--set", "a"]) == 1
    assert "not a film folder" in capsys.readouterr().err
    assert not (tmp_path / ".moshfilm").exists()
