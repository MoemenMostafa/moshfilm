"""Export progress: the exporter's events, the percent/eta math, and the status JSON. No Chromium needed."""
import io
import shutil
import threading
from pathlib import Path

import pytest

from moshfilm import export, film, timing
from moshfilm.export_progress import ExportProgress

COLORS = Path(__file__).parent / "fixtures" / "films" / "colors"


class Clock:
    def __init__(self):
        self.t = 0.0

    def __call__(self):
        return self.t


def test_frames_throttle_reports_start_steady_and_last():
    clock, events, out = Clock(), [], io.BytesIO()

    def render(i):
        clock.t += 0.1  # 10 frames a second
        return b"x"

    export._run_frames(20, 10, render, out, events.append, clock)
    # first at 0, then roughly every 0.25 s (every third frame here), and always the last frame
    assert events[0] == 0 and events[-1] == 20 and events == sorted(events)
    assert events == [0, 3, 6, 9, 12, 15, 18, 20]
    assert len(out.getvalue()) == 20


@pytest.fixture
def fake_pipeline(tmp_path, monkeypatch):
    """The real export flow with audio, Chromium and ffmpeg replaced by fakes."""
    folder = tmp_path / "colors"
    shutil.copytree(COLORS, folder)
    f = film.load_film(folder)
    f.second_aspect = "9:16"
    film.save_film(folder, f)
    monkeypatch.setattr(export.shutil, "which", lambda name: "/bin/" + name)
    monkeypatch.setattr(export, "_build_audio", lambda *a, **k: tmp_path / "a.wav")

    def frames(base, the_film, aspect, slots, n, fps, stdin, report=lambda d: None):
        export._run_frames(n, fps, lambda i: b"png", stdin, report)

    class Proc:
        def __init__(self, cmd, **kw):
            self.out = Path(cmd[-1])
            self.stdin = io.BytesIO()
            self.stdout = io.BytesIO(b"out_time_us=N/A\nprogress=continue\n")

        def wait(self):
            self.out.write_bytes(b"movie")
            return 0

    monkeypatch.setattr(export, "_render_frames", frames)
    monkeypatch.setattr(export.subprocess, "Popen", Proc)
    return folder


def test_callback_order_and_totals(fake_pipeline, tmp_path):
    events = []
    export.export_aspects(fake_pipeline, "mp4", out=tmp_path / "o.mp4", voice=False, on_progress=events.append)
    f = film.load_film(fake_pipeline)
    n = -(-int(timing.total_length(timing.layout(f, {})) * f.fps * 1000) // 1000)
    stages = [(e["stage"], e["aspect"]) for e in events]
    collapsed = [s for i, s in enumerate(stages) if i == 0 or s != stages[i - 1]]
    assert collapsed == [("audio", None), ("frames", "16:9"), ("encode", "16:9"),
                         ("frames", "9:16"), ("encode", "9:16")]
    assert events[0]["done"] == 0 and events[1]["done"] == 1 and events[1]["total"] == 1  # audio 0/1 then 1/1
    for aspect in ("16:9", "9:16"):
        fr = [e for e in events if e["stage"] == "frames" and e["aspect"] == aspect]
        assert fr[0]["done"] == 0 and fr[-1]["done"] == fr[-1]["total"] and fr[-1]["total"] >= n - 1
        assert [e["done"] for e in fr] == sorted(e["done"] for e in fr)
        enc = [e for e in events if e["stage"] == "encode" and e["aspect"] == aspect]
        assert enc[0]["done"] == 0 and enc[-1]["done"] == enc[-1]["total"]
    assert {e["aspect_count"] for e in events} == {2}
    assert [e["aspect_index"] for e in events if e["stage"] == "frames"][-1] == 1


def test_gif_has_no_audio_stage(fake_pipeline, tmp_path):
    events = []
    export.export_aspects(fake_pipeline, "gif", out=tmp_path / "o.gif", voice=False, on_progress=events.append)
    assert "audio" not in {e["stage"] for e in events}


def ev(stage, done, total, index=0, count=1, aspect="16:9"):
    return {"stage": stage, "aspect": aspect, "aspect_index": index, "aspect_count": count,
            "done": done, "total": total}


def test_percent_math_two_shapes_mp4():
    p = ExportProgress("mp4", Clock())
    assert p.snapshot() is None
    p.update(ev("audio", 0, 1, count=2))
    assert p.percent() == 0
    p.update(ev("audio", 1, 1, count=2))
    assert p.percent() == pytest.approx(3)
    p.update(ev("frames", 500, 1000, count=2))  # half the frames of the first of two shapes
    assert p.percent() == pytest.approx(3 + 97 / 2 * 0.9 * 0.5)
    p.update(ev("encode", 0, 40, count=2))
    assert p.percent() == pytest.approx(3 + 97 / 2 * 0.9)
    p.update(ev("frames", 0, 1000, index=1, count=2, aspect="9:16"))
    assert p.percent() == pytest.approx(3 + 97 / 2)
    p.update(ev("encode", 40, 40, index=1, count=2, aspect="9:16"))
    assert p.percent() == pytest.approx(100)


def test_gif_gives_audio_no_share():
    p = ExportProgress("gif", Clock())
    p.update(ev("frames", 900, 1000))
    assert p.percent() == pytest.approx(81)


def test_eta_is_null_before_three_seconds_then_follows_the_measured_rate():
    clock = Clock()
    p = ExportProgress("gif", clock)
    p.update(ev("frames", 0, 900))
    assert p.eta_seconds() is None
    clock.t = 2.9
    p.update(ev("frames", 290, 900))
    assert p.eta_seconds() is None
    clock.t = 3.0
    p.update(ev("frames", 300, 900))  # 100 frames a second
    # 600 frames left, plus the encode share (100 frame equivalents) = 700 / 100
    assert p.eta_seconds() == 7
    clock.t = 5.0
    p.update(ev("frames", 500, 900))
    assert p.eta_seconds() == 5
    p.update(ev("encode", 0, 9))
    assert p.eta_seconds() == 1
    p.update(ev("encode", 9, 9))
    assert p.eta_seconds() == 0


def test_eta_counts_the_second_shape():
    clock = Clock()
    p = ExportProgress("gif", clock)
    p.update(ev("frames", 0, 100, count=2))
    clock.t = 4.0
    p.update(ev("frames", 40, 100, count=2))  # 10 frames a second
    # frame equivalents: 2 * 111.1 - 40 = 182.2 -> 18 s
    assert p.eta_seconds() == 18


def test_status_json_carries_progress(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient
    from moshfilm import layout_check, server
    folder = tmp_path / "colors"
    shutil.copytree(COLORS, folder)
    monkeypatch.setattr(layout_check, "check_layout", lambda f: [])
    seen, gate, mid = threading.Event(), threading.Event(), {}

    def fake(folder_, fmt, out=None, fps=None, width=None, voice=True, progress=None, on_progress=None):
        progress("16:9")
        on_progress(ev("audio", 1, 1))
        on_progress(ev("frames", 250, 1000))
        seen.set()
        gate.wait(5)
        p = out
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(b"x")
        return {"16:9": p}

    monkeypatch.setattr(export, "export_aspects", fake)
    client = TestClient(server.create_app(folder), base_url="http://127.0.0.1:5802")
    assert client.get("/api/export").json()["progress"] is None
    client.post("/api/export", json={"format": "mp4"})
    assert seen.wait(5)
    st = client.get("/api/export").json()
    assert st["state"] == "running" and st["current"] == "16:9"
    assert set(st["progress"]) == {"stage", "aspect", "aspect_index", "aspect_count", "done", "total",
                                   "percent", "eta_seconds"}
    assert st["progress"]["stage"] == "frames" and st["progress"]["done"] == 250
    assert st["progress"]["percent"] == pytest.approx(3 + 97 * 0.9 * 0.25, abs=0.1)
    assert st["progress"]["eta_seconds"] is None
    assert {"state", "format", "files", "warnings", "current", "error", "started_at", "finished_at"} <= set(st)
    gate.set()
    import time
    for _ in range(200):
        st = client.get("/api/export").json()
        if st["state"] != "running":
            break
        time.sleep(0.02)
    assert st["state"] == "done" and st["progress"] is None


def test_cli_progress_line_formats():
    from moshfilm.cli import _ProgressLine

    class Tty(io.StringIO):
        def isatty(self):
            return True

    plain = io.StringIO()
    line = _ProgressLine(plain)
    for done in (0, 5, 140, 1380):
        line(ev("frames", done, 1380))
    assert plain.getvalue() == "16:9  frames 0/1380  0%\n16:9  frames 140/1380  10%\n16:9  frames 1380/1380  100%\n"
    tty = Tty()
    line = _ProgressLine(tty)
    line(ev("frames", 412, 1380))
    assert tty.getvalue() == "\r16:9  frames 412/1380  29%"
    line.finish()
    assert tty.getvalue().endswith("\n")
