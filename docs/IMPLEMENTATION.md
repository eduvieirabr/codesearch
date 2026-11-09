# Implementation record — version 0.1

Historical record of the initial product. For the comparison-driven 0.2 update and current validation, see [UPGRADE.md](UPGRADE.md).

Plan: docs/superpowers/plans/2026-11-08-local-codesearch.md

- Design builder review: no implementation-blocking questions.
- Parsing/workspace/store: 78 passed, 1 skipped (Windows symlink privilege unavailable).
- MCP/service/stdio: 91 passed, 1 skipped.
- Original source reused: parser.py, imports.py, indexer.py, parser/import/indexer tests and fixtures.
- Decision: use official grammar wheels with tree-sitter 0.26 instead of the old bundled parser package, avoiding runtime grammar downloads.
- Decision: checksum admitted text on scans, but only reparse changed content; catches same-size edits and preserved timestamps at the cost of reading admitted files each scan interval.
- Decision: cap total admitted content at 128 MiB in addition to file count and individual size; report partial indexes explicitly.
- Decision: install distribution-packaged Podman in Ubuntu-24.04 WSL because none was installed on Windows or WSL.
- Final independent review: four actionable findings, all fixed with five regression cases (two BOM formats).
- Fixed shared-volume cache invalidation using a persistent revision and serialized SQLite scans/initialization.
- Fixed directory replacement races with descriptor-relative no-follow traversal on Linux and opened-handle path validation on Windows.
- Fixed UTF-8 BOM ignore files and added explicit clipping metadata for long symbol/import fields.
- Final Windows suite: 96 passed, 1 skipped (symlink privilege unavailable); Ruff lint and format checks pass.
- Final Linux suite in Podman with network disabled: 97 passed, no skips.
- Final runtime smoke: HTTP health + 15 MCP tools + summary resource + prompt; incremental edit updates; read-only source mount enforced; real PowerShell stdio passes.
- Linux launcher stdio also passes with network disabled and a workspace path containing spaces.
- Runtime inspection: healthy, UID/GID 10001:10001, read-only root filesystem.
- Podman installed rootless in Ubuntu-24.04 WSL; final local image localhost/codesearch:latest built successfully.
- Running instance: codesearch-local, host 127.0.0.1:8091, source C:/git/pessoal/codeSearch read-only. Port 8090 was already occupied and left intact.
- Temporary HTTP verification container was stopped; test image and fixture artifacts remain available for reruns.
- Deferred review findings: none. No remote publication, license assignment, or automatic commit.
