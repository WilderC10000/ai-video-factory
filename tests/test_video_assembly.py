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


# --- source audio: preserved, retimed, normalized, synchronized ------------------------------

from app.services.video_assembly import ATEMPO_MAX, ATEMPO_MIN, atempo_chain, has_audio_stream  # noqa: E402

SYNC_TOLERANCE_S = 0.08


def _make_clip(path: Path, seconds: float = 2.0, audio: str | None = "sine", rate: int = 48000) -> Path:
    """Real test clip: 64x64 test pattern, optionally with audio.
    audio="sine" -> tone throughout; "late_tone" -> silence for the first half, tone in the
    second half (lets a test tell retiming apart from truncation); None -> no audio stream."""
    cmd = ["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i", f"testsrc=size=64x64:rate=24:duration={seconds}"]
    if audio == "sine":
        cmd += ["-f", "lavfi", "-i", f"sine=frequency=440:sample_rate={rate}:duration={seconds}", "-ac", "1"]
    elif audio == "late_tone":
        half = seconds / 2
        cmd += ["-f", "lavfi", "-i", f"sine=frequency=440:sample_rate={rate}:duration={seconds}",
                "-af", f"volume=enable='lt(t,{half})':volume=0"]
    if audio:
        cmd += ["-c:a", "aac", "-shortest"]
    cmd += ["-c:v", "libx264", "-pix_fmt", "yuv420p", str(path)]
    subprocess.run(cmd, check=True, capture_output=True)
    return path


def _stream(path: Path, stream: str, entries: str) -> list[str]:
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", stream, "-show_entries", f"stream={entries}",
         "-of", "default=noprint_wrappers=1:nokey=1", str(path)],
        capture_output=True, text=True, check=True,
    ).stdout.split()
    return out


def _durations(path: Path) -> tuple[float, float]:
    return float(_stream(path, "v:0", "duration")[0]), float(_stream(path, "a:0", "duration")[0])


def _assert_normalized_audio(path: Path) -> None:
    codec, rate, channels = _stream(path, "a:0", "codec_name,sample_rate,channels")
    assert (codec, rate, channels) == ("aac", "44100", "2")


def _mean_volume(path: Path, start: float, end: float) -> float:
    err = subprocess.run(
        ["ffmpeg", "-v", "info", "-i", str(path), "-af", f"atrim={start}:{end},volumedetect", "-f", "null", "-"],
        capture_output=True, text=True,
    ).stderr
    line = next(l for l in err.splitlines() if "mean_volume" in l)
    return float(line.split("mean_volume:")[1].split("dB")[0])


@pytest.mark.parametrize("factor, expected", [
    (1.1, [1.1]), (2.0, [2.0]), (3.7, [2.0, 1.85]), (4.5, [2.0, 2.0, 1.125]), (0.3, [0.5, 0.6]),
])
def test_atempo_chain_stays_within_portable_limits_and_multiplies_to_factor(factor, expected):
    parts = [float(p.split("=")[1]) for p in atempo_chain(factor).split(",")]
    assert parts == pytest.approx(expected)
    assert all(ATEMPO_MIN <= p <= ATEMPO_MAX for p in parts)
    product = 1.0
    for p in parts:
        product *= p
    assert product == pytest.approx(factor)


@pytest.mark.parametrize("factor", [1.1, 2.0, 3.7])
def test_accelerate_preserves_and_retimes_source_audio(tmp_path, factor):
    src = _make_clip(tmp_path / "src.mp4", seconds=3.0, audio="sine")
    out = accelerate_video(src, tmp_path / f"out_{factor}.mp4", factor=factor)

    assert has_audio_stream(out)
    _assert_normalized_audio(out)
    video, audio = _durations(out)
    assert video == pytest.approx(3.0 / factor, abs=0.1)  # visual timing unchanged from before
    assert abs(audio - video) <= SYNC_TOLERANCE_S


def test_accelerate_retimes_audio_rather_than_truncating_it(tmp_path):
    src = _make_clip(tmp_path / "late.mp4", seconds=2.0, audio="late_tone")
    out = accelerate_video(src, tmp_path / "late_2x.mp4", factor=2.0)
    # The tone started at 1.0s in the source; at 2x it must start at ~0.5s. Plain truncation
    # to 1s would have kept only the silent first half.
    assert _mean_volume(out, 0.05, 0.40) < -60
    assert _mean_volume(out, 0.60, 0.95) > -40


def test_accelerate_adds_matching_silence_when_source_has_no_audio(tmp_path):
    src = _make_clip(tmp_path / "silent_src.mp4", seconds=2.0, audio=None)
    assert not has_audio_stream(src)
    out = accelerate_video(src, tmp_path / "silent_2x.mp4", factor=2.0)
    assert has_audio_stream(out)
    _assert_normalized_audio(out)
    video, audio = _durations(out)
    assert abs(audio - video) <= SYNC_TOLERANCE_S
    assert _mean_volume(out, 0.0, 0.9) < -80


def test_concatenate_mixed_clips_outputs_synchronized_audio(tmp_path):
    with_audio = accelerate_video(_make_clip(tmp_path / "a.mp4", 3.0, "sine", rate=48000), tmp_path / "a_fast.mp4", 3.7)
    raw_with_audio = _make_clip(tmp_path / "b.mp4", 2.0, "sine", rate=22050)  # different rate, mono
    no_audio = _make_clip(tmp_path / "c.mp4", 2.0, None)

    out = concatenate_videos([with_audio, raw_with_audio, no_audio], tmp_path / "final.mp4")

    assert has_audio_stream(out)
    assert _stream(out, "v:0", "codec_name") == ["h264"]
    _assert_normalized_audio(out)
    video, audio = _durations(out)
    assert video == pytest.approx(3.0 / 3.7 + 2.0 + 2.0, abs=0.15)
    assert abs(audio - video) <= SYNC_TOLERANCE_S
    # The silent clip's segment really is silent, the others carry the tone.
    assert _mean_volume(out, video - 1.5, video - 0.2) < -80
    assert _mean_volume(out, 1.2, 2.5) > -40
