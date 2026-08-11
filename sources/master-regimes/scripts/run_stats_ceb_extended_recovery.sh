#!/usr/bin/env bash
set -Eeuo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
INFRA_DIR="${MASTER_REGIMES_INFRA_DIR:-$ROOT/../master-regimes-infra}"
LOGICAL_RUN_ID="stats-ceb-full-recovery-1800s-v1"
RUN_ID="${RUN_ID:-$(date -u +%Y%m%dT%H%M%SZ)-stats-ceb-recovery-1800s}"
LABEL="${STATS_CEB_RECOVERY_LABEL:-$LOGICAL_RUN_ID-attempt-01}"
LOG_DIR="${LOG_DIR:-$ROOT/generated/stats-ceb-recovery-runs/$RUN_ID}"
LOG_FILE="$LOG_DIR/recovery.log"
STATUS_FILE="$LOG_DIR/status.tsv"
LOGICAL_DIR="$INFRA_DIR/generated/runs/corpus-sweeps/_logical-runs/$LOGICAL_RUN_ID"

MODE="run"
SKIP_PREFLIGHT="${SKIP_PREFLIGHT:-false}"

usage() {
  cat <<'EOF'
Usage:
  scripts/run_stats_ceb_extended_recovery.sh [--dry-run|--analyze-only]

Modes:
  default         Validate, dry-run, execute 16 queries, index and analyze.
  --dry-run       Validate and render only; no SQL is executed.
  --analyze-only  Index and analyze an already completed recovery run.

The recovery contract is intentionally fixed:
  timeout:        1800 seconds per phase
  queries:        16 predeclared primary incomplete cases
  repetitions:    1
  concurrency:    1 query
  model refit:    prohibited

The script never deletes or overwrites the primary 300-second audit and never
shuts down the infrastructure.
EOF
}

case "${1:-}" in
  "")
    ;;
  --dry-run)
    MODE="dry-run"
    ;;
  --analyze-only)
    MODE="analyze-only"
    ;;
  -h|--help)
    usage
    exit 0
    ;;
  *)
    usage >&2
    exit 2
    ;;
esac

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
    record done ok
    log DONE "STATS-CEB recovery workflow completed"
  else
    record failed "exit_code=$rc"
    log FAIL "workflow stopped with exit_code=$rc"
    log INFO "Existing raw artifacts were not deleted"
  fi
  log INFO "log: $LOG_FILE"
  log INFO "status: $STATUS_FILE"
  exit "$rc"
}

on_interrupt() {
  record interrupted "$1"
  log STOP "received $1; current command is being stopped"
  log INFO "Primary stats-ceb-full-no-refit-v1 result remains unchanged"
  exit "$2"
}

trap on_exit EXIT
trap 'on_interrupt SIGINT 130' INT
trap 'on_interrupt SIGTERM 143' TERM

log INFO "mode: $MODE"
log INFO "logical_run_id: $LOGICAL_RUN_ID"
log INFO "fixed timeout: 1800 seconds"
log INFO "query count: 16"
log INFO "query concurrency: 1"
record started "$RUN_ID mode=$MODE"

if [[ "$MODE" == "analyze-only" ]]; then
  record analysis start
  make_mr stats-ceb-recovery-analyze
  record analysis done
  exit 0
fi

record contract-gate start
make_mr stats-ceb-recovery-local-gate
record contract-gate done

if [[ "$SKIP_PREFLIGHT" != "true" ]]; then
  record infrastructure-preflight start
  log CHECK "validating local infrastructure environment"
  make_infra configure-env-check
  log CHECK "checking EU+US+GAC node reachability"
  make_infra eu-us-gac-vps-ping
  record infrastructure-preflight done
else
  log CHECK "infrastructure preflight skipped by SKIP_PREFLIGHT=true"
  record infrastructure-preflight skipped
fi

record infrastructure-dry-run start
make_mr stats-ceb-recovery-infra-dry-run
record infrastructure-dry-run done

if [[ "$MODE" == "dry-run" ]]; then
  log DONE "dry-run passed; no SQL query was executed"
  exit 0
fi

EXISTING_ATTEMPT="$(
  python3 - "$INFRA_DIR/generated/runs/corpus-sweeps" "$LOGICAL_RUN_ID" <<'PY'
import json
import sys
from pathlib import Path

root = Path(sys.argv[1])
logical_run_id = sys.argv[2]
for path in sorted(root.glob("*/corpus_execution_manifest.json")):
    try:
        manifest = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        continue
    if (
        manifest.get("logical_run_id") == logical_run_id
        and manifest.get("dry_run") is not True
    ):
        attempt_dir = path.parent
        correctness_started = any(
            candidate.is_dir()
            for candidate in attempt_dir.glob(
                "database-sweeps/**/result-validation"
            )
        )
        query_started = any(
            candidate.is_dir()
            for candidate in attempt_dir.glob(
                "database-sweeps/**/query-collections"
            )
        )
        if correctness_started or query_started:
            print(attempt_dir)
            break
PY
)"
if [[ -n "$EXISTING_ATTEMPT" || -e "$LOGICAL_DIR" ]]; then
  log FAIL "a real recovery attempt already exists"
  [[ -n "$EXISTING_ATTEMPT" ]] && log INFO "attempt: $EXISTING_ATTEMPT"
  [[ -e "$LOGICAL_DIR" ]] && log INFO "logical index: $LOGICAL_DIR"
  log INFO "Use --analyze-only instead of creating an unplanned second attempt"
  exit 1
fi

record execution start
log RUN "starting one fixed extended-budget attempt"
log RUN "worst-case duration can be many hours because each phase is sequential"
make_mr stats-ceb-recovery-start STATS_CEB_RECOVERY_LABEL="$LABEL"
record execution done

record analysis start
make_mr stats-ceb-recovery-analyze
record analysis done

log RESULT "primary 300-second audit was preserved"
log RESULT "recovery summary: analysis/reports/$LOGICAL_RUN_ID-summary/README.md"
