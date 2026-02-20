"""
Pipeline: update job status, run fetch (if link), preprocess, face detection, inference, save result.
"""
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from db import AsyncSessionLocal
from config import settings
from worker.download import download_video, DownloadError
from worker.preprocess import trim_and_extract, get_video_duration, has_audio
from worker.face_detect import detect_faces_in_frames
from worker.inference import run_inference
import os
import uuid
import asyncio


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
        single_face = options.get("single_face", True)

        try:
            # For uploads: move to PREPROCESSING immediately so UI shows progress
            if job.input_type == "upload":
                update_status("PREPROCESSING", "PREPROCESSING", 2, 5)
                await db.commit()

            # Step 1: FETCHING (if link)
            if job.input_type == "link" and job.input_url:
                update_status("FETCHING", "FETCHING", 1, 5)
                await db.commit()
                await download_video(
                    job.input_url,
                    os.path.join(job_dir, "video.mp4"),
                    settings.max_video_bytes,
                )
                job.artifacts = job.artifacts or {}
                job.artifacts["video_path"] = os.path.join(job_dir, "video.mp4")
            else:
                video_path = (job.artifacts or {}).get("video_path") or os.path.join(job_dir, job.input_filename or "upload.mp4")
                if not os.path.isfile(video_path):
                    job.status = "FAILED"
                    job.error_code = "INTERNAL_ERROR"
                    job.error_message = f"Uploaded file not found at {video_path}"
                    await db.commit()
                    return
                job.artifacts = job.artifacts or {}
                job.artifacts["video_path"] = video_path

            if job.input_type == "link":
                update_status("PREPROCESSING", "PREPROCESSING", 2, 5)
                await db.commit()

            # Step 2: PREPROCESSING
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
            job.artifacts["audio_path"] = preproc.get("audio_path")
            job.artifacts["frame_paths"] = preproc.get("frame_paths", [])
            job.artifacts["duration_seconds"] = preproc["duration_seconds"]
            await db.commit()

            # Face detection
            face_coverage, multi_face = detect_faces_in_frames(preproc.get("frame_paths", []))
            if face_coverage < 10:
                job.status = "FAILED"
                job.error_code = "NO_FACE_DETECTED"
                job.error_message = "No face detected in video"
                await db.commit()
                return
            if single_face and multi_face:
                job.status = "FAILED"
                job.error_code = "MULTIPLE_FACES"
                job.error_message = "Multiple faces detected; single-face mode is on"
                await db.commit()
                return

            # Step 3: INFERENCING
            update_status("INFERENCING", "INFERENCING", 3, 5)
            await db.commit()

            score_overall, segments, model_meta = run_inference(
                video_path=video_path,
                audio_path=preproc.get("audio_path"),
                frame_paths=preproc.get("frame_paths", []),
                duration_seconds=preproc["duration_seconds"],
                face_coverage=face_coverage,
                audio_present=preproc.get("audio_present", False),
                multi_face=multi_face,
                window_seconds=5.0,
            )

            signals = {
                "face_coverage": face_coverage,
                "audio_present": preproc.get("audio_present", False),
                "multi_face": multi_face,
                "duration_seconds": preproc["duration_seconds"],
                "frames_analyzed": len(preproc.get("frame_paths", [])),
            }

            if face_coverage > 80 and preproc.get("audio_present") and not multi_face:
                confidence = "high"
            elif face_coverage >= 50:
                confidence = "med"
            else:
                confidence = "low"

            # Step 4: REPORTING
            update_status("REPORTING", "REPORTING", 4, 5)
            await db.commit()

            result = Result(
                id=str(uuid.uuid4()),
                job_id=job_id,
                score_overall=str(round(score_overall, 6)),
                confidence=confidence,
                segments=segments,
                signals=signals,
                model_meta=model_meta,
            )
            db.add(result)
            await db.flush()
            job.result_id = result.id
            job.status = "DONE"
            job.progress_step = "DONE"
            job.progress_done = "5"
            job.progress_total = "5"
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


