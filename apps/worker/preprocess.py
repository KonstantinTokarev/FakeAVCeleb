"""
Preprocessing: ffmpeg trim to max_seconds, extract audio to 16kHz mono wav, sample frames.
"""
import os
import subprocess
import ffmpeg


def get_video_duration(path: str) -> float:
    """Probe duration in seconds."""
    try:
        info = ffmpeg.probe(path)
        stream = next((s for s in info["streams"] if s["codec_type"] == "video"), None)
        if not stream:
            return 0.0
        return float(stream.get("duration", 0) or 0)
    except Exception:
        return 0.0


def has_audio(path: str) -> bool:
    try:
        info = ffmpeg.probe(path)
        return any(s.get("codec_type") == "audio" for s in info.get("streams", []))
    except Exception:
        return False


def trim_and_extract(
    video_path: str,
    out_dir: str,
    max_seconds: int,
    audio_path: str | None = None,
    frames_dir: str | None = None,
    num_frames: int = 32,
) -> dict:
    """
    Trim video to max_seconds, optionally extract audio (16kHz mono wav) and sample frames.
    Returns dict with duration_seconds, audio_path (if extracted), frame_paths.
    """
    duration = get_video_duration(video_path)
    if duration <= 0:
        raise ValueError("Could not get video duration")
    trim_to = min(duration, max_seconds)
    has_aud = has_audio(video_path)

    os.makedirs(out_dir, exist_ok=True)
    trimmed_path = os.path.join(out_dir, "trimmed.mp4")

    # Trim
    out_kw = {"c:v": "copy"}
    if has_aud:
        out_kw["c:a"] = "copy"
    (
        ffmpeg
        .input(video_path, t=trim_to)
        .output(trimmed_path, **out_kw)
        .overwrite_output()
        .run(capture_stderr=True)
    )

    result = {"duration_seconds": trim_to, "audio_present": has_aud, "frame_paths": []}

    if has_aud and audio_path:
        (
            ffmpeg
            .input(trimmed_path)
            .output(
                audio_path,
                acodec="pcm_s16le",
                ac=1,
                ar="16k",
            )
            .overwrite_output()
            .run(capture_stderr=True)
        )
        result["audio_path"] = audio_path

    if frames_dir:
        os.makedirs(frames_dir, exist_ok=True)
        # Evenly spaced frames
        for i in range(num_frames):
            t = (trim_to * (i + 0.5)) / num_frames if num_frames else 0
            frame_path = os.path.join(frames_dir, f"frame_{i:04d}.jpg")
            (
                ffmpeg
                .input(trimmed_path, ss=t)
                .output(frame_path, vframes=1)
                .overwrite_output()
                .run(capture_stderr=True)
            )
            result["frame_paths"].append(frame_path)
        result["frames_analyzed"] = num_frames

    return result
