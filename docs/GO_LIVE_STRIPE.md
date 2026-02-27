# Go live: detailed step-by-step

Follow this in order. Each step lists what you do, what you need, and how to verify before moving on.

---

## 1. Get a server

**What:** A Linux VPS with Docker. The worker runs ML inference (CPU) so get at least 4 GB RAM, 2 vCPU, 40 GB disk. GPU optional (speeds up inference but not required — PyTorch uses CPU by default).

**Providers:** Hetzner, DigitalOcean, Linode, AWS Lightsail, etc.

**Do:**

1. Create a VPS (Ubuntu 22.04 or 24.04).
2. SSH in: `ssh root@YOUR_IP`.
3. Install Docker and Docker Compose:
   ```bash
   curl -fsSL https://get.docker.com | sh
   ```
4. Install Git: `apt install -y git`.
5. Set up a firewall — only allow SSH (22), HTTP (80), HTTPS (443):
   ```bash
   ufw allow OpenSSH
   ufw allow 80/tcp
   ufw allow 443/tcp
   ufw enable
   ```
   This blocks direct access to ports 8000 (API), 3000 (web), 6379 (Redis), 5432 (Postgres) from the internet. They'll only be reachable through the reverse proxy.

**Verify:** `docker --version` prints a version. `ufw status` shows 22, 80, 443 allowed.

---

## 2. Get a domain and point DNS

**What:** A domain (e.g. `yourapp.com`) with DNS A record pointing to the server IP. You can use a single domain for both web and API (e.g. `yourapp.com` for web, `/api/*` proxied to the API container), or a subdomain (e.g. `api.yourapp.com`).

**Do:**

1. Buy or use a domain from any registrar (Namecheap, Cloudflare, etc.).
2. Add a DNS **A record**: `yourapp.com` → `YOUR_SERVER_IP`.
3. If using a subdomain for the API: add another A record: `api.yourapp.com` → `YOUR_SERVER_IP`.

**Single-domain setup (recommended, simpler):** Use one domain (`yourapp.com`). Caddy will route `/api/*` to the API container and everything else to the web container. This means `NEXT_PUBLIC_API_URL` = `https://yourapp.com` (same origin — no CORS needed for the browser, but keep `ALLOWED_ORIGINS` set anyway for safety).

**Verify:** `dig yourapp.com +short` returns your server IP (may take a few minutes to propagate).

---

## 3. Clone the repo on the server

```bash
cd /opt
git clone <your-repo-url> deepfake-detector
cd deepfake-detector
```

If the repo is private, either set up an SSH deploy key or use a personal access token.

---

## 4. Fix Content-Security-Policy for production

The file `apps/web/next.config.ts` has `connect-src` hardcoded to `localhost`. For production the browser must be allowed to connect to your real API URL.

**Do:** Edit `apps/web/next.config.ts` on the server (or commit the fix beforehand). Change the `connect-src` line:

**Before:**
```
connect-src 'self' http://localhost:8000 http://127.0.0.1:8000 ws://localhost:3000 ws://127.0.0.1:3000
```

**After (single-domain):**
```
connect-src 'self' https://yourapp.com wss://yourapp.com
```

**After (subdomain):**
```
connect-src 'self' https://api.yourapp.com wss://yourapp.com
```

If you use the single-domain setup (`/api/*` on the same origin), `'self'` is actually enough, but listing it explicitly doesn't hurt.

---

## 5. Create `.env` with production values

```bash
cp .env.example .env
nano .env
```

Set these values (replace placeholders):

```
# ── Database ──
POSTGRES_PASSWORD=<STRONG_RANDOM_PASSWORD>
DATABASE_URL=postgresql://postgres:<SAME_PASSWORD>@db:5432/deepfake
POSTGRES_DB=deepfake

# ── Redis ──
REDIS_URL=redis://redis:6379/0

# ── Storage ──
STORAGE_PATH=/data/storage

# ── CORS ──
ALLOWED_ORIGINS=https://yourapp.com

# ── Web (build arg) ──
NEXT_PUBLIC_API_URL=https://yourapp.com

# ── Stripe (leave blank for now, set in step 10) ──
STRIPE_SECRET_KEY=
STRIPE_WEBHOOK_SECRET=
STRIPE_PRICE_ID=
PAYMENT_SUCCESS_URL=https://yourapp.com/payment/success
PAYMENT_CANCEL_URL=https://yourapp.com
```

Generate a strong password:
```bash
openssl rand -base64 24
```

**Important:**
- `NEXT_PUBLIC_API_URL` = the URL the **browser** uses to reach the API. For single-domain setup this is `https://yourapp.com`. For subdomain setup this is `https://api.yourapp.com`.
- `ALLOWED_ORIGINS` = your **web** origin (no trailing slash).
- `DATABASE_URL` uses `db` as the hostname (the docker-compose service name).

---

## 6. Build and start Docker Compose

```bash
docker compose up --build -d
```

This builds all three images (web, api, worker) and starts the five services (web, api, worker, db, redis). The web image bakes in `NEXT_PUBLIC_API_URL` at build time.

**First build takes a while** (Python deps, Node deps, Next.js build). ~5–15 min depending on server speed.

**Verify services are running:**
```bash
docker compose ps
```
All 5 should show `Up` or `running`. Check logs:
```bash
docker compose logs api --tail 20
docker compose logs worker --tail 20
docker compose logs web --tail 20
```

The API should log that it started on port 8000. The worker should print "Worker started, waiting for jobs...".

---

## 7. ML models: first-run download

The worker auto-downloads ML models from HuggingFace on the first job:

| Model | Size | Purpose |
|-------|------|---------|
| `yermandy/deepfake-detection` (CLIP ViT-L/14) | ~900 MB | A/V deepfake detection |
| `CommunityForensics/deepfake-det-vit` | ~140 MB | Frame-level AI vs real |
| `MelodyMachine/Wav2Vec2-large-anti-deepfake` | ~1.2 GB | Audio deepfake |

The first analysis will be slow (~2–5 min extra) while models download. After that they're cached in the container. If the container is recreated, they download again.

**To avoid re-downloading on container rebuild**, add a named volume for the HuggingFace cache. Add to `docker-compose.yml` under the `worker` service:
```yaml
volumes:
  - storage_data:/data/storage
  - hf_cache:/root/.cache/huggingface
```
And add `hf_cache:` to the top-level `volumes:` section.

**Verify:** After running one analysis through, check `docker compose logs worker` — you should see model loading messages, then inference results.

---

## 8. Set up Caddy reverse proxy for HTTPS

Caddy auto-provisions TLS certificates from Let's Encrypt. No manual cert setup.

**Do:**

1. Install Caddy on the host (not inside Docker):
   ```bash
   apt install -y debian-keyring debian-archive-keyring apt-transport-https curl
   curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/gpg.key' | gpg --dearmor -o /usr/share/keyrings/caddy-stable-archive-keyring.gpg
   curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/debian.deb.txt' | tee /etc/apt/sources.list.d/caddy-stable.list
   apt update && apt install -y caddy
   ```

2. Edit `/etc/caddy/Caddyfile`:

   **Single-domain setup:**
   ```
   yourapp.com {
       handle /api/* {
           reverse_proxy localhost:8000
       }
       handle /health {
           reverse_proxy localhost:8000
       }
       handle {
           reverse_proxy localhost:3000
       }
   }
   ```

   **Subdomain setup:**
   ```
   yourapp.com {
       reverse_proxy localhost:3000
   }

   api.yourapp.com {
       reverse_proxy localhost:8000
   }
   ```

3. Restart Caddy:
   ```bash
   systemctl restart caddy
   ```

Caddy will automatically get a TLS certificate. Wait ~30 seconds.

**Verify:**
- `curl https://yourapp.com/health` → `{"status":"ok"}`
- Open `https://yourapp.com` in a browser → the web app loads.

---

## 9. Smoke test (before Stripe)

Test the core app works before adding payments.

1. Open `https://yourapp.com` in your browser.
2. Upload a short video (or paste a video URL). Wait for the result.
3. Check the result page shows a verdict, confidence, sub-scores.

If this works, the full stack is confirmed: web → API → Redis queue → worker → DB → result.

**If something is wrong**, check:
```bash
docker compose logs api --tail 50
docker compose logs worker --tail 50
docker compose logs web --tail 50
```

Common issues:
- **CORS error in browser console:** `ALLOWED_ORIGINS` doesn't match the actual origin (check protocol, trailing slash).
- **API unreachable from web:** `NEXT_PUBLIC_API_URL` doesn't match how Caddy routes. Rebuild web after fixing: `docker compose up --build -d web`.
- **Worker stuck on first job:** Models downloading. Wait a few minutes, check logs.
- **CSP `connect-src` block in browser console:** The CSP in `next.config.ts` still has localhost. Fix and rebuild web.

---

## 10. Stripe: product, keys, webhook

Do this only after step 9 passes (app is live and a free analysis works).

1. **Stripe account** — Log in at [dashboard.stripe.com](https://dashboard.stripe.com). Turn **live mode** on (toggle top-right).

2. **Product and price:**
   - **Products** → **Add product**
   - Name: `Deepfake check`
   - **Pricing:** One time, **1.00 EUR**
   - Save → copy the **Price ID** (starts with `price_`). → `STRIPE_PRICE_ID`

3. **API keys:**
   - **Developers** → **API keys**
   - Copy the **Secret key** (starts with `sk_live_`). → `STRIPE_SECRET_KEY`

4. **Webhook:**
   - **Developers** → **Webhooks** → **Add endpoint**
   - **URL:** `https://yourapp.com/api/webhooks/stripe` (or `https://api.yourapp.com/api/webhooks/stripe` for subdomain setup)
   - **Events:** select **`checkout.session.completed`**
   - Save → open the endpoint → **Reveal** signing secret (starts with `whsec_`). → `STRIPE_WEBHOOK_SECRET`

---

## 11. Set Stripe env vars and restart API

SSH into the server:

```bash
cd /opt/deepfake-detector
nano .env
```

Fill in the Stripe values you copied:

```
STRIPE_SECRET_KEY=sk_live_...
STRIPE_WEBHOOK_SECRET=whsec_...
STRIPE_PRICE_ID=price_...
PAYMENT_SUCCESS_URL=https://yourapp.com/payment/success
PAYMENT_CANCEL_URL=https://yourapp.com
```

Restart the API to pick up the new env:
```bash
docker compose up -d api
```

**Verify:** `docker compose logs api --tail 10` — no errors on startup.

---

## 12. Test Stripe end-to-end

From the same browser where you did the free analysis in step 9:

1. **Second analysis → payment required.** Start another analysis. You should see "Pay 1 €" (the API returns 402).

2. **Pay 1 €.** Click the pay button → Stripe Checkout loads → pay with a real card (1 €). You should be redirected to `https://yourapp.com/payment/success`.

3. **Check webhook delivery.** In Stripe Dashboard → **Developers** → **Webhooks** → your endpoint. The `checkout.session.completed` event should show a green checkmark (200 response).

4. **Paid analysis runs.** The analysis you paid for should now run. Wait for the result.

5. **Third analysis → free again.** Start one more analysis from the same browser. It should be free (no payment prompt).

If the webhook shows a red X (failed delivery), check:
- Is the URL correct? Try `curl -X POST https://yourapp.com/api/webhooks/stripe` — you should get a non-404 response (likely 400 for missing signature, which means the route exists).
- Is Caddy passing the raw body? By default it does, so this shouldn't be an issue.
- Check `docker compose logs api --tail 30` for webhook errors.

---

## 13. Production hardening (optional but recommended)

### A. Persistent HuggingFace model cache
Add a volume to avoid re-downloading ~2 GB of models when containers rebuild (see step 7).

### B. Protect admin endpoint
`GET /api/admin/jobs` has no auth. Add HTTP Basic Auth in Caddy:
```
handle /api/admin/* {
    basicauth {
        admin <hashed-password>
    }
    reverse_proxy localhost:8000
}
```
Generate a hash: `caddy hash-password`.

### C. Hide or guard debug endpoints
`GET /api/debug/rate-limit` and `POST /api/debug/rate-limit/reset` are dev-only. Block them in Caddy or remove them from code.

### D. Log rotation
```bash
# Docker logs (JSON file driver, default)
# Add to /etc/docker/daemon.json:
{
  "log-driver": "json-file",
  "log-opts": { "max-size": "10m", "max-file": "3" }
}
# Then: systemctl restart docker
```

### E. Backups
- **Postgres:** `docker compose exec db pg_dump -U postgres deepfake > backup.sql` (cron daily).
- **Storage volume:** back up `/var/lib/docker/volumes/deepfake-detector_storage_data/` or wherever it mounts.

### F. Monitoring
Set up uptime monitoring on `https://yourapp.com/health` (UptimeRobot, Hetrixtools — free tier).

---

## Quick checklist

- [ ] VPS provisioned, Docker installed, firewall set (22, 80, 443 only)
- [ ] Domain DNS A record → server IP
- [ ] Repo cloned on server
- [ ] `connect-src` in `apps/web/next.config.ts` updated for production domain
- [ ] `.env` created with strong Postgres password, correct `DATABASE_URL`, `REDIS_URL`, `ALLOWED_ORIGINS`, `NEXT_PUBLIC_API_URL`
- [ ] `docker compose up --build -d` — all 5 services running
- [ ] Caddy installed, Caddyfile configured, HTTPS working
- [ ] `https://yourapp.com` loads, `https://yourapp.com/health` returns `{"status":"ok"}`
- [ ] Free analysis works end-to-end (upload → result)
- [ ] Stripe live mode: product + price, secret key, webhook endpoint created
- [ ] `STRIPE_SECRET_KEY`, `STRIPE_PRICE_ID`, `STRIPE_WEBHOOK_SECRET`, `PAYMENT_SUCCESS_URL`, `PAYMENT_CANCEL_URL` set in `.env`, API restarted
- [ ] Stripe tested: free → pay 1 € → paid run → next free

---

## Appendix: testing Stripe locally (no server yet)

Use **Stripe test mode** + **Stripe CLI** to test payments on localhost before deploying:

1. In the Stripe Dashboard, switch to **Test mode**. Create a test product/price, copy test keys (`sk_test_...`).
2. Set `STRIPE_SECRET_KEY`, `STRIPE_PRICE_ID` in `.env` with test values.
3. Install [Stripe CLI](https://stripe.com/docs/stripe-cli), then:
   ```bash
   stripe listen --forward-to localhost:8000/api/webhooks/stripe
   ```
4. Copy the CLI-printed `whsec_...` into `STRIPE_WEBHOOK_SECRET` in `.env`, restart the API.
5. Test: free → pay with card `4242 4242 4242 4242` → paid run → next free.
