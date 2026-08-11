#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd -- "$SCRIPT_DIR/.." && pwd)"

SYSTEM_CONFIG="${SYSTEM_CONFIG:-configs/systems/eu-us-apac-gac-vps.yml}"
RENDER_OUT="${RENDER_OUT:-generated/systems/eu-us-apac-gac-vps}"
PLAN_DIR="${PLAN_DIR:-generated/tfplans/eu-us-apac-gac-shared-vpc}"
CONFIRM_VALUE="extend-eu-us-gac-with-apac"

cd "$REPO_ROOT"

if [[ "${MASTER_REGIMES_UP_CONFIRM:-}" != "$CONFIRM_VALUE" ]]; then
  cat >&2 <<EOF
Refusing to extend EU+US+GAC with APAC without explicit confirmation.

Run through the Make target or set:
  MASTER_REGIMES_UP_CONFIRM=$CONFIRM_VALUE $0
EOF
  exit 2
fi

export UV_CACHE_DIR="${UV_CACHE_DIR:-$REPO_ROOT/.uv-cache}"
export TF_INPUT=0

EU_TF_DIR="$REPO_ROOT/terraform/envs/eu"
APAC_TF_DIR="$REPO_ROOT/terraform/envs/apac"
PLAN_DIR_ABS="$REPO_ROOT/$PLAN_DIR"
ENV_FILE="${MASTER_REGIMES_ENV_FILE:-$HOME/.config/master-regimes-infra/env}"

if [[ -f "$ENV_FILE" ]]; then
  # shellcheck disable=SC1090
  . "$ENV_FILE"
fi

if [[ -n "${MASTER_REGIMES_POSTGRES_ADMIN_PASSWORD:-}" && -z "${TF_VAR_postgres_admin_password:-}" ]]; then
  export TF_VAR_postgres_admin_password="$MASTER_REGIMES_POSTGRES_ADMIN_PASSWORD"
fi
if [[ -n "${MASTER_REGIMES_APP_DB_PASSWORD:-}" && -z "${TF_VAR_app_db_password:-}" ]]; then
  export TF_VAR_app_db_password="$MASTER_REGIMES_APP_DB_PASSWORD"
fi

require_env() {
  local missing=0
  local name
  for name in "$@"; do
    if [[ -z "${!name:-}" ]]; then
      echo "Missing required environment variable: $name" >&2
      missing=1
    fi
  done
  if [[ "$missing" == "1" ]]; then
    exit 2
  fi
}

hcl_string() {
  local value="$1"
  value="${value//\\/\\\\}"
  value="${value//\"/\\\"}"
  printf '"%s"' "$value"
}

set_tfvar_string() {
  local file="$1"
  local key="$2"
  local value="$3"
  local encoded
  local tmp
  encoded="$(hcl_string "$value")"
  tmp="$(mktemp)"
  awk -v key="$key" -v encoded="$encoded" '
    BEGIN { replaced = 0 }
    $0 ~ "^[[:space:]]*" key "[[:space:]]*=" {
      print key " = " encoded
      replaced = 1
      next
    }
    { print }
    END {
      if (replaced == 0) {
        print key " = " encoded
      }
    }
  ' "$file" >"$tmp"
  install -m 0600 "$tmp" "$file"
  rm -f "$tmp"
}

inventory_group_count() {
  local group="$1"
  python3 - "$REPO_ROOT/ansible/inventory/generated.json" "$group" <<'PY'
import json
import sys
from pathlib import Path

inventory = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
hosts = inventory.get("all", {}).get("children", {}).get(sys.argv[2], {}).get("hosts", {})
print(len(hosts))
PY
}

require_env \
  VULTR_API_KEY \
  MASTER_REGIMES_SSH_PUBLIC_KEY \
  MASTER_REGIMES_SSH_PRIVATE_KEY_FILE \
  MASTER_REGIMES_ADMIN_IPV4_CIDRS \
  MASTER_REGIMES_DATABASE_CLIENT_IPV4_CIDRS \
  MASTER_REGIMES_WEB_IPV4_CIDRS \
  MASTER_REGIMES_GAC_PUBLIC_ACCESS_CIDRS \
  MASTER_REGIMES_POSTGRES_ADMIN_PASSWORD \
  MASTER_REGIMES_APP_DB_PASSWORD \
  MASTER_REGIMES_ANALYTICS_DB_PASSWORD \
  MASTER_REGIMES_DEMO_DB_PASSWORD \
  MASTER_REGIMES_CLOUDB_WEB_AUTH_USERS \
  MASTER_REGIMES_VIEWER_AUTH_USERS

if ! terraform -chdir="$EU_TF_DIR" state list 2>/dev/null | grep -q .; then
  echo "EU anchor Terraform state is empty. Create EU+US+GAC before extending it." >&2
  exit 1
fi

echo "Rendering N=3 configuration without applying EU or US Terraform state..."
uv run master-regimes-infra validate-config --system "$SYSTEM_CONFIG"
uv run master-regimes-infra render-config --system "$SYSTEM_CONFIG" --out "$RENDER_OUT"

mkdir -p "$APAC_TF_DIR" "$REPO_ROOT/ansible/group_vars" "$PLAN_DIR_ABS"
install -m 0600 "$RENDER_OUT/terraform/envs/apac/terraform.tfvars" "$APAC_TF_DIR/terraform.tfvars"
install -m 0600 "$RENDER_OUT/ansible/group_vars/all.yml" "$REPO_ROOT/ansible/group_vars/all.yml"

shared_vpc_id="$(terraform -chdir="$EU_TF_DIR" output -raw vpc_id)"
shared_vpc_cidr="$(terraform -chdir="$EU_TF_DIR" output -raw vpc_cidr)"
if [[ -z "$shared_vpc_id" || -z "$shared_vpc_cidr" ]]; then
  echo "EU anchor did not expose a reusable VPC ID and CIDR." >&2
  exit 1
fi
set_tfvar_string "$APAC_TF_DIR/terraform.tfvars" existing_vpc_id "$shared_vpc_id"
set_tfvar_string "$APAC_TF_DIR/terraform.tfvars" existing_vpc_cidr "$shared_vpc_cidr"

terraform -chdir="$APAC_TF_DIR" init -input=false
plan_file="$PLAN_DIR_ABS/apac-create.tfplan"
terraform -chdir="$APAC_TF_DIR" plan -input=false -out="$plan_file"
terraform -chdir="$APAC_TF_DIR" show -no-color "$plan_file" >"$PLAN_DIR_ABS/apac-create.plan.txt"
terraform -chdir="$APAC_TF_DIR" apply -auto-approve "$plan_file"

mapfile -t apac_hosts < <(
  terraform -chdir="$APAC_TF_DIR" output -json ssh_commands \
    | python3 common-scripts/terraform_ssh_hosts.py
)
if [[ "${#apac_hosts[@]}" -ne 3 ]]; then
  echo "Expected one APAC coordinator and two workers, got ${#apac_hosts[@]} SSH hosts." >&2
  exit 1
fi
common-scripts/wait_for_ssh_hosts.sh "${apac_hosts[@]}"
common-scripts/wait_for_cloud_init_hosts.sh "${apac_hosts[@]}"

mkdir -p ansible/inventory
TF_BASE_DIR="$REPO_ROOT/terraform" python3 ansible/inventory/terraform_inventory.py >ansible/inventory/generated.json
if [[ "$(inventory_group_count apac)" -ne 3 ]]; then
  echo "Generated inventory does not contain the expected three APAC DB nodes." >&2
  exit 1
fi
if [[ "$(inventory_group_count analytics_clients)" -lt 1 ]]; then
  echo "Generated inventory lost the existing GAC/analytics node." >&2
  exit 1
fi

common-scripts/run_ansible.sh ansible apac -m ansible.builtin.ping
common-scripts/run_ansible.sh ansible-playbook playbooks/site.yml --limit 'apac:analytics_clients'
common-scripts/run_ansible.sh ansible-playbook playbooks/verify-citus.yml --limit apac

echo "APAC extension is ready. EU and US Terraform stacks were read but not planned or applied."
echo "Plan evidence: $PLAN_DIR_ABS/apac-create.plan.txt"
