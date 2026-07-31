# Recall Radar — marketplace overview

Recall Radar turns the fragmented world of US product-recall data into a
single, searchable JSON API. Recalls are announced by different federal
agencies, in different formats, on different schedules — the FDA publishes
food, drug, and medical-device enforcement reports; the CPSC handles consumer
products; NHTSA covers vehicles, tires, and child seats. Each exposes its data
differently: one is a paginated JSON API with a hard depth limit, one returns
its entire history as a single unpaginated array, and one is a tab-delimited
bulk file with one row per vehicle model. Recall Radar ingests all three,
normalizes them into one consistent record shape, and serves them through five
straightforward endpoints. One integration replaces three, and you never write
another date-format parser.

The archive currently holds **111,733 recalls**. Coverage runs deep as well as
wide: CPSC consumer-product recalls go back to **June 1973**, FDA enforcement
reports from 2007, and NHTSA safety campaigns from 2010. Recent years are
dense and complete — roughly **6,000 to 7,000 recalls per year** since 2020,
spanning **16,600 distinct brands** and **1,380 product categories**. That
depth makes the API useful for more than alerting: you can chart a supplier's
recall history over a decade, quantify hazard patterns in a product class, or
backfill a compliance database in a single paginated pull.

Data refreshes **daily at 06:00 UTC**, pulled directly from the official
government publishers rather than scraped from secondary sites. NHTSA and CPSC
update within about a day of an agency announcement; the FDA publishes in
roughly weekly batches upstream, which sets the ceiling on how fresh its
records can be — we document this plainly rather than implying real-time
coverage nobody can deliver. Every record carries an `ingested_at` timestamp
so you always know when it was last verified. Updates are idempotent: when an
agency amends a recall to add affected units or a remedy, the existing record
is updated in place, keeping the agency's own identifier stable so your stored
references never break.

The API is built for production use. Postgres full-text search across product,
brand, and hazard text supports quoted phrases, exclusions, and OR queries, so
`"air bag" -inflator` does what you would expect. Every response uses a
consistent envelope — `data`, `pagination`, `meta` — with clean, specific error
objects that name the offending field. Filter by agency, category, or date
range; page through results up to 100 at a time; or look up any single recall
by the identifier its own agency assigned it. Typical uses include pre-shipment
supplier checks, brand and competitor monitoring, consumer safety alerting,
compliance dashboards, and enriching product catalogs with recall status.

**One note on scope:** USDA FSIS meat and poultry recalls are **not currently
included**. The FSIS API sits behind bot protection that rejects automated
clients; the integration is written and will be enabled if access is restored.
If your use case depends on USDA-regulated meat and poultry, this API does not
yet cover it — we would rather say so here than have you discover it after
subscribing.

Recall data is republished from US federal government sources and is in the
public domain. Recall Radar is not affiliated with or endorsed by the FDA,
CPSC, or NHTSA, and every record links to the official notice.
