# codeSearch 0.2 — comparison-driven improvements

## Intent and evidence
User requested reading C:/git/pessoal/jcodemunch-mcp-main, identifying capabilities absent or better there, and incorporating improvements into C:/git/pessoal/codeSearch. The local reference is version 1.108.426. Its tools, parser and storage were inspected independently in three domains. No upstream source/tests will be copied; equivalent behavior is implemented in this product.

## Chosen approach
Extend the existing offline, single-workspace, read-only Python/FastMCP product. Keep all 15 current tools and legacy keyword/output fields. Alternatives were importing the upstream package wholesale (different license, transport and product boundary) or pursuing every advertised feature (compiler/LSP/cloud/multi-repo prerequisites). Prioritize verified correctness, context efficiency and local structural analysis.

## Deliverables
1. Rich symbols with additive language, qualified_name, parent, decorators, docstring, bases, calls, start_byte/end_byte, source_start_line and collision-safe stable symbol_id. Preserve legacy id=file:line and nested-function omission; ambiguous legacy IDs are errors. Improve Python async/docstrings, TS/Java declarations, source ranges for structured text, and Python/JS import correctness. Preserve legacy three-key imports; use detailed records internally. Add Bash function extraction and TOML tables/keys.
2. Exact identifier ranking ahead of lexical approximations, deterministic ties, filters for language/path/decorator applied before pagination. Query results disclose match type and index coverage.
3. Contextual literal/regex grep with optional case sensitivity, enclosing symbol, bounded aggregate output and real regex timeouts. FTS retains ranked-word semantics and gains filters.
4. get_symbol_source supports ordered batches and partial errors using stable IDs. get_context_bundle and assemble_task_context assemble source-attributed responses under a serialized character budget. No claims of exact token counts or AI task understanding.
5. Cached per-generation dependency analysis from admitted detailed imports. New find_importers, get_dependency_graph, get_blast_radius and get_dependency_cycles. Resolve Python roots '.' and 'src', relative imports and JS/TS relative imports. Extract Bash literal sources but report runtime_context without edges because execution CWD/PATH are unknown. Preserve unsupported/external/dynamic/ambiguous boundaries; no fake edges or safety-to-delete verdicts.
6. get_call_hierarchy and get_class_hierarchy expose conservative static candidates from syntactic call/base observations, with explicit unresolved/ambiguous evidence and no compiler-resolution claim. get_repo_outline summarizes directories. get_index_changes reports the last meaningful index change, not Git history.
7. Metadata-based content reuse with dev/ino/size/mtime_ns/ctime_ns and same-handle before/after read verification, while rerunning admission and securely reading ignores each scan. Force performs full verification/reparse. Non-destructive DB migration and parser-generation rebuild; persistent diagnostics, coverage and change summary. Persistent revision polling even within scan interval, with transactional snapshot reads.
8. Every composed tool pins one snapshot for source/coordinates/graph consistency. Maintain current read-only, symlink/junction confinement, secret filename exclusions and response caps.

## Boundaries
No copying upstream proprietary code, automatic source edits, semantic-model downloads, cloud summarization, IDE extension, multiple workspaces per process, Git-history queries, compiler/LSP/SCIP integration or unqualified absence/dead-code claims. The comparison report records these differences openly.

## Validation and deployment
Behavioral regression tests before changes, original suite retained, actual MCP tool/schema calls, deterministic ranking and budget checks, metadata-read counters, concurrent-client freshness, migration from v0.1 cache, Linux Podman suite without network, and real HTTP+stdio smoke. Upgrade the existing owned codesearch-local container on 8091 only after the new image passes; preserve its workspace/data volume. Other services remain untouched.

## Interfaces
- SymbolInfo adds defaults for qualified_name:str, language:str, parent:str|None, decorators:list[str], docstring:str, bases:list[str], calls:list[str], start_byte:int, end_byte:int, source_start_line:int, symbol_id:str.
- extract_imports(path, language) stays legacy; extract_import_details(path, language) returns legacy fields plus local_name/imported_name/line/dynamic where known.
- IndexStore.snapshot() -> dict with generation:int, report:dict, files:list[dict], changes:dict; immutable-by-convention JSON-shaped data from one DB read transaction. Files include detailed imports and rich symbol dicts.
- IndexStore.latest_changes() -> bounded persisted change report.
- DependencyAnalysis(files:list[dict]) owns graph queries; no filesystem reads.
- Root implements service/search/context integration; parser, store and relationships modules have distinct owners.
