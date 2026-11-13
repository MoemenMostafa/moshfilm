import threading
from datetime import datetime, timedelta, timezone

import pytest

from moshfilm import queue


def test_add_and_take_marks_delivered(tmp_path):
    item = queue.add_item(tmp_path, "comment", "too slow", time=3.25, scene="s1", scene_time=1.0,
                          point=queue.Point(x=0.5, y=0.25))
    assert item.id == "q1" and item.state == "queued"
    taken = queue.take_queued(tmp_path)
    assert [i.id for i in taken] == ["q1"]
    assert taken[0].state == "delivered" and taken[0].delivered_at
    assert queue.snapshot(tmp_path).items[0].state == "delivered"


def test_queued_items_delivered_oldest_first(tmp_path):
    for n in range(3):
        queue.add_item(tmp_path, "chat", f"m{n}")
    assert [i.id for i in queue.take_queued(tmp_path)] == ["q1", "q2", "q3"]
    assert queue.take_queued(tmp_path) == []


def test_reply_resolves_by_default(tmp_path):
    queue.add_item(tmp_path, "chat", "hi")
    msg = queue.reply(tmp_path, "q1", "hello")
    assert msg.id == "r1" and msg.reply_to == "q1" and msg.role == "claude"
    item = queue.snapshot(tmp_path).items[0]
    assert item.state == "resolved" and item.resolved_at


def test_reply_keep_open(tmp_path):
    queue.add_item(tmp_path, "chat", "hi")
    queue.take_queued(tmp_path)
    queue.reply(tmp_path, "q1", "working on it", resolve=False)
    assert queue.snapshot(tmp_path).items[0].state == "delivered"


def test_reply_without_item_is_plain_message(tmp_path):
    msg = queue.reply(tmp_path, None, "hello")
    assert msg.reply_to is None


def test_reply_unknown_id_raises(tmp_path):
    with pytest.raises(KeyError):
        queue.reply(tmp_path, "q9", "x")
    with pytest.raises(KeyError):
        queue.resolve(tmp_path, "q9")


def test_status_set_and_clear(tmp_path):
    queue.set_status(tmp_path, "building s2")
    assert queue.snapshot(tmp_path).status == "building s2"
    queue.set_status(tmp_path, None)
    assert queue.snapshot(tmp_path).status is None


def test_connected_follows_heartbeat(tmp_path):
    assert not queue.is_connected(tmp_path)
    queue.heartbeat(tmp_path)
    assert queue.is_connected(tmp_path)
    assert queue.snapshot(tmp_path).connected
    later = datetime.now(timezone.utc) + timedelta(seconds=31)
    assert not queue.is_connected(tmp_path, now=later)
    queue.heartbeat(tmp_path, alive=False)
    assert not queue.is_connected(tmp_path)


def test_only_heartbeat_makes_connected(tmp_path):
    queue.add_item(tmp_path, "chat", "x")
    queue.reply(tmp_path, "q1", "y")
    queue.set_status(tmp_path, "z")
    assert not queue.is_connected(tmp_path)


def test_concurrent_writers_lose_nothing(tmp_path):
    stop = threading.Event()
    taken: list[str] = []

    def taker():
        while not stop.is_set():
            taken.extend(i.id for i in queue.take_queued(tmp_path))

    def writer(w):
        for n in range(25):
            queue.add_item(tmp_path, "comment", f"{w}-{n}")

    t = threading.Thread(target=taker)
    t.start()
    ws = [threading.Thread(target=writer, args=(w,)) for w in range(8)]
    for w in ws:
        w.start()
    for w in ws:
        w.join()
    stop.set()
    t.join()
    items = queue.snapshot(tmp_path).items
    assert len(items) == 200
    assert len({i.id for i in items}) == 200
    taken.extend(i.id for i in queue.take_queued(tmp_path))
    assert sorted(taken) == sorted(i.id for i in items)
    assert len(taken) == len(set(taken))


def test_heartbeat_is_replaced_atomically_and_leaves_no_temp_files(tmp_path, monkeypatch):
    import os

    replaced = []
    real_replace = os.replace
    monkeypatch.setattr(os, "replace", lambda a, b: (replaced.append((a, b)), real_replace(a, b))[1])
    queue.heartbeat(tmp_path)
    assert len(replaced) == 1 and str(replaced[0][1]).endswith("heartbeat")
    assert queue.is_connected(tmp_path)
    queue.heartbeat(tmp_path, alive=False)
    assert not queue.is_connected(tmp_path)
    assert sorted(p.name for p in (tmp_path / ".moshfilm").iterdir()) == ["heartbeat"]


def test_old_comments_json_still_loads(tmp_path):
    import json
    (tmp_path / "comments.json").write_text(json.dumps({"items": [
        {"id": "q1", "kind": "comment", "text": "old", "created": "2026-01-01T00:00:00.000+00:00",
         "time": 1.0, "point": {"x": 0.5, "y": 0.5}, "at": {"time": 1.0}}], "messages": []}))
    item = queue.snapshot(tmp_path).items[0]
    assert item.aspect is None and item.at.aspect is None
