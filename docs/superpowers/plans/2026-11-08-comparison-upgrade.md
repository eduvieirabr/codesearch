# codeSearch Comparison Upgrade Implementation Plan

> Use parallel domain workers with explicit ownership, then independent whole-project review. Execution is authorized by the user's request to incorporate improvements.

**Goal:** Improve local MCP retrieval, context, structure and freshness using verified comparison findings.
**Architecture:** Existing FastMCP service consumes atomic SQLite snapshots; rich parsers and a pure snapshot dependency layer feed bounded tools.
**Tech Stack:** Python, official tree-sitter wheels, stdlib AST/TOML, SQLite, regex timeout engine, pytest, Ruff, Podman.
**Spec:** ../specs/2026-11-08-comparison-upgrade-design.md

## Global constraints
Maintain all current tools and legacy keys. No source writes or upstream code copying. One offline workspace. Admission policy and directory-handle confinement remain mandatory. New metadata has defaults and existing SQLite data upgrades without removal.

## Review focus
- Same-line symbol collisions and line shifts must not return the wrong source.
- Filters precede pagination; exact names beat summary coincidences.
- Every response budget covers serialized overhead; continuation/omission is explicit.
- Graph ambiguity, dynamic imports and partial coverage must not appear as certainty.
- Cache reuse cannot bypass changed ignore rules, link checks, parser upgrades or cross-client revisions.

## Task 1 — parser/import correctness (worker)
Own parser.py, imports.py, grammars.py, new parsing helpers and tests/test_rich_parser.py.
Write failing behavior tests, implement additive schema/AST imports/ranges/Bash/TOML, verify original parser/import suite. Produce PARSER_REVISION constant for store invalidation.

## Task 2 — persistent incremental snapshots (worker)
Own workspace.py, safeio.py, store.py and tests/test_incremental_v2.py.
Test no source rereads on unchanged scans, forced verification, ignore changes, identity races, persistent diagnostics, parser upgrade and concurrent-client changes within interval. Implement snapshot/latest_changes APIs and counters; preserve current public methods.

## Task 3 — relationships (worker)
Own relationships.py and tests/test_relationships.py.
Implement pure admitted-record resolution, deterministic bounded graph traversal, reverse importers, impact, SCC cycles and conservative symbol call/class candidates. Test cycles, aliases, ambiguity, external/dynamic boundaries and caps.

## Task 4 — search/context/MCP integration (root)
Own service.py, indexer.py, server.py, CLI/version/dependencies, new integration tests.
Implement deterministic exact-first ranking and filters; real regex timeout and contextual grep; stable-ID batch source; serialized-budget bundles/task context; register graph/status tools. Pin one snapshot per request, including nested composition. Test every new MCP tool and keep prior contracts.

## Task 5 — comparison report, validation and runtime (root)
Write evidence-based feature matrix in Portuguese, update README/tool reference and contributor guide, migrate v0.1 cache without deleting user data, lock dependencies. Run Windows and offline Linux suites, lint, budget/ranking regressions, HTTP+stdio checks. Get fresh final review; fix material findings with regression tests. Rebuild and replace only owned codesearch-local on 8091 after verification.
