#!/usr/bin/env bash
set -euo pipefail

SYSTEM_FILE="${1:-configs/systems/eu-vps-single.yml}"
TF_DIR="${2:-terraform/envs/eu}"
ENV_FILE="${MASTER_REGIMES_ENV_FILE:-$HOME/.config/master-regimes-infra/env}"

if [[ -f "$ENV_FILE" ]]; then
  # shellcheck disable=SC1090
  . "$ENV_FILE"
fi

failures=0
warnings=0

ok() {
  printf '[OK] %s\n' "$1"
}

warn() {
  warnings=$((warnings + 1))
  printf '[WARN] %s\n' "$1"
}

fail() {
  failures=$((failures + 1))
  printf '[FAIL] %s\n' "$1"
}

require_cmd() {
  if command -v "$1" >/dev/null 2>&1; then
    ok "command available: $1"
  else
    fail "missing command: $1"
  fi
}

require_env() {
  if [[ -n "${!1:-}" ]]; then
    ok "environment variable set: $1"
  else
    fail "missing environment variable: $1"
  fi
}

require_cmd terraform
require_cmd ansible
require_cmd ansible-galaxy
require_cmd python3
require_cmd ssh
require_cmd uv

if [[ -f "$SYSTEM_FILE" ]]; then
  ok "system config exists: $SYSTEM_FILE"
else
  fail "missing system config: $SYSTEM_FILE"
fi

require_env VULTR_API_KEY
require_env MASTER_REGIMES_SSH_PUBLIC_KEY
require_env MASTER_REGIMES_ADMIN_IPV4_CIDRS
require_env MASTER_REGIMES_DATABASE_CLIENT_IPV4_CIDRS
require_env MASTER_REGIMES_POSTGRES_ADMIN_PASSWORD
require_env MASTER_REGIMES_APP_DB_PASSWORD

web_portal_enabled="$(
  python3 - "$SYSTEM_FILE" <<'PY'
from __future__ import annotations

import sys
from pathlib import Path

in_web_portal = False
enabled = False
for line in Path(sys.argv[1]).read_text(encoding="utf-8").splitlines():
    if line.startswith("web_portal:"):
        in_web_portal = True
        continue
    if in_web_portal and line and not line.startswith((" ", "\t")):
        break
    if in_web_portal and line.strip().startswith("enabled:"):
        enabled = line.split(":", 1)[1].strip().lower() in {"true", "yes", "1"}
        break
print("true" if enabled else "false")
PY
)"
if [[ "$web_portal_enabled" == "true" ]]; then
  require_env MASTER_REGIMES_DEMO_DB_PASSWORD
  require_env MASTER_REGIMES_CLOUDB_WEB_AUTH_USERS
  require_env MASTER_REGIMES_VIEWER_AUTH_USERS
fi

if [[ -n "${MASTER_REGIMES_GIT_PAT:-}" ]]; then
  ok "optional Git PAT is set"
else
  warn "MASTER_REGIMES_GIT_PAT is empty; HTTPS clone fallback for private repos will not work"
fi

if [[ -f "$SYSTEM_FILE" ]]; then
  if grep -q "replace-with-public-key" "$SYSTEM_FILE"; then
    fail "SSH public key placeholder is still present in $SYSTEM_FILE"
  else
    ok "SSH public key placeholder is not present"
  fi

  if grep -q "203.0.113." "$SYSTEM_FILE"; then
    fail "documentation CIDR placeholder 203.0.113.x is still present in $SYSTEM_FILE"
  else
    ok "documentation CIDR placeholder is not present"
  fi

  private_key_path_ref="$(
    python3 - "$SYSTEM_FILE" <<'PY'
from __future__ import annotations

import sys
from pathlib import Path

for line in Path(sys.argv[1]).read_text(encoding="utf-8").splitlines():
    stripped = line.strip()
    if stripped.startswith("private_key_path:"):
        value = stripped.split(":", 1)[1].strip().strip('"').strip("'")
        print(value)
        break
PY
  )"
  private_key_path="$private_key_path_ref"
  if [[ "$private_key_path" == env:* ]]; then
    env_name="${private_key_path#env:}"
    private_key_path="${!env_name:-~/.ssh/id_ed25519}"
  fi
  private_key_path="${private_key_path/#\~/$HOME}"
  if [[ -n "$private_key_path" && -f "$private_key_path" ]]; then
    ok "SSH private key exists: $private_key_path"
    private_key_mode="$(stat -c '%a' "$private_key_path")"
    if (((8#$private_key_mode & 8#077) == 0)); then
      ok "SSH private key permissions are restricted: $private_key_mode"
    else
      fail "SSH private key permissions are too open: $private_key_mode; run chmod 600 $private_key_path"
    fi
  else
    fail "SSH private key from system config/env does not exist: ${private_key_path:-<empty>}"
  fi
fi

if [[ -f "$TF_DIR/terraform.tfvars" ]]; then
  if grep -q 'compute_resource_type[[:space:]]*=[[:space:]]*"instance"' "$TF_DIR/terraform.tfvars"; then
    ok "installed Terraform tfvars selects VPS instances"
  else
    fail "$TF_DIR/terraform.tfvars does not select compute_resource_type = \"instance\""
  fi
else
  warn "$TF_DIR/terraform.tfvars is not installed yet; run make single-eu-install before Terraform plan"
fi

if ANSIBLE_LOCAL_TEMP="${ANSIBLE_LOCAL_TEMP:-/tmp/ansible-local}" ansible-galaxy collection list ansible.posix >/dev/null 2>&1; then
  ok "Ansible collection available: ansible.posix"
else
  warn "Ansible collection ansible.posix is not installed; run make ansible-deps"
fi

if [[ "$failures" -gt 0 ]]; then
  printf 'Doctor failed with %d failure(s) and %d warning(s).\n' "$failures" "$warnings" >&2
  exit 1
fi

printf 'Doctor passed with %d warning(s).\n' "$warnings"
