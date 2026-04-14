-- ============================================================
-- CDS — PostgreSQL Initialization
-- Enables required extensions on both databases.
-- The databases themselves are created by Docker via POSTGRES_DB env var.
-- ============================================================

-- Identity service database extensions
\c cds_identity;
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
CREATE EXTENSION IF NOT EXISTS "pg_trgm";
CREATE EXTENSION IF NOT EXISTS "btree_gin";
