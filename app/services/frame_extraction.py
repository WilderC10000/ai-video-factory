"""Extracts a still frame from a local video file using ffmpeg. This is the
mechanism behind "last-frame propagation": feeding the final frame of one
generated clip back in as the reference image for the next generation, so
each stage inherits the actual pixels of the previous one instead of a
fresh, independently-imagined starting frame.

Pure local tooling - no network, no cost. Requires ffmpeg on PATH.
"""
import shutil
import subprocess
from pathlib import Path


class FrameExtractionError(Exception):
    """Raised when ffmpeg is missing, the input video is unreadable, or
    extraction otherwise fails."""


def extract_last_frame(video_path: str | Path, output_path: str | Path, offset_seconds: float = 0.3) -> Path:
    """Extract a frame from near the end of `video_path` and save it as a
    JPEG at `output_path`.

    `offset_seconds` counts backward from the end of the clip (ffmpeg's
    `-sseof`), not forward from the start - the default of 0.3s deliberately
    avoids the literal last frame, which can land mid-cut or motion-blurred
    on some clips; a moment just before the end is usually more visually
    settled. Pass 0.0 to get as close as possible to the literal last frame
    (ffmpeg's `-sseof` requires a strictly negative offset, so 0.0 is
    substituted with a negligible epsilon rather than rejected).
    """
    if offset_seconds < 0:
        raise ValueError(f"offset_seconds must be >= 0, got {offset_seconds}")

    # -sseof needs a value < 0; 0.0 is a valid *request* ("as close to the
    # end as possible") but not a valid ffmpeg argument, so nudge it.
    # Measured directly against this repo's fixture clip: offsets smaller
    # than one frame's duration (0.1s at the fixture's 10fps) land in the
    # zero-duration gap right at EOF and produce nothing, so the epsilon
    # needs real margin above typical frame durations (16fps real Wan clips
    # are ~0.0625s/frame) - 0.15s clears that with room to spare.
    sseof_seconds = offset_seconds if offset_seconds > 0 else 0.15

    ffmpeg_path = shutil.which("ffmpeg")
    if not ffmpeg_path:
        raise FrameExtractionError(
            "ffmpeg was not found on PATH. Install it (e.g. https://ffmpeg.org/download.html "
            "or `winget install ffmpeg` on Windows) and try again."
        )

    video_path = Path(video_path)
    if not video_path.exists():
        raise FrameExtractionError(f"Video file does not exist: {video_path}")

    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    result = subprocess.run(
        [
            ffmpeg_path,
            "-y",
            "-sseof", f"-{sseof_seconds}",
            "-i", str(video_path),
            "-frames:v", "1",
            "-update", "1",
            "-q:v", "3",
            str(output_path),
        ],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0 or not output_path.exists():
        raise FrameExtractionError(
            f"ffmpeg frame extraction failed (exit {result.returncode}) for {video_path} "
            f"at offset {offset_seconds}s: {result.stderr.strip()[-2000:]}"
        )

    return output_path
