"""
Temporal consistency analysis for AI-generated video detection.

AI-generated videos (Sora, Runway, Kling, Pika, AnimateDiff) have characteristic
temporal artifacts that image classifiers miss:

1. Optical flow irregularity  — unnatural motion fields; objects "swim" or warp
2. Frame-to-frame flicker     — pixel-level intensity variance inconsistent with
                                real camera noise
3. Texture temporal stability — AI models regenerate textures each frame causing
                                high-frequency flickering in smooth regions
4. Motion boundary coherence  — real motion has consistent edges; AI video has
                                edges that appear/disappear between frames
5. Luminance drift            — overall brightness can drift or pulse unnaturally

None of these require a trained model — they are pure signal-processing metrics
computed with OpenCV + NumPy. They work on any video type.
"""
from __future__ import annotations

import os
import math
from typing import List, Tuple

import numpy as np


# ---------------------------------------------------------------------------
# Frame loading
# ---------------------------------------------------------------------------

def _load_frames_gray(frame_paths: List[str], size: int = 128) -> List[np.ndarray]:
    """Load frames as grayscale float32 arrays in [0,1]."""
    frames = []
    for path in frame_paths:
        if not os.path.isfile(path):
            continue
        try:
            from PIL import Image
            img = Image.open(path).convert("L").resize((size, size))
            frames.append(np.array(img, dtype=np.float32) / 255.0)
        except Exception:
            continue
    return frames


def _load_frames_rgb(frame_paths: List[str], size: int = 128) -> List[np.ndarray]:
    """Load frames as RGB float32 arrays."""
    frames = []
    for path in frame_paths:
        if not os.path.isfile(path):
            continue
        try:
            from PIL import Image
            img = Image.open(path).convert("RGB").resize((size, size))
            frames.append(np.array(img, dtype=np.float32) / 255.0)
        except Exception:
            continue
    return frames


# ---------------------------------------------------------------------------
# Signal 1: Optical flow irregularity (Lucas-Kanade via OpenCV)
# ---------------------------------------------------------------------------

def _optical_flow_score(frames_gray: List[np.ndarray]) -> Tuple[float, dict]:
    """
    Estimate optical flow between consecutive frames using Farneback dense flow.
    AI video has two distinct patterns:
      - "Swimmy" motion: flow magnitude variance is too high in smooth regions
      - Teleportation: sudden large displacements with no intermediate motion
    Returns score in [0,1] and diagnostic dict.
    """
    if len(frames_gray) < 4:
        return 0.0, {"skip": "too few frames"}

    try:
        import cv2
    except ImportError:
        return 0.0, {"skip": "cv2 not available"}

    magnitudes = []
    variances = []
    sudden_jumps = 0

    prev = (frames_gray[0] * 255).astype(np.uint8)
    for curr_arr in frames_gray[1:]:
        curr = (curr_arr * 255).astype(np.uint8)
        flow = cv2.calcOpticalFlowFarneback(
            prev, curr, None,
            pyr_scale=0.5, levels=3, winsize=15,
            iterations=3, poly_n=5, poly_sigma=1.2, flags=0
        )
        mag = np.sqrt(flow[..., 0]**2 + flow[..., 1]**2)
        mean_mag = float(mag.mean())
        var_mag  = float(mag.var())
        magnitudes.append(mean_mag)
        variances.append(var_mag)

        # Sudden jump: mean displacement > 8 pixels in a 128x128 frame
        if mean_mag > 8.0:
            sudden_jumps += 1
        prev = curr

    if not magnitudes:
        return 0.0, {}

    mean_flow = float(np.mean(magnitudes))
    std_flow  = float(np.std(magnitudes))
    mean_var  = float(np.mean(variances))

    # AI video: very low mean flow (objects barely move) but high variance
    # OR sudden large jumps between frames
    low_motion_high_var = (mean_flow < 1.0 and mean_var > 0.5)
    irregular_motion = std_flow / (mean_flow + 0.01) > 2.5   # coefficient of variation

    jump_ratio = sudden_jumps / max(len(magnitudes), 1)

    score = 0.0
    if low_motion_high_var:
        score += 0.35
    if irregular_motion:
        score += 0.30
    if jump_ratio > 0.1:
        score += min(0.35, jump_ratio * 1.5)

    findings = {
        "mean_flow_px": round(mean_flow, 3),
        "flow_cv": round(std_flow / (mean_flow + 0.01), 3),
        "sudden_jumps": sudden_jumps,
    }
    return round(min(1.0, score), 4), findings


# ---------------------------------------------------------------------------
# Signal 2: Frame-to-frame pixel flicker
# ---------------------------------------------------------------------------

def _flicker_score(frames_gray: List[np.ndarray]) -> Tuple[float, dict]:
    """
    Measure frame-to-frame absolute pixel difference statistics.
    AI video has characteristic high-frequency spatial flicker in smooth regions
    (each frame is independently generated, so textures aren't stable).
    Real cameras have smooth, physically consistent noise.
    """
    if len(frames_gray) < 3:
        return 0.0, {"skip": "too few frames"}

    diffs = []
    for i in range(1, len(frames_gray)):
        diff = np.abs(frames_gray[i] - frames_gray[i-1])
        diffs.append(diff)

    stacked = np.stack(diffs)              # (N-1, H, W)
    mean_diff = float(stacked.mean())
    # Temporal variance per pixel: high in AI video (flickering)
    temporal_var = float(stacked.var(axis=0).mean())
    # Spatial variance of diffs: AI flicker is spatially uniform; real motion is spatially varied
    spatial_var_of_diff = float(np.array([d.var() for d in diffs]).mean())

    # Real camera: mean_diff ~0.01–0.04, temporal_var low
    # AI video: mean_diff inconsistent, temporal_var elevated
    flicker_signal = temporal_var / (mean_diff + 1e-4)

    if flicker_signal > 0.8:
        score = min(1.0, 0.5 + (flicker_signal - 0.8) * 0.5)
    elif flicker_signal > 0.4:
        score = 0.3 + (flicker_signal - 0.4) * 0.5
    else:
        score = flicker_signal * 0.3

    findings = {
        "mean_frame_diff": round(mean_diff, 4),
        "temporal_variance": round(temporal_var, 6),
        "flicker_signal": round(flicker_signal, 4),
    }
    return round(min(1.0, score), 4), findings


# ---------------------------------------------------------------------------
# Signal 3: Texture temporal stability
# ---------------------------------------------------------------------------

def _texture_stability_score(frames_gray: List[np.ndarray]) -> Tuple[float, dict]:
    """
    Measure how stable local texture patches are over time.
    AI video regenerates textures each frame → high patch-level variance.
    Real video: textures are stable except where objects move.
    """
    if len(frames_gray) < 4:
        return 0.0, {"skip": "too few frames"}

    H, W = frames_gray[0].shape
    patch = 16
    stabilities = []

    for r in range(0, H - patch, patch):
        for c in range(0, W - patch, patch):
            patches = [f[r:r+patch, c:c+patch].mean() for f in frames_gray]
            stabilities.append(float(np.std(patches)))

    if not stabilities:
        return 0.0, {}

    mean_instability = float(np.mean(stabilities))
    high_instability_ratio = float(np.mean([s > 0.05 for s in stabilities]))

    # Real video: mean_instability ~0.01–0.03 in static regions
    if mean_instability > 0.06:
        score = min(1.0, 0.4 + (mean_instability - 0.06) * 5.0)
    elif mean_instability > 0.035:
        score = 0.2 + (mean_instability - 0.035) * 8.0
    else:
        score = mean_instability * 3.0

    findings = {
        "mean_patch_instability": round(mean_instability, 4),
        "high_instability_patch_ratio": round(high_instability_ratio, 3),
    }
    return round(min(1.0, score), 4), findings


# ---------------------------------------------------------------------------
# Signal 4: Luminance drift
# ---------------------------------------------------------------------------

def _luminance_drift_score(frames_gray: List[np.ndarray]) -> Tuple[float, dict]:
    """
    Track per-frame mean luminance over time.
    AI video often has pulsing or drifting brightness (no AGC / real-world lighting).
    """
    if len(frames_gray) < 4:
        return 0.0, {"skip": "too few frames"}

    lum = [float(f.mean()) for f in frames_gray]
    diffs = [abs(lum[i] - lum[i-1]) for i in range(1, len(lum))]

    mean_drift = float(np.mean(diffs))
    max_drift  = float(np.max(diffs))
    # Coefficient of variation of luminance
    lum_cv = float(np.std(lum) / (np.mean(lum) + 1e-4))

    # Real camera: small smooth luminance changes; AI: irregular pulsing
    score = 0.0
    if lum_cv > 0.08:
        score += min(0.5, (lum_cv - 0.08) * 3.0)
    if max_drift > 0.10:
        score += min(0.5, (max_drift - 0.10) * 2.0)

    findings = {
        "luminance_cv": round(lum_cv, 4),
        "max_frame_drift": round(max_drift, 4),
        "mean_drift": round(mean_drift, 4),
    }
    return round(min(1.0, score), 4), findings


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def run_temporal_analysis(
    frame_paths: List[str],
    duration_seconds: float,
    window_seconds: float = 5.0,
) -> Tuple[float, dict, List[dict]]:
    """
    Run temporal consistency analysis on sampled video frames.

    Returns:
        temporal_score  : float       overall temporal anomaly score [0,1]
        summary         : dict        per-signal scores and findings
        segments        : list[dict]  time-windowed temporal scores
    """
    if len(frame_paths) < 4:
        return 0.0, {"skip": "not enough frames"}, []

    frames_gray = _load_frames_gray(frame_paths, size=128)
    if len(frames_gray) < 4:
        return 0.0, {"skip": "could not load frames"}, []

    flow_score,    flow_findings    = _optical_flow_score(frames_gray)
    flicker_score, flicker_findings = _flicker_score(frames_gray)
    texture_score, texture_findings = _texture_stability_score(frames_gray)
    lum_score,     lum_findings     = _luminance_drift_score(frames_gray)

    # Weighted fusion — optical flow and flicker are strongest signals
    temporal_score = min(1.0,
        flow_score    * 0.35 +
        flicker_score * 0.30 +
        texture_score * 0.25 +
        lum_score     * 0.10
    )

    summary = {
        "optical_flow":    {"score": flow_score,    **flow_findings},
        "flicker":         {"score": flicker_score, **flicker_findings},
        "texture_stability": {"score": texture_score, **texture_findings},
        "luminance_drift": {"score": lum_score,     **lum_findings},
    }

    # Build time-window segments
    n = len(frame_paths)
    segments: List[dict] = []
    t = 0.0
    while t < duration_seconds:
        end = min(t + window_seconds, duration_seconds)
        i0 = max(0, int(t / duration_seconds * n) - 1)
        i1 = min(int(end / duration_seconds * n) + 1, len(frames_gray))
        if i1 - i0 >= 2:
            sub = frames_gray[i0:i1]
            fs, _ = _flicker_score(sub)
            ts, _ = _texture_stability_score(sub) if len(sub) >= 4 else (0.0, {})
            seg_score = fs * 0.6 + ts * 0.4
        else:
            seg_score = temporal_score
        segments.append({
            "start": round(t, 1),
            "end": round(end, 1),
            "score": round(seg_score, 4),
        })
        t = end

    return round(temporal_score, 6), summary, segments
