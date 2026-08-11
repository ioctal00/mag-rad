#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd -- "$SCRIPT_DIR/.." && pwd)"

SYSTEM_CONFIG="${SYSTEM_CONFIG:-configs/systems/eu-us-gac-vps.yml}"
RENDER_OUT="${RENDER_OUT:-generated/systems/eu-us-gac-vps}"
PLAN_DIR="${PLAN_DIR:-generated/tfplans/eu-us-gac-shared-vpc}"
CONFIRM_VALUE="destroy-eu-us-gac-vhp-shared-vpc"

cd "$REPO_ROOT"

if [[ "${MASTER_REGIMES_DESTROY_CONFIRM:-}" != "$CONFIRM_VALUE" ]]; then
  cat >&2 <<EOF
Refusing to destroy EU+US+GAC shared-VPC infrastructure without explicit confirmation.

Run manually with:
  MASTER_REGIMES_DESTROY_CONFIRM=$CONFIRM_VALUE $0
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

terraform_has_state_resources() {
  local tf_dir="$1"
  local state_output
  if ! state_output="$(terraform -chdir="$tf_dir" state list 2>/dev/null)"; then
    return 1
  fi
  [[ -n "$state_output" ]]
}

terraform_state_list() {
  local tf_dir="$1"
  terraform -chdir="$tf_dir" state list 2>/dev/null || true
}

assert_no_state_resources() {
  local name="$1"
  local tf_dir="$2"
  local state_output
  state_output="$(terraform_state_list "$tf_dir")"
  if [[ -n "$state_output" ]]; then
    echo "Terraform destroy for $name left resources in state:" >&2
    printf '%s\n' "$state_output" >&2
    exit 1
  fi
  echo "Terraform state for $name stack is empty."
}

terraform_destroy_if_needed() {
  local name="$1"
  local tf_dir="$2"
  local plan_file="$PLAN_DIR_ABS/$name-destroy.tfplan"
  local plan_text="$PLAN_DIR_ABS/$name-destroy.plan.txt"
  local apply_log="$PLAN_DIR_ABS/$name-destroy.apply.log"

  if terraform_has_state_resources "$tf_dir"; then
    echo "Planning destroy for $name stack..."
    terraform -chdir="$tf_dir" plan -destroy -input=false -out="$plan_file"
    terraform -chdir="$tf_dir" show -no-color "$plan_file" >"$plan_text"
    echo "Applying destroy for $name stack..."
    if ! terraform -chdir="$tf_dir" apply -auto-approve "$plan_file" 2>&1 | tee "$apply_log"; then
      if [[ "$name" == "eu" ]] && grep -q "cannot remove attached VPC" "$apply_log"; then
        echo "Vultr still reports attached servers on the shared VPC. Waiting 60s and retrying EU destroy once..."
        sleep 60
        terraform -chdir="$tf_dir" plan -destroy -input=false -out="$plan_file"
        terraform -chdir="$tf_dir" show -no-color "$plan_file" >"$plan_text"
        terraform -chdir="$tf_dir" apply -auto-approve "$plan_file"
      else
        exit 1
      fi
    fi
  else
    echo "No Terraform state resources for $name stack; skipping destroy."
  fi
}

require_env \
  VULTR_API_KEY \
  MASTER_REGIMES_POSTGRES_ADMIN_PASSWORD \
  MASTER_REGIMES_APP_DB_PASSWORD

mkdir -p "$EU_TF_DIR" "$US_TF_DIR" "$PLAN_DIR_ABS"

if [[ ! -f "$EU_TF_DIR/terraform.tfvars" || ! -f "$US_TF_DIR/terraform.tfvars" ]]; then
  require_env \
    MASTER_REGIMES_SSH_PUBLIC_KEY \
    MASTER_REGIMES_ADMIN_IPV4_CIDRS \
    MASTER_REGIMES_DATABASE_CLIENT_IPV4_CIDRS \
    MASTER_REGIMES_WEB_IPV4_CIDRS \
    MASTER_REGIMES_GAC_PUBLIC_ACCESS_CIDRS
  env UV_CACHE_DIR="$UV_CACHE_DIR" uv run master-regimes-infra validate-config --system "$SYSTEM_CONFIG"
  env UV_CACHE_DIR="$UV_CACHE_DIR" uv run master-regimes-infra render-config --system "$SYSTEM_CONFIG" --out "$RENDER_OUT"
  [[ -f "$EU_TF_DIR/terraform.tfvars" ]] || install -m 0600 "$RENDER_OUT/terraform/envs/eu/terraform.tfvars" "$EU_TF_DIR/terraform.tfvars"
  [[ -f "$US_TF_DIR/terraform.tfvars" ]] || install -m 0600 "$RENDER_OUT/terraform/envs/us/terraform.tfvars" "$US_TF_DIR/terraform.tfvars"
fi

terraform -chdir="$EU_TF_DIR" init -input=false
terraform -chdir="$US_TF_DIR" init -input=false

if terraform_has_state_resources "$EU_TF_DIR"; then
  SHARED_VPC_ID="$(terraform -chdir="$EU_TF_DIR" output -raw vpc_id 2>/dev/null || true)"
  SHARED_VPC_CIDR="$(terraform -chdir="$EU_TF_DIR" output -raw vpc_cidr 2>/dev/null || true)"
  if [[ -n "$SHARED_VPC_ID" && -n "$SHARED_VPC_CIDR" ]]; then
    set_tfvar_string "$US_TF_DIR/terraform.tfvars" existing_vpc_id "$SHARED_VPC_ID"
    set_tfvar_string "$US_TF_DIR/terraform.tfvars" existing_vpc_cidr "$SHARED_VPC_CIDR"
  fi
fi

terraform_destroy_if_needed us "$US_TF_DIR"
assert_no_state_resources us "$US_TF_DIR"

if terraform_state_list "$EU_TF_DIR" | grep -q "vultr_instance.web_portal"; then
  echo "EU destroy includes Terraform-managed web portal node."
fi
terraform_destroy_if_needed eu "$EU_TF_DIR"
assert_no_state_resources eu "$EU_TF_DIR"

echo "Destroyed EU+US+GAC shared-VPC infrastructure."
echo "Terraform destroy plan text files are in: $PLAN_DIR"
