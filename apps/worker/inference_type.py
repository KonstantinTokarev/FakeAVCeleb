"""
Video type classifier — Step 1 of the smart detection pipeline.

Classifies a video into one of 6 types using existing frame data,
face-detection results, SigLIP2 frame votes, and temporal signals.
No new model download required.

Types:
  face_swap    — single face, identity shifts between frames
  talking_head — single face, direct gaze, minimal background motion
  ai_generated — no stable face, high AI-frame votes, strong temporal anomaly
  real_person  — stable face(s), natural motion, predominantly real frames
  multi_person — multiple people, group/conversation scene
  animation    — flat colours, very low texture variance, no real camera noise

Output:
  {
    "type": str,
    "label": str,           # human-readable label
    "confidence": float,    # 0–1
    "signals": dict,        # raw signals used to decide
  }
"""
from __future__ import annotations

from typing import List


VIDEO_TYPE_LABELS = {
    "face_swap":    "Face Video",
    "talking_head": "Person Speaking on Camera",
    "ai_generated": "AI-Generated Scene",
    "real_person":  "Person Video",
    "multi_person": "Multi-Person Scene",
    "animation":    "Animation / CGI",
}

# Labels used only when the video IS confirmed fake — more specific
VIDEO_TYPE_LABELS_FAKE = {
    "face_swap":    "Face Swap / Identity Replacement",
    "talking_head": "Synthetic Talking Head / Lip Sync",
    "ai_generated": "AI-Generated Scene",
    "real_person":  "Manipulated Video",
    "multi_person": "Manipulated Multi-Person Video",
    "animation":    "Animation / CGI",
}


def classify_video_type(
    frame_paths: List[str],
    face_coverage: float,
    multi_face: bool,
    has_face: bool,
    audio_present: bool,
    # SigLIP2 frame votes
    ai_frames: int,
    deepfake_frames: int,
    real_frames: int,
    total_classified: int,
    hc_fake_ratio: float,
    # Temporal signals
    temporal_score: float,
    temporal_summary: dict,
    # Duration
    duration_seconds: float,
) -> dict:
    """
    Classify video type from existing pipeline signals.
    Returns {"type", "label", "confidence", "signals"}.
    """
    n = max(total_classified, 1)
    ai_ratio   = ai_frames / n
    df_ratio   = deepfake_frames / n
    real_ratio = real_frames / n

    flow_score    = temporal_summary.get("optical_flow", {}).get("score", 0.0)
    flicker_score = temporal_summary.get("flicker", {}).get("score", 0.0)
    texture_score = temporal_summary.get("texture_stability", {}).get("score", 0.0)

    # Colour / texture analysis on a sample of frames
    colour_score, texture_variance = _colour_texture_signals(frame_paths[:8])

    raw_signals = {
        "face_coverage":  round(face_coverage, 1),
        "multi_face":     multi_face,
        "has_face":       has_face,
        "ai_ratio":       round(ai_ratio, 3),
        "deepfake_ratio": round(df_ratio, 3),
        "real_ratio":     round(real_ratio, 3),
        "hc_fake_ratio":  round(hc_fake_ratio, 3),
        "temporal_score": round(temporal_score, 3),
        "flow_score":     round(flow_score, 3),
        "flicker_score":  round(flicker_score, 3),
        "texture_score":  round(texture_score, 3),
        "colour_score":   round(colour_score, 3),
        "texture_var":    round(texture_variance, 4),
    }

    video_type, confidence = _classify(
        face_coverage=face_coverage,
        multi_face=multi_face,
        has_face=has_face,
        ai_ratio=ai_ratio,
        df_ratio=df_ratio,
        real_ratio=real_ratio,
        hc_fake_ratio=hc_fake_ratio,
        temporal_score=temporal_score,
        flow_score=flow_score,
        flicker_score=flicker_score,
        texture_score=texture_score,
        colour_score=colour_score,
        texture_variance=texture_variance,
        audio_present=audio_present,
        duration_seconds=duration_seconds,
    )

    return {
        "type":       video_type,
        "label":      VIDEO_TYPE_LABELS.get(video_type, video_type),
        "confidence": round(confidence, 3),
        "signals":    raw_signals,
    }


# ---------------------------------------------------------------------------
# Colour / texture signals (no external model)
# ---------------------------------------------------------------------------

def _colour_texture_signals(frame_paths: List[str]) -> tuple[float, float]:
    """
    Returns (colour_saturation_score, texture_variance).
    Animation / CGI has high saturation and very low local texture variance.
    """
    import numpy as np
    try:
        from PIL import Image
    except ImportError:
        return 0.0, 0.1

    sats, tvars = [], []
    for path in frame_paths:
        try:
            img = Image.open(path).convert("RGB").resize((64, 64))
            arr = np.array(img, dtype=np.float32) / 255.0
            r, g, b = arr[:,:,0], arr[:,:,1], arr[:,:,2]
            max_c = np.maximum(np.maximum(r, g), b)
            min_c = np.minimum(np.minimum(r, g), b)
            sat = np.where(max_c > 0, (max_c - min_c) / (max_c + 1e-6), 0.0)
            sats.append(float(sat.mean()))

            # Local texture variance: 8×8 patches
            gray = 0.299*r + 0.587*g + 0.114*b
            patch_vars = []
            for pr in range(0, 64, 8):
                for pc in range(0, 64, 8):
                    block = gray[pr:pr+8, pc:pc+8]
                    patch_vars.append(float(block.var()))
            tvars.append(float(np.mean(patch_vars)))
        except Exception:
            continue

    colour_score = float(np.mean(sats)) if sats else 0.3
    texture_var  = float(np.mean(tvars)) if tvars else 0.05
    return colour_score, texture_var


# ---------------------------------------------------------------------------
# Classification logic — rule-based decision tree
# ---------------------------------------------------------------------------

def _classify(
    face_coverage: float,
    multi_face: bool,
    has_face: bool,
    ai_ratio: float,
    df_ratio: float,
    real_ratio: float,
    hc_fake_ratio: float,
    temporal_score: float,
    flow_score: float,
    flicker_score: float,
    texture_score: float,
    colour_score: float,
    texture_variance: float,
    audio_present: bool,
    duration_seconds: float,
) -> tuple[str, float]:
    """
    Rule-based classifier. Returns (video_type, confidence).

    Decision priority:
      1. Animation (low texture var + high saturation → clear CGI signal)
      2. Multi-person (multi_face flag)
      3. AI-generated (high AI votes + temporal anomaly, no stable face)
      4. Face-swap (face present + high deepfake/AI votes)
      5. Talking head (single face, audio, low motion)
      6. Real person (default fallback with face)
    """

    # ── 1. Animation / CGI ────────────────────────────────────────────────
    is_flat_colour = texture_variance < 0.004
    is_saturated   = colour_score > 0.55
    if is_flat_colour and is_saturated:
        conf = min(1.0, (0.55 - texture_variance * 100) * 0.5 + (colour_score - 0.55) * 2)
        return "animation", max(0.5, conf)

    # ── 2. Multi-person ───────────────────────────────────────────────────
    if multi_face:
        # High AI signal in multi-face → still call it ai_generated
        if ai_ratio > 0.50 and hc_fake_ratio > 0.35:
            return "ai_generated", 0.65
        return "multi_person", 0.75

    # ── 3. Real person — check early so a single-face real video is never
    #       misclassified as multi_person or ai_generated due to noisy votes ──
    face_present = has_face and face_coverage >= 40
    strongly_real = real_ratio >= 0.55 and hc_fake_ratio < 0.20
    if face_present and strongly_real:
        # Could be talking head or generic real person
        is_talking_head = (
            audio_present
            and flow_score < 0.35
            and face_coverage >= 50
        )
        if is_talking_head:
            conf = min(1.0, real_ratio * 0.6 + (1 - flow_score) * 0.4)
            return "talking_head", max(0.60, conf)
        conf = min(1.0, real_ratio * 0.7 + (1 - temporal_score) * 0.3)
        return "real_person", max(0.55, conf)

    # ── 4. AI-generated scene (no stable face, strong AI+temporal signal) ─
    # Require BOTH AI frame votes AND temporal anomaly to avoid false positives
    # from normal video with a few compression artefacts.
    ai_signal      = ai_ratio > 0.45 or hc_fake_ratio > 0.40
    temporal_signal = temporal_score > 0.50 or flicker_score > 0.55
    no_stable_face  = not has_face or face_coverage < 25

    if ai_signal and no_stable_face:
        conf = min(1.0, ai_ratio * 0.6 + hc_fake_ratio * 0.4)
        return "ai_generated", max(0.55, conf)

    if ai_signal and temporal_signal and face_coverage < 50:
        conf = min(1.0, (ai_ratio + temporal_score) / 2 + hc_fake_ratio * 0.3)
        return "ai_generated", max(0.50, conf)

    # ── 5. Face swap ──────────────────────────────────────────────────────
    # Require high-confidence fake votes (frames that clearly beat Real by the
    # calibrated margin). Raw df_ratio is too noisy to trust alone.
    fake_signal = hc_fake_ratio > 0.35 or (hc_fake_ratio > 0.20 and ai_ratio > 0.30)
    if face_present and fake_signal:
        conf = min(1.0, hc_fake_ratio * 1.5 + 0.3)
        return "face_swap", max(0.50, conf)

    # ── 6. Talking head (fallback for face + audio cases) ─────────────────
    is_talking_head = (
        face_present
        and audio_present
        and flow_score < 0.35
        and face_coverage >= 50
    )
    if is_talking_head:
        conf = min(1.0, real_ratio * 0.6 + (1 - flow_score) * 0.4)
        return "talking_head", max(0.50, conf)

    # ── 7. Real person (default fallback with face) ───────────────────────
    if face_present:
        conf = min(1.0, real_ratio * 0.7 + (1 - temporal_score) * 0.3)
        return "real_person", max(0.45, conf)

    # ── Fallback: AI-generated (no face, nothing else matched) ────────────
    return "ai_generated", 0.40
