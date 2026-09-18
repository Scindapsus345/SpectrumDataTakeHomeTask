CREATE EXTENSION IF NOT EXISTS pg_trgm;

CREATE TABLE IF NOT EXISTS pages (
    url TEXT PRIMARY KEY,
    title TEXT,
    html TEXT NOT NULL,
    fetched_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS pages_url_trgm_idx
    ON pages USING GIN (url gin_trgm_ops);
CREATE INDEX IF NOT EXISTS pages_title_trgm_idx
    ON pages USING GIN (title gin_trgm_ops);
