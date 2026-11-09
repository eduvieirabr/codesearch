#!/usr/bin/env bash
set -euo pipefail
if [[ $# -lt 1 ]]; then
  echo "Usage: bash scripts/run.sh WORKSPACE [http|stdio] [--build]" >&2
  exit 2
fi
workspace="$(cd -- "$1" && pwd -P)"
transport="${2:-http}"
project_root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd -P)"
if [[ "$workspace" == *","* ]]; then echo "Workspace paths containing commas are unsupported." >&2; exit 2; fi
if [[ "$transport" != http && "$transport" != stdio ]]; then echo "Transport must be http or stdio." >&2; exit 2; fi
identity="$(printf '%s' "$workspace" | sha256sum | cut -d' ' -f1)"
volume="${CODESEARCH_VOLUME:-codesearch-${identity:0:12}}"
if [[ "${3:-}" == --build ]]; then
  podman build --format docker --quiet -t localhost/codesearch:latest -f "$project_root/Containerfile" "$project_root" >/dev/null
fi
args=(run --rm --read-only --cap-drop=ALL --security-opt=no-new-privileges
      --userns=keep-id:uid=10001,gid=10001
      --tmpfs /tmp:rw,noexec,nosuid,size=64m
      --mount "type=bind,source=$workspace,destination=/workspace,ro"
      --volume "$volume:/data" --env "CODESEARCH_WORKSPACE_ID=$identity")
if [[ "$transport" == http ]]; then
  podman "${args[@]}" --detach --name "${CODESEARCH_NAME:-codesearch-local}" \
    --publish "127.0.0.1:${CODESEARCH_PORT:-8091}:8090" localhost/codesearch:latest \
    --transport http --host 0.0.0.0
  echo "MCP: http://127.0.0.1:${CODESEARCH_PORT:-8091}/mcp"
else
  exec podman "${args[@]}" --interactive --network=none --no-healthcheck \
    localhost/codesearch:latest --transport stdio
fi
