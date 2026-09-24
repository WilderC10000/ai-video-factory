"""Read-only ffprobe inspection of generated media, for the Sound Booth.

Every answer comes from the file itself: `ffprobe -select_streams a` lists the
audio streams actually present. Results are cached per (path, size, mtime), so
the studio's snapshot polling doesn't re-probe unchanged files, and a
regenerated file is probed again automatically.
"""
import json
import shutil
import subprocess
import threading
from dataclasses import asdict, dataclass
from pathlib import Path


@dataclass(frozen=True)
class AudioProbe:
    has_audio: bool | None           # None = could not be determined (see error)
    codec: str | None = None
    channels: int | None = None
    sample_rate: int | None = None
    error: str | None = None

    def as_dict(self) -> dict:
        return asdict(self)


_cache: dict[tuple[str, int, int], AudioProbe] = {}
_lock = threading.Lock()


def ffprobe_available() -> bool:
    return shutil.which("ffprobe") is not None


def probe_audio(path: str | Path) -> AudioProbe:
    path = Path(path)
    try:
        stat = path.stat()
    except OSError:
        return AudioProbe(has_audio=None, error="file not found")
    key = (str(path.resolve()), stat.st_size, stat.st_mtime_ns)
    with _lock:
        if key in _cache:
            return _cache[key]

    ffprobe = shutil.which("ffprobe")
    if ffprobe is None:
        return AudioProbe(has_audio=None, error="ffprobe not found on PATH")
    try:
        result = subprocess.run(
            [ffprobe, "-v", "error", "-select_streams", "a",
             "-show_entries", "stream=codec_name,channels,sample_rate", "-of", "json", str(path)],
            capture_output=True, text=True, timeout=20,
        )
    except (OSError, subprocess.TimeoutExpired) as e:
        return AudioProbe(has_audio=None, error=f"ffprobe failed: {e}")
    if result.returncode != 0:
        return AudioProbe(has_audio=None, error=f"ffprobe failed: {result.stderr.strip()[-300:]}")

    streams = json.loads(result.stdout or "{}").get("streams", [])
    if streams:
        first = streams[0]
        rate = first.get("sample_rate")
        probe = AudioProbe(has_audio=True, codec=first.get("codec_name"), channels=first.get("channels"),
                           sample_rate=int(rate) if rate and str(rate).isdigit() else None)
    else:
        probe = AudioProbe(has_audio=False)
    with _lock:
        _cache[key] = probe
    return probe
