"""
Frame-level AI/deepfake detector — second-opinion pass.

Model: aiwithoutborders-xyz/CommunityForensics-DeepfakeDet-ViT
  - ViT-Small/16 fine-tuned on 2.7M images from 4,803 AI generators
  - University of Michigan / "Community Forensics" (arXiv:2411.04125)
  - Single sigmoid output: 0 = real, 1 = AI-generated/fake
  - 97.2% accuracy, 2.1% false positive rate, MIT licence
  - Auto-downloads from HuggingFace (~140 MB, cached after first run)

The key improvement over the previous SigLIP2 model:
  - SigLIP2 had ~30-70% false positive rate on real cinematic/phone footage
  - CommunityForensics has 2.1% FPR — designed specifically for forensic use
  - Trained for AI-generated image detection, NOT for face-swap deepfakes
    → weight is 0 for face/person video types; only used for ai_generated/animation

Returns:
    artifact_score : float        fake probability in [0,1]
    frame_scores   : list[float]  per-frame fake probability
    frame_findings : list[dict]   per-frame details
    segments       : list[dict]   time-windowed segments
"""
from __future__ import annotations

import os
from typing import List, Tuple

MODEL_ID = "aiwithoutborders-xyz/CommunityForensics-DeepfakeDet-ViT"

# Module-level cache — loaded once per worker process
_model     = None
_processor = None
_device    = None


def _get_model():
    global _model, _processor, _device
    if _model is not None:
        return _model, _processor, _device

    import torch
    from transformers import ViTForImageClassification, AutoImageProcessor

    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    print(f"Loading {MODEL_ID} on {device}…", flush=True)

    processor = AutoImageProcessor.from_pretrained(MODEL_ID)
    model     = ViTForImageClassification.from_pretrained(MODEL_ID)
    model     = model.to(device).eval()

    _model     = model
    _processor = processor
    _device    = device
    print(f"Loaded {MODEL_ID} (CommunityForensics ViT — 2.1% FPR)", flush=True)
    return model, processor, device


def _classify_frame(path: str) -> Tuple[float, dict]:
    """
    Classify a single frame.
    Returns (fake_prob, findings).

    The model outputs a single logit; sigmoid maps it to [0,1].
    0 = real, 1 = AI-generated/fake.

    We apply a small calibration margin: the model must be at least
    60% confident (sigmoid > 0.60) before we call a frame "fake".
    This guards against borderline cases on real footage.
    """
    import torch
    from PIL import Image

    model, processor, device = _get_model()

    img    = Image.open(path).convert("RGB")
    inputs = processor(images=img, return_tensors="pt")
    inputs = {k: v.to(device) for k, v in inputs.items()}

    with torch.no_grad():
        outputs  = model(**inputs)
        logit    = outputs.logits.squeeze()          # scalar logit
        p_fake   = float(torch.sigmoid(logit).item())

    # Label: only call "Fake" if model is clearly confident
    CONFIDENCE_MARGIN = 0.60
    label = "Fake" if p_fake >= CONFIDENCE_MARGIN else "Real"

    findings = {
        "label":  label,
        "p_fake": round(p_fake, 4),
        "p_real": round(1.0 - p_fake, 4),
    }
    return p_fake, findings


def run_frame_classifier(
    frame_paths: List[str],
    duration_seconds: float,
    window_seconds: float = 5.0,
    use_resnet: bool = True,  # kept for API compatibility
) -> Tuple[float, List[float], List[dict], List[dict]]:
    """
    Run CommunityForensics ViT on every frame.

    Returns:
        artifact_score : float               overall fake probability [0,1]
        frame_scores   : list[float]         per-frame fake probability
        frame_findings : list[dict]          per-frame breakdown
        segments       : list[dict]          time-windowed segments
    """
    if not frame_paths:
        return 0.0, [], [], []

    frame_scores:   List[float] = []
    frame_findings: List[dict]  = []

    for path in frame_paths:
        if not os.path.isfile(path):
            frame_scores.append(0.0)
            frame_findings.append({"error": "missing"})
            continue
        try:
            score, findings = _classify_frame(path)
        except Exception as e:
            score    = 0.0
            findings = {"error": str(e)}
        frame_scores.append(score)
        frame_findings.append(findings)

    n = len(frame_scores)

    # Use 70th-percentile — robust against frames where a face isn't present
    # while still catching AI-generated footage sustained across most frames.
    sorted_scores = sorted(frame_scores)
    p70_idx       = min(int(0.70 * n), n - 1)
    artifact_score = float(sorted_scores[p70_idx])

    # Build time-window segments
    segments: List[dict] = []
    t = 0.0
    while t < duration_seconds:
        end  = min(t + window_seconds, duration_seconds)
        i0   = int(t   / duration_seconds * n)
        i1   = min(int(end / duration_seconds * n), n)
        window_scores = frame_scores[i0:i1] if i1 > i0 else [artifact_score]
        segments.append({
            "start": round(t, 1),
            "end":   round(end, 1),
            "score": round(sum(window_scores) / len(window_scores), 4),
        })
        t = end

    return round(artifact_score, 6), frame_scores, frame_findings, segments
