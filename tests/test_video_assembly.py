"""Real tests (not mocked) - ffmpeg is a local, free tool, and
app/providers/video/fixtures/mock_clip.mp4 is a real 1-second video already
committed to the repo, so this exercises actual concatenation."""
from pathlib import Path

import pytest

from app.services.video_assembly import VideoAssemblyError, concatenate_videos

FIXTURE_CLIP = (
    Path(__file__).resolve().parent.parent / "app" / "providers" / "video" / "fixtures" / "mock_clip.mp4"
)


def test_concatenate_two_clips(tmp_path):
    out = tmp_path / "combined.mp4"
    result = concatenate_videos([FIXTURE_CLIP, FIXTURE_CLIP], out)

    assert result == out
    assert out.exists()
    assert out.stat().st_size > 0


def test_concatenate_requires_at_least_two_clips(tmp_path):
    with pytest.raises(VideoAssemblyError, match="at least 2 clips"):
        concatenate_videos([FIXTURE_CLIP], tmp_path / "combined.mp4")


def test_concatenate_missing_clip_raises_clear_error(tmp_path):
    with pytest.raises(VideoAssemblyError, match="does not exist"):
        concatenate_videos([FIXTURE_CLIP, tmp_path / "missing.mp4"], tmp_path / "combined.mp4")


def test_concatenate_output_directory_created_if_missing(tmp_path):
    out = tmp_path / "nested" / "dir" / "combined.mp4"
    concatenate_videos([FIXTURE_CLIP, FIXTURE_CLIP], out)

    assert out.exists()
