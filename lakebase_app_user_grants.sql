-- Run this against Lakebase yourself (psql, or Databricks' SQL editor) whenever
-- you're ready — mirrors the local `app_user` role this session created and
-- tested (tests/test_least_privilege.py). Not run automatically by anything.
--
-- Assumes app_user already exists (you created it earlier). If your Lakebase
-- role setup differs, adjust the role name below to match.

GRANT CONNECT ON DATABASE databricks_postgres TO app_user;
GRANT USAGE ON SCHEMA public TO app_user;
GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO app_user;
GRANT USAGE ON ALL SEQUENCES IN SCHEMA public TO app_user;
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO app_user;

-- Deliberately NOT granted: CREATE, DROP, ALTER, TRUNCATE, or anything on
-- pg_catalog/information_schema beyond the default. Schema changes (running
-- init_db(), adding the new HNSW index / CHECK constraints from this session)
-- should keep using your own owner-level credentials, not app_user — same
-- separation this session set up and tested locally: migrations run as owner,
-- the app runs as app_user.

-- New in this pass (run these too if the schema was created before today):
CREATE INDEX IF NOT EXISTS ix_papers_embedding_hnsw ON papers USING hnsw (embedding vector_cosine_ops);

ALTER TABLE collections DROP CONSTRAINT IF EXISTS ck_collection_name_length;
ALTER TABLE collections ADD CONSTRAINT ck_collection_name_length CHECK (char_length(name) <= 300);
ALTER TABLE collections DROP CONSTRAINT IF EXISTS ck_collection_description_length;
ALTER TABLE collections ADD CONSTRAINT ck_collection_description_length CHECK (description is null or char_length(description) <= 5000);
ALTER TABLE notes DROP CONSTRAINT IF EXISTS ck_notes_content_length;
ALTER TABLE notes ADD CONSTRAINT ck_notes_content_length CHECK (char_length(content) <= 20000);

ALTER TABLE reading_progress ADD COLUMN IF NOT EXISTS progress_pct INTEGER NOT NULL DEFAULT 0;
ALTER TABLE reading_progress DROP CONSTRAINT IF EXISTS ck_progress_pct_range;
ALTER TABLE reading_progress ADD CONSTRAINT ck_progress_pct_range CHECK (progress_pct >= 0 and progress_pct <= 100);
