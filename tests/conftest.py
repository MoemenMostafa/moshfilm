"""Shared pytest fixtures (later tasks add to this file)."""
import shutil
import subprocess

import pytest

HAVE_FFMPEG = bool(shutil.which("ffmpeg") and shutil.which("ffprobe"))
needs_ffmpeg = pytest.mark.skipif(not HAVE_FFMPEG, reason="ffmpeg/ffprobe not installed")


class FakeTTS:
    """Stands in for edge_tts.Communicate. Records calls; can fail the first `fail` times."""

    def __init__(self, write):
        self.write = write
        self.calls: list[tuple[str, str, str]] = []
        self.fail = 0

    def __call__(self, text, voice, rate="+0%"):
        outer = self

        class _Comm:
            async def save(self, path):
                outer.calls.append((text, voice, rate))
                if outer.fail > 0:
                    outer.fail -= 1
                    raise RuntimeError("NoAudioReceived")
                outer.write(text, path)

        return _Comm()


def _words(text: str) -> float:
    return 0.1 * len(text.split())


@pytest.fixture
def fake_tts(monkeypatch):
    """Fake voice service that needs no network and no ffmpeg.

    `save` writes a stub file; `probe_duration` is patched to 0.1 s per word.
    """
    import edge_tts

    from moshfilm import narrate

    sizes: dict[str, float] = {}

    def write(text, path):
        with open(path, "wb") as fh:
            fh.write(b"stub")
        sizes[str(path).removesuffix(".part")] = _words(text)

    fake = FakeTTS(write)
    monkeypatch.setattr(edge_tts, "Communicate", fake)
    monkeypatch.setattr(narrate, "probe_duration",
                        lambda path: sizes[str(path).removesuffix(".part")])
    return fake


@pytest.fixture
def fake_tts_audio(monkeypatch):
    """Like fake_tts but writes real audio (an ffmpeg sine, 0.1 s per word) and uses the real ffprobe."""
    if not HAVE_FFMPEG:
        pytest.skip("ffmpeg/ffprobe not installed")
    import edge_tts

    def write(text, path):
        subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i",
                        f"sine=frequency=440:duration={_words(text):.3f}", "-f", "mp3", str(path)],
                       check=True)

    fake = FakeTTS(write)
    monkeypatch.setattr(edge_tts, "Communicate", fake)
    return fake
