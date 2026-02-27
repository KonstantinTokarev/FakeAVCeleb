# Deepfake Detector

A web app that analyzes a **video from a link or upload** and returns a **deepfake likelihood score**, **confidence level**, and **flagged timestamps** using a Smart 4-Step multimodal detection pipeline.

## How it works

1. **Video type classification** — Identifies the kind of video (face swap, talking head, AI-generated, multi-person, cinematic, animation, real person) using face presence, frame-level signals, and temporal patterns.
2. **Type-aware model selection** — Chooses detector weights per type (e.g. CLIP A/V for face-swap, CommunityForensics + temporal for AI-generated scenes).
3. **Inference passes:**
   - **CLIP ViT-L/14** A/V consistency (face-swap / talking-head deepfakes)
   - **CommunityForensics-DeepfakeDet-ViT** binary frame classifier (AI vs real)
   - Optical flow + flicker + texture **temporal analysis**
   - **Wav2Vec2-large** (or signal-only) **audio** deepfake detection (voice cloning / TTS)
4. **Score fusion and verdict** — Type-specific thresholds; multi-person and AI-generated scenes get a confidence-weighted score boost when the type classifier flags them but per-signal scores are low (fully generated, no face deepfake).
5. **Plain-English report** — Verdict, “What we checked”, “What we found”, and optional PDF export.

## Repo structure

```
apps/
  web/      Next.js 14 frontend
  api/      FastAPI backend (jobs, upload, SSRF-safe URL validation)
  worker/   Python ML pipeline (async job consumer)
packages/
  shared/   TypeScript types and constants
```

## Local development

### Prerequisites

- Docker & Docker Compose (recommended)
- Or: Node 20+, pnpm, Python 3.12+, Redis, ffmpeg

### With Docker (recommended)

```bash
# 1. Create your env file
cp .env.example .env
# Edit .env and set POSTGRES_PASSWORD and DATABASE_URL

# 2. Build and start
docker compose up --build
```

- Web: http://localhost:3000
- API: http://localhost:8000
- API docs: http://localhost:8000/docs

### Without Docker

```bash
# Terminal 1 — API
cd apps/api && python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cd ../..
PYTHONPATH=apps uvicorn api.main:app --reload --port 8000

# Terminal 2 — Worker
cd apps/worker && python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cd ../..
PYTHONPATH=apps python -m worker.run

# Terminal 3 — Web
pnpm install && pnpm dev:web
```

## Production deployment

**Full checklist (hosting + Stripe):** see **[docs/GO_LIVE_STRIPE.md](docs/GO_LIVE_STRIPE.md)** for going live online with Stripe payments (env vars, webhook, smoke test).

### 1. Set environment variables

Copy `.env.example` to `.env` and configure:

| Variable | Description | Required |
|---|---|---|
| `DATABASE_URL` | PostgreSQL connection string | Yes |
| `POSTGRES_PASSWORD` | Postgres root password | Yes |
| `REDIS_URL` | Redis connection string | Yes |
| `ALLOWED_ORIGINS` | Comma-separated frontend URLs for CORS | Yes |
| `NEXT_PUBLIC_API_URL` | Public URL of the API (used at build time by Next.js) | Yes |
| `STORAGE_PATH` | Where uploaded/downloaded files are stored | No (default `/data/storage`) |
| `JOB_TTL_HOURS` | Hours before jobs are cleaned up | No (default 24) |
| `MAX_UPLOAD_BYTES` | Max upload size in bytes | No (default 200 MB) |
| `MAX_VIDEO_SECONDS` | Max video duration to process | No (default 300 s) |
| `MAX_FIRST_FREE_PER_IP_PER_DAY` | Max “first free” analyses per IP per day (rate limit) | No (default 3) |
| Stripe (`STRIPE_SECRET_KEY`, `STRIPE_WEBHOOK_SECRET`, `STRIPE_PRICE_ID`) | For 1 € payment | No (payment disabled if unset) |

**Abuse mitigation:** Users are identified by an anonymous ID (cookie/localStorage). Clearing cookies lets them get another free first check. To limit that, the API rate-limits how many “first free” jobs can be created per IP per day (see `MAX_FIRST_FREE_PER_IP_PER_DAY`). When exceeded, the API returns 429 and the UI shows a message to try again tomorrow or pay 1 €.

### 2. Deploy

```bash
docker compose up --build -d
```

Ensure the `storage_data` volume is backed by persistent storage (e.g. a mounted EBS volume or NFS share).

### 3. Reverse proxy

Place Nginx or Caddy in front:

- `/` → web container (port 3000)
- `/api/` → api container (port 8000)

Example Caddy config:

```
yourdomain.com {
    reverse_proxy /api/* api:8000
    reverse_proxy /* web:3000
}
```

### 4. Security checklist before going live

- [ ] Set a strong `POSTGRES_PASSWORD` (not `postgres`)
- [ ] Set `ALLOWED_ORIGINS` to your real domain only
- [ ] Place the `/api/admin/jobs` endpoint behind HTTP Basic Auth in your reverse proxy (it has no auth by default)
- [ ] Enable HTTPS (TLS termination at the reverse proxy)
- [ ] Mount `storage_data` on persistent block storage
- [ ] Configure log rotation / monitoring

## API reference

| Method | Path | Description |
|---|---|---|
| `POST` | `/api/jobs` | Create a job (`input_type`, `input_url?`, `options?`) |
| `POST` | `/api/jobs/{id}/upload` | Upload video file for an upload job |
| `GET` | `/api/jobs/{id}` | Poll job status and progress |
| `GET` | `/api/jobs/{id}/result` | Fetch full result once `status == DONE` |
| `GET` | `/api/admin/jobs` | List recent jobs (no auth — protect in production) |
| `GET` | `/health` | Health check |

## Documentation

- **[TESTING.md](TESTING.md)** — How to run and test the app (Docker, browser, logs).
- **[docs/AV_MODEL.md](docs/AV_MODEL.md)** — A/V model integration (CLIP default, optional FakeAVCeleb), custom model contract.

## License

Private / use as specified.
