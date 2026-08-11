#!/usr/bin/env bash
set -euo pipefail

ENV_FILE="${MASTER_REGIMES_ENV_FILE:-$HOME/.config/master-regimes-infra/env}"
LOAD_LINE="test -f ${ENV_FILE} && . ${ENV_FILE}"
BASHRC="${HOME}/.bashrc"
ONLY_MISSING=0

usage() {
  cat <<'EOF'
Usage: common-scripts/configure_env.sh [--only-missing]

Without flags, every known variable is prompted. Empty input keeps the current
value, if one exists, and otherwise leaves the variable unset.

With --only-missing, variables already present in the current shell or env file
are accepted without prompting; only missing values are requested.
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --only-missing | --missing-only | --check-existing)
      ONLY_MISSING=1
      ;;
    -h | --help)
      usage
      exit 0
      ;;
    *)
      echo "Unknown option: $1" >&2
      usage >&2
      exit 2
      ;;
  esac
  shift
done

mkdir -p "$(dirname "$ENV_FILE")"
chmod 700 "$(dirname "$ENV_FILE")"

if [[ -f "$ENV_FILE" ]]; then
  # Load existing values so empty answers can preserve them.
  # shellcheck disable=SC1090
  . "$ENV_FILE"
fi

prompt_var() {
  local name="$1"
  local prompt="$2"
  local secret="${3:-0}"
  local default_value="${4:-}"
  local optional="${5:-0}"
  local current_value="${!name:-}"
  local value

  if [[ "$ONLY_MISSING" == "1" && -n "$current_value" ]]; then
    echo "Keeping existing $name."
    return
  fi

  if [[ "$ONLY_MISSING" == "1" && "$optional" == "1" && -z "$current_value" ]]; then
    echo "Skipping optional $name."
    return
  fi

  if [[ -n "$current_value" ]]; then
    if [[ "$secret" == "1" ]]; then
      printf '%s [already set, Enter keeps it]: ' "$prompt"
    else
      printf '%s [%s]: ' "$prompt" "$current_value"
    fi
  elif [[ -n "$default_value" ]]; then
    printf '%s [%s, Enter skips]: ' "$prompt" "$default_value"
  else
    printf '%s: ' "$prompt"
  fi

  if [[ "$secret" == "1" ]]; then
    read -rsp "" value
    echo
  else
    read -r value
  fi

  if [[ -z "$value" ]]; then
    if [[ -n "$current_value" ]]; then
      printf -v "$name" '%s' "$current_value"
    fi
    return
  fi

  printf -v "$name" '%s' "$value"
}

echo "Configuring master-regimes-infra environment."
echo "Env file: $ENV_FILE"

prompt_var VULTR_API_KEY "Vultr API key" 1
prompt_var MASTER_REGIMES_SSH_PUBLIC_KEY "SSH public key content" 0
prompt_var MASTER_REGIMES_SSH_PRIVATE_KEY_FILE "SSH private key path" 0 "~/.ssh/id_ed25519" 1
prompt_var MASTER_REGIMES_ADMIN_IPV4_CIDRS "Admin IPv4 CIDRs for SSH/PostgreSQL, comma-separated" 0
prompt_var MASTER_REGIMES_DATABASE_CLIENT_IPV4_CIDRS "Database client IPv4 CIDRs, comma-separated" 0
prompt_var MASTER_REGIMES_WEB_IPV4_CIDRS "Web IPv4 CIDRs" 0 "0.0.0.0/0" 1
prompt_var MASTER_REGIMES_GAC_PUBLIC_ACCESS_CIDRS "GAC public access IPv4 CIDRs (optional until GAC topology)" 0 "" 1
prompt_var MASTER_REGIMES_POSTGRES_ADMIN_PASSWORD "Postgres admin password" 1
prompt_var MASTER_REGIMES_APP_DB_PASSWORD "App DB password" 1
prompt_var MASTER_REGIMES_ANALYTICS_DB_PASSWORD "Analytics DB password (optional for GAC)" 1 "" 1
prompt_var MASTER_REGIMES_DEMO_DB_PASSWORD "Read-only demo DB password for cloudb-web/Pgweb" 1
prompt_var MASTER_REGIMES_CLOUDB_WEB_AUTH_USERS "cloudb-web Basic Auth users, comma-separated user:password pairs" 1
prompt_var MASTER_REGIMES_VIEWER_AUTH_USERS "Regime viewer users, comma-separated user:password pairs" 1
prompt_var MASTER_REGIMES_GIT_PAT "Git PAT for remote repository clones (optional)" 1 "" 1
prompt_var MASTER_REGIMES_GIT_USERNAME "Git HTTPS username" 0 "x-access-token" 1

umask 077
{
  for name in \
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
    MASTER_REGIMES_VIEWER_AUTH_USERS \
    MASTER_REGIMES_GIT_PAT \
    MASTER_REGIMES_GIT_USERNAME; do
    if [[ -n "${!name:-}" ]]; then
      printf 'export %s=%q\n' "$name" "${!name}"
    fi
  done

  if [[ -n "${MASTER_REGIMES_POSTGRES_ADMIN_PASSWORD:-}" ]]; then
    printf 'export TF_VAR_postgres_admin_password="$MASTER_REGIMES_POSTGRES_ADMIN_PASSWORD"\n'
  fi
  if [[ -n "${MASTER_REGIMES_APP_DB_PASSWORD:-}" ]]; then
    printf 'export TF_VAR_app_db_password="$MASTER_REGIMES_APP_DB_PASSWORD"\n'
  fi
} > "$ENV_FILE"
chmod 600 "$ENV_FILE"

touch "$BASHRC"
grep -qxF "$LOAD_LINE" "$BASHRC" || printf '%s\n' "$LOAD_LINE" >> "$BASHRC"

echo "Saved $ENV_FILE and registered it in $BASHRC."
echo "Load it in the current shell with: . $ENV_FILE"
