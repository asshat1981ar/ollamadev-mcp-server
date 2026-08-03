# Intelligence gap analysis — current → desired

## Current state (evidence)
- Grep-based search tool present: code.py _search_files / search_workspace (ollamadev_mcp_server/tools/code.py:35,48-49,59-60).
- Tools are registered and exposed via MCP (registry.register_module("code", ...) — ollamadev_mcp_server/registry.py:183).
- Tests exist for search behavior (tests/test_code.py:41-55).
- Build/helpers for Gradle/pytest present (tools/build.py:272-296).
- Repo contains Python code (server + tools); no Kotlin/Java/TypeScript sources present in workspace.

## Gaps
1. No persistent semantic symbol graph or index (search is grep-first; no symbol graph table found).
2. No vector/embedding pipeline or vector store for semantic similarity.
3. Symbol parsing/resolution per-language is partial (get_file_outline exists for Kotlin signatures, but cross-file resolution needs a symbol graph).
4. No TypeScript/JS support detected in workspace (no .ts/.js files); no TS-specific parsing tool present.
5. No automated incremental indexer / watcher component visible.

## Recommendations (prioritized)
1. Implement on-disk SQLite index with FTS5 + symbols & references tables; integrate with existing MCP tools (semantic_search tool). Priority: high.
2. Add language parser adapters (Tree-sitter bindings) for Kotlin/Java/Python. Priority: high.
3. Add incremental indexer (file-hash based) and tests. Priority: high.
4. Optional: local embedding pipeline + HNSWlib (for richer semantic search). Priority: medium.
5. Add integration tests that compare grep-based search vs semantic search results. Priority: medium.

## Verification
- Unit tests: tests/test_semantic_index.py
- Integration: start server and call MCP semantic_search, compare with search_workspace.
- Targeted pytest: pytest tests/test_code.py::test_search_workspace_finds_matches

## 30-day plan
- Week 1: SQLite schema + index writer + unit tests.
- Week 2: Kotlin parser adapter (Tree-sitter) + integrate get_file_outline.
- Week 3: Incremental watcher + MCP tool wrappers (semantic_search).
- Week 4: Regression tests & benchmarks; optional vector store PoC.

## Notes
- Favor SQLite FTS5 for text search and HNSWlib for vector similarity if embeddings are added.
- Keep on-disk indexes ACID-safe and preserve low-cardinality labels in indexing metadata.