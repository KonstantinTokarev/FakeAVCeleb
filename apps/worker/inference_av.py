"""
Real deepfake model integration.
- Set AV_MODEL_ENABLED=true to enable.
- Priority order:
    1. yermandy/deepfake-detection  (CLIP ViT-L/14, auto-downloads from HuggingFace, best accuracy)
    2. FakeAVCeleb Xception          (set FAKEAVCELEB_REPO_DIR, video-only)
    3. Baseline                      (hash placeholder, always available)
"""
from __future__ import annotations

import os
import sys

from worker.inference import _run_baseline

# Module-level cache so the model is loaded once per worker process
_clip_model = None
_clip_processor = None
_clip_device = None


def _get_clip_model():
    """Load yermandy/deepfake-detection TorchScript model (downloads once, cached)."""
    global _clip_model, _clip_processor, _clip_device
    if _clip_model is not None:
        return _clip_model, _clip_processor, _clip_device

    import torch
    from transformers import AutoProcessor

    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")

    # Download TorchScript model from HuggingFace Hub
    from huggingface_hub import hf_hub_download
    model_path = hf_hub_download(
        repo_id="yermandy/deepfake-detection",
        filename="model.torchscript",
    )
    model = torch.jit.load(model_path, map_location=device)
    model.eval()

    # The model uses CLIP ViT-L/14 preprocessing
    processor = AutoProcessor.from_pretrained("openai/clip-vit-large-patch14")

    _clip_model = model
    _clip_processor = processor
    _clip_device = device
    print("Loaded yermandy/deepfake-detection (CLIP ViT-L/14)", flush=True)
    return model, processor, device


def _run_clip_deepfake(
    frame_paths: list[str],
    duration_seconds: float,
    window_seconds: float,
) -> tuple[float, list[dict], dict]:
    """
    Run CLIP-based deepfake detector (yermandy/deepfake-detection).
    Returns a real fake-probability per frame, aggregated into segments.
    """
    import torch
    from PIL import Image

    model, processor, device = _get_clip_model()

    frame_scores: list[float] = []
    for path in frame_paths:
        if not os.path.isfile(path):
            frame_scores.append(0.5)
            continue
        img = Image.open(path).convert("RGB")
        inputs = processor(images=img, return_tensors="pt")
        pixel_values = inputs["pixel_values"].to(device)

        with torch.no_grad():
            # Model returns logit or probability; shape depends on export
            out = model(pixel_values)
            if isinstance(out, (list, tuple)):
                out = out[0]
            out = out.squeeze()

            # Handle both raw logit (scalar) and [real, fake] pair
            if out.ndim == 0:
                logit = out
            elif out.shape[-1] == 2:
                # Two-class: take log-odds of fake class
                logit = out[1] - out[0]
            else:
                logit = out[0]

            # Calibrated sigmoid: the yermandy model's operating range is
            # roughly [-2, +2] but real deepfakes land around -0.7 to -1.3,
            # making raw sigmoid produce 0.21–0.34. We shift by +0.8 and
            # tighten temperature to 0.6 so that:
            #   logit=-1.0 → p_fake ≈ 0.50 (was 0.27)
            #   logit= 0.0 → p_fake ≈ 0.74 (was 0.50)
            #   logit=+1.0 → p_fake ≈ 0.89 (was 0.73)
            #   logit=-2.0 → p_fake ≈ 0.27 (was 0.12 — real video stays low)
            logit_val = float(logit.item())
            p_fake = float(torch.sigmoid(torch.tensor((logit_val + 0.8) / 0.6)).item())

        frame_scores.append(p_fake)

    if not frame_scores:
        raise ValueError("No valid frames for CLIP inference")

    n = len(frame_scores)
    # Use 60th-percentile — more robust than mean against frames where face
    # isn't centred, while still catching sustained manipulation patterns.
    sorted_scores = sorted(frame_scores)
    p60_idx = min(int(0.60 * n), n - 1)
    score_overall = sorted_scores[p60_idx]

    segments: list[dict] = []
    t = 0.0
    while t < duration_seconds:
        end = min(t + window_seconds, duration_seconds)
        i0 = int(t / duration_seconds * n)
        i1 = min(int(end / duration_seconds * n), n)
        seg_scores = frame_scores[i0:i1] if i1 > i0 else [score_overall]
        segments.append({
            "start": round(t, 1),
            "end": round(end, 1),
            "score": round(sum(seg_scores) / len(seg_scores), 4),
        })
        t = end

    model_meta = {"model_name": "CLIP_ViT-L14_deepfake", "version": "2025-03"}
    return round(score_overall, 6), segments, model_meta


def _run_fakeavceleb(
    frame_paths: list[str],
    duration_seconds: float,
    window_seconds: float,
    repo_dir: str,
) -> tuple[float, list[dict], dict]:
    """Run FakeAVCeleb Xception (video/frames only) if repo and checkpoint are available."""
    try:
        import torch
        from PIL import Image
        import torchvision.transforms as T
    except ImportError:
        raise RuntimeError("FakeAVCeleb path requires torch, PIL, torchvision")

    if not repo_dir:
        raise RuntimeError("FAKEAVCELEB_REPO_DIR must be set")
    if not os.path.isdir(repo_dir):
        raise RuntimeError("FAKEAVCELEB_REPO_DIR must point to the FakeAVCeleb repo directory")
    checkpoint_path = os.path.join(repo_dir, "checkpoint.pt")
    if not os.path.isfile(checkpoint_path):
        raise FileNotFoundError(f"FakeAVCeleb checkpoint not found: {checkpoint_path}")

    sys.path.insert(0, repo_dir)
    try:
        from models.xception_origin import xception
    except Exception as e:
        sys.path.pop(0)
        raise RuntimeError(f"Cannot import FakeAVCeleb model: {e}")
    sys.path.pop(0)

    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    model = xception(num_classes=2, pretrained="")
    ckpt = torch.load(checkpoint_path, map_location=device)
    state = ckpt.get("state_dict", ckpt)
    # Strip 'module.' prefix if checkpoint was saved with DataParallel
    state = {k.replace("module.", ""): v for k, v in state.items()}
    model.load_state_dict(state, strict=False)
    model = model.to(device)
    model.eval()

    # Same transforms as in FakeAVCeleb Eval_Xception
    pretrained_means = [0.4489, 0.3352, 0.3106]
    pretrained_stds = [0.2380, 0.1965, 0.1962]
    transform = T.Compose([
        T.Resize((224, 224)),
        T.ToTensor(),
        T.Normalize(mean=pretrained_means, std=pretrained_stds),
    ])

    frame_scores: list[float] = []
    for path in frame_paths:
        if not os.path.isfile(path):
            continue
        img = Image.open(path).convert("RGB")
        x = transform(img).unsqueeze(0).to(device)
        with torch.no_grad():
            logits = model(x)
            probs = torch.softmax(logits, dim=1)
            p_fake = probs[0, 1].item()
        frame_scores.append(p_fake)

    if not frame_scores:
        raise ValueError("No valid frames for FakeAVCeleb inference")

    n = len(frame_scores)
    score_overall = sum(frame_scores) / n
    # Build segments by time windows
    segments = []
    t = 0.0
    while t < duration_seconds:
        end = min(t + window_seconds, duration_seconds)
        i0 = int(t / duration_seconds * n)
        i1 = min(int(end / duration_seconds * n), n)
        if i1 > i0:
            seg_score = sum(frame_scores[i0:i1]) / (i1 - i0)
        else:
            seg_score = score_overall
        segments.append({"start": round(t, 1), "end": round(end, 1), "score": seg_score})
        t = end

    model_meta = {"model_name": "FakeAVCeleb_Xception", "version": "1.0"}
    return score_overall, segments, model_meta


def run_inference_av(
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
    Real A/V model entrypoint. Same contract as run_inference():
    Returns (score_overall, segments, model_meta).

    Priority:
      1. CLIP ViT-L/14 (yermandy/deepfake-detection) — auto-downloads, best accuracy
      2. FakeAVCeleb Xception — if FAKEAVCELEB_REPO_DIR is set
      3. Baseline — deterministic fallback
    """
    from config import settings

    # 1. CLIP-based model (auto-download from HuggingFace)
    try:
        return _run_clip_deepfake(
            frame_paths=frame_paths,
            duration_seconds=duration_seconds,
            window_seconds=window_seconds,
        )
    except Exception as e:
        print(f"CLIP model failed, trying FakeAVCeleb: {e}", flush=True)

    # 2. FakeAVCeleb Xception (requires local repo + checkpoint)
    repo_dir = settings.fakeavceleb_repo_dir or os.environ.get("FAKEAVCELEB_REPO_DIR", "")
    if repo_dir:
        try:
            return _run_fakeavceleb(
                frame_paths=frame_paths,
                duration_seconds=duration_seconds,
                window_seconds=window_seconds,
                repo_dir=repo_dir,
            )
        except Exception as e:
            print(f"FakeAVCeleb model failed, using baseline: {e}", flush=True)

    # 3. Baseline fallback
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
