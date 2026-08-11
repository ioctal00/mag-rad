#!/usr/bin/env bash
set -Eeuo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
INFRA_DIR="${MASTER_REGIMES_INFRA_DIR:-$ROOT/../master-regimes-infra}"

RUN_MODE="${RUN_MODE:-full}" # full | probe | dry-run
RUN_ID="${RUN_ID:-$(date -u +%Y%m%dT%H%M%SZ)-region-asymmetry-150}"
LOG_DIR="${LOG_DIR:-$ROOT/generated/region-asymmetry-runs/$RUN_ID}"
LOG_FILE="$LOG_DIR/region_asymmetry_150.log"
STATUS_FILE="$LOG_DIR/status.tsv"

SKIP_PREFLIGHT="${SKIP_PREFLIGHT:-false}"
SKIP_INDEX="${SKIP_INDEX:-false}"

REGION_ASYMMETRY_RUN_LOGICAL_RUN_ID="${REGION_ASYMMETRY_RUN_LOGICAL_RUN_ID:-clean-run-v1-region-asymmetry}"
REGION_ASYMMETRY_RUN_LABEL="${REGION_ASYMMETRY_RUN_LABEL:-clean-run-v1-region-asymmetry-attempt-01}"

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

on_exit() {
  rc=$?
  if [[ "$rc" -eq 0 ]]; then
    record done "ok"
    log DONE "region-asymmetry sequence completed"
  else
    record failed "exit_code=$rc"
    log FAIL "region-asymmetry sequence failed with exit_code=$rc"
  fi
  log INFO "log: $LOG_FILE"
  log INFO "status: $STATUS_FILE"
  exit "$rc"
}

on_interrupt() {
  record interrupted "$1"
  log FAIL "received $1; stopping"
  exit "$2"
}

trap on_exit EXIT
trap 'on_interrupt SIGINT 130' INT
trap 'on_interrupt SIGTERM 143' TERM

case "$RUN_MODE" in
  full|probe|dry-run) ;;
  *)
    log FAIL "invalid RUN_MODE=$RUN_MODE; expected full, probe or dry-run"
    exit 2
    ;;
esac

log INFO "master-regimes: $ROOT"
log INFO "master-regimes-infra: $INFRA_DIR"
log INFO "run_id: $RUN_ID"
log INFO "run_mode: $RUN_MODE"
log INFO "expected full corpus size: 150 query executions"
log INFO "log_dir: $LOG_DIR"
record started "$RUN_ID mode=$RUN_MODE"

if [[ "$SKIP_PREFLIGHT" != "true" && "$RUN_MODE" != "dry-run" ]]; then
  record preflight start
  log CHECK "configure-env-check"
  make_infra configure-env-check
  log CHECK "eu-us-gac-vps-ping"
  make_infra eu-us-gac-vps-ping
  record preflight done
else
  log CHECK "preflight skipped"
  record preflight skipped
fi

record validate start
log PLAN "validating corpus manifest"
make_mr region-asymmetry-run-validate
record validate done

record render start
log PLAN "rendering corpus execution plan"
make_mr region-asymmetry-run-render
record render done

case "$RUN_MODE" in
  dry-run)
    record dry-run start
    log RUN "dry-run only: no database execution"
    make_mr region-asymmetry-run-dry-run \
      REGION_ASYMMETRY_RUN_LABEL="$REGION_ASYMMETRY_RUN_LABEL" \
      REGION_ASYMMETRY_RUN_LOGICAL_RUN_ID="$REGION_ASYMMETRY_RUN_LOGICAL_RUN_ID"
    record dry-run done
    ;;
  probe)
    record probe start
    log RUN "probe: one asymmetric-medium analytics group, max 2 query executions"
    make_mr region-asymmetry-run-probe-start
    record probe done
    ;;
  full)
    record full-run start
    log RUN "starting full region-asymmetry companion run"
    make_mr region-asymmetry-run-start \
      REGION_ASYMMETRY_RUN_LABEL="$REGION_ASYMMETRY_RUN_LABEL" \
      REGION_ASYMMETRY_RUN_LOGICAL_RUN_ID="$REGION_ASYMMETRY_RUN_LOGICAL_RUN_ID"
    record full-run done

    if [[ "$SKIP_INDEX" != "true" ]]; then
      record index start
      log INDEX "indexing logical run $REGION_ASYMMETRY_RUN_LOGICAL_RUN_ID"
      make_mr region-asymmetry-run-index \
        REGION_ASYMMETRY_RUN_LOGICAL_RUN_ID="$REGION_ASYMMETRY_RUN_LOGICAL_RUN_ID"
      record index done
    else
      log INDEX "index skipped by SKIP_INDEX=true"
      record index skipped
    fi
    ;;
esac
