"""
Video type classifier — Step 1 of the smart detection pipeline.

Classifies a video into one of 7 types using existing frame data,
face-detection results, CommunityForensics frame votes, and temporal signals.
No new model download required.

Types:
  face_swap    — single face, identity shifts between frames
  talking_head — single face, direct gaze, minimal background motion
  ai_generated — no stable face, high AI-frame votes, strong temporal anomaly
  real_person  — stable face(s), natural motion, predominantly real frames
  multi_person — multiple people, group/conversation scene
  animation    — flat colours, very low texture variance, no real camera noise
  cinematic    — film/TV/broadcast footage: film grain, natural camera motion,
                 high dynamic range, no face or wide shot — NOT AI-generated

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
    "cinematic":    "Cinematic / Broadcast Footage",
}

# Labels used only when the video IS confirmed fake — more specific
VIDEO_TYPE_LABELS_FAKE = {
    "face_swap":    "Face Swap / Identity Replacement",
    "talking_head": "Synthetic Talking Head / Lip Sync",
    "ai_generated": "AI-Generated Scene",
    "real_person":  "Manipulated Video",
    "multi_person": "Manipulated Multi-Person Video",
    "animation":    "Animation / CGI",
    "cinematic":    "Manipulated Cinematic Footage",
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

    # Cinematic / broadcast signals (film grain, motion coherence, HDR, letterbox)
    cin_signals = _cinematic_signals(frame_paths)
    cin_score   = cinematic_score(cin_signals)

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
        "cinematic_score":     round(cin_score, 4),
        "cinematic_grain":     cin_signals.get("grain", 0.0),
        "cinematic_dr":        cin_signals.get("dynamic_range", 0.0),
        "cinematic_letterbox": cin_signals.get("letterbox", 0.0),
        "cinematic_motion":    cin_signals.get("motion_coherence", 0.0),
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
        cin_score=cin_score,
        cin_signals=cin_signals,
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
# Cinematic / broadcast signals (no external model)
# ---------------------------------------------------------------------------

def _cinematic_signals(frame_paths: List[str]) -> dict:
    """
    Detect signals characteristic of real film/TV/broadcast footage.

    Cinematic footage differs from both AI-generated video and casual phone video:

    1. Film grain / sensor noise:
       Real cameras have spatially correlated, spectrally white noise layered on
       top of the image. AI generators are trained to minimise this and produce
       unrealistically clean frames. We measure high-frequency noise energy in
       flat regions using a Laplacian residual after Gaussian blur.

    2. Natural camera motion (handheld jitter, pans, tilts):
       Real cinematography has smooth, purposeful motion with occasional
       micro-jitter. We measure the coefficient of variation of optical-flow
       magnitudes — real camera moves are directionally consistent (low CV),
       while AI video has inconsistent "swimming" motion (high CV).
       Importantly, cinematic pans produce *large coherent* flow, unlike AI.

    3. High dynamic range / shadow detail:
       Cinematic grading compresses highlights and lifts shadows (S-curve).
       We measure histogram fill — a well-graded frame has values spread across
       the full 0–255 range with filled mid-tones, unlike AI frames which are
       often over-saturated or unnaturally uniform.

    4. Letterbox / aspect ratio:
       Widescreen (2.35:1, 2.39:1, 1.85:1) black bars are a strong cinematic
       indicator. We detect solid black rows at top/bottom.

    Returns a dict of individual signal scores (all [0,1], higher = more cinematic).
    """
    import numpy as np
    try:
        from PIL import Image, ImageFilter
    except ImportError:
        return {"grain": 0.0, "motion_coherence": 0.0, "dynamic_range": 0.0, "letterbox": 0.0}

    grain_scores:   list[float] = []
    dr_scores:      list[float] = []
    letterbox_scores: list[float] = []

    frames_gray_small: list[np.ndarray] = []

    for path in frame_paths[:12]:
        try:
            img = Image.open(path).convert("RGB")
            w, h = img.size

            # ── Letterbox detection ───────────────────────────────────────
            gray_full = np.array(img.convert("L"), dtype=np.float32) / 255.0
            top_mean    = float(gray_full[:max(1, h // 10), :].mean())
            bottom_mean = float(gray_full[max(0, h - h // 10):, :].mean())
            # Black bars: both top and bottom average < 0.06 (near-black)
            letterbox_scores.append(1.0 if (top_mean < 0.06 and bottom_mean < 0.06) else 0.0)

            # ── Film grain: Laplacian residual in flat regions ───────────
            # Blur the image to remove edges, then measure residual noise
            img_small = img.resize((128, 128))
            arr  = np.array(img_small.convert("L"), dtype=np.float32) / 255.0
            blur = np.array(img_small.filter(ImageFilter.GaussianBlur(radius=2)).convert("L"),
                            dtype=np.float32) / 255.0
            residual = arr - blur

            # Only measure grain in "flat" regions (low local variance)
            flat_mask = np.abs(residual) < 0.05
            if flat_mask.sum() > 100:
                grain_rms = float(np.sqrt(np.mean(residual[flat_mask] ** 2)))
                # Real film: grain_rms ~0.008–0.030; AI: ~0.001–0.006
                grain_score = min(1.0, max(0.0, (grain_rms - 0.004) / 0.022))
            else:
                grain_score = 0.3  # neutral if no flat region
            grain_scores.append(grain_score)

            # ── Dynamic range / histogram fill ───────────────────────────
            hist, _ = np.histogram(arr, bins=32, range=(0.0, 1.0))
            # Fraction of bins with non-trivial content (> 0.5% of pixels)
            filled_bins = float(np.sum(hist > (arr.size * 0.005)) / 32)
            # Shadow presence: at least some pixels in bottom 10% of range
            shadow_fill = float(np.mean(arr < 0.10))
            # Highlight roll-off: smooth decrease in top bins (not clipped)
            top_bins = hist[28:32].astype(float)
            rolloff  = 1.0 if (top_bins[0] > top_bins[-1] > 0) else 0.0
            dr_score = min(1.0, filled_bins * 0.5 + min(shadow_fill * 10, 0.3) + rolloff * 0.2)
            dr_scores.append(dr_score)

            frames_gray_small.append(arr)

        except Exception:
            continue

    # ── Motion coherence from optical flow ───────────────────────────────────
    # Cinematic pans/tilts = large, directionally consistent flow vectors.
    # AI video = small, inconsistent "swimming" motion OR sudden jumps.
    motion_coherence = 0.0
    if len(frames_gray_small) >= 3:
        try:
            import cv2
            coherences = []
            for i in range(1, len(frames_gray_small)):
                prev = (frames_gray_small[i-1] * 255).astype(np.uint8)
                curr = (frames_gray_small[i]   * 255).astype(np.uint8)
                flow = cv2.calcOpticalFlowFarneback(
                    prev, curr, None,
                    pyr_scale=0.5, levels=2, winsize=12,
                    iterations=2, poly_n=5, poly_sigma=1.1, flags=0
                )
                fx, fy = flow[..., 0], flow[..., 1]
                # Mean direction vector
                mean_fx, mean_fy = float(fx.mean()), float(fy.mean())
                mean_mag = float(np.sqrt(fx**2 + fy**2).mean())

                if mean_mag > 0.3:
                    # Coherence: how well individual vectors align with the mean
                    dot = fx * mean_fx + fy * mean_fy
                    coherence = float(np.clip(dot / (mean_mag ** 2 + 1e-6), 0, 1).mean())
                    coherences.append(coherence)

            motion_coherence = float(np.mean(coherences)) if coherences else 0.4
        except Exception:
            motion_coherence = 0.3

    return {
        "grain":            round(float(np.mean(grain_scores))   if grain_scores   else 0.0, 4),
        "dynamic_range":    round(float(np.mean(dr_scores))      if dr_scores      else 0.0, 4),
        "letterbox":        round(float(np.mean(letterbox_scores)) if letterbox_scores else 0.0, 4),
        "motion_coherence": round(motion_coherence, 4),
    }


def cinematic_score(signals: dict) -> float:
    """
    Combine cinematic sub-signals into a single [0,1] score.
    Higher = more likely to be real cinematic/broadcast footage.
    """
    grain    = signals.get("grain",            0.0)
    dr       = signals.get("dynamic_range",    0.0)
    lb       = signals.get("letterbox",        0.0)
    mc       = signals.get("motion_coherence", 0.0)

    # Letterbox alone is a very strong indicator — short-circuit
    if lb >= 0.80:
        return min(1.0, 0.65 + lb * 0.35)

    # Weighted combination; grain is the strongest signal
    score = (
        grain * 0.40 +
        dr    * 0.30 +
        mc    * 0.20 +
        lb    * 0.10
    )
    return round(min(1.0, score), 4)


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
    cin_score: float = 0.0,
    cin_signals: dict | None = None,
) -> tuple[str, float]:
    """
    Rule-based classifier. Returns (video_type, confidence).

    Decision priority:
      0. Cinematic / broadcast (film grain + coherent motion + HDR — trumps ai_generated)
      1. Animation (low texture var + high saturation → clear CGI signal)
      2. Multi-person (multi_face flag)
      3. Real person early-exit (stable face + mostly real frames)
      4. AI-generated (high AI votes + temporal anomaly, no stable face)
      5. Face-swap (face present + high deepfake/AI votes)
      6. Talking head (single face, audio, low motion)
      7. Real person (default fallback with face)
    """
    if cin_signals is None:
        cin_signals = {}

    # ── 0. Cinematic / broadcast footage ─────────────────────────────────
    # Fires BEFORE the ai_generated check so cinematic footage with no
    # detected face isn't mis-labelled as AI-generated.
    #
    # Strong indicators: letterbox bars (widescreen crop), film grain, HDR,
    # and coherent directional camera motion (pan/tilt/dolly).
    #
    # We gate on low hc_fake_ratio to avoid catching actual AI videos that
    # happen to have cinematic-looking frames (e.g. Sora with grain).
    letterbox   = cin_signals.get("letterbox",        0.0)
    grain       = cin_signals.get("grain",            0.0)
    motion_coh  = cin_signals.get("motion_coherence", 0.0)

    # Definitive cinematic signals (any one of these alone is strong):
    # - Widescreen letterbox bars (common in movies/TV rips)
    # - Very high grain score (film camera sensor noise)
    strong_cinematic = letterbox >= 0.70 or grain >= 0.65

    # Combined evidence: moderate grain + good motion coherence + low fake ratio
    combined_cinematic = (
        cin_score >= 0.45
        and hc_fake_ratio < 0.30          # model doesn't confidently say fake
        and temporal_score < 0.55         # no AI-style temporal anomalies
    )

    if (strong_cinematic or combined_cinematic) and hc_fake_ratio < 0.40:
        conf = min(1.0, cin_score * 0.7 + (1.0 - hc_fake_ratio) * 0.3)
        return "cinematic", max(0.50, conf)

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
    ai_signal       = ai_ratio > 0.45 or hc_fake_ratio > 0.40
    temporal_signal = temporal_score > 0.50 or flicker_score > 0.55
    no_stable_face  = not has_face or face_coverage < 25

    if ai_signal and no_stable_face:
        # Before calling AI-generated, check whether cinematic evidence is
        # borderline — if so, prefer cinematic over ai_generated fallback.
        if cin_score >= 0.35 and hc_fake_ratio < 0.35:
            conf = min(1.0, cin_score * 0.6 + (1.0 - hc_fake_ratio) * 0.4)
            return "cinematic", max(0.45, conf)
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

    # ── Fallback: check cinematic one last time before defaulting to AI ────
    # This catches wide/action shots in movies that have no detected face
    # but show clear film grain and dynamic range.
    if cin_score >= 0.30 and hc_fake_ratio < 0.35:
        return "cinematic", max(0.40, cin_score)

    # ── Last resort: AI-generated (no face, nothing else matched) ─────────
    return "ai_generated", 0.40
