import json

import pytest

from moshfilm import queue
from moshfilm.cli import main


def test_watch_once_prints_json_lines(tmp_path, capsys):
    queue.add_item(tmp_path, "comment", "make it bigger", time=3.26, scene="s1", scene_time=1.04,
                   point=queue.Point(x=0.123, y=0.5))
    queue.add_item(tmp_path, "chat", "hello")
    assert main(["watch", str(tmp_path), "--once"]) == 0
    lines = [json.loads(x) for x in capsys.readouterr().out.splitlines()]
    assert lines[0] == {"id": "q1", "kind": "comment", "text": "make it bigger", "time": 3.3,
                        "scene": "s1", "scene_time": 1.0, "point": {"x": 0.12, "y": 0.5}}
    assert lines[1] == {"id": "q2", "kind": "chat", "text": "hello"}
    assert {i.state for i in queue.snapshot(tmp_path).items} == {"delivered"}


def test_watch_writes_heartbeat(tmp_path, capsys):
    queue.add_item(tmp_path, "chat", "x")
    main(["watch", str(tmp_path), "--once"])
    assert (tmp_path / ".moshfilm" / "heartbeat").exists()


def test_reply_cli_resolves(tmp_path, capsys):
    queue.add_item(tmp_path, "chat", "hi")
    assert main(["reply", str(tmp_path), "q1", "done"]) == 0
    snap = queue.snapshot(tmp_path)
    assert snap.items[0].state == "resolved" and snap.messages[0].text == "done"
    assert not snap.connected  # only watch writes the heartbeat


def test_reply_cli_keep_open_and_unknown(tmp_path, capsys):
    queue.add_item(tmp_path, "chat", "hi")
    assert main(["reply", str(tmp_path), "q1", "wip", "--keep-open"]) == 0
    assert queue.snapshot(tmp_path).items[0].state == "queued"
    assert main(["reply", str(tmp_path), "q7", "x"]) == 2
    assert "no item q7" in capsys.readouterr().err
    assert main(["resolve", str(tmp_path), "q7"]) == 2


def test_say_and_resolve_cli(tmp_path):
    queue.add_item(tmp_path, "chat", "hi")
    assert main(["say", str(tmp_path), "fyi"]) == 0
    assert queue.snapshot(tmp_path).messages[0].reply_to is None
    assert main(["resolve", str(tmp_path), "q1"]) == 0
    assert queue.snapshot(tmp_path).items[0].state == "resolved"


def test_status_and_clear(tmp_path):
    assert main(["status", str(tmp_path), "building s2"]) == 0
    assert queue.snapshot(tmp_path).status == "building s2"
    assert main(["status", str(tmp_path), "--clear"]) == 0
    assert queue.snapshot(tmp_path).status is None


def test_status_needs_text_or_clear(tmp_path):
    with pytest.raises(SystemExit):
        main(["status", str(tmp_path)])


def test_watch_prints_at_for_chat(tmp_path, capsys):
    queue.add_item(tmp_path, "chat", "here", at=queue.At(time=23.44, scene="s3", sceneTitle="Open the middle"))
    main(["watch", str(tmp_path), "--once"])
    line = json.loads(capsys.readouterr().out.splitlines()[0])
    assert line["at"] == {"time": 23.4, "scene": "s3", "sceneTitle": "Open the middle"}


def _film_with(tmp_path, second=None):
    from moshfilm import film as filmlib
    filmlib.new_film(tmp_path, "t")
    f = filmlib.load_film(tmp_path)
    f.second_aspect = second
    filmlib.save_film(tmp_path, f)
    return f


def test_watch_line_has_aspect_and_frame(tmp_path):
    from moshfilm.cli import _item_line
    f = _film_with(tmp_path)
    item = queue.QueueItem(id="q1", kind="comment", text="x", created="t", time=1.0, scene="s1", scene_time=1.0,
                           point=queue.Point(x=0.5, y=0.5), aspect="9:16")
    line = json.loads(_item_line(item, f))
    assert line["aspect"] == "9:16" and line["frame"] == {"width": 720, "height": 1280}
    old = item.model_copy(update={"aspect": None})  # an old comment counts as the main shape
    line = json.loads(_item_line(old, f))
    assert line["aspect"] == "16:9" and line["frame"] == {"width": 1280, "height": 720}


def test_chat_at_carries_aspect(tmp_path, capsys):
    _film_with(tmp_path, second="9:16")
    queue.add_item(tmp_path, "chat", "here", at=queue.At(time=2.0, scene="s1", sceneTitle="One", aspect="9:16"))
    main(["watch", str(tmp_path), "--once"])
    line = json.loads(capsys.readouterr().out.splitlines()[0])
    assert line["at"]["aspect"] == "9:16"
