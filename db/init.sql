-- Runs automatically on first container start (mounted into /docker-entrypoint-initdb.d).
-- Must run before any table with a `vector` column is created.
CREATE EXTENSION IF NOT EXISTS vector;

-- The semantic cache: one prompt/response pair per row, plus its 384-dim embedding
-- (matches all-MiniLM-L6-v2 / bge-small-en-v1.5; see config.py / DECISIONS D11).
-- The app supplies id + created_at explicitly; the defaults below only cover ad-hoc SQL.
CREATE TABLE IF NOT EXISTS cache_entries (
    id          uuid        PRIMARY KEY DEFAULT gen_random_uuid(),
    prompt      text        NOT NULL,
    response    text        NOT NULL,
    model_used  text        NOT NULL,
    embedding   vector(384) NOT NULL,
    created_at  timestamptz NOT NULL DEFAULT now()
);

-- HNSW with the cosine opclass to match the `<=>` operator used in lookups (DECISIONS D3).
CREATE INDEX IF NOT EXISTS cache_entries_embedding_hnsw
    ON cache_entries USING hnsw (embedding vector_cosine_ops);
