#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd -- "$SCRIPT_DIR/.." && pwd)"
APAC_TF_DIR="$REPO_ROOT/terraform/envs/apac"
PLAN_DIR="$REPO_ROOT/generated/tfplans/eu-us-apac-gac-shared-vpc"
CONFIRM_VALUE="destroy-apac-extension"
ENV_FILE="${MASTER_REGIMES_ENV_FILE:-$HOME/.config/master-regimes-infra/env}"

cd "$REPO_ROOT"
if [[ "${MASTER_REGIMES_DESTROY_CONFIRM:-}" != "$CONFIRM_VALUE" ]]; then
  echo "Refusing to destroy APAC without MASTER_REGIMES_DESTROY_CONFIRM=$CONFIRM_VALUE" >&2
  exit 2
fi
if [[ -f "$ENV_FILE" ]]; then
  # shellcheck disable=SC1090
  . "$ENV_FILE"
fi
export TF_INPUT=0
export TF_VAR_postgres_admin_password="${TF_VAR_postgres_admin_password:-${MASTER_REGIMES_POSTGRES_ADMIN_PASSWORD:-}}"
export TF_VAR_app_db_password="${TF_VAR_app_db_password:-${MASTER_REGIMES_APP_DB_PASSWORD:-}}"
mkdir -p "$PLAN_DIR"
terraform -chdir="$APAC_TF_DIR" init -input=false
if terraform -chdir="$APAC_TF_DIR" state list 2>/dev/null | grep -q .; then
  plan_file="$PLAN_DIR/apac-destroy.tfplan"
  terraform -chdir="$APAC_TF_DIR" plan -destroy -input=false -out="$plan_file"
  terraform -chdir="$APAC_TF_DIR" show -no-color "$plan_file" >"$PLAN_DIR/apac-destroy.plan.txt"
  terraform -chdir="$APAC_TF_DIR" apply -auto-approve "$plan_file"
fi
if terraform -chdir="$APAC_TF_DIR" state list 2>/dev/null | grep -q .; then
  echo "APAC Terraform state still contains resources after destroy." >&2
  exit 1
fi
TF_BASE_DIR="$REPO_ROOT/terraform" python3 ansible/inventory/terraform_inventory.py >ansible/inventory/generated.json
echo "APAC extension destroyed. EU, US and GAC resources were not modified."
