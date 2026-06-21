-- Runs automatically on first container start (mounted into /docker-entrypoint-initdb.d).
-- Must run before any table with a `vector` column is created.
CREATE EXTENSION IF NOT EXISTS vector;

-- The semantic cache: one prompt/response pair per row, plus its 384-dim embedding
-- (matches all-MiniLM-L6-v2 / bge-small-en-v1.5; see config.py / DECISIONS D11).
-- The app supplies id + created_at explicitly; the defaults below only cover ad-hoc SQL.
-- prompt_hash is the normalized-prompt SHA-256 (hex); UNIQUE collapses identical strings so
-- exact_lookup is a clean point-query, and store upserts rather than accumulating duplicates (D21).
CREATE TABLE IF NOT EXISTS cache_entries (
    id          uuid        PRIMARY KEY DEFAULT gen_random_uuid(),
    prompt      text        NOT NULL,
    prompt_hash text        NOT NULL UNIQUE,
    response    text        NOT NULL,
    model_used  text        NOT NULL,
    embedding   vector(384) NOT NULL,
    created_at  timestamptz NOT NULL DEFAULT now()
);

-- HNSW with the cosine opclass to match the `<=>` operator used in lookups (DECISIONS D3).
CREATE INDEX IF NOT EXISTS cache_entries_embedding_hnsw
    ON cache_entries USING hnsw (embedding vector_cosine_ops);

-- The intent cache: stores parameter-stripped (canonical) prompts + the extracted parameters
-- that were present when the answer was generated. Used by the intent tier and its gate (D27).
-- Separate from cache_entries: different match key (stripped vector), different lifecycle (long TTL).
CREATE TABLE IF NOT EXISTS intent_entries (
    id               uuid        PRIMARY KEY DEFAULT gen_random_uuid(),
    canonical_prompt text        NOT NULL,
    response         text        NOT NULL,
    model_used       text        NOT NULL,
    embedding        vector(384) NOT NULL,
    parameters       text[]      NOT NULL DEFAULT '{}',
    created_at       timestamptz NOT NULL DEFAULT now()
);

-- HNSW cosine index for the stripped-prompt vectors (same opclass as cache_entries, D3).
CREATE INDEX IF NOT EXISTS intent_entries_embedding_hnsw
    ON intent_entries USING hnsw (embedding vector_cosine_ops);
