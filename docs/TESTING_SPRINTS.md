# Testing between sprints

Run tests after each sprint to verify the testable results before moving on.

## Prerequisites

Use the API app environment (e.g. venv with API deps installed). From **project root**:

```bash
cd apps/api
pip install -r requirements.txt
# Optional for pytest: pip install -r requirements-dev.txt
```

On macOS use **`python3`** if `python` is not available.

## Sprint 1: Data model and anonymous user resolution

From **apps/api** (so if you're in project root, run `cd apps/api` first):

**Option A – Script (no pytest):**

```bash
cd apps/api
PYTHONPATH=. python3 scripts/run_sprint1_tests.py
```

**Option B – Pytest:**

```bash
cd apps/api
pip install pytest   # or: pip install -r requirements-dev.txt
PYTHONPATH=. python3 -m pytest tests/test_sprint1_anonymous_users.py -v
```

**Expected:** All checks pass (migration applied, job has anonymous_id, get-or-create, new ID in response when header missing).

## Sprint 2: Pricing logic (402 + credit deduction)

From **apps/api**:

**Option A – Script (no pytest):**

```bash
cd apps/api
PYTHONPATH=.. python3 scripts/run_sprint2_tests.py
```

**Option B – Pytest:**

```bash
cd apps/api
PYTHONPATH=.. python3 -m pytest tests/test_sprint2_pricing.py -v
```

**Expected:** 1st job free; 2nd without credits → 402; 2nd with 1 credit → job created and credit becomes 0; 3rd job free.

## Sprint 3: Worker increments total_completed

From **apps/api**:

**Option A – Script (no pytest):**

```bash
cd apps/api
PYTHONPATH=.. python3 scripts/run_sprint3_tests.py
```

**Option B – Pytest:**

```bash
cd apps/api
PYTHONPATH=.. python3 -m pytest tests/test_sprint3_worker_completion.py -v
```

**Expected:** Completing a job (simulated) increments `total_completed`; next create returns 402 (2nd = paid).

## Sprint 4: Stripe Checkout + webhook

From **apps/api** (install Stripe first: `pip install stripe` or `pip install -r requirements.txt`):

**Option A – Script (no pytest):**

```bash
cd apps/api
PYTHONPATH=.. python3 scripts/run_sprint4_tests.py
```

**Option B – Pytest:**

```bash
cd apps/api
PYTHONPATH=.. python3 -m pytest tests/test_sprint4_stripe.py -v
```

**Expected:** create-checkout 400 without header, 503 without config; webhook 503 without secret; mocked webhook increments `paid_credits` and is idempotent. For real Stripe: set `STRIPE_SECRET_KEY`, `STRIPE_WEBHOOK_SECRET`, `STRIPE_PRICE_ID` and use Stripe CLI or Dashboard to test live.

## Sprint 5: Frontend ID + 402 + Pay flow

This sprint is mostly **manual UI testing**.

### Build check (TypeScript)

```bash
cd apps/web
npm run build
```

### Manual flow test

1. Start web + API + worker normally (e.g. Docker Compose).
2. Open the web app and upload a video once (this is the **free** check).
3. Trigger a paid slot and confirm UI shows payment:
   - Easiest for now (without running a full paid cycle): manually set the user to `total_completed = 1` in DB for the same `anonymous_id`, then refresh and upload again.
   - Result: job create should return **402**, and the UI should show **“Pay 1 €”**.
4. Click **“Pay 1 €”**:
   - If Stripe is not configured yet: you should see an error like “Payment is not configured”.
   - When Stripe is configured: it should redirect to Stripe Checkout, then to `/payment/success`.

**Expected:** browser has a stable anonymous ID; API calls include `X-Anonymous-Id`; 402 renders the Pay button; payment button either redirects to Stripe or shows a clear “not configured” error.

## Sprint 6: GET /api/me + Next check UI

### Backend tests

From **apps/api**:

**Option A – Script (no pytest):**

```bash
cd apps/api
PYTHONPATH=.. python3 scripts/run_sprint6_tests.py
```

**Option B – Pytest:**

```bash
cd apps/api
PYTHONPATH=.. python3 -m pytest tests/test_sprint6_me_endpoint.py -v
```

**Expected:** `/api/me` creates an anonymous user if needed; returns `total_completed`, `paid_credits`, and `next_check_free` is **true** for the first check and **false** when the next is paid (2nd, 4th, ...).

---

Later sprints will add their own test files and script checks; run the corresponding tests before starting the next sprint.
