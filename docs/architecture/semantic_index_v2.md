# Semantic Index v2 — design

Purpose
- Provide offline, incremental, cross-file semantic indexing for code (symbols, references, and semantic search).
- Integrate with existing MCP tools (search_workspace, find_symbol, get_file_outline) and expose new MCP tools: semantic_search, get_symbol_graph, index_status.

Goals
- Offline operation (no external APIs required).
- Incremental updates: file-hash or mtime-driven delta indexing.
- Cross-file symbol graph (definitions ↔ references).
- Support Kotlin/Java/Python initially; TS/JS as add-on.

High-level architecture
- Ingest: workspace scanner or file-watcher producing file list + content_hash.
- Parse & extract: language-specific parsers (Tree-sitter preferred) → produce symbols (id, fq_name, kind, language, file_path, start_line, end_line, signature, snippet).
- Graph builder: create symbol nodes + edges (reference/calls/implements/extends).
- Full-text index: SQLite FTS5 (file_path, content) for fast grep-like searches.
- Optional vector store: on-disk HNSW (hnswlib) for semantic embeddings (offline embeddings optional).
- Storage: single SQLite DB under store/semantic_index_v2/index.db with tables: files, symbols, references, ft (FTS5), embeddings(optional).

Minimal schema (example)
- files(file_id INTEGER PRIMARY KEY, path TEXT UNIQUE, mtime INTEGER, hash TEXT)
- symbols(symbol_id INTEGER PRIMARY KEY, name TEXT, fq_name TEXT, kind TEXT, language TEXT, file_path TEXT, start_line INTEGER, end_line INTEGER, signature TEXT)
- references(from_symbol INTEGER, to_symbol INTEGER, rel TEXT, file_path TEXT, line INTEGER)
- CREATE VIRTUAL TABLE ft USING fts5(path, content);

Incremental indexing algorithm
1. Scan workspace, compute file hash (sha256).
2. For each file where hash != stored_hash:
   - Parse, extract symbols and references.
   - Begin transaction: delete old symbols for file, insert new symbols, update references, update files row, update FT entry.
   - Commit.
3. Optionally run background graph normalization (resolve fq_names → symbol_ids).

MCP tool additions (APIs)
- semantic_search(query: str, k:int=10, language:Optional[str]=None) -> list[SymbolMatch]
- get_symbol_graph(fq_name: str, depth:int=2) -> graph JSON
- index_workspace(scan_full:bool=False) -> status
- Backwards-compatible: have search_workspace consult semantic index first, fallback to grep if disabled.

Integration & migration
- Reuse get_file_outline and find_symbol as parser adapters (see tools/code.py).
- Start by indexing Kotlin (align with existing default file_glob='*.kt'), then add Java and Python.

Verification
- Unit: tests/test_semantic_index.py should assert symbol insertion, cross-file ref resolution, incremental update on file change.
- Integration: start server and compare semantic_search vs search_workspace outputs.
- Targeted pytest: pytest tests/test_code.py::test_search_workspace_finds_matches

Roadmap (30-day high-level)
- Week 1: SQLite schema + index writer + unit tests.
- Week 2: Kotlin parser adapter (Tree-sitter) + integrate get_file_outline.
- Week 3: Incremental watcher + MCP tool wrappers (semantic_search).
- Week 4: Regression tests, benchmarks, optional vector-store PoC.

Notes
- Keep on-disk index ACID-safe (SQLite). Prefer FTS5 for full-text and an optional HNSW vector index for semantic similarity.
- Keep label cardinality low in any indexing metadata to avoid high-cardinality query issues.