import json
import os

import pytest

from moshfilm import film, hooks
from moshfilm.cli import main


def settings(folder):
    return json.loads((folder / ".claude" / "settings.local.json").read_text())


def ours(data):
    return [(ev, h["command"]) for ev, groups in data["hooks"].items() for g in groups for h in g["hooks"]
            if "moshfilm" in h["command"]]


def test_install_writes_all_events(tmp_path):
    assert hooks.install(tmp_path) is True
    data = settings(tmp_path)
    assert set(data["hooks"]) == {"UserPromptSubmit", "PreToolUse", "PostToolUse", "PostToolUseFailure", "Stop"}
    assert all(cmd.endswith(" -I -m moshfilm.hook") for _, cmd in ours(data))
    assert data["hooks"]["Stop"][0]["hooks"][0]["type"] == "command"


def test_install_keeps_existing_keys_and_is_idempotent(tmp_path):
    path = tmp_path / ".claude" / "settings.local.json"
    path.parent.mkdir()
    other = {"type": "command", "command": "echo mine"}
    path.write_text(json.dumps({"permissions": {"allow": ["Bash(ls)"]},
                                "hooks": {"Stop": [{"hooks": [other]}], "Notification": [{"hooks": [other]}]}}))
    hooks.install(tmp_path)
    first = path.read_text()
    assert hooks.install(tmp_path) is False  # nothing changed
    assert path.read_text() == first
    data = settings(tmp_path)
    assert data["permissions"] == {"allow": ["Bash(ls)"]}
    assert data["hooks"]["Notification"] == [{"hooks": [other]}]
    assert {"hooks": [other]} in data["hooks"]["Stop"]
    assert len(ours(data)) == 5


def test_uninstall_removes_only_ours(tmp_path):
    path = tmp_path / ".claude" / "settings.local.json"
    path.parent.mkdir()
    other = {"type": "command", "command": "echo mine"}
    path.write_text(json.dumps({"model": "x", "hooks": {"Stop": [{"hooks": [other]}]}}))
    hooks.install(tmp_path)
    assert hooks.uninstall(tmp_path) is True
    assert settings(tmp_path) == {"model": "x", "hooks": {"Stop": [{"hooks": [other]}]}}
    assert hooks.uninstall(tmp_path) is False


def test_uninstall_deletes_file_it_created(tmp_path):
    hooks.install(tmp_path)
    hooks.uninstall(tmp_path)
    assert not (tmp_path / ".claude").exists()


def test_broken_settings_is_not_overwritten(tmp_path, capsys):
    path = tmp_path / ".claude" / "settings.local.json"
    path.parent.mkdir()
    path.write_text("{oops")
    assert main(["hooks", "install", str(tmp_path)]) == 1
    assert path.read_text() == "{oops"


def test_cli_install_uninstall(tmp_path):
    assert main(["hooks", "install", str(tmp_path)]) == 0
    assert main(["hooks", "install", str(tmp_path)]) == 0
    assert len(ours(settings(tmp_path))) == 5
    assert main(["hooks", "install", str(tmp_path), "--uninstall"]) == 0
    assert not (tmp_path / ".claude").exists()


def test_new_and_sample_install_by_default(tmp_path):
    assert main(["new", str(tmp_path / "a")]) == 0
    assert ours(settings(tmp_path / "a"))
    assert main(["new", str(tmp_path / "b"), "--no-hooks"]) == 0
    assert not (tmp_path / "b" / ".claude").exists()
    assert main(["sample", str(tmp_path / "c")]) == 0
    assert ours(settings(tmp_path / "c"))
    assert main(["sample", str(tmp_path / "d"), "--no-hooks"]) == 0
    assert not (tmp_path / "d" / ".claude").exists()


def test_never_touches_home_settings(tmp_path, monkeypatch):
    home = tmp_path / "home"
    (home / ".claude").mkdir(parents=True)
    monkeypatch.setenv("HOME", str(home))
    before = sorted(p.name for p in (home / ".claude").iterdir())
    main(["new", str(tmp_path / "f")])
    assert sorted(p.name for p in (home / ".claude").iterdir()) == before


def test_old_style_install_is_recognised_and_replaced(tmp_path):
    path = tmp_path / ".claude" / "settings.local.json"
    path.parent.mkdir()
    old = {"type": "command", "command": "/x/.venv/bin/moshfilm activity", "timeout": 5}
    path.write_text(json.dumps({"hooks": {"Stop": [{"hooks": [old]}]}}))
    hooks.install(tmp_path)
    assert old not in [h for g in settings(tmp_path)["hooks"]["Stop"] for h in g["hooks"]]
    assert len(ours(settings(tmp_path))) == 5


@pytest.mark.parametrize("body", ['{"hooks": {"Stop": {}}}', '{"hooks": {"Stop": ["x"]}}', '{"hooks": []}', "[]"])
def test_odd_shapes_are_refused_not_crashed(tmp_path, body):
    path = tmp_path / ".claude" / "settings.local.json"
    path.parent.mkdir()
    path.write_text(body)
    assert main(["hooks", "install", str(tmp_path)]) == 1
    assert main(["hooks", "install", str(tmp_path), "--uninstall"]) == 1
    assert path.read_text() == body


def test_new_and_sample_survive_odd_settings(tmp_path):
    # a folder that already has a bad settings file: the film is still created, hooks are skipped
    for name in ("new", "sample"):
        target = tmp_path / name
        (target / ".claude").mkdir(parents=True)
        (target / ".claude" / "settings.local.json").write_text('{"hooks": {"Stop": {}}}')
        if name == "sample":
            assert main(["sample", str(target)]) == 1  # sample refuses a non-empty folder; must not crash
        else:
            assert main(["new", str(target)]) == 0
            assert (target / "film.json").exists()


def test_symlinked_claude_dir_is_refused(tmp_path):
    outside = tmp_path / "outside"
    outside.mkdir()
    film_dir = tmp_path / "film"
    film_dir.mkdir()
    (film_dir / ".claude").symlink_to(outside)
    assert main(["hooks", "install", str(film_dir)]) == 1
    assert list(outside.iterdir()) == []


def test_symlinked_settings_file_is_refused(tmp_path):
    target = tmp_path / "elsewhere.json"
    target.write_text("{}")
    film_dir = tmp_path / "film"
    (film_dir / ".claude").mkdir(parents=True)
    (film_dir / ".claude" / "settings.local.json").symlink_to(target)
    assert main(["hooks", "install", str(film_dir)]) == 1
    assert target.read_text() == "{}"
    assert (film_dir / ".claude" / "settings.local.json").is_symlink()


def test_installed_command_is_isolated(tmp_path):
    hooks.install(tmp_path)
    assert all(" -I -m moshfilm.hook" in cmd for _, cmd in ours(settings(tmp_path)))


def test_previous_unisolated_command_is_replaced(tmp_path):
    path = tmp_path / ".claude" / "settings.local.json"
    path.parent.mkdir()
    old = {"type": "command", "command": "/x/python -m moshfilm.hook", "timeout": 5}
    path.write_text(json.dumps({"hooks": {"Stop": [{"hooks": [old]}]}}))
    hooks.install(tmp_path)
    assert old not in [h for g in settings(tmp_path)["hooks"]["Stop"] for h in g["hooks"]]
    assert len(ours(settings(tmp_path))) == 5


@pytest.mark.parametrize("planted", ["json.py", "filelock.py", "moshfilm.py"])
def test_planted_module_in_the_film_does_not_run(tmp_path, planted):
    import shlex
    import subprocess
    import sys
    if subprocess.run([sys.executable, "-I", "-c", "import moshfilm.hook"], cwd=tmp_path).returncode != 0:
        pytest.skip("moshfilm is not installed for this Python (isolated mode ignores PYTHONPATH); pip install -e .")
    film.new_film(tmp_path, "t")
    marker = tmp_path / "ran"
    (tmp_path / planted).write_text(f"open({str(marker)!r}, 'w').write('x')\nraise SystemExit(7)\n")
    hooks.install(tmp_path)
    command = next(c for _, c in ours(settings(tmp_path)))
    payload = json.dumps({"hook_event_name": "PreToolUse", "cwd": str(tmp_path), "tool_name": "Bash",
                          "tool_input": {"command": "ls"}, "tool_use_id": "a"})
    env = {**os.environ, "PYTHONPATH": str(__import__("pathlib").Path(hooks.__file__).parent.parent)}
    done = subprocess.run(shlex.split(command), input=payload, text=True, cwd=tmp_path, env=env)
    assert done.returncode == 0
    assert not marker.exists()


def test_hook_main_swallows_system_exit(monkeypatch):
    import io
    from moshfilm import activity, hook

    def boom(_payload):
        raise SystemExit(2)

    monkeypatch.setattr(activity, "handle_hook", boom)
    monkeypatch.setattr("sys.stdin", io.StringIO("{}"))
    assert hook.main() == 0
