import io
import json
from pathlib import Path

import pytest

from moshfilm import film as filmmod
from moshfilm import proposals
from moshfilm.cli import main
from moshfilm.film import Scene, TextClip, VoiceLine


@pytest.fixture
def folder(tmp_path: Path) -> Path:
    filmmod.new_film(tmp_path, "t")
    f = filmmod.load_film(tmp_path)
    f.scenes = [
        Scene(id="s1", title="one", length=9, pinned=True,
              voice=VoiceLine(text="old", offset=1.0, pinned=True)),
        Scene(id="s2", title="two", length=5),
    ]
    f.texts = [TextClip(id="t1", scene="s1", text="cap", start=2, pinned=True)]
    f.order_pinned = True
    filmmod.save_film(tmp_path, f)
    return tmp_path


def rebuild() -> dict:
    return {"summary": "rebuild", "changes": [
        {"op": "set_scene", "id": "s1", "length": 4},
        {"op": "set_voice", "id": "s1", "offset": 0.2, "text": "new words"},
        {"op": "set_text", "id": "t1", "start": 0},
        {"op": "move_scene", "id": "s1", "index": 1},
        {"op": "add_scene", "scene": {"id": "s3", "title": "three", "length": 3}, "after": None},
    ]}


def test_rebuild_never_changes_pinned_values(folder):
    pid = proposals.add_proposal(folder, rebuild()).id
    out = proposals.process_pending(folder)
    assert [p.id for p in out] == [pid]
    f = filmmod.load_film(folder)
    s1 = f.scenes[0]
    assert s1.id == "s1" and s1.length == 9 and s1.voice.offset == 1.0
    assert s1.voice.text == "new words"
    assert f.texts[0].start == 2
    assert [s.id for s in f.scenes] == ["s1", "s2", "s3"]
    p = out[0]
    assert p.status == "partial" and p.held == [0, 1, 2, 3]


def test_unpinned_changes_apply_automatically(folder):
    f = filmmod.load_film(folder)
    f.scenes[0].pinned = f.scenes[0].voice.pinned = f.texts[0].pinned = f.order_pinned = False
    filmmod.save_film(folder, f)
    proposals.add_proposal(folder, rebuild())
    (p,) = proposals.process_pending(folder)
    assert p.status == "applied" and p.held == []
    f = filmmod.load_film(folder)
    assert [s.id for s in f.scenes] == ["s2", "s1", "s3"]
    assert f.scenes[1].length == 4 and f.scenes[1].voice.offset == 0.2 and f.texts[0].start == 0
    assert not f.scenes[1].pinned  # automatic changes do not pin


def test_needs_approval_waits_then_applies(folder):
    data = {**rebuild(), "needs_approval": True}
    pid = proposals.add_proposal(folder, data).id
    before = filmmod.load_film(folder)
    (p,) = proposals.process_pending(folder)
    assert p.status == "awaiting_approval"
    assert filmmod.load_film(folder) == before
    done = proposals.approve(folder, pid, include_pinned=False)
    assert done.status == "partial" and done.held == [0, 1, 2, 3]
    assert [s.id for s in filmmod.load_film(folder).scenes] == ["s1", "s2", "s3"]


def test_needs_approval_applied_when_nothing_pinned(folder):
    pid = proposals.add_proposal(folder, {"needs_approval": True, "changes": [
        {"op": "add_scene", "scene": {"id": "s3", "title": "x", "length": 2}}]}).id
    proposals.process_pending(folder)
    assert proposals.approve(folder, pid, include_pinned=False).status == "applied"


def test_approve_include_pinned_overrides(folder):
    pid = proposals.add_proposal(folder, rebuild()).id
    proposals.process_pending(folder)
    done = proposals.approve(folder, pid, include_pinned=True)
    assert done.status == "applied" and done.held == []
    f = filmmod.load_film(folder)
    assert [s.id for s in f.scenes] == ["s2", "s1", "s3"]
    s1 = f.scenes[1]
    assert s1.length == 4 and s1.voice.offset == 0.2 and f.texts[0].start == 0
    assert s1.pinned and s1.voice.pinned and f.texts[0].pinned and f.order_pinned


def test_approve_pending_runs_it_first(folder):
    pid = proposals.add_proposal(folder, rebuild()).id
    assert proposals.approve(folder, pid, include_pinned=True).status == "applied"


def test_invalid_proposal_marked_and_reported(folder):
    pid = proposals.add_proposal(folder, {"changes": [
        {"op": "set_scene", "id": "nope", "title": "x"}]}).id
    events: list[str] = []
    (p,) = proposals.process_pending(folder, events.append)
    assert p.status == "invalid" and "nope" in p.error
    assert len(events) == 1 and pid in events[0] and "nope" in events[0]
    stored = json.loads((folder / "proposals.json").read_text())["proposals"][0]
    assert stored["status"] == "invalid" and "nope" in stored["error"]
    assert proposals.process_pending(folder, events.append) == []
    assert len(events) == 1


def test_hand_edited_garbage_on_disk_is_invalid_not_a_crash(folder):
    (folder / "proposals.json").write_text(json.dumps({"proposals": [
        {"id": "p1", "created": "x", "status": "pending", "changes": [{"op": "explode"}]}]}))
    events: list[str] = []
    proposals.process_pending(folder, events.append)
    stored = json.loads((folder / "proposals.json").read_text())["proposals"][0]
    assert stored["status"] == "invalid" and stored["error"]
    assert len(events) == 1 and "p1" in events[0]


def test_failed_proposal_changes_nothing(folder):
    proposals.add_proposal(folder, {"changes": [
        {"op": "add_scene", "scene": {"id": "s3", "title": "x", "length": 2}},
        {"op": "remove_text", "id": "nope"}]})
    before = filmmod.load_film(folder)
    proposals.process_pending(folder)
    assert filmmod.load_film(folder) == before


def test_proposal_bounds_and_validation(folder):
    for bad in ({"changes": [{"op": "set_scene", "id": "s2", "length": 0.1}]},
                {"changes": [{"op": "set_scene", "id": "s2", "length": 9999}]},
                {"changes": [{"op": "nope"}]},
                {"summary": "no changes"}):
        with pytest.raises(proposals.ProposalError):
            proposals.add_proposal(folder, bad)
    assert [p for p in json.loads((folder / "proposals.json").read_text())["proposals"]] == []


def test_ids_increment_and_reject(folder):
    a = proposals.add_proposal(folder, {"changes": []})
    b = proposals.add_proposal(folder, {"changes": []})
    assert (a.id, b.id) == ("p1", "p2")
    assert proposals.reject(folder, "p2").status == "rejected"
    with pytest.raises(proposals.ProposalError):
        proposals.reject(folder, "p9")


def test_remove_pinned_is_held(folder):
    proposals.add_proposal(folder, {"changes": [
        {"op": "remove_scene", "id": "s1"}, {"op": "remove_text", "id": "t1"},
        {"op": "remove_scene", "id": "s2"}]})
    (p,) = proposals.process_pending(folder)
    f = filmmod.load_film(folder)
    assert [s.id for s in f.scenes] == ["s1"] and len(f.texts) == 1
    assert p.held == [0, 1] and p.status == "partial"


def test_add_scene_after_and_text(folder):
    proposals.add_proposal(folder, {"changes": [
        {"op": "add_scene", "scene": {"id": "s3", "title": "x", "length": 2}, "after": "s1"},
        {"op": "add_text", "text": {"id": "t2", "scene": "s3", "text": "hello"}}]})
    (p,) = proposals.process_pending(folder)
    f = filmmod.load_film(folder)
    assert p.status == "applied"
    assert [s.id for s in f.scenes] == ["s1", "s3", "s2"] and f.texts[1].id == "t2"


def test_cli_propose_from_stdin(folder, monkeypatch, capsys):
    monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps({"summary": "x", "changes": []})))
    assert main(["propose", str(folder), "-"]) == 0
    assert capsys.readouterr().out.strip() == "p1"
    monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps({"changes": [{"op": "bad"}]})))
    assert main(["propose", str(folder), "-"]) == 2
    assert capsys.readouterr().err.startswith("error:")
    monkeypatch.setattr("sys.stdin", io.StringIO("not json"))
    assert main(["propose", str(folder), "-"]) == 2


def _clip(folder, pinned):
    f = filmmod.load_film(folder)
    f.texts[0].end, f.texts[0].start, f.texts[0].pinned = 7.0, 2.0, pinned
    filmmod.save_film(folder, f)


TEXT_ONLY = {"changes": [{"op": "set_text", "id": "t1", "text": "new caption"}]}


def test_text_only_set_text_keeps_end_on_unpinned_clip(folder):
    _clip(folder, False)
    proposals.add_proposal(folder, TEXT_ONLY)
    (p,) = proposals.process_pending(folder)
    t = filmmod.load_film(folder).texts[0]
    assert p.status == "applied" and t.text == "new caption" and (t.start, t.end) == (2.0, 7.0)


def test_text_only_set_text_on_pinned_clip_is_not_held(folder):
    _clip(folder, True)
    proposals.add_proposal(folder, TEXT_ONLY)
    (p,) = proposals.process_pending(folder)
    t = filmmod.load_film(folder).texts[0]
    assert p.status == "applied" and p.held == []
    assert t.text == "new caption" and (t.start, t.end) == (2.0, 7.0)


def test_approve_include_pinned_after_text_only_change_keeps_timing(folder):
    _clip(folder, True)
    pid = proposals.add_proposal(folder, {**TEXT_ONLY, "needs_approval": True}).id
    proposals.process_pending(folder)
    proposals.approve(folder, pid, include_pinned=True)
    t = filmmod.load_film(folder).texts[0]
    assert t.text == "new caption" and (t.start, t.end) == (2.0, 7.0)


def test_approving_held_changes_applies_only_their_timing(folder):
    pid = proposals.add_proposal(folder, {"summary": "mixed", "changes": [
        {"op": "set_scene", "id": "s1", "title": "claude title", "length": 4},
        {"op": "set_voice", "id": "s1", "text": "claude words", "offset": 0.2},
        {"op": "set_text", "id": "t1", "text": "claude cap", "x": 0.9, "start": 0},
    ]}).id
    proposals.process_pending(folder)
    f = filmmod.load_film(folder)  # the person edits the non-timing fields afterwards
    f.scenes[0].title = "my title"
    f.scenes[0].voice.text = "my words"
    f.texts[0].text = "my cap"
    f.texts[0].x = 0.1
    filmmod.save_film(folder, f)
    done = proposals.approve(folder, pid, include_pinned=True)
    assert done.status == "applied"
    f = filmmod.load_film(folder)
    s1 = f.scenes[0]
    assert (s1.length, s1.voice.offset, f.texts[0].start) == (4, 0.2, 0)
    assert (s1.title, s1.voice.text) == ("my title", "my words")
    assert (f.texts[0].text, f.texts[0].x) == ("my cap", 0.1)


# ------------------------------------------------------------------ sound (Task 5)

from moshfilm import edits  # noqa: E402
from moshfilm.film import Music, MusicBed, SfxClip  # noqa: E402

BED = {"mood": "calm", "tempo": 80, "key": "C", "scale": "major", "palette": "keys", "seed": 1}


def _propose(folder, *changes):
    pid = proposals.add_proposal(folder, {"summary": "sound", "changes": list(changes)}).id
    proposals.process_pending(folder)
    return pid


def _add_change(id="fx9", scene="s2", preset="ding", at=1.0):
    return {"op": "add_sfx", "sfx": {"id": id, "scene": scene, "preset": preset, "at": at}}


def _with(folder, fn):
    f = filmmod.load_film(folder)
    fn(f)
    filmmod.save_film(folder, f)


def _status(folder, pid):
    return next(p for p in proposals._read_raw(folder) if p["id"] == pid)


def test_proposal_adds_sfx_unpinned(folder):
    pid = _propose(folder, _add_change())
    f = filmmod.load_film(folder)
    assert [(c.id, c.pinned) for c in f.sfx] == [("fx9", False)]
    assert _status(folder, pid)["status"] == "applied"
    with pytest.raises(proposals.ProposalError, match="sound fx9 already exists"):
        proposals.apply_proposal(f, proposals.Proposal(id="p", created="x", changes=[_add_change()]))


def test_proposal_cannot_move_or_remove_pinned_sfx(folder):
    _with(folder, lambda f: f.sfx.extend([SfxClip(id="fx1", scene="s2", preset="pop", pinned=True),
                                          SfxClip(id="fx2", scene="s2", preset="tick", pinned=True)]))
    pid = _propose(folder, {"op": "set_sfx", "id": "fx1", "scene": "s1", "at": 2.0},
                   {"op": "remove_sfx", "id": "fx2"})
    p = _status(folder, pid)
    assert p["status"] == "partial" and p["held"] == [0, 1]
    f = filmmod.load_film(folder)
    assert (f.sfx[0].scene, f.sfx[0].at) == ("s2", 0) and len(f.sfx) == 2
    proposals.approve(folder, pid, include_pinned=True)
    f = filmmod.load_film(folder)
    assert [(c.id, c.scene, c.at) for c in f.sfx] == [("fx1", "s1", 2.0)]


def test_proposal_cannot_bring_back_removed_sound(folder):
    def person_removed(f):
        edits.add_tombstone(f, "sfx", "fx1", scene="s2", text="ding")
    _with(folder, person_removed)
    pid = _propose(folder, _add_change("fx1"))
    assert _status(folder, pid)["held_reasons"] == {"0": "you removed this sound"}
    pid = _propose(folder, _add_change("fx7", "s2", "ding"))
    assert _status(folder, pid)["held_reasons"] == {"0": "you removed the same sound in this scene"}
    assert filmmod.load_film(folder).sfx == []
    pid = _propose(folder, _add_change("fx8", "s2", "pop"))
    assert _status(folder, pid)["status"] == "applied"


def test_proposal_sets_bed_unless_person_picked_music(folder):
    pid = _propose(folder, {"op": "set_music", "bed": BED, "volume": 0.5})
    m = filmmod.load_film(folder).music
    assert m.bed.mood == "calm" and m.pinned is False and _status(folder, pid)["status"] == "applied"
    # Claude may replace its own bed
    _propose(folder, {"op": "set_music", "bed": {**BED, "mood": "tense", "tempo": 92}})
    assert filmmod.load_film(folder).music.bed.mood == "tense"
    # the person picked: held
    _with(folder, lambda f: setattr(f, "music", Music(bed=MusicBed(**BED), pinned=True)))
    pid = _propose(folder, {"op": "set_music", "bed": {**BED, "mood": "bright"}})
    assert _status(folder, pid)["held"] == [0]
    assert filmmod.load_film(folder).music.bed.mood == "calm"
    pid = _propose(folder, {"op": "set_music", "bed": None})
    assert _status(folder, pid)["held"] == [0]
    # an old file music is the person's too
    _with(folder, lambda f: setattr(f, "music", Music.model_validate({"file": "music/a.mp3"})))
    assert _status(folder, _propose(folder, {"op": "set_music", "bed": BED}))["status"] == "partial"
    # removed by the person
    def removed(f):
        f.music = None
        edits.add_tombstone(f, "music", "music", text="calm bed")
    _with(folder, removed)
    pid = _propose(folder, {"op": "set_music", "bed": BED})
    assert _status(folder, pid)["held_reasons"] == {"0": "you removed the music"}
    assert filmmod.load_film(folder).music is None
    proposals.approve(folder, pid, include_pinned=True)
    assert filmmod.load_film(folder).music.bed.mood == "calm"


def test_proposal_remove_scene_with_pinned_sfx_is_held(folder):
    def prep(f):
        f.scenes[1].pinned = False
        f.sfx.append(SfxClip(id="fx1", scene="s2", preset="pop", pinned=True))
    _with(folder, prep)
    pid = _propose(folder, {"op": "remove_scene", "id": "s2"})
    assert _status(folder, pid)["held"] == [0]
    proposals.approve(folder, pid, include_pinned=True)
    f = filmmod.load_film(folder)
    assert [s.id for s in f.scenes] == ["s1"] and f.sfx == []
