"""
Inference interface: takes preprocessed artifacts and returns overall score + per-window scores.
- By default uses a baseline (no trained model).
- If AV_MODEL_ENABLED=true and worker.inference_av implements run_inference_av(), that is used instead.
See inference_av.py and docs/AV_MODEL.md for how to plug in a real A/V model.
"""
from config import settings


def _run_baseline(
    video_path: str,
    audio_path: str | None,
    frame_paths: list[str],
    duration_seconds: float,
    face_coverage: float,
    audio_present: bool,
    multi_face: bool,
    window_seconds: float = 5.0,
) -> tuple[float, list[dict], dict]:
    """Placeholder: deterministic pseudo-scores. Replace with real model in inference_av.py."""
    segments = []
    t = 0.0
    while t < duration_seconds:
        end = min(t + window_seconds, duration_seconds)
        score = 0.3 + (hash(str(t)) % 20) / 100.0
        segments.append({"start": round(t, 1), "end": round(end, 1), "score": min(1.0, score)})
        t = end
    overall = sum(s["score"] for s in segments) / len(segments) if segments else 0.0
    model_meta = {"model_name": "baseline_av", "version": "0.1.0"}
    return overall, segments, model_meta


def run_inference(
    video_path: str,
    audio_path: str | None,
    frame_paths: list[str],
    duration_seconds: float,
    face_coverage: float,
    audio_present: bool,
    multi_face: bool,
    window_seconds: float = 5.0,
) -> tuple[float, list[dict], dict]:
    """
    Returns (score_overall, segments, model_meta).
    score_overall and segment scores are in [0, 1] (deepfake probability).
    """
    if settings.av_model_enabled:
        try:
            from worker.inference_av import run_inference_av
            return run_inference_av(
                video_path=video_path,
                audio_path=audio_path,
                frame_paths=frame_paths,
                duration_seconds=duration_seconds,
                face_coverage=face_coverage,
                audio_present=audio_present,
                multi_face=multi_face,
                window_seconds=window_seconds,
            )
        except Exception as e:
            import warnings
            warnings.warn(f"AV model failed, falling back to baseline: {e}")
    return _run_baseline(
        video_path=video_path,
        audio_path=audio_path,
        frame_paths=frame_paths,
        duration_seconds=duration_seconds,
        face_coverage=face_coverage,
        audio_present=audio_present,
        multi_face=multi_face,
        window_seconds=window_seconds,
    )
