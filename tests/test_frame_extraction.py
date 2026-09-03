"""Real tests (not mocked) - ffmpeg is a local, free tool, and
app/providers/video/fixtures/mock_clip.mp4 is a real 1-second video already
committed to the repo, so this exercises actual frame extraction."""
from pathlib import Path

import pytest

from app.services.frame_extraction import FrameExtractionError, extract_last_frame

FIXTURE_CLIP = (
    Path(__file__).resolve().parent.parent / "app" / "providers" / "video" / "fixtures" / "mock_clip.mp4"
)


def test_extract_last_frame_default_offset(tmp_path):
    out = tmp_path / "frame.jpg"
    result = extract_last_frame(FIXTURE_CLIP, out)

    assert result == out
    assert out.exists()
    assert out.stat().st_size > 0
    assert out.read_bytes()[:2] == b"\xff\xd8"  # JPEG magic bytes


def test_extract_last_frame_custom_offset(tmp_path):
    out = tmp_path / "frame.jpg"
    extract_last_frame(FIXTURE_CLIP, out, offset_seconds=0.1)

    assert out.exists()
    assert out.stat().st_size > 0


def test_extract_last_frame_zero_offset_is_literal_last_frame(tmp_path):
    out = tmp_path / "frame.jpg"
    extract_last_frame(FIXTURE_CLIP, out, offset_seconds=0.0)

    assert out.exists()
    assert out.stat().st_size > 0


def test_negative_offset_rejected(tmp_path):
    with pytest.raises(ValueError):
        extract_last_frame(FIXTURE_CLIP, tmp_path / "frame.jpg", offset_seconds=-1.0)


def test_missing_video_raises_clear_error(tmp_path):
    with pytest.raises(FrameExtractionError, match="does not exist"):
        extract_last_frame(tmp_path / "does_not_exist.mp4", tmp_path / "frame.jpg")


def test_corrupt_video_raises_clear_error(tmp_path):
    bad_video = tmp_path / "not_really_a_video.mp4"
    bad_video.write_bytes(b"this is not a valid mp4 file")

    with pytest.raises(FrameExtractionError, match="ffmpeg frame extraction failed"):
        extract_last_frame(bad_video, tmp_path / "frame.jpg")


def test_output_directory_created_if_missing(tmp_path):
    out = tmp_path / "nested" / "dir" / "frame.jpg"
    extract_last_frame(FIXTURE_CLIP, out)

    assert out.exists()
