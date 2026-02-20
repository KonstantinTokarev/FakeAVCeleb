"""
Optional real A/V deepfake model integration.
- Set AV_MODEL_ENABLED=true to use a real model here instead of the baseline.
- FakeAVCeleb: set FAKEAVCELEB_REPO_DIR to the cloned repo (with checkpoint.pt) for video-only Xception.
- DiMoDif: requires pre-extracted features; see docs/AV_MODEL.md.
"""
from __future__ import annotations

import os
import sys

from worker.inference import _run_baseline


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
    """
    from config import settings

    repo_dir = settings.fakeavceleb_repo_dir or os.environ.get("FAKEAVCELEB_REPO_DIR", "")
    if repo_dir:
        try:
            return _run_fakeavceleb(
                frame_paths=frame_paths,
                duration_seconds=duration_seconds,
                window_seconds=window_seconds,
                repo_dir=repo_dir,
            )
        except Exception:
            pass

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
