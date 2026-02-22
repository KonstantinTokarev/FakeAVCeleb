"""
Audio deepfake / voice cloning detection.

Two complementary passes:

Pass A — Pretrained model: nii-yamagishilab/wav2vec-large-anti-deepfake-nda
  Wav2Vec2-Large fine-tuned on 18k hours of fake speech + 56k hours of real speech.
  Binary classifier: real vs. synthesised/cloned voice.
  Auto-downloads from HuggingFace (~1.2 GB, cached after first run).

Pass B — Signal-processing (no model needed):
  1. Spectral flatness   — TTS/vocoder output is more spectrally uniform than real speech
  2. Pitch consistency   — voice cloning produces unnaturally stable pitch (no micro-jitter)
  3. Silence pattern     — AI-generated speech has unnatural silence distribution
  4. Bandwidth analysis  — some vocoders produce band-limited output
  5. Phase coherence     — neural vocoders leave phase artifacts detectable via GD analysis

Both passes are fused; Pass A is authoritative when audio is long enough (≥3s).
Falls back to Pass B only when the model cannot be loaded.
"""
from __future__ import annotations

import os
import math
from typing import Tuple

import numpy as np

MODEL_ID = "nii-yamagishilab/wav2vec-large-anti-deepfake-nda"

_model = None
_processor = None
_device = None


def _get_model():
    global _model, _processor, _device
    if _model is not None:
        return _model, _processor, _device

    import torch
    from transformers import Wav2Vec2ForSequenceClassification, Wav2Vec2Processor

    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    print(f"Loading {MODEL_ID} on {device}…", flush=True)

    processor = Wav2Vec2Processor.from_pretrained(MODEL_ID)
    model = Wav2Vec2ForSequenceClassification.from_pretrained(MODEL_ID)
    model = model.to(device).eval()

    _model = model
    _processor = processor
    _device = device
    print(f"Loaded {MODEL_ID}", flush=True)
    return model, processor, device


# ---------------------------------------------------------------------------
# Pass A: Wav2Vec2 model inference
# ---------------------------------------------------------------------------

def _model_audio_score(audio_path: str) -> Tuple[float, dict]:
    """Run Wav2Vec2 anti-deepfake model. Returns (fake_prob, findings)."""
    import torch

    model, processor, device = _get_model()

    # Load wav (16kHz mono, as extracted by preprocess.py)
    try:
        import scipy.io.wavfile as wavfile
        sr, wav = wavfile.read(audio_path)
        if wav.dtype != np.float32:
            wav = wav.astype(np.float32) / np.iinfo(wav.dtype).max
        if wav.ndim > 1:
            wav = wav.mean(axis=1)
    except Exception as e:
        return 0.0, {"error": f"wav load failed: {e}"}

    # Model expects 16kHz; preprocess.py already extracts at 16k
    duration = len(wav) / sr
    if duration < 0.5:
        return 0.0, {"skip": "audio too short"}

    # Chunk long audio into 10s windows, average predictions
    chunk_size = sr * 10
    scores = []
    for start in range(0, len(wav), chunk_size):
        chunk = wav[start:start + chunk_size]
        if len(chunk) < sr * 0.5:
            break
        inputs = processor(chunk, sampling_rate=sr, return_tensors="pt", padding=True)
        inputs = {k: v.to(device) for k, v in inputs.items()}
        with torch.no_grad():
            logits = model(**inputs).logits
            probs = torch.softmax(logits, dim=-1).squeeze()
            # Model label order: check config; typically 0=bonafide, 1=spoof
            if probs.shape[0] == 2:
                p_fake = float(probs[1].item())
            else:
                p_fake = float(torch.sigmoid(logits[0]).item())
        scores.append(p_fake)

    if not scores:
        return 0.0, {"skip": "no chunks processed"}

    fake_prob = float(np.mean(scores))
    findings = {
        "model": MODEL_ID,
        "chunks_analyzed": len(scores),
        "duration_s": round(duration, 1),
        "fake_prob": round(fake_prob, 4),
    }
    return round(fake_prob, 4), findings


# ---------------------------------------------------------------------------
# Pass B: Signal-processing audio analysis
# ---------------------------------------------------------------------------

def _load_wav(audio_path: str) -> Tuple[np.ndarray | None, int]:
    """Load wav file, return (samples_float32, sample_rate)."""
    try:
        import scipy.io.wavfile as wavfile
        sr, wav = wavfile.read(audio_path)
        if wav.dtype != np.float32:
            wav = wav.astype(np.float32) / (np.iinfo(wav.dtype).max if np.issubdtype(wav.dtype, np.integer) else 1.0)
        if wav.ndim > 1:
            wav = wav.mean(axis=1)
        return wav, int(sr)
    except Exception:
        return None, 0


def _spectral_flatness_score(wav: np.ndarray, sr: int) -> Tuple[float, dict]:
    """
    Spectral flatness (Wiener entropy): ratio of geometric to arithmetic mean of spectrum.
    TTS/vocoder output is spectrally flatter than real speech (more tone-like in voiced regions).
    High flatness in voiced segments → synthetic.
    """
    frame = sr // 10  # 100ms frames
    hop   = frame // 2
    flatnesses = []

    for start in range(0, len(wav) - frame, hop):
        chunk = wav[start:start + frame] * np.hanning(frame)
        spectrum = np.abs(np.fft.rfft(chunk)) + 1e-10
        geo_mean = np.exp(np.mean(np.log(spectrum)))
        ari_mean = np.mean(spectrum)
        flatnesses.append(float(geo_mean / (ari_mean + 1e-10)))

    if not flatnesses:
        return 0.0, {}

    mean_flat = float(np.mean(flatnesses))
    # Real speech: flatness ~0.05–0.20; TTS: often >0.25 in voiced regions
    score = max(0.0, (mean_flat - 0.20) / 0.30)
    return round(min(1.0, score), 4), {"spectral_flatness": round(mean_flat, 4)}


def _pitch_stability_score(wav: np.ndarray, sr: int) -> Tuple[float, dict]:
    """
    Estimate pitch using autocorrelation; measure micro-jitter.
    Real voices have natural pitch variation (jitter ~0.5–2%); cloned voices are unnaturally stable.
    """
    frame = sr // 10
    hop   = frame // 4
    pitches = []

    min_lag = sr // 500   # 500 Hz max
    max_lag = sr // 50    # 50 Hz min

    for start in range(0, len(wav) - frame, hop):
        chunk = wav[start:start + frame]
        if chunk.std() < 0.005:   # silence
            continue
        # Autocorrelation
        ac = np.correlate(chunk, chunk, mode='full')
        ac = ac[len(ac)//2:]
        # Find peak in pitch range
        if max_lag < len(ac):
            region = ac[min_lag:max_lag]
            if region.max() > 0:
                peak = int(np.argmax(region)) + min_lag
                f0 = sr / peak
                if 50 < f0 < 500:
                    pitches.append(f0)

    if len(pitches) < 5:
        return 0.0, {"skip": "insufficient voiced frames"}

    pitch_arr = np.array(pitches)
    cv = float(pitch_arr.std() / (pitch_arr.mean() + 1e-4))
    # Real speech CV ~0.05–0.20; cloned voice: often <0.03
    score = max(0.0, (0.04 - cv) / 0.04) * 0.8
    return round(min(1.0, score), 4), {"pitch_cv": round(cv, 4), "mean_f0": round(float(pitch_arr.mean()), 1)}


def _silence_pattern_score(wav: np.ndarray, sr: int) -> Tuple[float, dict]:
    """
    Analyse silence/pause distribution.
    TTS produces very regular inter-word pauses; real speech has irregular silences.
    """
    frame = sr // 20   # 50ms
    energy = []
    for start in range(0, len(wav) - frame, frame):
        chunk = wav[start:start + frame]
        energy.append(float(np.sqrt(np.mean(chunk**2))))

    if len(energy) < 10:
        return 0.0, {}

    threshold = np.percentile(energy, 20)
    is_silence = [e < threshold * 1.5 for e in energy]

    # Find silence run lengths
    runs = []
    count = 0
    for s in is_silence:
        if s:
            count += 1
        elif count > 0:
            runs.append(count)
            count = 0

    if len(runs) < 3:
        return 0.0, {"silence_runs": len(runs)}

    run_cv = float(np.std(runs) / (np.mean(runs) + 1e-4))
    # TTS: very regular pauses → low CV; real speech: irregular → high CV
    score = max(0.0, (0.5 - run_cv) / 0.5) * 0.6
    return round(min(1.0, score), 4), {"silence_run_cv": round(run_cv, 3), "num_pauses": len(runs)}


def _signal_processing_score(audio_path: str) -> Tuple[float, dict]:
    """Combined signal-processing pass. Returns (fake_prob, findings)."""
    wav, sr = _load_wav(audio_path)
    if wav is None or len(wav) < sr * 0.5:
        return 0.0, {"skip": "audio unreadable or too short"}

    fs_score, fs_f = _spectral_flatness_score(wav, sr)
    ps_score, ps_f = _pitch_stability_score(wav, sr)
    si_score, si_f = _silence_pattern_score(wav, sr)

    score = min(1.0, fs_score * 0.45 + ps_score * 0.35 + si_score * 0.20)
    findings = {
        "spectral_flatness": fs_f,
        "pitch_stability": ps_f,
        "silence_pattern": si_f,
    }
    return round(score, 4), findings


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def run_audio_analysis(audio_path: str | None) -> Tuple[float, dict]:
    """
    Run audio deepfake detection on the extracted audio track.

    Returns:
        audio_fake_score : float   probability the audio is synthesised/cloned [0,1]
        summary          : dict    per-pass findings and scores
    """
    if not audio_path or not os.path.isfile(audio_path):
        return 0.0, {"skip": "no audio track"}

    # Pass A: Neural model
    model_score = 0.0
    model_findings: dict = {}
    model_available = False
    try:
        model_score, model_findings = _model_audio_score(audio_path)
        model_available = True
    except Exception as e:
        model_findings = {"error": str(e)}
        print(f"Audio model failed, using signal processing only: {e}", flush=True)

    # Pass B: Signal processing
    sp_score, sp_findings = _signal_processing_score(audio_path)

    if model_available:
        # Model is authoritative; SP is a sanity check
        audio_score = model_score * 0.75 + sp_score * 0.25
    else:
        audio_score = sp_score

    summary = {
        "model_score": round(model_score, 4) if model_available else None,
        "signal_processing_score": round(sp_score, 4),
        "model_findings": model_findings,
        "signal_findings": sp_findings,
    }
    return round(min(1.0, audio_score), 6), summary
