#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd -- "$SCRIPT_DIR/.." && pwd)"

SYSTEM_CONFIG="${SYSTEM_CONFIG:-configs/systems/eu-us-gac-vps.yml}"
RENDER_OUT="${RENDER_OUT:-generated/systems/eu-us-gac-vps}"
PLAN_DIR="${PLAN_DIR:-generated/tfplans/eu-us-gac-shared-vpc}"
CONFIRM_VALUE="create-eu-us-gac-vhp-shared-vpc"

cd "$REPO_ROOT"

if [[ "${MASTER_REGIMES_UP_CONFIRM:-}" != "$CONFIRM_VALUE" ]]; then
  cat >&2 <<EOF
Refusing to create EU+US+GAC shared-VPC infrastructure without explicit confirmation.

Run manually with:
  MASTER_REGIMES_UP_CONFIRM=$CONFIRM_VALUE $0
EOF
  exit 2
fi

export UV_CACHE_DIR="${UV_CACHE_DIR:-$REPO_ROOT/.uv-cache}"
export TF_INPUT=0

EU_TF_DIR="$REPO_ROOT/terraform/envs/eu"
US_TF_DIR="$REPO_ROOT/terraform/envs/us"
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
    echo "Run common-scripts/configure_env.sh first, or export the missing values." >&2
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

  if grep -Eq "^[[:space:]]*${key}[[:space:]]*=" "$file"; then
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
  else
    cp "$file" "$tmp"
    {
      printf '\n# Attached by shared-VPC lifecycle script.\n'
      printf '%s = %s\n' "$key" "$encoded"
    } >>"$tmp"
  fi

  install -m 0600 "$tmp" "$file"
  rm -f "$tmp"
}

terraform_apply_plan() {
  local name="$1"
  local tf_dir="$2"
  local plan_file="$PLAN_DIR_ABS/$name-create.tfplan"
  local plan_text="$PLAN_DIR_ABS/$name-create.plan.txt"

  echo "Planning create/apply for $name stack..."
  terraform -chdir="$tf_dir" plan -input=false -out="$plan_file"
  terraform -chdir="$tf_dir" show -no-color "$plan_file" >"$plan_text"
  echo "Applying create/apply for $name stack..."
  terraform -chdir="$tf_dir" apply -auto-approve "$plan_file"
}

terraform_ssh_hosts() {
  local tf_dir="$1"
  terraform -chdir="$tf_dir" output -json ssh_commands | python3 common-scripts/terraform_ssh_hosts.py
}

rendered_bool() {
  local key="$1"
  local file="$REPO_ROOT/ansible/group_vars/all.yml"
  python3 - "$file" "$key" <<'PY'
import re
import sys
from pathlib import Path

path = Path(sys.argv[1])
key = sys.argv[2]
if not path.exists():
    print("false")
    raise SystemExit

pattern = re.compile(rf"^\s*{re.escape(key)}\s*:\s*(true|false)\s*$", re.IGNORECASE)
for line in path.read_text(encoding="utf-8").splitlines():
    match = pattern.match(line)
    if match:
        print(match.group(1).lower())
        break
else:
    print("false")
PY
}

inventory_group_count() {
  local group="$1"
  python3 - "$REPO_ROOT/ansible/inventory/generated.json" "$group" <<'PY'
import json
import sys
from pathlib import Path

path = Path(sys.argv[1])
group = sys.argv[2]
inventory = json.loads(path.read_text(encoding="utf-8"))
hosts = inventory.get("all", {}).get("children", {}).get(group, {}).get("hosts", {})
print(len(hosts))
PY
}

assert_inventory_group_present() {
  local group="$1"
  local label="$2"
  local count
  count="$(inventory_group_count "$group")"
  if [[ "$count" -eq 0 ]]; then
    echo "Expected $label hosts in Ansible inventory group '$group', but none were found." >&2
    echo "Check Terraform outputs and rendered inventory before continuing." >&2
    exit 1
  fi
  echo "Inventory includes $count $label host(s) in group '$group'."
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

echo "Rendering EU+US+GAC shared-VPC config from $SYSTEM_CONFIG..."
env UV_CACHE_DIR="$UV_CACHE_DIR" uv run master-regimes-infra validate-config --system "$SYSTEM_CONFIG"
env UV_CACHE_DIR="$UV_CACHE_DIR" uv run master-regimes-infra render-config --system "$SYSTEM_CONFIG" --out "$RENDER_OUT"

mkdir -p \
  "$EU_TF_DIR" \
  "$US_TF_DIR" \
  "$REPO_ROOT/ansible/group_vars" \
  "$PLAN_DIR_ABS"

install -m 0600 "$RENDER_OUT/terraform/envs/eu/terraform.tfvars" "$EU_TF_DIR/terraform.tfvars"
install -m 0600 "$RENDER_OUT/terraform/envs/us/terraform.tfvars" "$US_TF_DIR/terraform.tfvars"
install -m 0600 "$RENDER_OUT/ansible/group_vars/all.yml" "$REPO_ROOT/ansible/group_vars/all.yml"

terraform -chdir="$EU_TF_DIR" init -input=false
terraform -chdir="$US_TF_DIR" init -input=false

terraform_apply_plan eu "$EU_TF_DIR"

SHARED_VPC_ID="$(terraform -chdir="$EU_TF_DIR" output -raw vpc_id)"
SHARED_VPC_CIDR="$(terraform -chdir="$EU_TF_DIR" output -raw vpc_cidr)"

if [[ -z "$SHARED_VPC_ID" || -z "$SHARED_VPC_CIDR" ]]; then
  echo "Failed to read EU shared VPC outputs." >&2
  exit 1
fi

set_tfvar_string "$US_TF_DIR/terraform.tfvars" existing_vpc_id "$SHARED_VPC_ID"
set_tfvar_string "$US_TF_DIR/terraform.tfvars" existing_vpc_cidr "$SHARED_VPC_CIDR"

terraform_apply_plan us "$US_TF_DIR"

mapfile -t EU_HOSTS < <(terraform_ssh_hosts "$EU_TF_DIR")
mapfile -t US_HOSTS < <(terraform_ssh_hosts "$US_TF_DIR")
HOSTS=("${EU_HOSTS[@]}" "${US_HOSTS[@]}")

if [[ "${#HOSTS[@]}" -eq 0 ]]; then
  echo "No SSH hosts found after Terraform apply." >&2
  exit 1
fi

common-scripts/wait_for_ssh_hosts.sh "${HOSTS[@]}"
common-scripts/wait_for_cloud_init_hosts.sh "${HOSTS[@]}"

mkdir -p ansible/inventory
TF_BASE_DIR="$REPO_ROOT/terraform" python3 ansible/inventory/terraform_inventory.py >ansible/inventory/generated.json

assert_inventory_group_present db_nodes "database"
assert_inventory_group_present analytics_clients "GAC/analytics"
if [[ "$(rendered_bool web_portal_enabled)" == "true" ]]; then
  assert_inventory_group_present web_portals "web portal"
fi

common-scripts/run_ansible.sh ansible-playbook playbooks/site.yml --limit 'eu:us'
common-scripts/run_ansible.sh ansible-playbook playbooks/verify-citus.yml --limit 'eu:us'

echo "Created EU+US+GAC using active_profile from $SYSTEM_CONFIG in one Vultr VPC."
if [[ "$(rendered_bool web_portal_enabled)" == "true" ]]; then
  echo "The web portal node was provisioned through Terraform and configured through the cloudb_web Ansible role."
  echo "Portal public IP: $(terraform -chdir="$EU_TF_DIR" output -raw web_portal_public_ip 2>/dev/null || true)"
fi
echo "Terraform plan text files are in: $PLAN_DIR"
