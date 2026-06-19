-- Runs automatically on first container start (mounted into /docker-entrypoint-initdb.d).
-- Must run before any table with a `vector` column is created.
CREATE EXTENSION IF NOT EXISTS vector;
