# Implementation plan: First free, every second check 1 EUR

## Pricing logic

- **1st analysis**: free  
- **2nd analysis**: 1 EUR  
- **3rd analysis**: free  
- **4th analysis**: 1 EUR  
- … (odd = free, even = 1 EUR)

**Rule:** Charge 1 EUR when the *next* job would be the 2nd, 4th, 6th, … for this user.

```text
next_job_number = total_completed + 1
requires_payment = (next_job_number % 2 == 0)   # 2nd, 4th, 6th...
```

No registration: user is identified by an **anonymous ID** (cookie/localStorage). Same browser = same user.

---

## Payment: as easy as possible

Use **Stripe Payment Link** (or one-time Checkout):

1. User clicks **"Pay 1 €"** → opens Stripe-hosted page (card, Apple Pay, Google Pay).
2. Pays → Stripe redirects back to your app with `session_id` (or you use success_url only).
3. Your backend credits the user via **Stripe webhook** (`checkout.session.completed`).
4. User returns to the upload page and tries again → job is created (one credit deducted).

No card form on your site, no PCI scope, minimal UI.

---

## 1. Data model

### 1.1 New table: `anonymous_users`

| Column        | Type      | Description                          |
|---------------|-----------|--------------------------------------|
| `id`          | UUID (PK) | Same as anonymous ID from frontend   |
| `total_completed` | Integer (default 0) | Number of analyses completed (DONE) |
| `paid_credits`    | Integer (default 0) | Credits from payments (1 EUR = 1 credit) |
| `created_at`  | Timestamp | First seen                           |
| `updated_at`  | Timestamp | Last update                          |

- **Create row** on first request that sends `anonymous_id` (or when first job is created).
- **total_completed**: incremented by worker/API when a job for this user reaches status DONE.
- **paid_credits**: incremented by Stripe webhook when payment succeeds; decremented when user starts a chargeable job (2nd, 4th, …).

### 1.2 Jobs table

- Add column: `anonymous_id` (UUID, nullable, FK to `anonymous_users.id` or just string for simplicity).
- Set when job is created from header or body.

### 1.3 Migration

- Add `anonymous_users` table.
- Add `jobs.anonymous_id` (nullable for existing rows).

---

## 2. API changes

### 2.1 Anonymous ID

- **Option A (recommended):** Header `X-Anonymous-Id: <uuid>` on `POST /api/jobs` and `POST /api/jobs/{id}/upload`.
- **Option B:** Body field `anonymous_id` in `POST /api/jobs`.

If missing or invalid UUID: create a new ID server-side and return it in response (e.g. `X-Anonymous-Id` or JSON `anonymous_id`); frontend stores and reuses it.

### 2.2 Create job (upload flow)

**POST /api/jobs** (and then **POST /api/jobs/{id}/upload**):

1. Resolve anonymous user (from header or body): get or create row in `anonymous_users`.
2. Compute:
   - `total_completed` = current value for this user
   - `next_number = total_completed + 1`
   - `requires_payment = (next_number % 2 == 0)`
3. If `requires_payment`:
   - If `paid_credits <= 0`: return **402 Payment Required** with body e.g. `{"code": "PAYMENT_REQUIRED", "amount_eur": 1, "message": "This check costs 1 €"}`. Do not create job.
   - If `paid_credits > 0`: decrement `paid_credits` by 1, then create job and set `job.anonymous_id`.
4. If not `requires_payment`: create job and set `job.anonymous_id`.
5. Commit; for upload flow continue with existing upload and enqueue logic.

### 2.3 Increment total_completed

When a job reaches **DONE** (or **FAILED** if you still count it as “used” — recommend only DONE):

- In API: either expose **PATCH /api/jobs/{id}/complete** called by worker, or have worker update DB directly.
- Prefer: **worker** (or API called by worker) updates `anonymous_users.total_completed += 1` where `anonymous_id = job.anonymous_id`, and only when `job.status` becomes DONE.

So: **job completion** is the single place that increments `total_completed` (and only for jobs that have `anonymous_id`).

### 2.4 Payment endpoints

**GET /api/me** (or **GET /api/users/me**)

- Requires `X-Anonymous-Id`.
- Returns e.g. `{ "anonymous_id": "...", "total_completed": 1, "paid_credits": 0, "next_check_free": false }` so the frontend can show “Next check: 1 €” or “Next check: free”.

**POST /api/payment/create-checkout**

- Body or header: `X-Anonymous-Id`.
- Backend: create Stripe Checkout Session (one-time, 1 EUR), with `metadata.anonymous_id = <id>` and `success_url` / `cancel_url` pointing to your app.
- Return `{ "checkout_url": "https://checkout.stripe.com/..." }`.
- Frontend: redirect to `checkout_url` (easiest: `window.location.href = checkout_url`).

**Stripe webhook** (e.g. **POST /api/webhooks/stripe**)

- Verify signature (Stripe webhook secret).
- On `checkout.session.completed`: read `metadata.anonymous_id`, increment `anonymous_users.paid_credits` by 1 for that id.
- Return 200 quickly; do not run analysis in webhook.

### 2.5 Config

- `STRIPE_SECRET_KEY`, `STRIPE_WEBHOOK_SECRET`, `STRIPE_PRICE_ID` (or create a 1 EUR price in Stripe and use its ID).

---

## 3. Worker change

When setting `job.status = "DONE"` (in `pipeline.py`):

- After commit, if `job.anonymous_id` is not null:
  - Update `anonymous_users` set `total_completed = total_completed + 1` where `id = job.anonymous_id`.
- Use a single DB update (or call a small API endpoint that does this) so it’s atomic and consistent.

No change to queue or job creation; only this one update when a job completes.

---

## 4. Frontend changes

### 4.1 Anonymous ID

- On load: read `df_uid` from cookie (e.g. httpOnly=false or a non-httpOnly cookie) or localStorage. If missing, generate UUID, store it, and send in header `X-Anonymous-Id` on all API calls that need it (create job, upload, optional GET /api/me).
- Cookie recommended: long expiry (e.g. 1 year), same-site.

### 4.2 Create job + upload

- Before **POST /api/jobs**, add header `X-Anonymous-Id: <uuid>`.
- If response is **402**:
  - Parse body (`PAYMENT_REQUIRED`, `amount_eur`, etc.).
  - Show inline message: “This check costs 1 €. Pay once to continue.” and a single button **“Pay 1 €”**.
  - On click: call **POST /api/payment/create-checkout** (with same anonymous id), get `checkout_url`, then `window.location.href = checkout_url`.
  - Success URL (Stripe redirect): e.g. `https://yourapp.com?payment=success`. On that page show “Payment successful. You can run your analysis now.” and a link/button “Analyze video” that goes back to upload. Do not auto-upload the same file (user may choose to upload again).

### 4.3 Optional: show “Next check free / 1 €”

- Call **GET /api/me** with `X-Anonymous-Id` and show a small line under the upload area: “Next check: free” or “Next check: 1 €”.

---

## 5. Stripe setup (minimal)

1. **Stripe account** (live or test).
2. **Product**: e.g. “Deepfake check” (one-time).
3. **Price**: 1 EUR (one-time) → copy **Price ID** (`price_xxx`).
4. **Payment Link** (optional): create a 1 EUR payment link, or use Checkout Session from backend (more control over success_url and metadata).
5. **Webhook**: endpoint `https://your-api.com/api/webhooks/stripe`, event `checkout.session.completed`; copy **Signing secret**.
6. Env: `STRIPE_SECRET_KEY`, `STRIPE_WEBHOOK_SECRET`, `STRIPE_PRICE_ID`.

---

## 6. Implementation order

| Step | Task |
|------|------|
| 1 | Add `anonymous_users` table and `jobs.anonymous_id`; migration. |
| 2 | API: resolve anonymous user in create-job flow; implement `requires_payment` and 402; deduct `paid_credits` when starting a chargeable job. |
| 3 | API: GET /api/me (anonymous user info). |
| 4 | API: POST /api/payment/create-checkout (Stripe Session); webhook POST /api/webhooks/stripe (increment paid_credits). |
| 5 | Worker: on job DONE, increment `anonymous_users.total_completed` for `job.anonymous_id`. |
| 6 | Frontend: anonymous ID (cookie + header X-Anonymous-Id). |
| 7 | Frontend: handle 402 on job create; “Pay 1 €” button → redirect to Stripe; success page and back to upload. |
| 8 | Optional: GET /api/me and “Next check: free / 1 €” on landing. |
| 9 | Test: first job free, second requires payment, pay then second works, third free again. |

---

## 7. Sprints with testable results

Each sprint ends with **testable results** you can verify before moving on.

---

### Sprint 1: Data model and anonymous user resolution  
**Goal:** DB and API can identify users by anonymous ID; no pricing yet.

| Task | Detail |
|------|--------|
| Add `anonymous_users` table | Columns: `id` (UUID PK), `total_completed`, `paid_credits`, `created_at`, `updated_at`. |
| Add `jobs.anonymous_id` | UUID, nullable. Migration runs clean. |
| API: accept anonymous ID | In create-job flow, read `X-Anonymous-Id` (or body); validate UUID. |
| API: get-or-create user | For valid ID: get or create row in `anonymous_users`; attach to job. For missing/invalid: optionally create new UUID and return in response. |
| Create job sets `job.anonymous_id` | Every new job stores the resolved anonymous_id. |

**Testable results**

- [ ] Migration applies; `anonymous_users` and `jobs.anonymous_id` exist.
- [ ] `POST /api/jobs` with valid `X-Anonymous-Id` creates job and `job.anonymous_id` matches.
- [ ] Same `X-Anonymous-Id` twice creates one `anonymous_users` row (get-or-create).
- [ ] New anonymous ID creates new `anonymous_users` row.

**No pricing logic in this sprint** — all jobs are created regardless of count.

---

### Sprint 2: Pricing logic (402 and credit deduction)  
**Goal:** 2nd, 4th, 6th… job require payment; API returns 402 when no credits; deduct credit when paid job starts.

| Task | Detail |
|------|--------|
| Compute `requires_payment` | `next_number = total_completed + 1`; `requires_payment = (next_number % 2 == 0)`. |
| Return 402 when payment required and no credits | If `requires_payment` and `paid_credits <= 0`: 402 + JSON `{ "code": "PAYMENT_REQUIRED", "amount_eur": 1, "message": "..." }`. Do not create job. |
| Deduct credit when starting paid job | If `requires_payment` and `paid_credits > 0`: decrement `paid_credits` in same transaction as job creation. |
| Free slots | When `requires_payment` is false, create job without touching `paid_credits`. |

**Testable results**

- [ ] User A: 1st job (no DONE yet) → job created (free).
- [ ] User A: 2nd job (still 0 DONE) → **402** (next is 2nd = paid, no credits).
- [ ] Manually set User A `paid_credits = 1`; 2nd job → job created, `paid_credits` becomes 0.
- [ ] After one DONE (Sprint 3): User A 2nd job → 402 again; 3rd job → created (free).

**Worker does not yet increment `total_completed`** — for tests, set `total_completed` manually or use Sprint 3.

---

### Sprint 3: Worker increments total_completed  
**Goal:** When a job completes, the user’s analysis count goes up so pricing stays in sync.

| Task | Detail |
|------|--------|
| On job DONE | In worker (e.g. `pipeline.py`), when setting `status = DONE`: if `job.anonymous_id` is set, run `UPDATE anonymous_users SET total_completed = total_completed + 1 WHERE id = job.anonymous_id`. |
| Single place | Only DONE; not FAILED (unless you explicitly count FAILED as “used”). |

**Testable results**

- [ ] Create and complete job with `anonymous_id`; `anonymous_users.total_completed` increases by 1.
- [ ] Job without `anonymous_id` (legacy): no error; `total_completed` unchanged.
- [ ] Full flow: 1st job created → completed → `total_completed = 1`; next create returns 402 (2nd = paid).

---

### Sprint 4: Stripe Checkout and webhook  
**Goal:** Backend can create a 1 EUR checkout and credit the user when Stripe confirms payment.

| Task | Detail |
|------|--------|
| Config | `STRIPE_SECRET_KEY`, `STRIPE_WEBHOOK_SECRET`, `STRIPE_PRICE_ID` in API config. |
| POST /api/payment/create-checkout | Accept `X-Anonymous-Id`; create Stripe Checkout Session (1 EUR, metadata.anonymous_id); return `{ "checkout_url": "..." }`. |
| POST /api/webhooks/stripe | Verify Stripe signature; on `checkout.session.completed` read `metadata.anonymous_id`, increment `anonymous_users.paid_credits` by 1; idempotent by session_id. |
| Success/cancel URLs | Point to your app (e.g. `/payment/success`, `/`). |

**Testable results**

- [ ] `POST /api/payment/create-checkout` with valid `X-Anonymous-Id` returns 200 and `checkout_url` (Stripe test mode).
- [ ] Opening `checkout_url` shows Stripe Checkout for 1 EUR.
- [ ] After paying with test card (4242…): webhook receives event; `paid_credits` for that user +1.
- [ ] Sending same webhook event again: no double increment (idempotent).

---

### Sprint 5: Frontend — anonymous ID and 402 handling  
**Goal:** Browser has a stable anonymous ID; user sees “Pay 1 €” when API returns 402 and can go to Stripe.

| Task | Detail |
|------|--------|
| Anonymous ID | On load: read from cookie (e.g. `df_uid`) or localStorage; if missing, generate UUID and store. Send as `X-Anonymous-Id` on POST /api/jobs (and upload). |
| Handle 402 | On create-job response 402: parse body; show message “This check costs 1 €…” and button “Pay 1 €”. |
| Pay 1 € flow | On click: POST /api/payment/create-checkout with same anonymous ID; redirect to `checkout_url`. |
| Success page | Stripe success_url → e.g. `/payment/success` with “Payment successful. You can run your analysis now.” and link back to upload. |

**Testable results**

- [ ] First visit: cookie/localStorage has UUID; subsequent requests send same `X-Anonymous-Id`.
- [ ] After 1 free job completed: starting 2nd job shows “Pay 1 €” (no job created until payment).
- [ ] Click “Pay 1 €” → Stripe Checkout opens; after test payment → redirect to success page; back to upload; 2nd job now creates (credit deducted).

---

### Sprint 6: GET /api/me and “Next check” UI (optional)  
**Goal:** User sees whether the next analysis is free or 1 €.

| Task | Detail |
|------|--------|
| GET /api/me | Header `X-Anonymous-Id`; return `{ "anonymous_id", "total_completed", "paid_credits", "next_check_free" }`. |
| Frontend | Call on landing load; show line “Next check: free” or “Next check: 1 €”. |

**Testable results**

- [ ] With 0 completed: “Next check: free”. After 1 completed: “Next check: 1 €”. After payment + 1 paid job: “Next check: free”.
- [ ] No 402 when starting a free check; 402 when starting a paid check with 0 credits.

---

### Sprint 7: End-to-end and edge cases  
**Goal:** Full pricing and payment flow works; no double-spend or webhook duplicates.

| Task | Detail |
|------|--------|
| E2E test | 1st free → 2nd 402 → Pay 1 € → 2nd created and completes → 3rd free. |
| Concurrency | Two tabs: only one can use the same credit (transaction: deduct + create job). |
| Webhook idempotency | Replay same `checkout.session.completed`: paid_credits increases once. |

**Testable results**

- [ ] Full flow without clearing cookies: free → pay → paid → free.
- [ ] New browser/cookie: new user, 1st free again.
- [ ] Two tabs “Pay 1 €” then both try to start 2nd job: only one job created, one credit used.

---

### Sprint 8: Production deployment  
**Goal:** App and payment flow are live and reachable online.

| Task | Detail |
|------|--------|
| Hosting | Deploy API, worker, and web app to chosen platform (e.g. PaaS: Railway, Render, Fly.io; or VPS + Docker). |
| Database | Production DB (e.g. managed PostgreSQL); run migrations / init. |
| Redis | Production Redis for job queue (managed or same host). |
| Stripe live | Create live product/price (1 EUR); set live API keys and webhook endpoint in Stripe Dashboard. |
| Env and secrets | Set in prod: `DATABASE_URL`, `REDIS_URL`, `STRIPE_SECRET_KEY`, `STRIPE_WEBHOOK_SECRET`, `STRIPE_PRICE_ID`, `ALLOWED_ORIGINS` (prod domain). |
| Webhook URL | Register `https://your-api-domain.com/api/webhooks/stripe` in Stripe; verify webhook secret. |
| Domain and TLS | Point domain to API and web; ensure HTTPS. |
| Smoke test | In prod: create job (free), complete flow; pay 1 € (live or test card if still testing); verify credit and 3rd free. |

**Testable results**

- [ ] API and web are reachable over HTTPS at production URLs.
- [ ] First analysis (free) runs end-to-end in prod.
- [ ] Payment (1 €) completes; webhook receives event; user gets credit; second analysis runs.
- [ ] Third analysis is free again.

---

### Sprint summary

| Sprint | Focus | Main testable outcome |
|--------|--------|------------------------|
| 1 | Data model + anonymous ID | Jobs have anonymous_id; get-or-create user works. |
| 2 | 402 + credit deduction | 2nd/4th/6th job require payment; 402 when no credits; deduct on create. |
| 3 | Worker completion | total_completed increments on job DONE. |
| 4 | Stripe Checkout + webhook | Checkout URL works; webhook adds paid_credits; idempotent. |
| 5 | Frontend ID + 402 + Pay flow | Cookie/ID stable; 402 → “Pay 1 €” → Stripe → success page. |
| 6 | /api/me + “Next check” UI | Correct “free” / “1 €” label. |
| 7 | E2E + edge cases | Full free/paid cycle; no double-spend; idempotent webhook. |
| 8 | Production deployment | App live; HTTPS; Stripe live; free → pay → free works in prod. |

---

## 8. Files to add or touch (reference)

| Area | Files |
|------|--------|
| API models | `apps/api/models.py` (AnonymousUser, Job.anonymous_id) |
| API migrations | New migration or `database.py` alter table for anonymous_users + jobs.anonymous_id |
| API jobs | `apps/api/routers/jobs.py` (anonymous_id, 402, deduct credit) |
| API payment | New `apps/api/routers/payment.py` (create-checkout, webhook) or under jobs |
| API config | `apps/api/config.py` (Stripe keys, price id) |
| Worker | `apps/worker/pipeline.py` (increment total_completed on DONE) |
| Worker models | `apps/worker/models.py` (AnonymousUser if worker touches DB) or worker calls API to record completion |
| Web | `apps/web/app/page.tsx` (cookie, header, 402, Pay button, redirect) |
| Web | Optional: `apps/web/app/payment/success/page.tsx` (success URL target) |

---

## 9. Security and edge cases

- **Anonymous ID**: Treat as opaque; no PII. If user clears cookies they get a new “user” (new first free). Acceptable for “no registration” model.
- **Idempotency**: Stripe webhook can retry; make incrementing `paid_credits` idempotent (e.g. check `payment_intent_id` or `session_id` already processed).
- **Concurrency**: Use a single DB update for “deduct credit” and “create job” (transaction) so two tabs cannot use the same credit twice.
- **Refunds**: Handle outside this flow (Stripe dashboard or support); optionally decrement `paid_credits` in a small admin or webhook for `charge.refunded` if you want to keep credits in sync.

This plan gives you: **first free, every second check 1 EUR**, no registration, and the **easiest payment path** (one click → Stripe → redirect back).
