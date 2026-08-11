#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd -- "$SCRIPT_DIR/.." && pwd)"
ANSIBLE_DIR="$REPO_ROOT/ansible"

mkdir -p \
  "$REPO_ROOT/.ansible/tmp/local" \
  "$REPO_ROOT/.ansible/tmp/remote" \
  "$REPO_ROOT/.ansible/collections"

export ANSIBLE_CONFIG="${ANSIBLE_CONFIG:-$ANSIBLE_DIR/ansible.cfg}"
export ANSIBLE_HOME="${ANSIBLE_HOME:-$REPO_ROOT/.ansible}"
export ANSIBLE_LOCAL_TEMP="${ANSIBLE_LOCAL_TEMP:-$REPO_ROOT/.ansible/tmp/local}"
export ANSIBLE_REMOTE_TEMP="${ANSIBLE_REMOTE_TEMP:-$REPO_ROOT/.ansible/tmp/remote}"
export ANSIBLE_COLLECTIONS_PATH="${ANSIBLE_COLLECTIONS_PATH:-$REPO_ROOT/.ansible/collections:/usr/share/ansible/collections:$HOME/.ansible/collections}"

cd "$ANSIBLE_DIR"
exec "${ANSIBLE_PYTHON:-/usr/bin/python3}" "$SCRIPT_DIR/ansible_shim.py" "$@"
