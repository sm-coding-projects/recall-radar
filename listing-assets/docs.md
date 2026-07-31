# Recall Radar — Documentation

**One API for every US product recall.** FDA, CPSC, and NHTSA recalls,
normalized into a single schema and searchable in one call.

**111,733 recalls** · consumer products back to **1973** · updated **daily**

---

## Quick start

### 1. Subscribe and get your key

1. Open the **Pricing** tab and subscribe to a plan (there is a free tier).
2. Your key appears automatically as `X-RapidAPI-Key` in the code samples on
   the **Endpoints** tab.
3. Every request needs two headers:

   | Header | Value |
   |---|---|
   | `X-RapidAPI-Key` | your key |
   | `X-RapidAPI-Host` | `recall-radar.p.rapidapi.com` |

RapidAPI adds both automatically from its playground and its generated
snippets. You only set them by hand when calling from your own code.

### 2. Your first call

The 50 most recent recalls across all agencies — no parameters needed.

**curl**

```bash
curl --request GET \
  --url 'https://recall-radar.p.rapidapi.com/recalls/latest' \
  --header 'X-RapidAPI-Key: YOUR_KEY' \
  --header 'X-RapidAPI-Host: recall-radar.p.rapidapi.com'
```

**Python**

```python
import requests

response = requests.get(
    "https://recall-radar.p.rapidapi.com/recalls/latest",
    headers={
        "X-RapidAPI-Key": "YOUR_KEY",
        "X-RapidAPI-Host": "recall-radar.p.rapidapi.com",
    },
    timeout=30,
)
response.raise_for_status()

for recall in response.json()["data"]:
    print(f"{recall['recall_date']}  {recall['agency']:6}  {recall['product'][:60]}")
```

**JavaScript**

```javascript
const response = await fetch(
  "https://recall-radar.p.rapidapi.com/recalls/latest",
  {
    headers: {
      "X-RapidAPI-Key": "YOUR_KEY",
      "X-RapidAPI-Host": "recall-radar.p.rapidapi.com",
    },
  }
);

const { data } = await response.json();
data.forEach((r) => console.log(r.recall_date, r.agency, r.product));
```

### 3. What comes back

Every list endpoint returns the same envelope:

```json
{
  "data": [ /* recall objects */ ],
  "pagination": { "page": 1, "per_page": 25, "total": 111733,
                  "total_pages": 4470, "has_next": true, "has_prev": false },
  "meta": { "filters": {} }
}
```

Single-item endpoints return `{"data": {...}, "meta": {}}`.
Errors always return `{"error": {"code": ..., "message": ..., "detail": ...}}`.

---

## Endpoints

### `GET /recalls/latest`

The 50 most recent recalls across all agencies. No parameters. This is the
cheapest call — it skips the count query that `/recalls` runs — so it is the
right choice for a polling feed or dashboard.

```bash
curl --request GET \
  --url 'https://recall-radar.p.rapidapi.com/recalls/latest' \
  --header 'X-RapidAPI-Key: YOUR_KEY' \
  --header 'X-RapidAPI-Host: recall-radar.p.rapidapi.com'
```

```json
{
  "data": [
    {
      "id": 535,
      "agency": "NHTSA",
      "source_id": "26V490000",
      "product": "IMAGINE (2026)",
      "brand": "GRAND DESIGN",
      "category": "EQUIPMENT:RECREATIONAL VEHICLE/TRAILER:120/240 VAC ELECTRICAL SYSTEM:RECEPTACLE",
      "hazard": "Grand Design RV, LLC (Grand Design) is recalling certain 2026 Imagine travel trailers. The outlet cover may have been improperly secured, allowing screws to contact wiring. Contact with wiring may cause a short circuit or an electrical arc, increasing the risk of a fire.",
      "classification": "Vehicle",
      "recall_date": "2026-07-28",
      "published_at": "2026-07-29T00:00:00Z",
      "url": "https://www.nhtsa.gov/recalls?nhtsaId=26V490000",
      "ingested_at": "2026-07-31T04:07:31.164779Z"
    },
    {
      "id": 494,
      "agency": "NHTSA",
      "source_id": "26V483000",
      "product": "ANTHEM (2026)",
      "brand": "ENTEGRA",
      "category": "EQUIPMENT:OTHER:LABELS",
      "hazard": "Jayco, Inc. (Jayco) is recalling certain 2026 Entegra Anthem motorhomes. The tire size may be incorrect on the vehicle certification label. Incorrect information may result in the wrong sized replacement tires being installed, increasing the risk of a crash.",
      "classification": "Vehicle",
      "recall_date": "2026-07-27",
      "published_at": "2026-07-27T00:00:00Z",
      "url": "https://www.nhtsa.gov/recalls?nhtsaId=26V483000",
      "ingested_at": "2026-07-31T04:07:31.164779Z"
    }
  ],
  "pagination": null,
  "meta": { "limit": 50 }
}
```

`pagination` is `null` here by design — the result set is a fixed 50.

---

### `GET /recalls`

Browse and filter the full archive, newest first.

| Parameter | Type | Default | Notes |
|---|---|---|---|
| `agency` | string | – | `FDA`, `CPSC`, or `NHTSA`. Case-insensitive. |
| `category` | string | – | Case-insensitive **substring** match. |
| `since` | date | – | `YYYY-MM-DD`, inclusive. |
| `until` | date | – | `YYYY-MM-DD`, inclusive. |
| `page` | integer | `1` | 1-based. |
| `per_page` | integer | `25` | Maximum **100**. |

All filters are optional and combine with AND. Sending a parameter blank
(`?agency=`) is treated as "not supplied", so you can pass your whole
parameter set every time without stripping empty values.

```bash
curl --request GET \
  --url 'https://recall-radar.p.rapidapi.com/recalls?agency=CPSC&since=2026-07-01&per_page=2' \
  --header 'X-RapidAPI-Key: YOUR_KEY' \
  --header 'X-RapidAPI-Host: recall-radar.p.rapidapi.com'
```

```json
{
  "data": [
    {
      "id": 401,
      "agency": "CPSC",
      "source_id": "26636",
      "product": "Sviyatp Pool Drain Covers",
      "brand": null,
      "category": null,
      "hazard": "The recalled drain covers violate the entrapment protection standards of the Virginia Graeme Baker Pool and Spa Safety Act (VGBA), posing deadly entrapment and drowning hazards to consumers.",
      "classification": "Refund",
      "recall_date": "2026-07-23",
      "published_at": "2026-07-24T00:00:00Z",
      "url": "https://www.cpsc.gov/Recalls/2026/Sviyatp-Pool-Drain-Covers-Recalled-Due-to-Risk-of-Serious-Injury-or-Death-from-Entrapment-and-Drowning-Hazards-Violate-Virginia-Graeme-Baker-Pool-Spa-Safety-Act",
      "ingested_at": "2026-07-31T04:07:22.046254Z"
    },
    {
      "id": 400,
      "agency": "CPSC",
      "source_id": "26639",
      "product": "Personalized Baby Bibs and Stroller Bags",
      "brand": "Peony Design Co., of Howell, MI",
      "category": null,
      "hazard": "The snap can detach from the recalled bibs and stroller bags, posing a risk of serious injury or death from a choking hazard to young children.",
      "classification": "Refund",
      "recall_date": "2026-07-23",
      "published_at": "2026-07-24T00:00:00Z",
      "url": "https://www.cpsc.gov/Recalls/2026/Peony-Design-Recalls-Personalized-Baby-Bibs-and-Stroller-Bags-Due-to-Risk-of-Serious-Injury-or-Death-from-Choking-Hazard",
      "ingested_at": "2026-07-31T04:07:22.046254Z"
    }
  ],
  "pagination": {
    "page": 1, "per_page": 2, "total": 40,
    "total_pages": 20, "has_next": true, "has_prev": false
  },
  "meta": { "filters": { "agency": "CPSC", "since": "2026-07-01" } }
}
```

**Paginating a full pull.** `pagination.total` is the count of *all* matches,
so you can size a job before running it:

```python
import requests

HEADERS = {"X-RapidAPI-Key": "YOUR_KEY",
           "X-RapidAPI-Host": "recall-radar.p.rapidapi.com"}
BASE = "https://recall-radar.p.rapidapi.com/recalls"

page, everything = 1, []
while True:
    body = requests.get(
        BASE,
        params={"agency": "CPSC", "since": "2026-01-01", "page": page, "per_page": 100},
        headers=HEADERS, timeout=30,
    ).json()
    everything += body["data"]
    if not body["pagination"]["has_next"]:
        break
    page += 1

print(f"pulled {len(everything)} recalls")
```

---

### `GET /recalls/search`

Full-text search across product name, brand, and hazard description, ranked
by relevance.

| Parameter | Type | Default | Notes |
|---|---|---|---|
| `q` | string | **required** | Minimum 2 characters. |
| `agency` | string | – | Optional filter. |
| `page` | integer | `1` | |
| `per_page` | integer | `25` | Maximum 100. |

Supports web-search style operators:

| Query | Meaning |
|---|---|
| `listeria cheese` | both terms |
| `"air bag"` | exact phrase |
| `"air bag" -inflator` | phrase, excluding a term |
| `salmonella or listeria` | either term |

Matching is stemmed English, so `recalled` also matches `recall`.

```bash
curl --request GET \
  --url 'https://recall-radar.p.rapidapi.com/recalls/search?q=listeria%20cheese&per_page=2' \
  --header 'X-RapidAPI-Key: YOUR_KEY' \
  --header 'X-RapidAPI-Host: recall-radar.p.rapidapi.com'
```

```json
{
  "data": [
    {
      "id": 54099,
      "agency": "FDA",
      "source_id": "F-0917-2024",
      "product": "Tio Francisco Blanco Suave 14 oz. UPC 7-27242-05355-6",
      "brand": "Rizo Lopez Foods, Inc. dba Don Francisco Cheese",
      "category": "Food",
      "hazard": "Listeria monocytogenes contamination.",
      "classification": "Class I",
      "recall_date": "2024-01-11",
      "published_at": "2024-02-07T00:00:00Z",
      "url": "https://www.fda.gov/safety/recalls-market-withdrawals-safety-alerts",
      "ingested_at": "2026-07-31T03:45:39.458427Z"
    }
  ],
  "pagination": {
    "page": 1, "per_page": 2, "total": 781,
    "total_pages": 391, "has_next": true, "has_prev": false
  },
  "meta": { "query": "listeria cheese" }
}
```

---

### `GET /recalls/{agency}/{source_id}`

Fetch one recall by the identifier its own agency uses. This is the stable
key to store on your side — prefer it over the internal `id`.

| Agency | Identifier format | Example |
|---|---|---|
| `FDA` | `recall_number` | `F-0917-2024` |
| `CPSC` | `RecallNumber` | `26636` |
| `NHTSA` | Campaign number | `26V481000` |

```bash
curl --request GET \
  --url 'https://recall-radar.p.rapidapi.com/recalls/NHTSA/26V481000' \
  --header 'X-RapidAPI-Key: YOUR_KEY' \
  --header 'X-RapidAPI-Host: recall-radar.p.rapidapi.com'
```

```json
{
  "data": {
    "id": 513,
    "agency": "NHTSA",
    "source_id": "26V481000",
    "product": "AMG GLB35 4MATIC; C 300; C 300 4MATIC; CLE 300 4MATIC; CLE 450 4MATIC; GLB 250; AMG A35; GLC 300; A 220; CLA 250; GLA 250 (+3 more) (2019-2026)",
    "brand": "MERCEDES-BENZ",
    "category": "LATCHES/LOCKS/LINKAGES:DOORS:LOCK",
    "hazard": "Mercedes-Benz USA, LLC (MBUSA) is recalling certain 2020-2021 CLA, 2019-2022 A-Class, 2022-2023 C-Class, 2024 CLE, 2020-2026 GLA/GLB, and 2023-2024 GLC vehicles. The micro-switch in the driver's door lock may corrode and fail to detect an open door, preventing the electronic parking brake or \"Auto-Park\" feature from engaging automatically. This may result in a vehicle rollaway.",
    "classification": "Vehicle",
    "recall_date": "2026-07-24",
    "published_at": "2026-07-27T00:00:00Z",
    "url": "https://www.nhtsa.gov/recalls?nhtsaId=26V481000",
    "ingested_at": "2026-07-31T04:07:31.164779Z"
  },
  "meta": {}
}
```

Returns `404` if no recall matches that agency and identifier.

---

### `GET /health`

Service status and total row count. Useful as an uptime check.

```json
{ "status": "ok", "database": "ok", "recalls": 111733, "version": "0.1.0" }
```

Returns `200` with `"status": "degraded"` if the database is briefly
unreachable — check the `status` field, not the HTTP code.

---

## The recall object

Every endpoint returns objects of this shape. Fields marked nullable are
genuinely absent for some records — agencies differ in what they publish.

| Field | Type | Nullable | Description |
|---|---|---|---|
| `id` | integer | no | Internal row ID. **Not stable across reloads** — store `agency` + `source_id` instead. |
| `agency` | string | no | `FDA`, `CPSC`, or `NHTSA`. |
| `source_id` | string | no | The agency's own recall identifier. Stable. Unique within an agency. |
| `product` | string | yes | Product name or description. For NHTSA, the affected models and year range. |
| `brand` | string | yes | Recalling firm, manufacturer, or vehicle make. |
| `category` | string | yes | `Food`, `Drugs`, `Devices` (FDA); the component path (NHTSA); often `null` for CPSC. |
| `hazard` | string | yes | Why it was recalled — the defect, contaminant, or risk. |
| `classification` | string | yes | Severity or type. See below. |
| `recall_date` | date | yes | When the recall was initiated. `YYYY-MM-DD`. **Sort field for all list endpoints.** |
| `published_at` | datetime | yes | When the agency published or last amended it. ISO 8601 UTC. |
| `url` | string | yes | Link to the official notice. |
| `ingested_at` | datetime | no | When Recall Radar last refreshed this record. |

### `classification` values by agency

The agencies do not share a severity scale, so this field means different
things depending on `agency`:

| Agency | Values | Meaning |
|---|---|---|
| FDA | `Class I` · `Class II` · `Class III` | Class I = reasonable probability of serious harm or death. Class III = unlikely to cause harm. |
| NHTSA | `Vehicle` · `Equipment` · `Tire` · `Child Restraint` | The type of item recalled, not a severity. |
| CPSC | `Refund` · `Replace` · `Repair` · … | The remedy offered to consumers. |

Filter on `agency` first if you need to compare severity meaningfully.

### Errors

| Status | `error.code` | Cause |
|---|---|---|
| `400` | `bad_request` | `since` is later than `until`. |
| `401` | `unauthorized` | Missing or invalid key — check both RapidAPI headers. |
| `404` | `not_found` | No recall with that agency and `source_id`. |
| `422` | `invalid_parameters` | Malformed date, `per_page` above 100, empty `q`. `detail` names the field. |
| `429` | – | Plan rate limit exceeded (enforced by RapidAPI). |
| `500` | `internal_error` | Server error. Retry with backoff. |

```json
{
  "error": {
    "code": "invalid_parameters",
    "message": "One or more query parameters are invalid.",
    "detail": [
      { "field": "per_page", "reason": "Input should be less than or equal to 100" }
    ]
  }
}
```

---

## Data sources and update schedule

Recall Radar ingests directly from the official US government publishers.
No scraping of secondary sites, and no editorial changes to the facts — only
normalization into one schema.

| Agency | Covers | Source | Records | History |
|---|---|---|---|---|
| **FDA** | Food, drug, and medical-device enforcement reports | openFDA enforcement API | 86,683 | 2007 onward |
| **NHTSA** | Vehicles, tires, equipment, child seats | NHTSA ODI recalls file | 15,138 | 2010 onward |
| **CPSC** | Consumer products | SaferProducts.gov | 9,912 | **1973 onward** |

**Total: 111,733 recalls.**

### How often data updates

Ingestion runs **daily at 06:00 UTC**. Upstream publishers refresh on their
own cadences, which set the real freshness ceiling:

| Agency | Upstream refresh | Practical lag |
|---|---|---|
| NHTSA | Daily | ~1 day |
| CPSC | Continuously as recalls publish | ~1 day |
| FDA | **Roughly weekly** | up to ~7 days |

A day on which FDA returns no new records is normal, not an outage — openFDA
simply publishes in weekly batches. `ingested_at` on every record tells you
exactly when Recall Radar last saw it, and `/health` confirms the service is
current.

Updates are idempotent: when an agency amends a recall (adding affected
units, models, or a remedy), the existing record is updated in place rather
than duplicated. `source_id` stays stable, so your stored references keep
working.

### Not yet included

**USDA FSIS** (meat, poultry, and egg products) is **not currently covered**.
The FSIS API is unreachable behind bot protection that rejects automated
clients. The integration is written and will be enabled if access is
restored. Until then, do not rely on this API for USDA-regulated meat and
poultry recalls.

### Accuracy

Data is republished from US federal government sources and is in the public
domain. Recall Radar adds normalization and hosting, not new facts, and is
not affiliated with or endorsed by the FDA, CPSC, or NHTSA.

Records reflect what the agency published, including occasional upstream
typos and encoding artifacts in free-text fields. Always link users to the
official notice in `url` before they act on a recall. This API must not be
the sole basis for medical, safety, or legal decisions.
