-- recall-radar schema
-- Idempotent: safe to run repeatedly against the same database.

CREATE TABLE IF NOT EXISTS recalls (
    id             bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    agency         text NOT NULL,
    source_id      text NOT NULL,
    product        text,
    brand          text,
    category       text,
    hazard         text,
    classification text,
    recall_date    date,
    published_at   timestamptz,
    url            text,
    raw            jsonb,
    ingested_at    timestamptz NOT NULL DEFAULT now(),

    -- Full-text vector kept as a stored generated column rather than a bare
    -- expression index. An expression index is only used when the query
    -- repeats the expression character-for-character; a generated column can
    -- be queried directly (search_tsv @@ ...), so the GIN index is always hit.
    search_tsv tsvector GENERATED ALWAYS AS (
        to_tsvector(
            'english',
            coalesce(product, '') || ' ' ||
            coalesce(brand,   '') || ' ' ||
            coalesce(hazard,  '')
        )
    ) STORED,

    -- Upsert target for the fetcher: ON CONFLICT (agency, source_id) DO UPDATE.
    CONSTRAINT recalls_agency_source_id_key UNIQUE (agency, source_id)
);

-- Default listing order: newest first. NULLS LAST matches the API's ORDER BY
-- so the index covers the common /recalls query without a sort step.
CREATE INDEX IF NOT EXISTS recalls_recall_date_idx
    ON recalls (recall_date DESC NULLS LAST);

CREATE INDEX IF NOT EXISTS recalls_agency_idx
    ON recalls (agency);

-- Serves /recalls?agency=…&since=…&until=… , which filters and sorts together.
CREATE INDEX IF NOT EXISTS recalls_agency_recall_date_idx
    ON recalls (agency, recall_date DESC NULLS LAST);

-- Full-text search over product + brand + hazard.
CREATE INDEX IF NOT EXISTS recalls_search_tsv_idx
    ON recalls USING GIN (search_tsv);
