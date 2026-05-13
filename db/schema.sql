-- Supabase / PostgreSQL schema for the Incorporation Intelligence Engine
-- Run this migration against your Supabase project via the SQL editor or psql.

-- ─────────────────────────────────────────────────────────────────────────────
-- canonical_entities
-- Deduplicated master entity records.  One row per real-world company.
-- Must be created before companies because companies holds a FK to this table.
-- ─────────────────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS canonical_entities (
    id              BIGSERIAL PRIMARY KEY,
    canonical_name  TEXT        NOT NULL,
    jurisdictions   TEXT[]      NOT NULL DEFAULT '{}',  -- all jurisdictions seen
    first_seen      DATE,
    last_seen       DATE,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_canonical_entities_canonical_name ON canonical_entities (canonical_name);

-- ─────────────────────────────────────────────────────────────────────────────
-- companies
-- Raw, normalised company records from all ingestion sources.
-- ─────────────────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS companies (
    id                  BIGSERIAL PRIMARY KEY,

    -- Identity
    company_name        TEXT        NOT NULL,
    normalized_name     TEXT        NOT NULL,
    jurisdiction        TEXT        NOT NULL,          -- 'UK', 'DIFC', 'Mauritius'
    entity_type         TEXT,                          -- 'Ltd', 'GBC', 'Authorised Company', …
    incorporation_date  DATE,

    -- Classification
    sector              TEXT,                          -- human-readable sector description
    assigned_to         TEXT,                          -- downstream CRM assignee (optional)

    -- Scoring
    score               NUMERIC(5, 2),                 -- 0–100

    -- Source provenance
    source              TEXT        NOT NULL,          -- connector identifier
    raw_data            JSONB       NOT NULL DEFAULT '{}',

    -- Deduplication
    canonical_entity_id BIGINT      REFERENCES canonical_entities(id) ON DELETE SET NULL,

    -- Audit
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_companies_normalized_name      ON companies (normalized_name);
CREATE INDEX IF NOT EXISTS idx_companies_jurisdiction         ON companies (jurisdiction);
CREATE INDEX IF NOT EXISTS idx_companies_incorporation_date   ON companies (incorporation_date);
CREATE INDEX IF NOT EXISTS idx_companies_canonical_entity_id  ON companies (canonical_entity_id);
CREATE INDEX IF NOT EXISTS idx_companies_score                ON companies (score);

-- ─────────────────────────────────────────────────────────────────────────────
-- Auto-update updated_at via trigger
-- ─────────────────────────────────────────────────────────────────────────────
CREATE OR REPLACE FUNCTION update_updated_at_column()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_trigger WHERE tgname = 'trg_companies_updated_at'
    ) THEN
        CREATE TRIGGER trg_companies_updated_at
        BEFORE UPDATE ON companies
        FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();
    END IF;

    IF NOT EXISTS (
        SELECT 1 FROM pg_trigger WHERE tgname = 'trg_canonical_entities_updated_at'
    ) THEN
        CREATE TRIGGER trg_canonical_entities_updated_at
        BEFORE UPDATE ON canonical_entities
        FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();
    END IF;
END
$$;
