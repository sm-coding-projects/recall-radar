# recall-radar

**One API for every US product recall.**

The US government publishes product recalls across four unrelated agencies, in
four different shapes, with four different quirks. `recall-radar` fetches all of
them daily, normalizes them into a single schema, and serves them as clean,
searchable JSON.

| Agency | Covers | Source |
|---|---|---|
| **FDA** | Food, drug, and device recalls | openFDA enforcement API |
| **CPSC** | Consumer products | SaferProducts.gov REST service |
| **USDA FSIS** | Meat, poultry, egg products | FSIS Recall API |
| **NHTSA** | Vehicles, tires, child seats | ODI recalls flat file |

---

## Architecture

```
   ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌──────────┐
   │ openFDA  │  │   CPSC   │  │   FSIS   │  │  NHTSA   │
   │ food/drug│  │  Safer   │  │  recall  │  │ ODI flat │
   │  /device │  │ Products │  │   API    │  │   file   │
   └────┬─────┘  └────┬─────┘  └────┬─────┘  └────┬─────┘
        └─────────────┴───┬─────────┴─────────────┘
                          │  one adapter per agency
                          ▼
              ┌───────────────────────┐
              │   fetcher/run.py      │   GitHub Actions
              │  normalize + upsert   │◄── cron 06:00 UTC
              │  ON CONFLICT DO UPDATE│    (+ manual dispatch)
              └───────────┬───────────┘
                          ▼
              ┌───────────────────────┐
              │   Neon Postgres 17    │
              │   table: recalls      │
              │   GIN full-text index │
              └───────────┬───────────┘
                          ▼
              ┌───────────────────────┐
              │  FastAPI + uvicorn    │
              │   on Render (free)    │
              └───────────┬───────────┘
                          ▼
                    RapidAPI  ──►  customers
```

Ingest and serve are separate: the fetcher runs on GitHub Actions (free for
public repos), so the web service only ever reads. A cold or sleeping Render
instance can never miss a fetch.

---

## Endpoints

Base URL: `https://<your-service>.onrender.com`

Every success returns a consistent envelope — list endpoints return
`{data, pagination, meta}`, single-item endpoints return `{data, meta}`.
Every failure returns `{"error": {"code", "message", "detail"}}`.

### `GET /health`

Liveness plus a real database round-trip. Never requires auth.

```bash
curl https://<your-service>.onrender.com/health
```

```json
{
  "status": "ok",
  "database": "ok",
  "recalls": 112431,
  "version": "0.1.0"
}
```

Returns `200` with `"status": "degraded"` if the database is unreachable, so a
sleeping Neon compute does not flap Render's health check.

### `GET /recalls`

Recalls newest-first, with filters and pagination.

| Param | Type | Default | Notes |
|---|---|---|---|
| `agency` | string | – | `FDA`, `CPSC`, `FSIS`, `NHTSA` (case-insensitive) |
| `category` | string | – | Case-insensitive substring match |
| `since` | date | – | `YYYY-MM-DD`, inclusive |
| `until` | date | – | `YYYY-MM-DD`, inclusive |
| `page` | int | `1` | |
| `per_page` | int | `25` | **max 100** |

```bash
curl "https://<your-service>.onrender.com/recalls?agency=CPSC&since=2026-07-01&per_page=2"
```

```json
{
  "data": [
    {
      "id": 10875,
      "agency": "CPSC",
      "source_id": "26634",
      "product": "Romorgniz 12-Drawer Fabric Dressers",
      "brand": "Xuzhou Mingquanhe Household Co., Ltd.",
      "category": null,
      "hazard": "The recalled dressers are unstable if they are not anchored to the wall, posing tip-over and entrapment hazards.",
      "classification": "Refund",
      "recall_date": "2026-07-23",
      "published_at": "2026-07-24T00:00:00Z",
      "url": "https://www.cpsc.gov/Recalls/2026/12-Drawer-Fabric-Dressers-Recalled...",
      "ingested_at": "2026-07-31T03:37:09Z"
    }
  ],
  "pagination": {
    "page": 1, "per_page": 2, "total": 75,
    "total_pages": 38, "has_next": true, "has_prev": false
  },
  "meta": { "filters": { "agency": "CPSC", "since": "2026-07-01" } }
}
```

### `GET /recalls/latest`

The 50 most recent recalls across all agencies. No parameters.

```bash
curl https://<your-service>.onrender.com/recalls/latest
```

### `GET /recalls/search`

Postgres full-text search over product + brand + hazard, ranked by relevance.

| Param | Type | Default | Notes |
|---|---|---|---|
| `q` | string | **required** | min 2 chars |
| `agency` | string | – | optional filter |
| `page` / `per_page` | int | `1` / `25` | max 100 |

Uses `websearch_to_tsquery`, so callers get quoted phrases, `OR`, and leading
`-` for exclusion — and malformed input degrades instead of erroring.

```bash
curl "https://<your-service>.onrender.com/recalls/search?q=listeria+cheese"
curl "https://<your-service>.onrender.com/recalls/search?q=%22air+bag%22+-inflator"
```

### `GET /recalls/{agency}/{source_id}`

One recall by its agency-native identifier.

```bash
curl https://<your-service>.onrender.com/recalls/NHTSA/26V481000
```

```json
{
  "data": {
    "agency": "NHTSA",
    "source_id": "26V481000",
    "product": "C 300; C 300 4MATIC; CLE 300 4MATIC (2022-2026)",
    "brand": "MERCEDES-BENZ",
    "classification": "Vehicle",
    "url": "https://www.nhtsa.gov/recalls?nhtsaId=26V481000"
  },
  "meta": {}
}
```

Returns `404` with `{"error": {"code": "not_found", ...}}` if no such recall.

### Errors

| Status | `error.code` | When |
|---|---|---|
| `400` | `bad_request` | e.g. `since` after `until` |
| `401` | `unauthorized` | Missing/invalid `X-RapidAPI-Proxy-Secret` |
| `404` | `not_found` | Unknown recall |
| `422` | `invalid_parameters` | Bad date format, `per_page` > 100 |
| `500` | `internal_error` | Generic — never leaks internals |

---

## Local development

Requires Python 3.12 and a Postgres database (Neon free tier works).

```bash
git clone https://github.com/sm-coding-projects/recall-radar
cd recall-radar

python3.12 -m venv .venv && source .venv/bin/activate
pip install -r requirements-dev.txt

cp .env.example .env          # then fill in DATABASE_URL
psql "$DATABASE_URL" -f db/schema.sql
```

Run the API:

```bash
uvicorn api.main:app --reload
# http://127.0.0.1:8000/docs for interactive OpenAPI docs
```

Run the fetcher:

```bash
python -m fetcher.run                  # incremental, last 30 days
python -m fetcher.run --backfill       # all available history
python -m fetcher.run --agency FDA     # one source
python -m fetcher.run --dry-run        # fetch + normalize, no writes
```

Run the tests (no database required — the DB layer is stubbed):

```bash
pytest -q
```

### Environment variables

| Variable | Required | Purpose |
|---|---|---|
| `DATABASE_URL` | yes | Postgres connection string |
| `RAPIDAPI_PROXY_SECRET` | no | When set, all routes except `/health` require a matching `X-RapidAPI-Proxy-Secret` header |

Never commit `.env` — it is gitignored.

### ⚠️ FSIS is US-only

`fsis.usda.gov` sits behind Akamai and returns **403 for its entire domain** to
non-US IPs. If you develop from outside the US, the FSIS adapter will fail
locally with an explanatory error; every other source works fine. Ingest FSIS
by running the workflow from GitHub Actions (US runners) instead:

```bash
gh workflow run fetch.yml -f agency=FSIS -f backfill=true
```

Full details, and the rest of the per-source quirks, are in
[`docs/sources.md`](docs/sources.md).

---

## How it works

**Idempotent upserts.** Every record has a stable `(agency, source_id)` key
with `ON CONFLICT DO UPDATE`, so re-running never duplicates and amended
recalls are refreshed in place. Batches are deduplicated before insert —
Postgres rejects a statement that hits the same conflict target twice.

**Full-text search** uses a `GENERATED ALWAYS AS ... STORED` tsvector column
rather than an expression index, so the GIN index is used without every query
having to repeat the expression verbatim.

**Source quirks** are handled in the adapters and documented in
[`docs/sources.md`](docs/sources.md). The ones that shaped the design:

- openFDA returns **HTTP 404 for zero matches**, not an empty list. FDA
  refreshes roughly weekly, so an empty daily window is the normal case.
- openFDA's `skip` caps at 25,000 while the device dataset holds ~39,600
  records — a naive paginated backfill silently truncates. Backfill walks
  calendar-year windows instead.
- FDA sometimes ships a **blank `recall_number`** on newly published recalls.
  Those get a deterministic `EVT-` synthetic id rather than being dropped.
- NHTSA's JSON API has **no date filter** and mixes `DD/MM/YYYY` with
  `MM/DD/YYYY` in one field. The ODI flat file is used instead: clean
  `YYYYMMDD`, refreshed daily, one download.
- The NHTSA flat file has **one row per campaign × make × model × year**, so
  rows are grouped by campaign number before insert.

---

## Deployment

**Database** — Neon free tier, US East (`us-east-2`).

**API** — Render free web service:

- Build: `pip install -r requirements.txt`
- Start: `uvicorn api.main:app --host 0.0.0.0 --port $PORT`
- Env: `DATABASE_URL`, and `RAPIDAPI_PROXY_SECRET` once listed

Render's free tier sleeps after ~15 minutes idle; the first request afterwards
takes a few seconds to wake. The connection pool is configured with
`min_size=0` and connection checking so a suspended Neon compute does not
produce stale-connection errors on wake.

**Fetcher** — GitHub Actions, daily at 06:00 UTC, using the `DATABASE_URL`
repo secret. Each scheduled run commits a `heartbeat.txt` timestamp so GitHub
does not disable the schedule after 60 days of repo inactivity.

---

## Listing on RapidAPI

- [ ] **Deploy** and confirm `/health` returns `"status": "ok"` with a non-zero
      `recalls` count.
- [ ] **Generate a proxy secret** (`openssl rand -hex 32`), set it as
      `RAPIDAPI_PROXY_SECRET` on Render, and confirm unauthenticated requests
      now return `401` while `/health` still returns `200`.
- [ ] **Add the API** on RapidAPI → *My APIs* → *Add New API*. Category:
      *Data* or *Business*.
- [ ] **Set the base URL** to your Render URL, and paste the same proxy secret
      into RapidAPI's *Transform Headers* / secret field so it forwards
      `X-RapidAPI-Proxy-Secret`.
- [ ] **Import the OpenAPI spec** from `https://<your-service>.onrender.com/openapi.json`
      — FastAPI generates it, so every endpoint and parameter is described
      without hand-writing docs.
- [ ] **Write endpoint descriptions** and add a working example request for
      each of the five endpoints.
- [ ] **Define pricing tiers.** A common shape:
      Basic (free, ~100 req/day) → Pro → Ultra → Mega, with rate limits set in
      RapidAPI, not in this codebase.
- [ ] **Test every endpoint** from RapidAPI's own test console, including a
      `404` and a `422`, so buyers see clean error output.
- [ ] **Fill in the listing**: short description, long description, logo,
      and tags (`recalls`, `safety`, `FDA`, `CPSC`, `NHTSA`, `government`).
- [ ] **Document the data lag** honestly — FDA refreshes weekly, NHTSA and
      CPSC daily. Buyers will notice, so say it up front.
- [ ] **Add a terms note**: this repackages US federal public-domain data;
      the source agencies do not endorse the service.

---

## Data & licensing

All four sources are US federal government publications and are in the public
domain. This project adds normalization and hosting, not new data. It is not
affiliated with or endorsed by the FDA, CPSC, USDA, or NHTSA.

Recall data is provided as-is and must not be relied on for medical, safety,
or legal decisions — always confirm against the linked official notice.
