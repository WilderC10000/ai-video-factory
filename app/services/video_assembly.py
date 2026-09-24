"""Minimal ffmpeg-based video assembly: concatenating multiple already-
generated clips into one review file, speed-changing a single clip, and
trimming a clip to an in/out range. This is deliberately small - a
handful of functions, not an editing pipeline - existing only to let a
human review generated footage (e.g. the Wan Turbo 2-clip timelapse test,
or the causal-action-vs-accelerated comparison in scripts/
run_causal_action_test.py) without needing external tools.

Pure local tooling - no network, no cost. Requires ffmpeg on PATH.
"""
import shutil
import subprocess
from pathlib import Path


class VideoAssemblyError(Exception):
    """Raised when ffmpeg is missing, a clip is unreadable, or concatenation
    or acceleration otherwise fails."""


# Every audio track this module writes is normalized to one format, so clips
# from different sources concatenate reliably.
AUDIO_SAMPLE_RATE = 44100
AUDIO_CHANNEL_LAYOUT = "stereo"
_AUDIO_NORMALIZE = f"aresample={AUDIO_SAMPLE_RATE},aformat=sample_fmts=fltp:channel_layouts={AUDIO_CHANNEL_LAYOUT}"
_AUDIO_OUTPUT_ARGS = ["-c:a", "aac", "-ar", str(AUDIO_SAMPLE_RATE), "-ac", "2", "-b:a", "192k"]

# Some ffmpeg builds only accept atempo in [0.5, 2.0] per filter instance, so
# larger or smaller factors are split into a chain whose product is the factor.
ATEMPO_MIN, ATEMPO_MAX = 0.5, 2.0


def _require_tool(name: str) -> str:
    path = shutil.which(name)
    if not path:
        raise VideoAssemblyError(
            f"{name} was not found on PATH. Install ffmpeg (e.g. https://ffmpeg.org/download.html "
            "or `winget install ffmpeg` on Windows) and try again."
        )
    return path


def _probe(path: Path, entries: str, stream: str | None = None) -> str:
    cmd = [_require_tool("ffprobe"), "-v", "error"]
    if stream:
        cmd += ["-select_streams", stream]
    cmd += ["-show_entries", entries, "-of", "default=noprint_wrappers=1:nokey=1", str(path)]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise VideoAssemblyError(f"ffprobe could not read {path}: {result.stderr.strip()[-500:]}")
    return result.stdout.strip()


def has_audio_stream(path: str | Path) -> bool:
    """True if the file itself contains at least one audio stream (read with ffprobe)."""
    return bool(_probe(Path(path), "stream=index", "a"))


def _video_duration(path: Path) -> float:
    """Duration of the first video stream, falling back to the container duration."""
    value = _probe(path, "stream=duration", "v:0").splitlines()
    try:
        return float(value[0])
    except (IndexError, ValueError):
        return float(_probe(path, "format=duration"))


def atempo_chain(factor: float) -> str:
    """ffmpeg audio filter string that changes tempo by exactly `factor` (pitch
    preserved), split into several atempo instances when the factor falls outside
    one instance's portable [0.5, 2.0] range - e.g. 3.7 -> atempo=2.0,atempo=1.85."""
    if factor <= 0:
        raise VideoAssemblyError(f"factor must be > 0, got {factor}")
    parts: list[float] = []
    remaining = float(factor)
    while remaining > ATEMPO_MAX:
        parts.append(ATEMPO_MAX)
        remaining /= ATEMPO_MAX
    while remaining < ATEMPO_MIN:
        parts.append(ATEMPO_MIN)
        remaining /= ATEMPO_MIN
    parts.append(remaining)
    return ",".join(f"atempo={p:.10g}" for p in parts)


def concatenate_videos(clip_paths: list[str | Path], output_path: str | Path) -> Path:
    """Concatenate 2+ video clips into one file at `output_path`, in the
    given order, with BOTH video and audio.

    Uses ffmpeg's `concat` *filter* (re-encodes) rather than the `concat`
    *demuxer* (`-c copy`) - the demuxer requires byte-identical codec
    parameters across inputs, which two separately generated clips from
    the same model aren't guaranteed to have; the filter re-encodes and so
    works regardless. Every clip's audio is normalized to AAC-compatible
    44.1 kHz stereo before joining; a clip with no audio stream contributes
    silence of exactly its own video length, so audio never drifts against
    video across the cut.
    """
    if len(clip_paths) < 2:
        raise VideoAssemblyError(f"concatenate_videos needs at least 2 clips, got {len(clip_paths)}.")
    ffmpeg_path = _require_tool("ffmpeg")

    for p in clip_paths:
        if not Path(p).exists():
            raise VideoAssemblyError(f"Clip does not exist: {p}")

    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    inputs: list[str] = []
    filters: list[str] = []
    segments: list[str] = []
    next_input = len(clip_paths)
    for i, p in enumerate(clip_paths):
        inputs += ["-i", str(p)]
    for i, p in enumerate(clip_paths):
        duration = _video_duration(Path(p))
        if has_audio_stream(p):
            source = f"[{i}:a:0]"
        else:
            inputs += ["-f", "lavfi", "-t", f"{duration:.6f}",
                       "-i", f"anullsrc=r={AUDIO_SAMPLE_RATE}:cl={AUDIO_CHANNEL_LAYOUT}"]
            source = f"[{next_input}:a]"
            next_input += 1
        # Pad/trim each clip's audio to its video length so every segment is A/V-aligned.
        filters.append(f"{source}{_AUDIO_NORMALIZE},apad,atrim=0:{duration:.6f},asetpts=PTS-STARTPTS[a{i}]")
        segments.append(f"[{i}:v:0][a{i}]")
    filters.append(f"{''.join(segments)}concat=n={len(clip_paths)}:v=1:a=1[outv][outa]")

    result = subprocess.run(
        [ffmpeg_path, "-y", *inputs, "-filter_complex", ";".join(filters),
         "-map", "[outv]", "-map", "[outa]", *_AUDIO_OUTPUT_ARGS, str(output_path)],
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

    Video: `setpts=PTS/factor` (re-encodes; this changes presentation
    timestamps, so `-c copy` isn't an option) - unchanged from before.
    Audio: if the source has an audio stream it is kept and sped up by the
    same factor with a chained `atempo` (pitch preserved), then padded/trimmed
    to exactly the accelerated video's length; if it has none, a silent track
    of that length is added so later concatenation is reliable. Output audio
    is AAC, 44.1 kHz, stereo.
    """
    if factor <= 0:
        raise VideoAssemblyError(f"factor must be > 0, got {factor}")
    ffmpeg_path = _require_tool("ffmpeg")

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

    # Upper bound for generated silence; the real cut happens at the video's end (-shortest).
    target = _video_duration(input_path) / factor + 1.0
    inputs = ["-i", str(input_path)]
    if has_audio_stream(input_path):
        audio = f"[0:a:0]{atempo_chain(factor)},{_AUDIO_NORMALIZE}"
    else:
        inputs += ["-f", "lavfi", "-t", f"{target:.6f}",
                   "-i", f"anullsrc=r={AUDIO_SAMPLE_RATE}:cl={AUDIO_CHANNEL_LAYOUT}"]
        audio = f"[1:a]{_AUDIO_NORMALIZE}"
    # The audio is padded with silence and cut where the *encoded* video ends
    # (-shortest), not at a computed length: frame-rate quantization of setpts
    # can make the real video a frame or two longer than duration / factor.
    filter_complex = f"[0:v:0]setpts=PTS/{factor}[v];{audio},apad[a]"

    result = subprocess.run(
        [
            ffmpeg_path,
            "-y",
            *inputs,
            "-filter_complex", filter_complex,
            "-map", "[v]",
            "-map", "[a]",
            *_AUDIO_OUTPUT_ARGS,
            "-shortest",
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


def trim_video(
    input_path: str | Path, output_path: str | Path, start: float = 0.0, end: float | None = None
) -> Path:
    """Cut `input_path` down to the [start, end) range (seconds) and save the
    result to `output_path`, WITHOUT modifying or overwriting `input_path` -
    the source clip is only ever read. `end=None` keeps everything from
    `start` to the clip's natural end.

    Re-encodes rather than using `-c copy` - stream-copy trimming can only
    cut on keyframe boundaries, which would make "use only the first 2-4
    convincing seconds" imprecise. No audio stream is mapped (unchanged;
    final assembly does not use trim_video).
    """
    if start < 0:
        raise VideoAssemblyError(f"start must be >= 0, got {start}")
    if end is not None and end <= start:
        raise VideoAssemblyError(f"end ({end}) must be > start ({start})")

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

    cmd = [ffmpeg_path, "-y", "-i", str(input_path), "-ss", str(start)]
    if end is not None:
        cmd += ["-to", str(end)]
    cmd += ["-an", str(output_path)]

    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0 or not output_path.exists():
        raise VideoAssemblyError(
            f"ffmpeg trim failed (exit {result.returncode}) for {input_path} "
            f"[{start}, {end}]: {result.stderr.strip()[-2000:]}"
        )

    return output_path
