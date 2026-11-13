"""Narration: Edge TTS per scene line, a cache keyed by what was said, and the audio tracks.

The cache lives in `<film>/.moshfilm/voice/`: one `<key>.mp3` per line and an
`index.json` of `{key: duration seconds}`. The key covers text + voice + rate,
so an edited line never reuses old audio or an old duration.
"""
from __future__ import annotations

import asyncio
import hashlib
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from .film import Film
from .store import locked, read_json, write_json_atomic
from .timing import SceneSlot

DEFAULT_VOICE = "en-US-AndrewNeural"
DEFAULT_RATE = "+8%"
TTS_TRIES = 4
MUSIC_VOLUME = 0.6
DUCKING = "sidechaincompress=threshold=0.03:ratio=8:attack=20:release=400"
SAMPLE_RATE = 48000


class NarrationError(Exception):
    pass


def voice_key(text: str, voice: str, rate: str) -> str:
    return hashlib.sha256(f"{voice}\n{rate}\n{text}".encode("utf-8")).hexdigest()[:16]


def _voice_dir(folder: Path) -> Path:
    return Path(folder) / ".moshfilm" / "voice"


def voice_file(folder: Path, key: str) -> Path:
    return _voice_dir(folder) / f"{key}.mp3"


def _index_path(folder: Path) -> Path:
    return _voice_dir(folder) / "index.json"


def _run(cmd: list[str]) -> str:
    try:
        r = subprocess.run([str(c) for c in cmd], capture_output=True, text=True)
    except FileNotFoundError:
        raise NarrationError(f"{cmd[0]} is not installed (moshfilm needs ffmpeg for audio)") from None
    if r.returncode:
        raise NarrationError(f"{cmd[0]} failed: {r.stderr[-1500:].strip()}")
    return r.stdout


def probe_duration(path: Path) -> float:
    out = _run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", path])
    return float(out.strip())


_trust_store_done = False


def use_os_trust_store() -> bool:
    """Make Python verify TLS against the operating system's trust store.

    Behind a company proxy that re-signs HTTPS traffic, the system already trusts the
    proxy's certificate, but Python's bundled list does not. `truststore` lets Python
    use the system list. Verification stays fully on; if the package is missing we
    continue with Python's defaults. Returns True when the injection happened.
    """
    global _trust_store_done
    if _trust_store_done:
        return True
    try:
        import truststore

        truststore.inject_into_ssl()
    except Exception:  # noqa: BLE001 - optional helper: fall back to the defaults
        return False
    _trust_store_done = True
    return True


async def synthesize(text: str, voice: str, rate: str, out: Path, tries: int = TTS_TRIES) -> None:
    """Speak `text` into `out`. The service drops requests now and then, so retry.

    Audio goes to a temporary name first and is renamed, so no half file stays.
    """
    use_os_trust_store()
    import edge_tts

    out = Path(out)
    out.parent.mkdir(parents=True, exist_ok=True)
    tmp = out.with_name(out.name + ".part")
    last: Exception | None = None
    for i in range(tries):
        try:
            await edge_tts.Communicate(text, voice, rate=rate).save(str(tmp))
            tmp.replace(out)
            return
        except Exception as exc:  # noqa: BLE001 - any network/service failure is retried
            last = exc
            tmp.unlink(missing_ok=True)
            if i < tries - 1:
                await asyncio.sleep(1 + i)
    raise NarrationError(
        f"could not reach the Edge TTS voice service after {tries} tries: {last}")


def _key_for(film: Film, text: str) -> str:
    return voice_key(text, film.voice.name, film.voice.rate)


def voice_durations(folder: Path, film: Film) -> dict[str, float]:
    """Scene id -> duration of its current line. Cache only: never touches the network."""
    index = read_json(_index_path(folder), {})
    out: dict[str, float] = {}
    for scene in film.scenes:
        text = scene.voice.text.strip()
        if not text:
            continue
        key = _key_for(film, text)
        if key in index and voice_file(folder, key).exists():
            out[scene.id] = float(index[key])
    return out


def ensure_voice(folder: Path, film: Film,
                 on_progress: Callable[[str], None] | None = None) -> dict[str, float]:
    """Synthesise every line that is not cached yet; return scene id -> duration."""
    folder = Path(folder)
    done = voice_durations(folder, film)
    for scene in film.scenes:
        text = scene.voice.text.strip()
        if not text or scene.id in done:
            continue
        key = _key_for(film, text)
        path = voice_file(folder, key)
        if on_progress:
            on_progress(f"voice {scene.id}: {text[:50]}")
        asyncio.run(synthesize(text, film.voice.name, film.voice.rate, path))
        try:
            duration = probe_duration(path)
        except NarrationError:
            path.unlink(missing_ok=True)
            raise
        with locked(folder):
            index = read_json(_index_path(folder), {})
            index[key] = duration
            write_json_atomic(_index_path(folder), index)
        done[scene.id] = duration
    return done


@dataclass
class VoiceClip:
    path: Path
    start: float
    speed: float


def voice_clips(folder: Path, film: Film, slots: list[SceneSlot]) -> list[VoiceClip]:
    """Clips for every scene whose line is cached, placed by the layout."""
    cached = voice_durations(folder, film)
    by_id = {s.id: s for s in slots}
    clips = []
    for scene in film.scenes:
        if scene.id in cached and scene.id in by_id:
            slot = by_id[scene.id]
            key = _key_for(film, scene.voice.text.strip())
            clips.append(VoiceClip(voice_file(folder, key), slot.voice_start, slot.voice_speed))
    return clips


def build_voice_track(clips: list[VoiceClip], total: float, out_wav: Path) -> None:
    """One 48 kHz stereo wav of `total` seconds with each clip delayed to its start."""
    base = ["ffmpeg", "-y", "-v", "error"]
    tail = ["-ar", str(SAMPLE_RATE), "-ac", "2", out_wav]
    if not clips:
        _run([*base, "-f", "lavfi", "-i", f"anullsrc=r={SAMPLE_RATE}:cl=stereo",
              "-t", f"{total:.3f}", *tail])
        return
    inputs: list = []
    filters, labels = [], []
    for i, clip in enumerate(clips):
        inputs += ["-i", clip.path]
        tempo = f"atempo={clip.speed:.4f}," if clip.speed > 1 else ""
        ms = int(round(clip.start * 1000))
        filters.append(f"[{i}:a]{tempo}aresample={SAMPLE_RATE},adelay={ms}|{ms},"
                       f"asetpts=N/SR/TB[c{i}]")
        labels.append(f"[c{i}]")
    filters.append(f"{''.join(labels)}amix=inputs={len(clips)}:normalize=0,apad,"
                   f"atrim=0:{total:.3f}[voice]")
    _run([*base, *inputs, "-filter_complex", ";".join(filters), "-map", "[voice]", *tail])


def mix_music(voice_wav: Path, music: Path, volume: float, total: float, out_wav: Path) -> None:
    """Music at `volume`, ducked (turned down) while the voice talks, mixed with the voice."""
    fc = (f"[0:a]asplit=2[v1][v2];"
          f"[1:a]aresample={SAMPLE_RATE},volume={volume}[m];"
          f"[m][v1]{DUCKING}[duck];"
          f"[duck][v2]amix=inputs=2:normalize=0,atrim=0:{total:.3f}[aout]")
    _run(["ffmpeg", "-y", "-v", "error", "-i", voice_wav, "-i", music, "-filter_complex", fc,
          "-map", "[aout]", "-ar", str(SAMPLE_RATE), "-ac", "2", out_wav])
