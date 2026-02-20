# Using a real A/V deepfake model

You can replace the baseline (placeholder) scorer with a real audio-visual deepfake detection model.

## Checked repos: pretrained checkpoints

- **FakeAVCeleb** ([DASH-Lab/FakeAVCeleb](https://github.com/DASH-Lab/FakeAVCeleb)): Repo contains **checkpoint.pt** in the root. The app can use it for **video-only** (frame-based) inference: set `FAKEAVCELEB_REPO_DIR` to the cloned repo and `AV_MODEL_ENABLED=true`. Requires `torch`, `torchvision`, `Pillow`. Audio is not used in this integration (FakeAVCeleb’s eval expects separate spectrogram folders).
- **DiMoDif** ([mever-team/dimodif](https://github.com/mever-team/dimodif)): **No pretrained checkpoints in the repo** — `ckpt/dfd` and `ckpt/tfl` are empty. You must train with `scripts/best.py` (and run their feature extraction from [Visual_Speech_Recognition_for_Multiple_Languages](https://github.com/mpc001/Visual_Speech_Recognition_for_Multiple_Languages) first). DiMoDif works on **pre-extracted A/V features**, not raw video/audio, so it is not wired in this codebase.

## 1. Interface your model must implement

The worker calls `run_inference()` in `apps/worker/inference.py`, which can delegate to your implementation. Your code must provide a function with this signature and return shape:

```python
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
    # ...
    return score_overall, segments, model_meta
```

- **score_overall**: float in `[0, 1]` (deepfake probability for the whole clip).
- **segments**: list of `{"start": float, "end": float, "score": float}` for each time window (scores in `[0, 1]`).
- **model_meta**: e.g. `{"model_name": "digishield", "version": "1.0", "checksum": "..."}`.

Inputs you get from the pipeline:

- **video_path**: trimmed video file (e.g. MP4).
- **audio_path**: 16 kHz mono WAV, or `None` if no audio (then use visual-only and/or lower confidence).
- **frame_paths**: list of paths to sampled frames (e.g. 32 images).
- **duration_seconds**, **window_seconds**: to build segments (e.g. 5 s windows).
- **face_coverage**, **audio_present**, **multi_face**: for optional confidence/fallback logic.

## 2. Using FakeAVCeleb (video-only, pretrained)

1. Clone the repo and install deps:
   ```bash
   git clone https://github.com/DASH-Lab/FakeAVCeleb.git
   pip install torch torchvision Pillow
   ```
2. Set environment variables for the worker:
   - `AV_MODEL_ENABLED=true`
   - `FAKEAVCELEB_REPO_DIR=/path/to/FakeAVCeleb` (path to the cloned repo that contains `checkpoint.pt`)
3. Restart the worker. It will run the Xception model on each extracted frame and return per-segment and overall deepfake scores (audio is not used in this path).

## 3. Where to put your code

1. Implement `run_inference_av()` in **`apps/worker/inference_av.py`** (replace or extend the current stub).
2. Set **`AV_MODEL_ENABLED=true`** (or `1`) in the worker environment (e.g. in `docker-compose.yml` or `.env`).
3. Rebuild/restart the worker.

If `AV_MODEL_ENABLED` is set and `run_inference_av()` is present, it will be used; on any exception the worker falls back to the baseline and logs a warning.

## 4. Example: DigiShield-style model

The app was designed with the [DigiFakeAV / DigiShield](https://arxiv.org/abs/2505.16512) style in mind (spatiotemporal + cross-modal A/V fusion). If you have:

- PyTorch/ONNX code that takes video (or frames) + audio and outputs a deepfake score (and optionally per-segment scores), or
- A published implementation or checkpoint (e.g. from the paper’s authors or a reimplementation),

then:

1. Add your dependencies to **`apps/worker/requirements.txt`** (e.g. `torch`, `torchaudio`, or ONNX runtime).
2. In **`inference_av.py`**, load the model once (e.g. at module import or first call), then in `run_inference_av()`:
   - Run the model on `video_path` and `audio_path` (and/or `frame_paths`).
   - Map the model output to `score_overall` and to a list of segments with `start`, `end`, `score`.
   - Return `(score_overall, segments, model_meta)`.

## 5. Docker

In `docker-compose.yml`, under the `worker` service:

```yaml
environment:
  - AV_MODEL_ENABLED=1
  # For FakeAVCeleb (video-only): mount cloned repo
  - FAKEAVCELEB_REPO_DIR=/opt/fakeavceleb
```

Mount the FakeAVCeleb repo (and optional model dirs) if needed:

```yaml
volumes:
  - /path/on/host/to/FakeAVCeleb:/opt/fakeavceleb:ro
```

Install in the worker image: `torch`, `torchvision`, `Pillow` (add to `apps/worker/requirements.txt` if using FakeAVCeleb). Then rebuild: `docker compose build worker && docker compose up -d worker`.
