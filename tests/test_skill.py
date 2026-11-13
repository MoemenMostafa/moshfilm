import json
import re
import shutil
from pathlib import Path

import pytest

from moshfilm import cli, film, proposals

ROOT = Path(__file__).resolve().parent.parent
SKILL = ROOT / "skill" / "moshfilm"


def _commands() -> set[str]:
    sub = next(a for a in cli.build_parser()._actions if a.dest == "command")
    return set(sub.choices)


def test_frontmatter():
    text = (SKILL / "SKILL.md").read_text(encoding="utf-8")
    head = text.split("---")[1]
    assert "name: moshfilm" in head
    assert ("description: Use when the person wants to make or change a short motion-graphics "
            "film with moshFilm, or when a moshFilm chat message or frame comment arrives") in head


def test_commands_in_skill_exist():
    text = (SKILL / "SKILL.md").read_text(encoding="utf-8")
    used = set(re.findall(r"moshfilm ([a-z][a-z-]*)", text)) - {"skill", "folder"}
    assert used, "SKILL.md names no commands"
    assert used <= _commands(), used - _commands()


def test_skill_covers_core_commands():
    text = (SKILL / "SKILL.md").read_text(encoding="utf-8")
    for word in ("open", "watch", "reply", "say", "status", "propose", "check", "voice", "export"):
        assert f"moshfilm {word}" in text
    assert "voice doesn't fit — stretch scene or shorten line" in text
    assert "--force" not in text


def test_example_scene_passes_check(tmp_path):
    folder = tmp_path / "f"
    film.new_film(folder, "Example")
    shutil.copy(SKILL / "examples" / "example-scene.js", folder / "scenes" / "s1.js")
    proposals.add_proposal(folder, {"changes": [{"op": "add_scene", "scene": {
        "id": "s1", "title": "Bar", "file": "scenes/s1.js", "length": 4, "status": "ready"}}]})
    proposals.process_pending(folder)
    assert film.load_film(folder).scenes[0].status == "ready"
    assert film.check_film(folder) == []


def test_example_scene_follows_contract():
    src = (SKILL / "examples" / "example-scene.js").read_text(encoding="utf-8")
    assert "export default" in src and "setup(" in src and "render(" in src


def test_example_proposal_valid(tmp_path):
    folder = tmp_path / "f"
    film.new_film(folder, "Example")
    data = json.loads((SKILL / "examples" / "example-proposal.json").read_text(encoding="utf-8"))
    assert data["needs_approval"] is True
    assert sum(c["op"] == "add_scene" for c in data["changes"]) == 2
    proposals.add_proposal(folder, data)


def test_skill_teaches_sound():
    from moshfilm.sound import sfx

    text = (SKILL / "SKILL.md").read_text(encoding="utf-8")
    for word in ("add_sfx", "set_music", "moshfilm sounds", "0.35", "at most 3", *sfx.PRESETS):
        assert word in text, word


def test_sound_example_proposal_is_valid(tmp_path):
    data = json.loads((SKILL / "examples" / "example-sound-proposal.json").read_text(encoding="utf-8"))
    assert data["needs_approval"] is False
    assert [c["op"] for c in data["changes"]] == ["set_music", "add_sfx", "add_sfx"]
    proposal = proposals.Proposal.model_validate({**data, "id": "p1", "created": "x"})
    f = film.Film.model_validate({"title": "t", "scenes": [{"id": "s1", "title": "a", "length": 5},
                                                          {"id": "s2", "title": "b", "length": 5}]})
    result = proposals.apply_proposal(f, proposal)
    assert result.held == [] and len(result.applied) == 3
    assert result.film.music.bed.mood == "calm" and result.film.music.pinned is False
    assert [(c.scene, c.preset, c.at) for c in result.film.sfx] == [("s1", "pop", 1.2), ("s2", "ding", 0.4)]


def test_sample_command_without_bundle_or_with_one(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(cli, "SAMPLE_DIR", tmp_path / "nope")
    assert cli.main(["sample", str(tmp_path / "out")]) == 1
    assert "sample not bundled" in capsys.readouterr().err
    bundle = tmp_path / "bundle"
    film.new_film(bundle, "Sample")
    monkeypatch.setattr(cli, "SAMPLE_DIR", bundle)
    assert cli.main(["sample", str(tmp_path / "out")]) == 0
    assert (tmp_path / "out" / "film.json").is_file()
    assert cli.main(["sample", str(tmp_path / "out")]) == 1


def test_skill_names_attachment_and_exact_nondeterminism_terms():
    text = (SKILL / "SKILL.md").read_text(encoding="utf-8")
    assert "`attachment`" in text
    assert "`Date.now`, `new Date`" in text


def test_skill_teaches_responsive_scenes():
    text = (SKILL / "SKILL.md").read_text(encoding="utf-8")
    for word in ("ctx.width", "ctx.height", "--layout", "portrait", "aspect"):
        assert word in text, word


def test_example_scene_has_no_fixed_layout():
    src = (SKILL / "examples" / "example-scene.js").read_text(encoding="utf-8")
    assert not re.findall(r"\b(x|y|width)\s*:\s*\d{3,}", src)


def _have_chromium() -> bool:
    try:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            return Path(p.chromium.executable_path).exists()
    except Exception:
        return False


@pytest.mark.slow
@pytest.mark.skipif(not _have_chromium(), reason="Playwright Chromium not installed (run scripts/setup.sh)")
def test_example_scene_fits_every_shape(tmp_path):
    from moshfilm import aspects, layout_check
    folder = tmp_path / "f"
    film.new_film(folder, "Example")
    shutil.copy(SKILL / "examples" / "example-scene.js", folder / "scenes" / "s1.js")
    f = film.load_film(folder)
    f.scenes = [film.Scene(id="s1", title="Bar", file="scenes/s1.js", length=4, status="ready", pinned=True)]
    film.save_film(folder, f)
    assert layout_check.check_layout(folder, list(aspects.ALL)) == []
