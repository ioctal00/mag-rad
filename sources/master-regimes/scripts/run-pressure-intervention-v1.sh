#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
mode="${1:-dry-run}"

cd "$repo_root"

case "$mode" in
  build)
    exec make pressure-program-build
    ;;
  dry-run)
    exec make pressure-program-dry-run
    ;;
  start)
    exec make pressure-program-start
    ;;
  status)
    exec make pressure-program-status
    ;;
  *)
    printf 'Usage: %s {build|dry-run|start|status}\n' "$0" >&2
    exit 2
    ;;
esac
