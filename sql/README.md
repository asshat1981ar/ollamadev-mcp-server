This directory contains SQL DDL and migration helpers for ProjectMemory V2 (Postgres + pgvector).

Files:
- postgres_pgvector_ddl.sql : DDL to create kg_nodes, kg_edges, indexes, and pgvector index.

Usage:
1. Ensure Postgres has pgvector extension installed (apt/packaging or `CREATE EXTENSION vector`).
2. Apply the DDL: psql $DATABASE_URL -f sql/postgres_pgvector_ddl.sql
3. Run the migration script to import existing file-based memories.
