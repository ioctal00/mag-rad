#!/usr/bin/env bash
set -Eeuo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
INFRA_DIR="${MASTER_REGIMES_INFRA_DIR:-$ROOT/../master-regimes-infra}"

RUN_MODE="${RUN_MODE:-full}" # full | probe | dry-run
RUN_ID="${RUN_ID:-$(date -u +%Y%m%dT%H%M%SZ)-skew-replacement-rerun}"
LOG_DIR="${LOG_DIR:-$ROOT/generated/skew-replacement-reruns/$RUN_ID}"
LOG_FILE="$LOG_DIR/skew_replacement_rerun.log"
STATUS_FILE="$LOG_DIR/status.tsv"

SKIP_PREFLIGHT="${SKIP_PREFLIGHT:-false}"
SKIP_INDEX="${SKIP_INDEX:-false}"
BUILD_FEATURES="${BUILD_FEATURES:-true}"
BUILD_REPLACEMENT_PLAN="${BUILD_REPLACEMENT_PLAN:-true}"
WRITE_OVERLAY="${WRITE_OVERLAY:-false}"

REGION_ASYMMETRY_RUN_LOGICAL_RUN_ID="${REGION_ASYMMETRY_RUN_LOGICAL_RUN_ID:-clean-run-v1-region-asymmetry-skew-rerun}"
REGION_ASYMMETRY_RUN_LABEL="${REGION_ASYMMETRY_RUN_LABEL:-clean-run-v1-region-asymmetry-skew-rerun-$RUN_ID}"
REGION_ASYMMETRY_RUN_OUT="${REGION_ASYMMETRY_RUN_OUT:-generated/corpus/region-asymmetry-companion-v1}"

FEATURE_OUT="${FEATURE_OUT:-analysis/features/$REGION_ASYMMETRY_RUN_LOGICAL_RUN_ID}"
REPLACEMENT_REPORT_OUT="${REPLACEMENT_REPORT_OUT:-analysis/reports/$REGION_ASYMMETRY_RUN_LOGICAL_RUN_ID-skew-replacement-plan}"
BASELINE_FEATURE_DIR="${BASELINE_FEATURE_DIR:-analysis/features/clean-run-v1-flow-ratio-v3}"
BASELINE_INDEX_DIR="${BASELINE_INDEX_DIR:-$INFRA_DIR/generated/runs/corpus-sweeps/_logical-runs/clean-run-v1/_index}"
REPLACEMENT_INDEX_DIR="${REPLACEMENT_INDEX_DIR:-$INFRA_DIR/generated/runs/corpus-sweeps/_logical-runs/$REGION_ASYMMETRY_RUN_LOGICAL_RUN_ID/_index}"

# The current targeted companion uses a region-local asymmetric skew profile.
# This map only controls replacement-plan matching; it does not mutate corpus metadata.
DATASET_MAP="${DATASET_MAP:-pilot-skew-heavy-v1=pilot-region-local-skew-asymmetric-medium-v1}"

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
    log DONE "skew replacement rerun sequence completed"
  else
    record failed "exit_code=$rc"
    log FAIL "skew replacement rerun sequence failed with exit_code=$rc"
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
log INFO "logical_run_id: $REGION_ASYMMETRY_RUN_LOGICAL_RUN_ID"
log INFO "feature_out: $FEATURE_OUT"
log INFO "replacement_report_out: $REPLACEMENT_REPORT_OUT"
record started "$RUN_ID mode=$RUN_MODE logical_run_id=$REGION_ASYMMETRY_RUN_LOGICAL_RUN_ID"

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
log PLAN "validating region-asymmetry corpus"
make_mr region-asymmetry-run-validate
record validate done

record render start
log PLAN "rendering region-asymmetry corpus execution plan"
make_mr region-asymmetry-run-render REGION_ASYMMETRY_RUN_OUT="$REGION_ASYMMETRY_RUN_OUT"
record render done

case "$RUN_MODE" in
  dry-run)
    record dry-run start
    log RUN "dry-run only: no SQL execution"
    make_mr region-asymmetry-run-dry-run \
      REGION_ASYMMETRY_RUN_LABEL="$REGION_ASYMMETRY_RUN_LABEL" \
      REGION_ASYMMETRY_RUN_LOGICAL_RUN_ID="$REGION_ASYMMETRY_RUN_LOGICAL_RUN_ID" \
      REGION_ASYMMETRY_RUN_OUT="$REGION_ASYMMETRY_RUN_OUT"
    record dry-run done
    ;;
  probe)
    record probe start
    log RUN "probe run: one asymmetric group, bounded instance count"
    make_mr region-asymmetry-run-probe-start \
      REGION_ASYMMETRY_RUN_LABEL="$REGION_ASYMMETRY_RUN_LABEL" \
      REGION_ASYMMETRY_RUN_LOGICAL_RUN_ID="$REGION_ASYMMETRY_RUN_LOGICAL_RUN_ID" \
      REGION_ASYMMETRY_RUN_OUT="$REGION_ASYMMETRY_RUN_OUT"
    record probe done
    ;;
  full)
    record full-run start
    log RUN "starting targeted region-asymmetry rerun"
    make_mr region-asymmetry-run-start \
      REGION_ASYMMETRY_RUN_LABEL="$REGION_ASYMMETRY_RUN_LABEL" \
      REGION_ASYMMETRY_RUN_LOGICAL_RUN_ID="$REGION_ASYMMETRY_RUN_LOGICAL_RUN_ID" \
      REGION_ASYMMETRY_RUN_OUT="$REGION_ASYMMETRY_RUN_OUT"
    record full-run done
    ;;
esac

if [[ "$RUN_MODE" != "dry-run" && "$SKIP_INDEX" != "true" ]]; then
  record index start
  log INDEX "indexing logical run $REGION_ASYMMETRY_RUN_LOGICAL_RUN_ID"
  make_mr region-asymmetry-run-index \
    REGION_ASYMMETRY_RUN_LOGICAL_RUN_ID="$REGION_ASYMMETRY_RUN_LOGICAL_RUN_ID"
  record index done
elif [[ "$RUN_MODE" == "dry-run" ]]; then
  log INDEX "index skipped for dry-run"
  record index skipped-dry-run
else
  log INDEX "index skipped by SKIP_INDEX=true"
  record index skipped
fi

if [[ "$RUN_MODE" != "dry-run" && "$BUILD_FEATURES" == "true" ]]; then
  record feature-matrix start
  log FEATURE "building feature matrix from logical index"
  make_mr feature-matrix \
    LOGICAL_RUN_ID="$REGION_ASYMMETRY_RUN_LOGICAL_RUN_ID" \
    FEATURES_OUT="$FEATURE_OUT"
  record feature-matrix done
else
  log FEATURE "feature matrix skipped"
  record feature-matrix skipped
fi

if [[ "$RUN_MODE" != "dry-run" && "$BUILD_REPLACEMENT_PLAN" == "true" ]]; then
  record replacement-plan start
  log PLAN "building skew replacement plan"
  write_overlay_args=()
  if [[ "$WRITE_OVERLAY" == "true" ]]; then
    write_overlay_args+=(--write-overlay)
  fi
  (
    cd "$ROOT"
    uv run python analysis/scripts/agent/33_skew_replacement_plan.py \
      --baseline-feature-dir "$BASELINE_FEATURE_DIR" \
      --replacement-feature-dir "$FEATURE_OUT" \
      --baseline-index-dir "$BASELINE_INDEX_DIR" \
      --replacement-index-dir "$REPLACEMENT_INDEX_DIR" \
      --out-dir "$REPLACEMENT_REPORT_OUT" \
      --dataset-map "$DATASET_MAP" \
      "${write_overlay_args[@]}"
  )
  record replacement-plan done
else
  log PLAN "replacement plan skipped"
  record replacement-plan skipped
fi
