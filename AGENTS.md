# Repository Guidelines

## Structure
Source lives in src/codesearch/. workspace.py/safeio.py admit files; store.py owns SQLite; service.py/retrieval.py implement snapshot-based tools and response budgets; relationships.py resolves static candidates; server.py exposes MCP. parser.py, imports.py and indexer.py handle syntax and ranking. Tests and fixtures live in tests/. scripts/ contains Podman launchers and smoke checks; docs/ records decisions and comparisons.

## Commands
Use uv sync --frozen, uv run pytest -q, uv run ruff check src tests scripts, and uv run ruff format --check src tests scripts. Start locally with uv run codesearch --workspace PATH --transport http. Build/run with scripts/run.ps1 -Workspace PATH -Build or bash scripts/run.sh PATH http --build.

## Conventions
Use Python 3.11-compatible syntax, four spaces, type annotations at public interfaces, snake_case functions and PascalCase classes. Ruff owns formatting/import order. Keep MCP wrappers thin and filesystem policy centralized.

## Tests
Use pytest and pytest-asyncio. Name files test_*.py and use temporary workspaces. Cover changed tools, incremental invalidation, response bounds and exclusions. Test actual FastMCP clients for protocol changes. Tests must not access private repositories or user credentials.

## Safety and Compatibility
Source workspaces are read-only. Never execute indexed source or accept arbitrary host paths from MCP. All reads must use the admitted snapshot. Preserve existing tool names and keyword parameters. Keep budgets, coverage and unresolved evidence explicit. Increment PARSER_REVISION when extraction changes. Do not remove secret exclusions or symlink refusal to fix a test. Update uv.lock and verify the Podman build when dependencies change.

## Contributions
Use focused feat:, fix:, docs:, or test: commits. PRs should explain behavior changes and report test commands/results. Update README when CLI, schemas or container behavior changes. Do not publish or assign a third-party license without project-owner authorization.
