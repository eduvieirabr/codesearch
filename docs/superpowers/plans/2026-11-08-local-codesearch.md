# codeSearch Local Implementation Plan

> **For agentic workers:** Use superpowers:executing-plans to implement this plan task-by-task. The user authorized creation of the product; implement directly and verify the complete result.

**Goal:** Ship a local, read-only MCP code search service runnable with Podman.
**Architecture:** A bounded filesystem scanner feeds an incremental SQLite snapshot; reused parsing and BM25 components support a service layer exposed through FastMCP.
**Tech Stack:** Python, FastMCP, official tree-sitter grammars, SQLite FTS5, pathspec, pytest, Ruff, uv, Podman.
**Spec:** ../specs/2026-11-08-local-codesearch-design.md

## Global Constraints

- Work only in C:/git/pessoal/codeSearch; reuse selected source/fixtures without modifying the original repository.
- One workspace per container; source read-only; no runtime model downloads or cloud credentials.
- Preserve all nine existing tool names and keyword arguments/output keys.
- Python 3.11+ locally; Python 3.13 container; pinned uv.lock.
- Max file size 1 MiB, max 50,000 files, default scan interval two seconds.

## Review Focus

1. Ignored files, traversal, Windows junctions and symlinks must never bypass the scanner through other tools.
2. Deleted/changed files and changed ignore rules must invalidate persisted results, including after restart.
3. Empty/invalid query, pagination at exact limits, long lines and root-level globs must remain bounded and correct.
4. SQLite workspace identity, concurrent MCP calls and partial filesystem errors must not silently corrupt the index.
5. Container transports, writable data volume, read-only workspace and Windows/WSL paths must work together.

### Task 1: Modern parsing with retained behavior

**Files:** pyproject.toml, src/codesearch/{__init__,parser,imports,indexer,grammars}.py, tests/test_{parser,imports,indexer}.py, tests/fixtures/.
**Interfaces:** extract_symbols(path, language, filepath) -> list[SymbolInfo]; extract_imports(path, language) -> list[dict]; CodeIndex(symbols).search(query, limit, kind).
- [x] Copy regression tests and add TSX, Rust, arrow-function and UTF-8 cases; observe failures before migration.
- [x] Reuse existing components, replace obsolete tree-sitter bundle with official wheels, add end_line and missing language constructs.
- [x] Run parser/import/indexer tests; expected all pass.

### Task 2: Workspace scanning and persistent incremental index

**Files:** src/codesearch/workspace.py, src/codesearch/store.py, tests/test_workspace.py, tests/test_store.py.
**Interfaces:** Workspace(root, data_dir, max_file_bytes, max_files); scan() -> admitted files and diagnostics; IndexStore(workspace).refresh(force=False) -> counts; snapshot() -> file records; close().
- [x] Write tests for ignore rules, forbidden files, traversal/symlink refusal, size limits, changed/deleted files, restart persistence and database identity; observe failures.
- [x] Implement safe scanning, per-directory ignore inheritance, transactional SQLite file records and FTS5 search; serialize refresh and queries.
- [x] Run workspace/store and retained regression tests; expected all pass.

### Task 3: MCP tools and CLI

**Files:** src/codesearch/{service,server,__main__}.py, tests/test_service.py, tests/test_mcp.py, tests/test_cli.py.
**Interfaces:** CodeSearchService(workspace, data_dir, scan_interval); create_server(service) -> FastMCP; codesearch CLI.
- [x] Test all nine compatibility tools plus six additions, shared exclusion policy, pagination and query validation; observe failures.
- [x] Implement tools, typed parameters, bounded results, resource, prompt, health route, and CLI stdio/HTTP.
- [x] Verify in-process MCP calls and a spawned stdio server. Expected 15 tools, one summary resource, one prompt, successful search and refusal of excluded files.

### Task 4: Podman distribution and user documentation

**Files:** Containerfile, .containerignore, scripts/run.ps1, scripts/run.sh, scripts/smoke.py, examples/, README.md, AGENTS.md, uv.lock.
- [x] Build locked environment; run full pytest and Ruff checks.
- [x] Implement HTTP/stdio launchers with read-only source bind mount, dedicated data volume, localhost publishing and non-root process.
- [x] Document Windows, WSL and Linux setup, client config, tools, limits and migration.
- [x] Build image with Podman, run health and MCP smoke against a small mounted fixture, verify incremental changes and source mount read-only. Report any environmental blocker precisely.
- [x] Request fresh whole-project review; fix important findings with regression tests; repeat affected checks and full suite.

## Execution Record

Implementation has been authorized by the user. This is a new empty target directory, so no worktree or branch operation is required. Source repository AGENTS.md stays untouched. No automatic commit or publication is planned.
