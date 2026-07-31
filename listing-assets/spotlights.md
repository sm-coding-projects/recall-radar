# Recall Radar — spotlights

Three short blurbs for the listing's spotlight/use-case section. Each is a
title, a one-line pitch, and a working curl example.

---

## 1. Check a product before you ship it

**Search 111,733 recalls by product, brand, or hazard before inventory leaves
your warehouse — one call, ranked by relevance.**

```bash
curl --request GET \
  --url 'https://recall-radar.p.rapidapi.com/recalls/search?q=%22pool%20drain%20cover%22' \
  --header 'X-RapidAPI-Key: YOUR_KEY' \
  --header 'X-RapidAPI-Host: recall-radar.p.rapidapi.com'
```

Quote a phrase to match it exactly, or exclude a term with `-`:
`?q="air bag" -inflator` returns 587 matches. `pagination.total` tells you
the size of the hit set before you page through it.

---

## 2. Monitor a brand

**Track every recall for a manufacturer across all three agencies in one
query, instead of three agency-specific integrations.**

```bash
curl --request GET \
  --url 'https://recall-radar.p.rapidapi.com/recalls/search?q=mercedes&per_page=100' \
  --header 'X-RapidAPI-Key: YOUR_KEY' \
  --header 'X-RapidAPI-Host: recall-radar.p.rapidapi.com'
```

Searching `mercedes` returns 560 records spanning vehicle campaigns and
related device or consumer-product recalls. Add `&agency=NHTSA` to narrow to
one publisher. Store `agency` + `source_id` to deduplicate across polls —
both stay stable when a recall is amended.

To restrict a brand sweep to a date window, use `/recalls` instead, which
supports `since` and `until`:

```bash
curl --request GET \
  --url 'https://recall-radar.p.rapidapi.com/recalls?agency=NHTSA&since=2026-01-01&per_page=100' \
  --header 'X-RapidAPI-Key: YOUR_KEY' \
  --header 'X-RapidAPI-Host: recall-radar.p.rapidapi.com'
```

---

## 3. Latest recalls feed

**The 50 newest recalls across every agency, no parameters required — drop it
straight into a dashboard or alerting job.**

```bash
curl --request GET \
  --url 'https://recall-radar.p.rapidapi.com/recalls/latest' \
  --header 'X-RapidAPI-Key: YOUR_KEY' \
  --header 'X-RapidAPI-Host: recall-radar.p.rapidapi.com'
```

The cheapest endpoint in the API — it skips the count query that `/recalls`
runs, so it is the right choice for polling. Data refreshes daily at
06:00 UTC; poll once a day and compare `source_id` against what you have
already seen.
