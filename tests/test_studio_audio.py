"""FORMA Virtual Studio - Sound Booth source-audio detection.

Uses real tiny MP4s generated with ffmpeg (one with an AAC stream, one without)
so detection is exercised against actual media, not assumptions.
"""
import shutil
import subprocess
from pathlib import Path

import pytest

from app.studio.importers.manifest_importer import import_all
from app.studio.media_probe import probe_audio
from app.studio.service import build_snapshot
from tests.test_studio_importer import ALPINE_DONE, CLIFFSIDE_DONE, data_dir  # noqa: F401  (fixture)

pytestmark = pytest.mark.skipif(not (shutil.which("ffmpeg") and shutil.which("ffprobe")), reason="needs ffmpeg")


def _clip(path: Path, audio: bool) -> Path:
    cmd = ["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i", "color=c=black:s=64x64:d=1:r=10"]
    if audio:
        cmd += ["-f", "lavfi", "-i", "anullsrc=r=44100:cl=stereo", "-shortest", "-c:a", "aac"]
    cmd += ["-c:v", "libx264", "-pix_fmt", "yuv420p", str(path)]
    subprocess.run(cmd, check=True, capture_output=True)
    return path


@pytest.fixture(scope="module")
def clips(tmp_path_factory):
    d = tmp_path_factory.mktemp("clips")
    return {"with": _clip(d / "with_audio.mp4", True), "without": _clip(d / "no_audio.mp4", False)}


def test_probe_reads_audio_streams_from_the_file(clips, tmp_path):
    with_audio = probe_audio(clips["with"])
    assert with_audio.has_audio is True and with_audio.codec == "aac"
    assert with_audio.channels == 2 and with_audio.sample_rate == 44100
    assert probe_audio(clips["without"]).has_audio is False

    garbage = tmp_path / "not_a_video.mp4"
    garbage.write_bytes(b"x")
    assert probe_audio(garbage).has_audio is None and "ffprobe failed" in probe_audio(garbage).error
    assert probe_audio(tmp_path / "missing.mp4").error == "file not found"


def _place(project_dir: Path, names: list[str], source: Path) -> None:
    for name in names:
        shutil.copy(source, project_dir / name)


def test_sound_booth_counts_source_audio_and_reports_discarded_final(db_session, data_dir, clips):  # noqa: F811
    alpine_shots = [out for _key, _cost, out, _prev in ALPINE_DONE if out.endswith(".mp4")]
    _place(data_dir / "alpine_video_2", alpine_shots[:-1], clips["with"])   # 4 of 5 shots carry audio
    _place(data_dir / "alpine_video_2", alpine_shots[-1:], clips["without"])
    cliff_shots = [out for _key, _cost, out, _prev in CLIFFSIDE_DONE if out.endswith(".mp4")]
    _place(data_dir / "cliffside_video_1", cliff_shots, clips["with"])
    _place(data_dir / "cliffside_video_1", ["final.mp4"], clips["without"])  # assembly dropped the audio
    import_all(db_session, data_dir)

    alpine = build_snapshot(db_session, "alpine_video_2")
    audio = alpine["audio"]
    assert (audio["clips_with_audio"], audio["clips_total"]) == (4, 5)
    assert audio["final_status"] == "not_assembled"
    booth = next(r for r in alpine["rooms"] if r["id"] == "sound_booth")["agent"]
    assert booth["status_reason"] == "Source audio detected: 4/5 generated clips"
    assert booth["next_action"].startswith("Additional sound design") and "not implemented yet" in booth["next_action"]

    cliff = build_snapshot(db_session, "cliffside_video_1")["audio"]
    assert (cliff["clips_with_audio"], cliff["clips_total"]) == (3, 3)
    assert cliff["final_status"] == "discarded" and cliff["final"]["has_audio"] is False


def test_sound_booth_says_none_when_no_clip_has_audio(db_session, data_dir, clips):  # noqa: F811
    shots = [out for _key, _cost, out, _prev in ALPINE_DONE if out.endswith(".mp4")]
    _place(data_dir / "alpine_video_2", shots, clips["without"])
    import_all(db_session, data_dir)
    snap = build_snapshot(db_session, "alpine_video_2")
    booth = next(r for r in snap["rooms"] if r["id"] == "sound_booth")["agent"]
    assert booth["status_reason"] == "Source audio detected: none"


def test_sound_booth_reports_preserved_source_audio(db_session, data_dir, clips):  # noqa: F811
    cliff_shots = [out for _key, _cost, out, _prev in CLIFFSIDE_DONE if out.endswith(".mp4")]
    _place(data_dir / "cliffside_video_1", cliff_shots, clips["with"])
    _place(data_dir / "cliffside_video_1", ["final.mp4"], clips["with"])  # new assembly keeps the audio
    import_all(db_session, data_dir)
    snap = build_snapshot(db_session, "cliffside_video_1")
    assert snap["audio"]["final_status"] == "preserved"
    booth = next(r for r in snap["rooms"] if r["id"] == "sound_booth")["agent"]
    assert booth["current_task"] == "Source audio - preserved in the final cut"
