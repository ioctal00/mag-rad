#!/usr/bin/env bash
set -euo pipefail

if [[ $# -lt 1 ]]; then
  echo "Usage: $0 <host> [host ...]" >&2
  exit 2
fi

WAIT_TIMEOUT_SECONDS="${WAIT_TIMEOUT_SECONDS:-900}"
WAIT_INTERVAL_SECONDS="${WAIT_INTERVAL_SECONDS:-10}"
SSH_USER="${SSH_USER:-root}"
ENV_FILE="${MASTER_REGIMES_ENV_FILE:-$HOME/.config/master-regimes-infra/env}"

if [[ -f "$ENV_FILE" ]]; then
  # shellcheck disable=SC1090
  . "$ENV_FILE"
fi

SSH_IDENTITY_OPTS=()
if [[ -n "${MASTER_REGIMES_SSH_PRIVATE_KEY_FILE:-}" ]]; then
  SSH_PRIVATE_KEY_FILE="${MASTER_REGIMES_SSH_PRIVATE_KEY_FILE/#\~/$HOME}"
  SSH_IDENTITY_OPTS=(-i "$SSH_PRIVATE_KEY_FILE" -o IdentitiesOnly=yes)
fi

deadline=$((SECONDS + WAIT_TIMEOUT_SECONDS))
pending=("$@")

echo "Waiting for cloud-init on ${#pending[@]} host(s): ${pending[*]}"

while ((${#pending[@]} > 0)); do
  next_pending=()

  for host in "${pending[@]}"; do
    if ssh \
      -o BatchMode=yes \
      -o StrictHostKeyChecking=accept-new \
      -o UserKnownHostsFile="${HOME}/.ssh/known_hosts" \
      -o ConnectTimeout=8 \
      -o ConnectionAttempts=1 \
      "${SSH_IDENTITY_OPTS[@]}" \
      "${SSH_USER}@${host}" \
      'if command -v cloud-init >/dev/null 2>&1; then cloud-init status --wait; else test -f /var/lib/cloud/instance/boot-finished; fi' \
      >/dev/null 2>&1; then
      echo "cloud-init ready: ${host}"
    else
      next_pending+=("${host}")
    fi
  done

  pending=("${next_pending[@]}")
  if ((${#pending[@]} == 0)); then
    exit 0
  fi

  if ((SECONDS >= deadline)); then
    echo "Timed out waiting for cloud-init on: ${pending[*]}" >&2
    exit 1
  fi

  echo "Still waiting for cloud-init on ${#pending[@]} host(s): ${pending[*]}"
  sleep "${WAIT_INTERVAL_SECONDS}"
done
