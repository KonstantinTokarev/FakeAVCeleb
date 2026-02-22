"""
Smart 4-Step Detection Pipeline
================================
Step 1 — Video type classification  (inference_type.py)
Step 2 — Type-aware model selection (this file, _model_config)
Step 3 — Inference passes           (inference_*.py modules)
Step 4 — Plain-English explanation  (inference_explain.py)
"""
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from db import AsyncSessionLocal
from config import settings
from worker.download import download_video, DownloadError
from worker.preprocess import trim_and_extract, get_video_duration, has_audio
from worker.face_detect import detect_faces_in_frames
from worker.inference import run_inference
from worker.inference_frames import run_frame_classifier
from worker.inference_temporal import run_temporal_analysis
from worker.inference_audio import run_audio_analysis
from worker.inference_type import classify_video_type, VIDEO_TYPE_LABELS_FAKE
from worker.inference_explain import explain_result
import os
import uuid
import asyncio


# ---------------------------------------------------------------------------
# Step 2 — Type-aware model configuration
# ---------------------------------------------------------------------------

_TYPE_WEIGHTS = {
    # face_swap / talking_head / real_person:
    #   CommunityForensics ViT is trained on AI-generated *images*, not face-swaps.
    #   Face-swaps look photo-realistic frame-by-frame → model misses them.
    #   → CLIP AV model dominates; artifact model weight = 0.
    "face_swap":    {"av": 0.72, "siglip": 0.00, "temporal": 0.15, "audio": 0.13},
    "talking_head": {"av": 0.60, "siglip": 0.00, "temporal": 0.15, "audio": 0.25},
    "real_person":  {"av": 0.65, "siglip": 0.00, "temporal": 0.20, "audio": 0.15},
    # multi_person: no reliable face-track → reduce AV, boost siglip+temporal
    # (most reliable signals for AI-generated crowd/group scenes)
    "multi_person": {"av": 0.10, "siglip": 0.35, "temporal": 0.40, "audio": 0.15},
    # ai_generated / animation: no real face → CLIP AV irrelevant, CommunityForensics+temporal dominate
    "ai_generated": {"av": 0.05, "siglip": 0.45, "temporal": 0.38, "audio": 0.12},
    "animation":    {"av": 0.00, "siglip": 0.35, "temporal": 0.50, "audio": 0.15},
    # cinematic: real film/TV/broadcast — AV model may run if face visible,
    #   CommunityForensics gets low weight (trained on still images, not film),
    #   temporal gets LOW weight because pans/cuts score high on real footage,
    #   audio is the most reliable remaining signal.
    "cinematic":    {"av": 0.45, "siglip": 0.05, "temporal": 0.20, "audio": 0.30},
}

_TYPE_SKIP = {
    "animation":    {"av"},        # no real faces → CLIP irrelevant
    "ai_generated": set(),
    "face_swap":    set(),
    "talking_head": set(),
    "multi_person": set(),
    "real_person":  set(),
    "cinematic":    set(),
}

# High-confidence threshold for CommunityForensics ViT per-frame fake probability
# (used in pipeline body where HC_THRESHOLD is defined as a local constant)
_HC_TRIGGER = 0.15  # fraction of high-confidence-fake frames that triggers elevated siglip_score


def _model_config(video_type: str) -> tuple[dict, set]:
    """Return (weights dict, set of passes to skip) for the detected video type."""
    weights = _TYPE_WEIGHTS.get(video_type, _TYPE_WEIGHTS["real_person"]).copy()
    skip    = _TYPE_SKIP.get(video_type, set())
    return weights, skip


# ---------------------------------------------------------------------------
# Main pipeline
# ---------------------------------------------------------------------------

async def run_pipeline(job_id: str):
    async with AsyncSessionLocal() as db:
        from models import Job, Result

        r = await db.execute(select(Job).where(Job.id == job_id))
        job = r.scalar_one_or_none()
        if not job or job.status in ("DONE", "FAILED", "CANCELED"):
            return

        def update_status(status: str, step: str = None, done: int = None, total: int = None):
            job.status = status
            job.progress_step = step or status
            job.progress_done = str(done) if done is not None else job.progress_done
            job.progress_total = str(total) if total is not None else job.progress_total

        job_dir = os.path.join(settings.storage_path, job_id)
        os.makedirs(job_dir, exist_ok=True)
        options = job.options or {}
        max_seconds = options.get("max_seconds", 60)

        try:
            # For uploads: move to PREPROCESSING immediately so UI shows progress
            if job.input_type == "upload":
                update_status("PREPROCESSING", "PREPROCESSING", 2, 6)
                await db.commit()

            # ── Step 1: FETCHING (if link) ────────────────────────────────
            if job.input_type == "link" and job.input_url:
                update_status("FETCHING", "FETCHING", 1, 6)
                await db.commit()
                await download_video(
                    job.input_url,
                    os.path.join(job_dir, "video.mp4"),
                    settings.max_video_bytes,
                )
                job.artifacts = {**(job.artifacts or {}), "video_path": os.path.join(job_dir, "video.mp4")}
            else:
                existing = job.artifacts or {}
                video_path = existing.get("video_path") or os.path.join(job_dir, job.input_filename or "upload.mp4")
                if not os.path.isfile(video_path):
                    job.status = "FAILED"
                    job.error_code = "INTERNAL_ERROR"
                    job.error_message = f"Uploaded file not found at {video_path}"
                    await db.commit()
                    return
                job.artifacts = {**existing, "video_path": video_path}

            if job.input_type == "link":
                update_status("PREPROCESSING", "PREPROCESSING", 2, 6)
                await db.commit()

            # ── Step 2: PREPROCESSING ─────────────────────────────────────
            video_path = job.artifacts["video_path"]
            duration = get_video_duration(video_path)
            if duration <= 0:
                job.status = "FAILED"
                job.error_code = "FORMAT_UNSUPPORTED"
                job.error_message = "Could not read video duration"
                await db.commit()
                return
            if duration > settings.max_video_seconds:
                job.status = "FAILED"
                job.error_code = "TOO_LONG"
                job.error_message = f"Video exceeds {settings.max_video_seconds}s"
                await db.commit()
                return

            audio_path = os.path.join(job_dir, "audio.wav")
            frames_dir = os.path.join(job_dir, "frames")
            preproc = await asyncio.to_thread(
                trim_and_extract,
                video_path,
                job_dir,
                max_seconds,
                audio_path=audio_path,
                frames_dir=frames_dir,
                num_frames=32,
            )
            job.artifacts = {
                **job.artifacts,
                "audio_path": preproc.get("audio_path"),
                "frame_paths": preproc.get("frame_paths", []),
                "duration_seconds": preproc["duration_seconds"],
            }
            await db.commit()

            frame_paths   = preproc.get("frame_paths", [])
            duration_sec  = preproc["duration_seconds"]
            audio_present = preproc.get("audio_present", False)

            # Face detection (non-fatal — gates A/V pass and type classifier)
            face_coverage, multi_face = detect_faces_in_frames(frame_paths)
            has_face = face_coverage >= 10

            # ── Step 3a: INFERENCING — passes 2–4 always run first ────────
            update_status("INFERENCING", "INFERENCING", 3, 6)
            await db.commit()

            # Pass 2: Frame-level CommunityForensics ViT (binary: real / AI-generated-or-fake)
            artifact_score, frame_scores, frame_findings, artifact_segments = await asyncio.to_thread(
                lambda: run_frame_classifier(
                    frame_paths=frame_paths,
                    duration_seconds=duration_sec,
                    window_seconds=5.0,
                )
            )

            # Pass 3: Temporal consistency (optical flow, flicker, texture)
            temporal_score, temporal_summary, temporal_segments = await asyncio.to_thread(
                lambda: run_temporal_analysis(
                    frame_paths=frame_paths,
                    duration_seconds=duration_sec,
                    window_seconds=5.0,
                )
            )

            # Pass 4: Audio deepfake detection (voice cloning / TTS)
            audio_fake_score, audio_summary = await asyncio.to_thread(
                lambda: run_audio_analysis(preproc.get("audio_path"))
            )

            # ── Frame vote counting (CommunityForensics ViT) ──────────────
            # Model outputs binary labels: "Fake" / "Real", with p_fake in [0,1].
            # We treat all "Fake" frames as the combined ai_frames bucket, and keep
            # deepfake_frames=0 (model does not distinguish subtypes).
            HC_THRESHOLD = 0.75  # "high-confidence" fake threshold
            ai_frames_high       = sum(1 for f in frame_findings if isinstance(f, dict) and f.get("label") == "Fake" and f.get("p_fake", 0) >= HC_THRESHOLD)
            deepfake_frames_high = 0
            ai_frames            = sum(1 for f in frame_findings if isinstance(f, dict) and f.get("label") == "Fake")
            deepfake_frames      = 0
            real_frames          = sum(1 for f in frame_findings if isinstance(f, dict) and f.get("label") == "Real")
            total_classified     = max(ai_frames + real_frames, 1)

            hc_fake_ratio = ai_frames_high / total_classified
            mv_fake_ratio = ai_frames / total_classified

            # CommunityForensics score → siglip_score
            # Model has 2.1% FPR, so we can trust it more and use a steeper curve.
            if hc_fake_ratio >= 0.40:
                siglip_score = min(1.0, 0.70 + (hc_fake_ratio - 0.40) * 1.0)
            elif hc_fake_ratio >= 0.15:
                siglip_score = 0.40 + (hc_fake_ratio - 0.15) * 1.2
            elif mv_fake_ratio >= 0.50:
                siglip_score = 0.30 + mv_fake_ratio * 0.20
            else:
                siglip_score = mv_fake_ratio * 0.30

            # ── Step 3b: VIDEO TYPE CLASSIFICATION (Step 1 of smart flow) ─
            update_status("CLASSIFYING", "CLASSIFYING", 4, 6)
            await db.commit()

            video_type_result = await asyncio.to_thread(
                lambda: classify_video_type(
                    frame_paths=frame_paths,
                    face_coverage=face_coverage,
                    multi_face=multi_face,
                    has_face=has_face,
                    audio_present=audio_present,
                    ai_frames=ai_frames,
                    deepfake_frames=deepfake_frames,
                    real_frames=real_frames,
                    total_classified=total_classified,
                    hc_fake_ratio=hc_fake_ratio,
                    temporal_score=temporal_score,
                    temporal_summary=temporal_summary,
                    duration_seconds=duration_sec,
                )
            )
            video_type       = video_type_result["type"]
            video_type_label = video_type_result["label"]

            # ── Step 3c: Type-aware model config ──────────────────────────
            weights, skip_passes = _model_config(video_type)

            # Pass 1: A/V consistency (face-swap / talking-head) — skip for animation
            av_score: float | None = None
            av_segments: list[dict] = []
            av_model_meta: dict = {}
            ran_av = has_face and "av" not in skip_passes
            if ran_av:
                av_score, av_segments, av_model_meta = await asyncio.to_thread(
                    lambda: run_inference(
                        video_path=video_path,
                        audio_path=preproc.get("audio_path"),
                        frame_paths=frame_paths,
                        duration_seconds=duration_sec,
                        face_coverage=face_coverage,
                        audio_present=audio_present,
                        multi_face=multi_face,
                        window_seconds=5.0,
                    )
                )

            has_audio_signal    = audio_present and not audio_summary.get("skip")
            has_temporal_signal = temporal_score > 0.0 and not temporal_summary.get("skip")

            # Apply type-aware weights, zero out unavailable signals
            w_av       = weights["av"]       if (av_score is not None) else 0.0
            w_siglip   = weights["siglip"]
            w_temporal = weights["temporal"] if has_temporal_signal else 0.0
            w_audio    = weights["audio"]    if has_audio_signal else 0.0

            # Renormalise so weights sum to 1
            w_total = w_av + w_siglip + w_temporal + w_audio
            if w_total > 0:
                w_av /= w_total; w_siglip /= w_total
                w_temporal /= w_total; w_audio /= w_total

            score_overall = min(1.0,
                (av_score or 0.0) * w_av +
                siglip_score      * w_siglip +
                temporal_score    * w_temporal +
                audio_fake_score  * w_audio
            )

            # ── Merge per-window segments ──────────────────────────────────
            time_buckets: dict[str, dict] = {}
            for seg in av_segments:
                key = f"{seg['start']}-{seg['end']}"
                time_buckets[key] = {**seg, "av_score": seg["score"], "artifact_score": None, "temporal_score": None}
            for seg in artifact_segments:
                key = f"{seg['start']}-{seg['end']}"
                if key in time_buckets:
                    time_buckets[key]["artifact_score"] = seg["score"]
                else:
                    time_buckets[key] = {**seg, "av_score": None, "artifact_score": seg["score"], "temporal_score": None}
            for seg in temporal_segments:
                key = f"{seg['start']}-{seg['end']}"
                if key in time_buckets:
                    time_buckets[key]["temporal_score"] = seg["score"]
                else:
                    time_buckets[key] = {**seg, "av_score": None, "artifact_score": None, "temporal_score": seg["score"]}
            for key, seg in time_buckets.items():
                s = (
                    (seg.get("av_score") or 0.0) * w_av +
                    (seg.get("artifact_score") or 0.0) * w_siglip +
                    (seg.get("temporal_score") or 0.0) * w_temporal
                )
                seg["score"] = round(min(1.0, s / max(w_av + w_siglip + w_temporal, 0.01)), 4)
            segments = sorted(time_buckets.values(), key=lambda s: s["start"])

            # ── Verdict ────────────────────────────────────────────────────
            # Type-specific thresholds:
            #   - multi_person / ai_generated: lower bar (0.40 FAKE, 0.25 UNCERTAIN)
            #     because CommunityForensics ViT is weak on crowded/AI-video frames
            #     and temporal is the primary signal, which scores lower than face-swap CLIP.
            #   - cinematic: higher FAKE bar (0.58) to avoid false positives on real film.
            #   - all others: standard 0.55 FAKE / 0.38 UNCERTAIN.
            if video_type in ("multi_person", "ai_generated"):
                fake_threshold      = 0.40
                uncertain_threshold = 0.25
            elif video_type == "cinematic":
                fake_threshold      = 0.58
                uncertain_threshold = 0.40
            else:
                fake_threshold      = 0.55
                uncertain_threshold = 0.38

            if score_overall >= fake_threshold:
                verdict_key = "FAKE"
                verdict     = "likely_fake"
            elif score_overall >= uncertain_threshold:
                verdict_key = "UNCERTAIN"
                verdict     = "uncertain"
            else:
                verdict_key = "REAL"
                verdict     = "likely_real"

            # ── Reconcile video type label with verdict ─────────────────────
            # For FAKE verdict: use the specific manipulation label (Face Swap, etc.)
            # For REAL/UNCERTAIN: use a neutral content descriptor, never an attack label.
            if verdict_key == "FAKE":
                video_type_label = VIDEO_TYPE_LABELS_FAKE.get(video_type, video_type_label)
            elif video_type in ("face_swap", "talking_head"):
                # Reclassify to neutral type since we didn't find manipulation
                if has_face and audio_present:
                    video_type = "talking_head"
                    video_type_label = "Person Speaking on Camera"
                else:
                    video_type = "real_person"
                    video_type_label = "Person Video"
            elif video_type in ("ai_generated", "animation", "multi_person") and verdict_key == "REAL":
                # These types are inherently ambiguous when the score is low —
                # the detectors are weaker for crowded/AI-video frames.
                # Override to UNCERTAIN rather than claiming "authentic."
                verdict_key = "UNCERTAIN"
                verdict     = "uncertain"
            # cinematic: keep label as-is on any verdict — it is a neutral,
            # accurate description of the content type.

            # ── Confidence ────────────────────────────────────────────────
            # Confidence = how certain we are of the verdict (not how fake it is).
            # For a REAL verdict: high confidence = low score + multiple detectors agree it's real.
            # For a FAKE verdict: high confidence = high score + multiple detectors agree it's fake.
            # For UNCERTAIN: always low/med confidence by definition.

            fake_signals_agree = sum([
                (av_score or 0) >= 0.60,          # calibrated CLIP says fake
                hc_fake_ratio >= 0.40,             # SigLIP high-conf votes (only matters for AI/animation)
                temporal_score >= 0.50,            # motion anomaly
                audio_fake_score >= 0.55,          # voice cloning
            ])
            real_signals_agree = sum([
                (av_score or 0) < 0.40,            # CLIP says real
                hc_fake_ratio < 0.10,              # SigLIP sees mostly real
                temporal_score < 0.25,             # natural motion
            ])

            if verdict_key == "FAKE":
                if fake_signals_agree >= 2 or (av_score or 0) >= 0.70:
                    confidence_label = "high"
                    confidence_value = 0.85
                elif fake_signals_agree >= 1:
                    confidence_label = "med"
                    confidence_value = 0.60
                else:
                    # Borderline — CLIP just crossed threshold
                    confidence_label = "low"
                    confidence_value = 0.40
            elif verdict_key == "REAL":
                if real_signals_agree >= 2 and score_overall < 0.28:
                    confidence_label = "high"
                    confidence_value = 0.85
                elif real_signals_agree >= 1 or score_overall < 0.38:
                    confidence_label = "med"
                    confidence_value = 0.60
                else:
                    confidence_label = "low"
                    confidence_value = 0.35
            else:  # UNCERTAIN
                confidence_label = "low"
                confidence_value = 0.30

            # ── Step 4: Plain-English Explanation ─────────────────────────
            explanation = explain_result(
                video_type=video_type,
                video_type_label=video_type_label,
                video_type_confidence=video_type_result["confidence"],
                final_score=score_overall,
                verdict=verdict_key,
                confidence=confidence_value,
                av_score=av_score,
                siglip_score=siglip_score,
                temporal_score=temporal_score if has_temporal_signal else None,
                audio_score=audio_fake_score if (has_audio_signal or audio_present) else None,
                ai_frames=ai_frames,
                deepfake_frames=deepfake_frames,
                real_frames=real_frames,
                total_classified=total_classified,
                has_face=has_face,
                multi_face=multi_face,
                audio_present=audio_present,
                ran_av=ran_av,
                ran_siglip=True,
                ran_temporal=has_temporal_signal,
                ran_audio=has_audio_signal,
                hc_fake_ratio=hc_fake_ratio,
            )

            # ── Findings (now the structured explanation) ─────────────────
            findings = {
                **explanation,
                "type_signals": video_type_result["signals"],
            }

            flagged_frames = [
                {"index": i, "score": round(s, 4), "findings": frame_findings[i]}
                for i, s in enumerate(frame_scores)
                if isinstance(frame_findings[i], dict) and
                    frame_findings[i].get("p_fake", 0) >= HC_THRESHOLD
            ]

            sub_scores: dict = {
                "av_consistency":     round(av_score, 6) if av_score is not None else None,
                "artifact_detection": round(siglip_score, 6),
                "temporal":           round(temporal_score, 6),
                "audio":              round(audio_fake_score, 6) if not audio_summary.get("skip") else None,
                "frame_votes": {
                    "ai_generated":         ai_frames,
                    "deepfake":             deepfake_frames,
                    "real":                 real_frames,
                    "total":                total_classified,
                    "high_confidence_fake": ai_frames_high + deepfake_frames_high,
                },
                "video_type": {
                    "type":       video_type,
                    "label":      video_type_label,
                    "confidence": round(video_type_result["confidence"], 3),
                },
                "weights_used": {
                    "av": round(w_av, 3),
                    "siglip": round(w_siglip, 3),
                    "temporal": round(w_temporal, 3),
                    "audio": round(w_audio, 3),
                },
            }

            signals = {
                "face_coverage":    face_coverage,
                "has_face":         has_face,
                "audio_present":    audio_present,
                "multi_face":       multi_face,
                "duration_seconds": duration_sec,
                "frames_analyzed":  len(frame_paths),
                "frames_flagged":   len(flagged_frames),
                "video_type":       video_type,
            }

            model_meta = {
                "av_model":       av_model_meta,
                "artifact_model": "CommunityForensics-DeepfakeDet-ViT (2.1% FPR)",
                "temporal_model": "optical_flow+flicker+texture (signal processing)",
                "audio_model":    "Wav2Vec2-large-anti-deepfake + signal processing",
                "type_classifier": "signal-based (no model download)",
                "fusion":         f"type-aware weighted linear (type={video_type})",
            }

            # ── REPORTING ─────────────────────────────────────────────────
            update_status("REPORTING", "REPORTING", 5, 6)
            await db.commit()

            result = Result(
                id=str(uuid.uuid4()),
                job_id=job_id,
                score_overall=str(round(score_overall, 6)),
                confidence=confidence_label,
                segments=segments,
                signals=signals,
                model_meta=model_meta,
                verdict=verdict,
                sub_scores=sub_scores,
                findings=findings,
                flagged_frames=flagged_frames,
            )
            db.add(result)
            await db.flush()
            job.result_id = result.id
            job.status = "DONE"
            job.progress_step = "DONE"
            job.progress_done = "6"
            job.progress_total = "6"
            await db.commit()

        except DownloadError as e:
            job.status = "FAILED"
            job.error_code = e.code
            job.error_message = e.message
            await db.commit()
        except Exception as e:
            job.status = "FAILED"
            job.error_code = "INTERNAL_ERROR"
            job.error_message = str(e)
            await db.commit()
            raise
