# codeSearch Local — Design

## Intent
Create a standalone local MCP code intelligence service in C:/git/pessoal/codeSearch, reusing the SDA parsers, import extraction, BM25 ranking, and regression fixtures. The user authorizes implementation and delegates additional useful tools. The original repository stays unchanged.

## Approach
Use Python 3.11+ (Python 3.13 container), current compatible FastMCP and individual official tree-sitter grammar wheels, SQLite persistence, and Podman. Alternatives: a minimal in-memory fork loses indexes on restart; an embeddings/vector service adds model downloads and hardware requirements. The chosen architecture runs offline after installation, needs no model or API token, and supplies lexical and structural search.

## Product boundary
One configured workspace per process/container. MCP cannot select arbitrary host folders. Accept local, '.', workspace name, and the configured absolute root as repo aliases. index_repo(url) is a compatibility alias for refreshing this workspace, rejects remote URLs and unrelated roots. The developer chooses the folder at startup; mounting a parent folder includes its permitted descendants.

## Capabilities
Preserve index_repo, get_file_tree, get_file_outline, search_symbols, get_file_content, find_file, grep_content, find_references, get_file_imports names and existing output keys. Repo parameters become optional with local default; preserve legacy keyword argument names. Add index_directory, refresh_index, get_index_status, get_project_summary, search_text (SQLite FTS5 ranked matches), get_symbol_context (symbol plus bounded source). MCP resource codesearch://summary and a project exploration prompt help clients discover usage.

## Index and isolation
Read the folder directly, including uncommitted changes. Store file content, metadata, imports and symbols in SQLite outside the indexed workspace where possible. Each database is bound to a canonical workspace and schema version; a mismatched root fails clearly. Incremental scans use mtime/size then content hashes, transactionally update changed files and delete missing/ignored entries. Recheck on calls at a configurable interval (default two seconds); explicit refresh always scans. Serialize operations per process; SQLite busy timeout handles multiple sessions.

Honor root and nested .gitignore plus .codesearchignore without calling Git. Always exclude .git, dependency/build/cache folders, .env files except .env.example, private key files, binary/oversized files, and symlinks/junctions. All tools operate on the same admitted snapshot; direct content/outline/import requests cannot bypass exclusions. Max file size 1 MiB, configurable; max files 50,000 with explicit incomplete-index reporting. Pagination and content caps keep responses bounded. Source files never execute.

## Parsing
Retain nine existing language families, fix TSX grammar selection and JS/TS arrow functions, add Rust symbol extraction. Tree-sitter grammars are installed with the package (no runtime downloads). Preserve existing import behavior, improve Python via ast and JS multiline/alias parsing as useful. References remain textual identifier matches, not compiler-resolved references. Parse failures become bounded diagnostics while text search remains available.

## Runtime
CLI: codesearch --workspace PATH --data-dir PATH --transport stdio|http --host HOST --port PORT. Defaults: stdio and localhost; container entrypoint uses HTTP, 0.0.0.0:8090, mapped only to host 127.0.0.1. Source bind mount read-only; separate named volume for SQLite; non-root container; read-only root filesystem and no-new-privileges. Shell/PowerShell launchers support HTTP and stdio; stdio has no TTY/banner on stdout. Never automatically replace an existing container. Health endpoint reports service availability; status tool reports index state.

## Verification
Reuse original parser/import/indexer tests. Add tests for incremental changes/deletions/restarts, nested ignore precedence, glob root files, binary/large files, symlink traversal, invalid aliases, empty/invalid queries, pagination correctness, secret exclusions, concurrent calls, actual FastMCP client tools/resources/prompts, CLI stdio and HTTP, and real Podman smoke where available. Add Ruff, pinned uv lock, Portuguese README and client JSON/TOML examples.

## Decisions delegated to implementer
Exact module layout, pagination shape (retain existing keys), useful bounded defaults, grammar versions resolving on local Python, launcher fallback when Podman is absent on Windows but available in WSL. No publishing, remote services, or committing original-repository changes.
