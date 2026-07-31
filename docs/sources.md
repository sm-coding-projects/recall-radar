# Source APIs

Research notes for the four upstream recall sources. **All facts below were
verified against the live endpoints on 2026-07-31**, not taken from memory.
Quoted error strings are verbatim API responses.

Contents:
1. [openFDA (FDA)](#1-openfda--fda)
2. [CPSC — SaferProducts.gov](#2-cpsc--saferproductsgov)
3. [USDA FSIS](#3-usda-fsis)
4. [NHTSA](#4-nhtsa)
5. [Normalization mapping](#5-normalization-mapping)
6. [Cross-cutting decisions](#6-cross-cutting-decisions)

---

## 1. openFDA — FDA

**Base URL:** `https://api.fda.gov`

Three enforcement endpoints, one per center:

| Endpoint | Records (2026-07-31) | `recall_number` prefix |
|---|---|---|
| `/food/enforcement.json` | 29,264 | `H-` (one `N-` observed) |
| `/drug/enforcement.json` | 17,832 | `D-` |
| `/device/enforcement.json` | 39,588 | `Z-` |

`meta.last_updated` was `2026-07-22` for all three — the dataset refreshes
roughly weekly, so a daily incremental run will often be a no-op. That is fine
and expected; it is not a bug.

### Query parameters

| Param | Notes |
|---|---|
| `search` | Lucene-ish `field:term`; ranges are `field:[A+TO+B]` |
| `sort` | e.g. `report_date:desc` |
| `limit` | **Max 1000.** |
| `skip` | **Max 25000.** |
| `search_after` | Cursor for deep pagination past the `skip` cap |
| `count` | Faceting; not needed here |
| `api_key` | Optional, raises the daily quota |

Verified caps (verbatim errors):

- `limit=1001` → `"Limit cannot exceed 1000 results for search requests. Use the skip or search_after param to get additional results."`
- `skip=26000` → `"Skip value must 25000 or less."`

> ⚠️ **The `skip` cap is smaller than the device dataset.** `device` has 39,588
> records but `skip` stops at 25,000, so a naive `skip`-paginated backfill
> silently truncates at ~63% coverage. The backfill therefore **walks fixed
> date windows** (one calendar year at a time) rather than paging with `skip`.
> Each window stays well under 25,000.

### Date filtering

Dates are `YYYYMMDD` **strings**, not ISO dates:

```
GET /food/enforcement.json?search=report_date:[20260601+TO+20260731]&sort=report_date:desc&limit=1000
```

Available date fields: `report_date` (published), `recall_initiation_date`,
`center_classification_date`, and `termination_date` (drug only).

We filter incrementals on `report_date` — that is when FDA publishes the record,
so it is the field that actually moves when new data appears.
`recall_initiation_date` can be backdated months and would cause missed rows.

> Note for anyone reproducing these calls in a shell: `curl` treats `[` and `]`
> as glob syntax and rejects the URL. Use `curl -g`. Not an API issue.

### Rate limits

| | Per minute | Per day |
|---|---|---|
| No API key | 240 / IP | 1,000 / IP |
| With API key | 240 / key | 120,000 / key |

Key is passed as `?api_key=…` or as the basic-auth username.

**We run keyless.** A full backfill is ~90 windowed calls, far under 1,000/day,
and the daily incremental is ~12 calls. `FDA_API_KEY` is supported as an
optional env var if the quota ever becomes a constraint — free to obtain.

### Response fields

Envelope is `{meta: {...}, results: [...]}`. Result fields:

`status`, `city`, `state`, `country`, `classification`, `openfda`,
`product_type`, `event_id`, `recalling_firm`, `address_1`, `address_2`,
`postal_code`, `voluntary_mandated`, `initial_firm_notification`,
`distribution_pattern`, `recall_number`, `product_description`,
`product_quantity`, `reason_for_recall`, `recall_initiation_date`,
`center_classification_date`, `report_date`, `code_info`, `more_code_info`
(food/device), `termination_date` (drug).

### Data-quality findings

1. **`recall_number` is unique within an endpoint** (verified: 1,000 newest food
   records → 1,000 distinct values, zero duplicates), and prefixes are
   center-specific (`H`/`N`=food, `D`=drug, `Z`=device). So a single
   `agency='FDA'` namespace is safe — no cross-center collisions.
2. **`recall_number` is sometimes an empty string.** Found in both food
   (`event_id` 99068, SKS Copack) and drug (`event_id` 98647, Alembic).
   These are recalls published before classification is assigned.
   Since `source_id` is half our unique key, the adapter falls back to a
   deterministic synthetic id — `EVT-{event_id}-{sha1(product_description)[:8]}`
   — which is stable across runs, so upserts stay idempotent.
   Caveat: when FDA later assigns a real number, the record reappears under the
   real id and the `EVT-` row remains as a stale duplicate. Accepted tradeoff —
   dropping unnumbered records would hide the *newest* recalls, which are
   exactly the ones users care about most.
3. **Some dates are transposed but parse cleanly.** Two records in the live
   archive carry a mistyped `recall_initiation_date`:

   | Record | Raw value | Parses to | Reported |
   |---|---|---|---|
   | `F-0880-2013` | `02121207` | 0212-12-07 | 2013-01-23 |
   | `Z-0139-2014` | `19301211` | 1930-12-11 | 2013-11-13 |

   Both sorted ahead of every genuine recall. The adapter now applies two
   guards and falls back to `report_date`:

   - an absolute floor of 1900 plus a no-future-dates rule; and
   - a cross-field check, because `19301211` clears any floor low enough to
     keep CPSC's genuine 1973 archive. Measured across the live data,
     legitimate initiation-to-report gaps tail off smoothly to ~10 years
     (4 records) with one outlier at 15.4 years, then nothing until 82.9 and
     1800.1 years -- the two corruptions. The threshold sits at 20 years,
     inside that empty band.

   `raw` keeps the original upstream value untouched.
4. There is no per-recall public URL in the payload. We synthesize a search
   link (see [§6](#6-cross-cutting-decisions)).

---

## 2. CPSC — SaferProducts.gov

**Base URL:** `https://www.saferproducts.gov/RestWebServices/Recall`

`format=json` is **required** — the default response is XML.

### Query parameters (all verified working)

| Param | Example | Verified result |
|---|---|---|
| `format` | `json` | required for JSON |
| `RecallDateStart` / `RecallDateEnd` | `2026-07-01` / `2026-07-10` | 19 records |
| `LastPublishDateStart` / `LastPublishDateEnd` | `2026-07-20` | 21 records |
| `RecallNumber` | `26634` | 1 record |
| `RecallID` | `10875` | 1 record |

Dates are `YYYY-MM-DD`.

### Pagination & volume

**There is none — and it doesn't need any.** The response is a bare JSON array
(no envelope, no cursor) containing every matching record.

Full unfiltered dump, measured: **9,912 records, 27.3 MB, 2.2 s**, spanning
**1973-06-08 → 2026-07-23**. That is small enough that the `--backfill` path is
literally one request.

No documented rate limit. We still send a descriptive User-Agent and keep
concurrency at 1.

**Incremental strategy:** filter on `LastPublishDateStart`, not
`RecallDateStart`. CPSC edits existing recalls (adding units, images, remedies)
without changing `RecallDate`, so publish-date is what catches amendments.

### Response fields

Top level: `RecallID` (int), `RecallNumber`, `RecallDate`, `Description`,
`URL`, `Title`, `ConsumerContact`, `LastPublishDate`, `SoldAtLabel`.

Nested arrays: `Products[]` (`Name`, `Description`, `Model`, `Type`,
`CategoryID`, `NumberOfUnits`), `Hazards[]` (`Name`, `HazardType`),
`Remedies[]`, `RemedyOptions[]` (`Option`), `Manufacturers[]`, `Retailers[]`,
`Importers[]`, `Distributors[]`, `ManufacturerCountries[]` (`Country`),
`ProductUPCs[]`, `Injuries[]`, `Images[]` (`URL`, `Caption`),
`Inconjunctions[]` (links to partner-agency recalls, e.g. Health Canada).

CPSC is the only source that ships a real per-recall `URL` — use it directly.

---

## 3. USDA FSIS

**Base URL:** `https://www.fsis.usda.gov/fsis/api/recall/v/1`

### ⚠️ Blocked by Akamai bot protection — unresolved

Every request to `fsis.usda.gov` returns an Akamai **HTTP 403 "Access Denied"**,
from every client and location tried. The domain is blocked wholesale — the
homepage 403s just like the API.

| Target | Result |
|---|---|
| `/fsis/api/recall/v/1` | 403 |
| `/fsis/api/establishments/v/1`, `/fsis/api/mpi/v/1` | 403 |
| `/science-data/developer-resources/recall-api` (docs page) | 403 |
| `Recall-API-documentation.pdf` | 403 |
| `https://www.fsis.usda.gov/` (homepage) | 403 |
| `fsis-content/rss/recalls.xml` (RSS feed) | 403 |
| `foodsafety.gov/rss/recalls.xml` | 403 |

**An earlier revision of this document blamed geo-filtering. That was wrong.**
The initial evidence was consistent with it — the whole domain 403s and this
dev machine's egress IP is in Australia — but a controlled test from a US
GitHub Actions runner disproved it. From the US runner, all of these still
returned 403:

default curl UA · `recall-radar` UA · Chrome UA · Chrome UA + `Accept`
headers · Chrome UA + full client hints (`sec-ch-ua`, `Sec-Fetch-*`,
`Referer`) · HTTP/1.1 · HTTP/2 · Python `urllib`

Since neither the source IP's country nor any combination of request headers
changes the outcome, the block is on the **TLS handshake fingerprint** — curl
and Python present a different JA3 signature than a real browser, and Akamai
rejects on that before the HTTP request is considered. This matches the
observation that the public projects consuming this API all reach for
`cloudscraper` or `curl_cffi`, whose entire purpose is TLS impersonation.

**Status: FSIS is not ingested.** The adapter is written and unit-tested
against fixtures, and will work unchanged the moment the endpoint is
reachable, but no live data has been loaded.

**Not done unilaterally:** adding `curl_cffi`/`cloudscraper` TLS impersonation
would very likely work, but it means deliberately defeating a deployed bot
control. That is a call for the project owner, not a default — see the note in
the README. It also adds a fragile dependency that breaks whenever Akamai
updates its fingerprint set.

**No mirror found.** `catalog.data.gov`'s CKAN API now returns 404 for
`package_search`/`package_list`, and there is no non-Akamai FSIS host. USDA
meat/poultry recalls are *not* covered by openFDA's food endpoint, so this is
a genuine coverage gap rather than a duplicate.

### Schema (from three independent sources, pending live validation)

Reconstructed from public consumers of this API, cross-checked for agreement:
a dbt staging model, a typed Pydantic client, and a normalizer.

| Field | Notes |
|---|---|
| `field_recall_number` | our `source_id` |
| `field_title` | headline |
| `field_recall_url` | per-recall public URL |
| `field_recall_date` | recall date; reported always populated |
| `field_recall_classification` | `Class I` / `Class II` / `Class III` / `Public Health Alert` |
| `field_recall_reason` | array |
| `field_summary` | HTML — must be tag-stripped |
| `field_product_items` | array; HTML |
| `field_establishment` | array; company/plant |
| `field_states` | array; distribution |
| `field_active_notice` | `"True"` / `"False"` as strings |
| `field_year_id` | year facet, also a query filter |

Query params: `field_year_id`, `field_states_id`, `field_recall_date_value`,
`field_summary_value`, `items_per_page`. Response is a bare JSON array with no
pagination envelope, same shape as CPSC.

Note `field_recall_classification` carries a 4th value, `Public Health Alert`,
that the official PDF does not document — the normalizer accepts it rather than
rejecting the row.

**Everything in this section is marked provisional in the adapter** and gets
verified on the first successful US-side run.

---

## 4. NHTSA

Two independent access paths. We use the **flat file**, for reasons below.

### 4a. JSON API — `https://api.nhtsa.gov` (verified working)

| Endpoint | Behaviour |
|---|---|
| `/recalls/campaignNumber?campaignNumber=20V505000` | single campaign; rich fields |
| `/recalls/recallsByVehicle?make=&model=&modelYear=` | **all three params required** |
| `/products/vehicle/modelYears?issueType=r` | 80 years (1949→) |
| `/products/vehicle/makes?modelYear=2025&issueType=r` | 192 makes |
| `/products/vehicle/models?modelYear=&make=&issueType=r` | models |

Envelope: `{Count, Message, results: []}`. No auth, no documented rate limit.

**Why this path is unusable for ingestion — two blockers:**

1. **No date filter anywhere.** `recallsByVehicle` rejects a bare `modelYear`
   (`?modelYear=2026` → `Count: 0`); it needs make *and* model too. Enumerating
   the catalogue would be 80 years × ~190 makes × ~30 models ≈ **tens of
   thousands of requests per run**. Not viable, and not polite.
2. **`ReportReceivedDate` is inconsistently formatted.** Observed
   `"10/12/2020"` and `"26/08/2020"` in the same field. `26` cannot be a month,
   so that value is `DD/MM/YYYY`, while others appear to be `MM/DD/YYYY` —
   the format is genuinely ambiguous per record and **cannot be parsed safely**.
   (Cross-checked: campaign 20V505000's summary says the recall began
   September 11 2020, consistent with 26 August 2020 receipt.)

We therefore do not parse dates from this endpoint. It stays available as an
optional per-campaign enrichment lookup only.

### 4b. ODI flat file — chosen source

```
https://static.nhtsa.gov/odi/ffdd/rcl/FLAT_RCL_POST_2010.zip
```

- Verified `HTTP 200`, `Last-Modified: Thu, 30 Jul 2026 07:06:19 GMT` — **daily**.
- TAB-delimited, **29 fields**, **all dates clean `YYYYMMDD`** — no ambiguity.
- Covers all campaigns from 2010 onward.
- Data dictionary: `https://static.nhtsa.gov/odi/ffdd/rcl/RCL.txt`
- The legacy `FLAT_RCL.zip` (all years since 1967) now returns **404** — it is
  gone, and `POST_2010` is the current file. Pre-2010 vehicle recalls are
  therefore out of scope; noted as a known coverage limit.
- One download per run covers both incremental and backfill. No rate limit
  concerns.

Field layout (from `RCL.txt`):

| # | Name | Meaning |
|---|---|---|
| 1 | `RECORD_ID` | sequence number |
| 2 | `CAMPNO` | **NHTSA recall number** → our `source_id` |
| 3 | `MAKETXT` | make |
| 4 | `MODELTXT` | model |
| 5 | `YEARTXT` | model year (`9999` = unknown) |
| 6 | `MFGCAMPNO` | manufacturer campaign no. |
| 7 | `COMPNAME` | component → our `category` |
| 8 | `MFGNAME` | filing manufacturer |
| 9–10 | `BGMAN`, `ENDMAN` | manufacturing date range |
| 11 | `RCLTYPECD` | Vehicle / Equipment / Child Restraint / Tire |
| 12 | `POTAFF` | units affected |
| 13 | `ODATE` | owners notified |
| 14 | `INFLUENCED_BY` | MFR / OVSC / ODI |
| 15 | `MFGTXT` | manufacturer of recalled item |
| 16 | `RCDATE` | **Part 573 report received** → our `recall_date` |
| 17 | `DATEA` | record creation → our `published_at` |
| 18–19 | `RPNO`, `FMVSS` | regulation refs |
| 20 | `DESC_DEFECT` | defect summary → our `hazard` |
| 21 | `CONEQUENCE_DEFECT` | consequence (sic — misspelled upstream) |
| 22 | `CORRECTIVE_ACTION` | remedy |
| 23 | `NOTES` | notes |
| 24–27 | `RCL_CMPT_ID`, `MFR_COMP_*` | component detail |
| 28–29 | `DO_NOT_DRIVE`, `PARK_OUTSIDE` | consumer advisories |

> **Grain mismatch — important.** The flat file has **one row per
> campaign × make × model × year**, so a single campaign appears many times.
> Our table is one row per *recall*, so the adapter **groups by `CAMPNO`** and
> aggregates the distinct make/model/year values into `product` / `brand`.
> Without this, one Ford campaign would insert hundreds of near-identical rows.

---

## 5. Normalization mapping

How each source populates the `recalls` table (Step 3 schema).

| Column | FDA | CPSC | FSIS | NHTSA |
|---|---|---|---|---|
| `agency` | `FDA` | `CPSC` | `FSIS` | `NHTSA` |
| `source_id` | `recall_number` (→ `EVT-…` fallback) | `RecallNumber` | `field_recall_number` | `CAMPNO` |
| `product` | `product_description` | `Products[].Name` joined | `field_product_items` (stripped) | distinct `MODELTXT` joined |
| `brand` | `recalling_firm` | `Manufacturers[].Name` | `field_establishment` | distinct `MAKETXT` joined |
| `category` | `product_type` (Food/Drugs/Devices) | `Products[].Type` | `Meat and Poultry` | `COMPNAME` |
| `hazard` | `reason_for_recall` | `Hazards[].Name` | `field_recall_reason` / `field_summary` | `DESC_DEFECT` |
| `classification` | `classification` (`Class I–III`) | `RemedyOptions[].Option` | `field_recall_classification` | `RCLTYPECD` |
| `recall_date` | `recall_initiation_date` | `RecallDate` | `field_recall_date` | `RCDATE` |
| `published_at` | `report_date` | `LastPublishDate` | `field_recall_date` | `DATEA` |
| `url` | synthesized (see §6) | `URL` | `field_recall_url` | synthesized (see §6) |
| `raw` | full source record as `jsonb` | ” | ” | grouped rows as `jsonb` |

Dates arriving as `YYYYMMDD` (FDA, NHTSA) or `YYYY-MM-DDT00:00:00` (CPSC) are
parsed to `date` / `timestamptz` in the adapter, never in SQL.

## 6. Cross-cutting decisions

- **Auth:** none of the four require a key. openFDA has an optional free key
  (higher daily quota); everything stays inside free limits without it.
- **Synthesized URLs.** FDA and NHTSA don't return a per-recall link:
  - FDA → `https://www.fda.gov/safety/recalls-market-withdrawals-safety-alerts`
    plus the recall number as a search term.
  - NHTSA → `https://www.nhtsa.gov/recalls?nhtsaId={CAMPNO}`
  CPSC and FSIS ship real URLs and are used verbatim.
- **Incremental window** is 30 days by default (per spec), filtered on each
  source's *publish*-ish field so amendments are re-caught and upserted.
- **Politeness:** single-threaded per agency, descriptive User-Agent
  (`recall-radar/0.1 (+repo url)`), exponential backoff on 429/5xx.
- **Refresh cadence differs a lot** — openFDA weekly, NHTSA daily, CPSC
  continuous. A daily run finding zero new FDA rows is normal.

### Verification status

| Source | Endpoint verified live | Schema verified live |
|---|---|---|
| FDA | ✅ | ✅ |
| CPSC | ✅ | ✅ |
| NHTSA (flat file) | ✅ headers + dictionary | ⏳ on first parse |
| FSIS | ❌ blocked everywhere tried | ❌ not ingested |
