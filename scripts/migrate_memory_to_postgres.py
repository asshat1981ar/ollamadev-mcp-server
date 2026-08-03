#!/usr/bin/env python3
"""Migration script: import store/agent_memory.json into Postgres kg_nodes table.

Usage:
  DATABASE_URL=postgresql://user:pass@host:5432/db python scripts/migrate_memory_to_postgres.py

Notes:
- Requires psycopg2-binary: pip install psycopg2-binary
- DDL should be applied first (sql/postgres_pgvector_ddl.sql)
- Embeddings are left NULL; run embedding job separately to populate embedding column.
"""
import json
import os
import sys
from pathlib import Path
from typing import Any

try:
    import psycopg2
    from psycopg2.extras import Json
except Exception as exc:
    print('Missing dependency: psycopg2. Install via `pip install psycopg2-binary`')
    raise

STORE_PATH = Path(os.environ.get('WORKSPACE_ROOT', '.')) / 'store' / 'agent_memory.json'


def load_v1(path: Path) -> dict:
    if not path.exists():
        print('No legacy memory file found at', path)
        return {}
    return json.loads(path.read_text(encoding='utf-8'))


def upsert_node(conn, node_type: str, text: str, metadata: dict, session_id: str | None = None, source: str | None = None):
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO kg_nodes (node_type, text, metadata, session_id, source)
            VALUES (%s, %s, %s, %s, %s)
            RETURNING id
            """,
            (node_type, text, Json(metadata), session_id, source),
        )
        nid = cur.fetchone()[0]
        return nid


def main():
    database_url = os.environ.get('DATABASE_URL')
    if not database_url:
        print('Please set DATABASE_URL env var (e.g. postgresql://user:pass@host:5432/db)')
        sys.exit(2)

    v1 = load_v1(STORE_PATH)
    if not v1:
        print('No memories to migrate.')
        return

    conn = psycopg2.connect(database_url)
    conn.autocommit = False
    try:
        migrated = 0
        for k, v in v1.items():
            # Store each key as a Fact node with legacy_key metadata
            metadata = {'legacy_key': k}
            text = v if isinstance(v, str) else json.dumps(v)
            nid = upsert_node(conn, 'Fact', text, metadata, session_id=None, source='v1_json')
            migrated += 1
        conn.commit()
        print(f'Migrated {migrated} memory entries into kg_nodes')
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


if __name__ == '__main__':
    main()
