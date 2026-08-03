-- Postgres + pgvector DDL for ProjectMemory V2 (knowledge graph + vector store)
-- Requirements: PostgreSQL >= 14, pgvector extension installed
-- Usage: psql $DATABASE_URL -f postgres_pgvector_ddl.sql

CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- Nodes table: primary documents/facts/concepts/code snippets
CREATE TABLE IF NOT EXISTS kg_nodes (
  id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  node_type TEXT NOT NULL,
  text TEXT,
  embedding vector(1536), -- adjust dim as needed
  metadata JSONB DEFAULT '{}',
  session_id TEXT,
  source TEXT,
  created_at TIMESTAMPTZ DEFAULT now(),
  updated_at TIMESTAMPTZ DEFAULT now()
);

-- Edges table: directed relationships between nodes
CREATE TABLE IF NOT EXISTS kg_edges (
  id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  source_id UUID REFERENCES kg_nodes(id) ON DELETE CASCADE,
  target_id UUID REFERENCES kg_nodes(id) ON DELETE CASCADE,
  rel_type TEXT NOT NULL,
  weight FLOAT DEFAULT 1.0,
  metadata JSONB DEFAULT '{}',
  created_at TIMESTAMPTZ DEFAULT now()
);

-- Indexes
CREATE INDEX IF NOT EXISTS idx_kg_nodes_session ON kg_nodes(session_id);
CREATE INDEX IF NOT EXISTS idx_kg_nodes_source ON kg_nodes(source);
CREATE INDEX IF NOT EXISTS idx_kg_nodes_metadata ON kg_nodes USING GIN (metadata);

-- Full-text search using tsvector on text column
ALTER TABLE kg_nodes ADD COLUMN IF NOT EXISTS text_tsv tsvector;
UPDATE kg_nodes SET text_tsv = to_tsvector('english', coalesce(text,''));
CREATE INDEX IF NOT EXISTS idx_kg_nodes_text_tsv ON kg_nodes USING GIN (text_tsv);

-- Trigger to maintain text_tsv
CREATE OR REPLACE FUNCTION kg_nodes_tsv_trigger() RETURNS trigger AS $$
begin
  new.text_tsv := to_tsvector('english', coalesce(new.text,''));
  return new;
end
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS tsvectorupdate ON kg_nodes;
CREATE TRIGGER tsvectorupdate BEFORE INSERT OR UPDATE ON kg_nodes
  FOR EACH ROW EXECUTE PROCEDURE kg_nodes_tsv_trigger();

-- pgvector index (ANN)
-- Adjust "lists" based on dataset size; 100 is a reasonable starter for smaller datasets
DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM pg_class WHERE relname = 'idx_kg_nodes_embedding_ivfflat'
  ) THEN
    EXECUTE 'CREATE INDEX idx_kg_nodes_embedding_ivfflat ON kg_nodes USING ivfflat (embedding vector_l2_ops) WITH (lists = 100)';
  END IF;
END$$;

-- Utility view
CREATE OR REPLACE VIEW kg_node_summary AS
SELECT id, node_type, coalesce(metadata->>'legacy_key','') as legacy_key, session_id, source, created_at FROM kg_nodes;
