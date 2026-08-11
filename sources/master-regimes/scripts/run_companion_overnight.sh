#!/usr/bin/env bash
set -Eeuo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
INFRA_DIR="${MASTER_REGIMES_INFRA_DIR:-$ROOT/../master-regimes-infra}"

RUN_ID="${RUN_ID:-$(date -u +%Y%m%dT%H%M%SZ)-companion-overnight}"
LOG_DIR="${LOG_DIR:-$ROOT/generated/overnight-runs/$RUN_ID}"
LOG_FILE="$LOG_DIR/overnight.log"
STATUS_FILE="$LOG_DIR/status.tsv"

RUN_WAN="${RUN_WAN:-true}"
RUN_REGION_IMBALANCE="${RUN_REGION_IMBALANCE:-true}"
SKIP_PREFLIGHT="${SKIP_PREFLIGHT:-false}"
SKIP_INDEX="${SKIP_INDEX:-false}"
RESET_WAN_ON_EXIT="${RESET_WAN_ON_EXIT:-true}"
SHUTDOWN_INFRA_ON_SUCCESS="${SHUTDOWN_INFRA_ON_SUCCESS:-true}"

WAN_LOGICAL_RUN_ID="${WAN_RUN_LOGICAL_RUN_ID:-clean-run-v1-wan-latency}"
WAN_LABEL="${WAN_RUN_LABEL:-clean-run-v1-wan-latency-overnight-$RUN_ID}"
REGION_IMBALANCE_LOGICAL_RUN_ID="${REGION_IMBALANCE_RUN_LOGICAL_RUN_ID:-clean-run-v1-region-imbalance}"
REGION_IMBALANCE_LABEL="${REGION_IMBALANCE_RUN_LABEL:-clean-run-v1-region-imbalance-overnight-$RUN_ID}"

WAN_100MS_PROFILE='{"id":"wan_100ms","enabled":true,"scope":"analytics_egress_to_region","target_region_ids":["eu","us"],"configured_delay_ms":100,"configured_jitter_ms":0,"configured_loss_percent":0}'

mkdir -p "$LOG_DIR"
touch "$STATUS_FILE"
exec > >(tee -a "$LOG_FILE") 2>&1

ts() {
  date -u +%Y-%m-%dT%H:%M:%SZ
}

log() {
  printf '[%s] [%s] %s\n' "$(ts)" "$1" "$2"
}

record() {
  printf '%s\t%s\t%s\n' "$(ts)" "$1" "$2" >> "$STATUS_FILE"
}

make_mr() {
  (cd "$ROOT" && make "$@")
}

make_infra() {
  (cd "$INFRA_DIR" && make "$@")
}

reset_wan_best_effort() {
  if [[ "$RESET_WAN_ON_EXIT" != "true" ]]; then
    return 0
  fi
  if [[ ! -x "$INFRA_DIR/common-scripts/manage_network_latency.py" ]]; then
    log NET "skip WAN reset: manage_network_latency.py is not executable"
    return 0
  fi
  log NET "best-effort WAN latency reset"
  (
    cd "$INFRA_DIR"
    common-scripts/manage_network_latency.py \
      --action reset \
      --profile-json "$WAN_100MS_PROFILE" \
      --out-dir generated/runs/network-intervention-smoke \
      --label "overnight-${RUN_ID}-reset"
  ) || true
}

shutdown_infra() {
  if [[ "$SHUTDOWN_INFRA_ON_SUCCESS" != "true" ]]; then
    log INFRA "shutdown skipped by SHUTDOWN_INFRA_ON_SUCCESS=false"
    record infra-shutdown skipped
    return 0
  fi
  record infra-shutdown start
  log INFRA "shutting down eu-us-gac-vps after successful companion runs"
  make_infra eu-us-gac-vps-down
  record infra-shutdown done
}

on_exit() {
  rc=$?
  if [[ "$rc" -eq 0 ]]; then
    record done "ok"
    log DONE "overnight companion sequence completed"
  else
    record failed "exit_code=$rc"
    log FAIL "overnight companion sequence failed with exit_code=$rc"
    reset_wan_best_effort
  fi
  log INFO "log: $LOG_FILE"
  log INFO "status: $STATUS_FILE"
  exit "$rc"
}

on_interrupt() {
  record interrupted "$1"
  log FAIL "received $1; stopping after cleanup"
  exit "$2"
}

trap on_exit EXIT
trap 'on_interrupt SIGINT 130' INT
trap 'on_interrupt SIGTERM 143' TERM

log INFO "master-regimes: $ROOT"
log INFO "master-regimes-infra: $INFRA_DIR"
log INFO "run_id: $RUN_ID"
log INFO "log_dir: $LOG_DIR"
record started "$RUN_ID"

if [[ "$SKIP_PREFLIGHT" != "true" ]]; then
  record preflight start
  log CHECK "configure-env-check"
  make_infra configure-env-check
  log CHECK "eu-us-gac-vps-ping"
  make_infra eu-us-gac-vps-ping
  record preflight done
else
  log CHECK "preflight skipped by SKIP_PREFLIGHT=true"
  record preflight skipped
fi

if [[ "$RUN_WAN" == "true" ]]; then
  record wan start
  log WAN "starting WAN companion run logical_run_id=$WAN_LOGICAL_RUN_ID label=$WAN_LABEL"
  make_mr wan-run-start \
    WAN_RUN_LOGICAL_RUN_ID="$WAN_LOGICAL_RUN_ID" \
    WAN_RUN_LABEL="$WAN_LABEL"
  record wan-start done

  log NET "reset after WAN companion"
  reset_wan_best_effort

  if [[ "$SKIP_INDEX" != "true" ]]; then
    log WAN "indexing WAN companion logical_run_id=$WAN_LOGICAL_RUN_ID"
    make_mr wan-run-index WAN_RUN_LOGICAL_RUN_ID="$WAN_LOGICAL_RUN_ID"
    record wan-index done
  else
    log WAN "index skipped by SKIP_INDEX=true"
    record wan-index skipped
  fi
else
  log WAN "WAN companion skipped by RUN_WAN=false"
  record wan skipped
fi

if [[ "$RUN_REGION_IMBALANCE" == "true" ]]; then
  record region-imbalance start
  log REGION "starting regional imbalance companion run logical_run_id=$REGION_IMBALANCE_LOGICAL_RUN_ID label=$REGION_IMBALANCE_LABEL"
  make_mr region-imbalance-run-start \
    REGION_IMBALANCE_RUN_LOGICAL_RUN_ID="$REGION_IMBALANCE_LOGICAL_RUN_ID" \
    REGION_IMBALANCE_RUN_LABEL="$REGION_IMBALANCE_LABEL"
  record region-imbalance-start done

  if [[ "$SKIP_INDEX" != "true" ]]; then
    log REGION "indexing regional imbalance companion logical_run_id=$REGION_IMBALANCE_LOGICAL_RUN_ID"
    make_mr region-imbalance-run-index \
      REGION_IMBALANCE_RUN_LOGICAL_RUN_ID="$REGION_IMBALANCE_LOGICAL_RUN_ID"
    record region-imbalance-index done
  else
    log REGION "index skipped by SKIP_INDEX=true"
    record region-imbalance-index skipped
  fi
else
  log REGION "regional imbalance companion skipped by RUN_REGION_IMBALANCE=false"
  record region-imbalance skipped
fi

shutdown_infra
