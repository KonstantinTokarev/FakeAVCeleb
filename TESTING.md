# Testing the Deepfake Detector (Docker, macOS)

Use Docker to run the full stack, then test in the browser.

## 1. Start the stack

From the **project root**:

```bash
docker compose up --build
```

First run will build the API, worker, and web images and start:

- **Web** → http://localhost:3000  
- **API** → http://localhost:8000  
- **Postgres** (internal)  
- **Redis** (internal, port 6379 exposed)

Wait until you see the API and worker logs (no errors). The web app may take a bit to finish building.

## 2. Test in the browser

1. Open **http://localhost:3000**.
2. **Option A — Upload**
   - Click “Upload video (MP4, MOV, WebM)” and pick a short talking-head video (e.g. 10–60 seconds).
   - You should be redirected to the processing page, then to the result page with a score and timeline.
3. **Option B — Link**
   - Paste a **public** video URL (e.g. a direct link to an MP4).
   - Click “Analyze from link”.
   - Same flow: processing → result (or error if the URL is invalid or the worker can’t download it).

## 3. Verify FakeAVCeleb is used

When the real A/V model (FakeAVCeleb) is enabled:

1. **Env:** Worker must have `AV_MODEL_ENABLED=true` and `FAKEAVCELEB_REPO_DIR=/path/to/FakeAVCeleb` (path to the cloned repo that contains `checkpoint.pt`).
2. **Run one analysis** (upload a short video or use a link).
3. **On the result page**, under the score you should see **Model: FakeAVCeleb_Xception (v1.0)**. If you see **Model: baseline_av (v0.1.0)** instead, the worker fell back to the baseline (check env vars, repo path, and worker logs).
4. **Worker logs:** `docker compose logs worker` (or your worker process). If FakeAVCeleb fails to load, you’ll see a warning like “AV model failed, falling back to baseline: …”.

## 4. Optional checks

- **API health:**  
  `curl http://localhost:8000/health`  
  → `{"status":"ok"}`

- **Admin (job list):**  
  Open http://localhost:3000/admin to see recent jobs and their status/errors.

- **Logs:**  
  `docker compose logs -f worker` to watch the pipeline (fetch → preprocess → face → inference).

## 5. Stop

```bash
docker compose down
```

To remove DB and storage data as well:

```bash
docker compose down -v
```

## Troubleshooting

| Issue | What to do |
|-------|-------------|
| **Stuck at “Analyzing video” / Step 1 of 5** | The worker is not processing the job. Run `docker compose logs worker` and ensure the worker container is running (`docker compose ps`). You should see “Worker started, waiting for jobs…” and “Processing job &lt;id&gt;” when a job is picked up. If the worker exits or shows connection errors, fix Redis/Postgres URLs or rebuild: `docker compose up -d --build worker`. |
| Port 3000 or 8000 in use | Change ports in `docker-compose.yml` (e.g. `"3001:3000"` for web). |
| “No face detected” | Use a video with a clear, visible face (talking head). |
| Link analysis fails | Use a **public** URL; avoid private or redirect-heavy links. |
| Worker errors in logs | Ensure ffmpeg and dependencies are present in the worker image; rebuild with `docker compose build --no-cache worker`. |
