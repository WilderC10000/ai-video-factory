"""Real tests (not mocked) - ffmpeg is a local, free tool, and
app/providers/video/fixtures/mock_clip.mp4 is a real 1-second video already
committed to the repo, so this exercises actual concatenation and
acceleration."""
import subprocess
from pathlib import Path

import pytest

from app.services.video_assembly import VideoAssemblyError, accelerate_video, concatenate_videos, trim_video

FIXTURE_CLIP = (
    Path(__file__).resolve().parent.parent / "app" / "providers" / "video" / "fixtures" / "mock_clip.mp4"
)


def _ffprobe_duration(path: Path) -> float:
    result = subprocess.run(
        [
            "ffprobe", "-v", "error", "-show_entries", "format=duration",
            "-of", "default=noprint_wrappers=1:nokey=1", str(path),
        ],
        capture_output=True, text=True, check=True,
    )
    return float(result.stdout.strip())


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


def test_accelerate_video_halves_duration_at_2x(tmp_path):
    out = tmp_path / "fast_2x.mp4"
    result = accelerate_video(FIXTURE_CLIP, out, factor=2.0)

    assert result == out
    assert out.exists()
    assert out.stat().st_size > 0

    original_duration = _ffprobe_duration(FIXTURE_CLIP)
    accelerated_duration = _ffprobe_duration(out)
    # The fixture clip is only 10 frames at 10fps, which gives ffmpeg very
    # coarse frame-boundary granularity to round to - real Wan clips (16fps,
    # 10s = 160 frames) have plenty of resolution for a clean ~2x ratio.
    # This just confirms real, meaningful acceleration happened, not exact
    # timing - test_accelerate_video_at_4x_is_faster_than_at_2x below is the
    # stronger relative-ordering check.
    assert accelerated_duration < original_duration * 0.85


def test_accelerate_video_at_4x_is_faster_than_at_2x(tmp_path):
    out_2x = tmp_path / "fast_2x.mp4"
    out_4x = tmp_path / "fast_4x.mp4"
    accelerate_video(FIXTURE_CLIP, out_2x, factor=2.0)
    accelerate_video(FIXTURE_CLIP, out_4x, factor=4.0)

    assert _ffprobe_duration(out_4x) < _ffprobe_duration(out_2x)


def test_accelerate_video_never_overwrites_source(tmp_path):
    source = tmp_path / "source.mp4"
    source.write_bytes(FIXTURE_CLIP.read_bytes())
    original_bytes = source.read_bytes()

    accelerate_video(source, tmp_path / "fast.mp4", factor=3.0)

    assert source.read_bytes() == original_bytes


def test_accelerate_video_rejects_output_path_equal_to_input(tmp_path):
    source = tmp_path / "source.mp4"
    source.write_bytes(FIXTURE_CLIP.read_bytes())

    with pytest.raises(VideoAssemblyError, match="must differ from input_path"):
        accelerate_video(source, source, factor=2.0)


def test_accelerate_video_rejects_non_positive_factor(tmp_path):
    with pytest.raises(VideoAssemblyError, match="factor must be > 0"):
        accelerate_video(FIXTURE_CLIP, tmp_path / "fast.mp4", factor=0.0)


def test_accelerate_video_missing_clip_raises_clear_error(tmp_path):
    with pytest.raises(VideoAssemblyError, match="does not exist"):
        accelerate_video(tmp_path / "missing.mp4", tmp_path / "fast.mp4", factor=2.0)


def test_accelerate_video_output_directory_created_if_missing(tmp_path):
    out = tmp_path / "nested" / "dir" / "fast.mp4"
    accelerate_video(FIXTURE_CLIP, out, factor=2.0)

    assert out.exists()


def test_trim_video_cuts_to_requested_range(tmp_path):
    out = tmp_path / "trimmed.mp4"
    result = trim_video(FIXTURE_CLIP, out, start=0.3, end=0.7)

    assert result == out
    assert out.exists()
    assert out.stat().st_size > 0
    # 0.3-0.7s of a 1s/10fps fixture - allow generous tolerance for frame
    # rounding on such a coarse source.
    assert abs(_ffprobe_duration(out) - 0.4) < 0.25


def test_trim_video_with_no_end_keeps_rest_of_clip(tmp_path):
    out = tmp_path / "trimmed.mp4"
    trim_video(FIXTURE_CLIP, out, start=0.5)

    original_duration = _ffprobe_duration(FIXTURE_CLIP)
    assert _ffprobe_duration(out) < original_duration


def test_trim_video_never_overwrites_source(tmp_path):
    source = tmp_path / "source.mp4"
    source.write_bytes(FIXTURE_CLIP.read_bytes())
    original_bytes = source.read_bytes()

    trim_video(source, tmp_path / "trimmed.mp4", start=0.2, end=0.6)

    assert source.read_bytes() == original_bytes


def test_trim_video_rejects_output_path_equal_to_input(tmp_path):
    source = tmp_path / "source.mp4"
    source.write_bytes(FIXTURE_CLIP.read_bytes())

    with pytest.raises(VideoAssemblyError, match="must differ from input_path"):
        trim_video(source, source, start=0.0, end=0.5)


def test_trim_video_rejects_negative_start(tmp_path):
    with pytest.raises(VideoAssemblyError, match="start must be >= 0"):
        trim_video(FIXTURE_CLIP, tmp_path / "trimmed.mp4", start=-1.0)


def test_trim_video_rejects_end_not_after_start(tmp_path):
    with pytest.raises(VideoAssemblyError, match="must be > start"):
        trim_video(FIXTURE_CLIP, tmp_path / "trimmed.mp4", start=0.5, end=0.5)


def test_trim_video_missing_clip_raises_clear_error(tmp_path):
    with pytest.raises(VideoAssemblyError, match="does not exist"):
        trim_video(tmp_path / "missing.mp4", tmp_path / "trimmed.mp4", start=0.0, end=0.5)


def test_trim_video_output_directory_created_if_missing(tmp_path):
    out = tmp_path / "nested" / "dir" / "trimmed.mp4"
    trim_video(FIXTURE_CLIP, out, start=0.0, end=0.5)

    assert out.exists()
