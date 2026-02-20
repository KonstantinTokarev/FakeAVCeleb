# Deepfake Detector

A web app that analyzes a **video from a link or upload** and returns a **deepfake likelihood score**, **confidence**, and **flagged timestamps**, using **audio-visual (A/V) consistency** (multimodal fusion), inspired by research such as [DigiShield / DigiFakeAV](https://arxiv.org/abs/2505.16512).

## Product summary

- **Input:** Paste a public video URL or upload a file (MP4, MOV, WebM). Optional: analyze first N seconds (default 60).
- **Output:** Overall score (0–100), confidence (High/Med/Low), timeline of suspicious segments, and reliability notes (face coverage %, audio present, etc.).
- **Processing:** Async job queue (Redis), worker pipeline: fetch → preprocess (ffmpeg) → face detection → inference → report.

## Repo structure

- `apps/web` — Next.js frontend (landing, processing, results, error screens)
- `apps/api` — FastAPI backend (jobs API, upload, SSRF-safe URL validation)
- `apps/worker` — Python pipeline (queue consumer, download, ffmpeg, face detection, inference)
- `packages/shared` — TypeScript types, error codes, constants (and JSON schemas for contracts)

**Using a real A/V model:** The worker uses a baseline (placeholder) scorer by default. You can plug in a real audio-visual deepfake model (e.g. DigiShield-style) by implementing the interface in `apps/worker/inference_av.py` and setting `AV_MODEL_ENABLED=true`. See **[docs/AV_MODEL.md](docs/AV_MODEL.md)** for the exact contract and steps.

## Quick start (local)

### Prerequisites

- Node 18+, pnpm
- Python 3.12+
- Redis
- ffmpeg (for worker)
- (Optional) Docker for full stack

### 1. API

From repo root (so API and worker share the same `./data`):

```bash
cd apps/api
python -m venv .venv
source .venv/bin/activate   # or .venv\Scripts\activate on Windows
pip install -r requirements.txt
cd ../..
mkdir -p data
# Optional: copy .env.example to .env and set DATABASE_URL, REDIS_URL, STORAGE_PATH
PYTHONPATH=apps uvicorn api.main:app --reload --host 0.0.0.0 --port 8000
```

### 2. Worker

From repo root (same `./data` and DB as API):

```bash
cd apps/worker
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cd ../..
# Use same DATABASE_URL and REDIS_URL as API
PYTHONPATH=apps python -m worker.run
```

### 3. Web

```bash
pnpm install
pnpm build:shared
pnpm dev:web
```

Set `NEXT_PUBLIC_API_URL=http://localhost:8000` if needed. Open [http://localhost:3000](http://localhost:3000).

### 4. With Docker

From repo root:

```bash
docker compose up --build
```

API: http://localhost:8000  
Web: run separately with `pnpm dev:web` and set `NEXT_PUBLIC_API_URL=http://localhost:8000`.

## API (MVP)

- `POST /api/jobs` — Create job (body: `input_type`, `input_url?`, `options?`). Returns `job_id`, `status`.
- `POST /api/jobs/{job_id}/upload` — Multipart file upload for upload jobs.
- `GET /api/jobs/{job_id}` — Job status and progress.
- `GET /api/jobs/{job_id}/result` — Result (score, confidence, segments, signals).

## Error codes

`URL_INVALID`, `URL_BLOCKED_SSRF`, `DOWNLOAD_FAILED`, `FORMAT_UNSUPPORTED`, `TOO_LARGE`, `TOO_LONG`, `NO_AUDIO`, `NO_FACE_DETECTED`, `MULTIPLE_FACES`, `INFERENCE_FAILED`, `INTERNAL_ERROR`, `JOB_NOT_FOUND`, `JOB_CANCELED`.

## Development phases

- **Phase 0–1:** Repo, API skeleton, worker dummy pipeline, frontend screens ✅
- **Phase 2:** Upload + storage ✅
- **Phase 3:** SSRF-safe link ingestion (URL validation + safe download in worker)
- **Phase 4:** Preprocessing (ffmpeg trim, audio 16 kHz mono, frame sampling)
- **Phase 5:** Face detection/tracking, face coverage %, multi-face
- **Phase 6:** Model inference (A/V baseline + visual-only fallback), segments + timeline
- **Phase 7:** Error mapping, progress, rate limiting, admin page
- **Phase 8:** Deployment (S3, Postgres, Redis, secrets)

## License

Private / use as specified.
