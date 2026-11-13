import os
import shutil
import subprocess
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "setup.sh"


def test_syntax():
    subprocess.run(["bash", "-n", str(SCRIPT)], check=True)


def test_script_text():
    text = SCRIPT.read_text(encoding="utf-8")
    assert "set -euo pipefail" in text
    assert ("ffmpeg not found. Install it (macOS: brew install ffmpeg; Debian/Ubuntu: "
            "sudo apt install ffmpeg) and run setup again.") in text
    assert "moshFilm needs Python 3.11 or newer" in text
    for flag in ("--no-skill", "--skill", "--no-path", "--path", "--dry-run"):
        assert flag in text


@pytest.mark.skipif(not shutil.which("shellcheck"), reason="shellcheck not installed")
def test_shellcheck():
    subprocess.run(["shellcheck", str(SCRIPT)], check=True)


def _run(tmp_path, *args, stdin=""):
    home = tmp_path / "home"
    home.mkdir(exist_ok=True)
    env = {**os.environ, "HOME": str(home)}
    return home, subprocess.run(["bash", str(SCRIPT), "--dry-run", *args], env=env, input=stdin,
                                capture_output=True, text=True)


def test_dry_run_writes_nothing_and_never_touches_home(tmp_path):
    home, r = _run(tmp_path, "--skill", "--no-path")
    assert r.returncode == 0, r.stdout + r.stderr
    assert list(home.rglob("*")) == []
    assert str(home / ".claude" / "skills" / "moshfilm") in r.stdout


def test_dry_run_no_skill_mentions_nothing_in_claude(tmp_path):
    home, r = _run(tmp_path, "--no-skill", "--no-path")
    assert r.returncode == 0, r.stdout + r.stderr
    assert "would run: mkdir -p" not in r.stdout
    assert "inked skill" not in r.stdout
    assert list(home.rglob("*")) == []


def test_dry_run_asks_before_writing_outside_repo(tmp_path):
    # no flags, no terminal: the script must not write; it prints what it would ask
    home, r = _run(tmp_path, stdin="")
    assert r.returncode == 0, r.stdout + r.stderr
    assert list(home.rglob("*")) == []
    assert "skipped" in r.stdout.lower()
