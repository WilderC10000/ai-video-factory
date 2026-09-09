"""Minimal ffmpeg-based video assembly: concatenating multiple already-
generated clips into one review file, and speed-changing a single clip.
This is deliberately small - a handful of functions, not an editing
pipeline - existing only to let a human review generated footage (e.g. the
Wan Turbo 2-clip timelapse test, or the causal-action-vs-accelerated
comparison in scripts/run_causal_action_test.py) without needing external
tools. The real trim-aware assembly system (aggressive trimming,
transitions, captions) is future work noted in the README's "What's
next", not this module.

Pure local tooling - no network, no cost. Requires ffmpeg on PATH.
"""
import shutil
import subprocess
from pathlib import Path


class VideoAssemblyError(Exception):
    """Raised when ffmpeg is missing, a clip is unreadable, or concatenation
    or acceleration otherwise fails."""


def concatenate_videos(clip_paths: list[str | Path], output_path: str | Path) -> Path:
    """Concatenate 2+ video clips into one file at `output_path`, in the
    given order.

    Uses ffmpeg's `concat` *filter* (re-encodes) rather than the `concat`
    *demuxer* (`-c copy`) - the demuxer requires byte-identical codec
    parameters across inputs, which two separately generated clips from
    the same model aren't guaranteed to have; the filter re-encodes and so
    works regardless. No audio stream is mapped - none of this project's
    video providers produce one for the models used here.
    """
    if len(clip_paths) < 2:
        raise VideoAssemblyError(f"concatenate_videos needs at least 2 clips, got {len(clip_paths)}.")

    ffmpeg_path = shutil.which("ffmpeg")
    if not ffmpeg_path:
        raise VideoAssemblyError(
            "ffmpeg was not found on PATH. Install it (e.g. https://ffmpeg.org/download.html "
            "or `winget install ffmpeg` on Windows) and try again."
        )

    for p in clip_paths:
        if not Path(p).exists():
            raise VideoAssemblyError(f"Clip does not exist: {p}")

    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    inputs: list[str] = []
    for p in clip_paths:
        inputs += ["-i", str(p)]
    filter_inputs = "".join(f"[{i}:v]" for i in range(len(clip_paths)))
    filter_complex = f"{filter_inputs}concat=n={len(clip_paths)}:v=1:a=0[outv]"

    result = subprocess.run(
        [ffmpeg_path, "-y", *inputs, "-filter_complex", filter_complex, "-map", "[outv]", str(output_path)],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0 or not output_path.exists():
        raise VideoAssemblyError(
            f"ffmpeg concatenation failed (exit {result.returncode}) for {clip_paths}: "
            f"{result.stderr.strip()[-2000:]}"
        )

    return output_path


def accelerate_video(input_path: str | Path, output_path: str | Path, factor: float) -> Path:
    """Speed up `input_path` by `factor` (e.g. 2.0 = twice as fast, half the
    duration) and save the result to `output_path`, WITHOUT modifying or
    overwriting `input_path` - the source clip is only ever read.

    Uses ffmpeg's `setpts=PTS/factor` video filter (re-encodes; this changes
    presentation timestamps, so `-c copy` isn't an option). No audio stream
    is mapped - none of this project's video providers produce one for the
    models used here, matching concatenate_videos()'s behavior above.
    """
    if factor <= 0:
        raise VideoAssemblyError(f"factor must be > 0, got {factor}")

    ffmpeg_path = shutil.which("ffmpeg")
    if not ffmpeg_path:
        raise VideoAssemblyError(
            "ffmpeg was not found on PATH. Install it (e.g. https://ffmpeg.org/download.html "
            "or `winget install ffmpeg` on Windows) and try again."
        )

    input_path = Path(input_path)
    if not input_path.exists():
        raise VideoAssemblyError(f"Clip does not exist: {input_path}")

    output_path = Path(output_path)
    if output_path.resolve() == input_path.resolve():
        raise VideoAssemblyError(
            f"output_path must differ from input_path (got {output_path}) - "
            "the source clip must never be overwritten."
        )
    output_path.parent.mkdir(parents=True, exist_ok=True)

    result = subprocess.run(
        [
            ffmpeg_path,
            "-y",
            "-i", str(input_path),
            "-filter:v", f"setpts=PTS/{factor}",
            "-an",
            str(output_path),
        ],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0 or not output_path.exists():
        raise VideoAssemblyError(
            f"ffmpeg acceleration failed (exit {result.returncode}) for {input_path} "
            f"at factor {factor}: {result.stderr.strip()[-2000:]}"
        )

    return output_path
