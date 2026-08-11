#!/usr/bin/env python3
"""Prepare, materialize, and analyze a live feedback-loop release."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

from master_regimes.feedback_loop_live import (  # noqa: E402
    analyze_state,
    append_decision,
    capture_initial_snapshot,
    capture_mutable_snapshot,
    create_frozen_replay_manifests,
    create_smoke_manifest,
    create_state_instance_manifest,
    decision_record,
    finalize_feedback_loop_run,
    prepare_run,
    record_transition,
    refresh_checksums,
    supersede_invalid_replay_attempt,
)


def main() -> int:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)

    prepare = subparsers.add_parser("prepare")
    prepare.add_argument("--run-root", type=Path, required=True)
    prepare.add_argument("--infra-root", type=Path, default=ROOT.parent / "master-regimes-infra")

    snapshot = subparsers.add_parser("initial-snapshot")
    snapshot.add_argument("--run-root", type=Path, required=True)
    snapshot.add_argument("--infra-root", type=Path, default=ROOT.parent / "master-regimes-infra")

    mutable_snapshot = subparsers.add_parser("mutable-snapshot")
    mutable_snapshot.add_argument("--run-root", type=Path, required=True)
    mutable_snapshot.add_argument("--label", required=True)
    mutable_snapshot.add_argument(
        "--infra-root", type=Path, default=ROOT.parent / "master-regimes-infra"
    )
    prepare.add_argument("--thesis-root", type=Path, default=ROOT.parent / "master-regimes-thesis")

    manifest = subparsers.add_parser("state-manifest")
    manifest.add_argument("--run-root", type=Path, required=True)
    manifest.add_argument("--trajectory-id", required=True)
    manifest.add_argument("--state-id", required=True)
    manifest.add_argument("--phase", required=True)
    manifest.add_argument("--step-index", type=int, required=True)
    manifest.add_argument("--action-id", required=True)
    manifest.add_argument("--template-id", required=True)
    manifest.add_argument("--repetitions", type=int, required=True)
    manifest.add_argument("--pg-option", action="append", default=[])

    smoke = subparsers.add_parser("smoke-manifest")
    smoke.add_argument("--run-root", type=Path, required=True)

    replay_manifests = subparsers.add_parser("replay-manifests")
    replay_manifests.add_argument("--run-root", type=Path, required=True)

    analyze = subparsers.add_parser("analyze-state")
    analyze.add_argument("--run-root", type=Path, required=True)
    analyze.add_argument("--state-id", required=True)
    analyze.add_argument("--phase", required=True)
    analyze.add_argument("--trajectory-id", required=True)
    analyze.add_argument("--step-index", type=int, required=True)
    analyze.add_argument("--action-id", required=True)
    analyze.add_argument("--template-id", required=True)
    analyze.add_argument("--sweep-dir", type=Path, action="append", required=True)
    analyze.add_argument("--origin-state-id")
    analyze.add_argument("--previous-state-id")
    analyze.add_argument("--history-state-id", action="append", default=[])

    decision = subparsers.add_parser("append-record")
    decision.add_argument("--run-root", type=Path, required=True)
    decision.add_argument("--record-json", type=Path, required=True)

    lock = subparsers.add_parser("lock-decision")
    lock.add_argument("--run-root", type=Path, required=True)
    lock.add_argument("--decision-id", required=True)
    lock.add_argument("--trajectory-id", required=True)
    lock.add_argument("--step-index", type=int, required=True)
    lock.add_argument("--source-state-id", required=True)
    lock.add_argument("--action-id", required=True)
    lock.add_argument("--hypothesis", required=True)
    lock.add_argument("--target-domain", action="append", required=True)
    lock.add_argument("--expected-direction", action="append", required=True)
    lock.add_argument("--expected-end-to-end-impact", required=True)
    lock.add_argument("--known-risk", action="append", required=True)
    lock.add_argument("--rollback-plan", required=True)
    lock.add_argument("--evidence-ref", action="append", required=True)
    lock.add_argument("--identity-mode", required=True)
    lock.add_argument("--applicability-status", default="applicable")

    checksums = subparsers.add_parser("checksums")
    checksums.add_argument("--run-root", type=Path, required=True)

    finalize = subparsers.add_parser("finalize")
    finalize.add_argument("--run-root", type=Path, required=True)

    supersede = subparsers.add_parser("supersede-replay-attempt")
    supersede.add_argument("--run-root", type=Path, required=True)
    supersede.add_argument("--reason", required=True)

    transition = subparsers.add_parser("record-transition")
    transition.add_argument("--run-root", type=Path, required=True)
    transition.add_argument("--decision-id", required=True)
    transition.add_argument("--trajectory-id", required=True)
    transition.add_argument("--step-index", type=int, required=True)
    transition.add_argument("--source-state-id", required=True)
    transition.add_argument("--target-state-id", required=True)
    transition.add_argument("--action-id", required=True)
    transition.add_argument("--rollback-status", required=True)
    transition.add_argument("--accept-state", action="store_true")

    args = parser.parse_args()
    if args.command == "prepare":
        result = prepare_run(
            repo_root=ROOT,
            infra_root=args.infra_root.resolve(),
            thesis_root=args.thesis_root.resolve(),
            experiment_dir=ROOT / "experiments/feedback-loop-v1",
            run_root=args.run_root.resolve(),
        )
        print(json.dumps(result, indent=2, ensure_ascii=False))
        return 0
    if args.command == "initial-snapshot":
        result = capture_initial_snapshot(
            run_root=args.run_root.resolve(), infra_root=args.infra_root.resolve()
        )
        print(json.dumps(result, indent=2, ensure_ascii=False))
        return 0
    if args.command == "mutable-snapshot":
        result = capture_mutable_snapshot(
            run_root=args.run_root.resolve(),
            infra_root=args.infra_root.resolve(),
            label=args.label,
        )
        print(json.dumps(result, indent=2, ensure_ascii=False))
        return 0
    if args.command == "state-manifest":
        pg_options = dict(option.split("=", 1) for option in args.pg_option)
        path = create_state_instance_manifest(
            run_root=args.run_root.resolve(),
            trajectory_id=args.trajectory_id,
            state_id=args.state_id,
            phase=args.phase,
            step_index=args.step_index,
            action_id=args.action_id,
            template_id=args.template_id,
            repetitions=args.repetitions,
            pg_options=pg_options,
        )
        print(path)
        return 0
    if args.command == "smoke-manifest":
        print(create_smoke_manifest(args.run_root.resolve()))
        return 0
    if args.command == "replay-manifests":
        print(create_frozen_replay_manifests(args.run_root.resolve()))
        return 0
    if args.command == "analyze-state":
        result = analyze_state(
            run_root=args.run_root.resolve(),
            state_id=args.state_id,
            phase=args.phase,
            trajectory_id=args.trajectory_id,
            step_index=args.step_index,
            action_id=args.action_id,
            template_id=args.template_id,
            sweep_dirs=[path.resolve() for path in args.sweep_dir],
            origin_state_id=args.origin_state_id,
            previous_state_id=args.previous_state_id,
            accepted_history_state_ids=args.history_state_id,
        )
        print(json.dumps(result, indent=2, ensure_ascii=False))
        return 0
    if args.command == "append-record":
        record = json.loads(args.record_json.read_text(encoding="utf-8"))
        append_decision(args.run_root.resolve(), record)
        print(args.run_root.resolve() / "decision_log.jsonl")
        return 0
    if args.command == "lock-decision":
        directions = dict(value.split("=", 1) for value in args.expected_direction)
        record = decision_record(
            decision_id=args.decision_id,
            trajectory_id=args.trajectory_id,
            step_index=args.step_index,
            source_state_id=args.source_state_id,
            action_id=args.action_id,
            hypothesis=args.hypothesis,
            target_domains=args.target_domain,
            expected_domain_directions=directions,
            expected_end_to_end_impact=args.expected_end_to_end_impact,
            known_risks=args.known_risk,
            rollback_plan=args.rollback_plan,
            evidence_snapshot_refs=args.evidence_ref,
            identity_mode=args.identity_mode,
            applicability_status=args.applicability_status,
        )
        append_decision(args.run_root.resolve(), record)
        print(json.dumps(record, indent=2, ensure_ascii=False))
        return 0
    if args.command == "checksums":
        print(refresh_checksums(args.run_root.resolve()))
        return 0
    if args.command == "finalize":
        result = finalize_feedback_loop_run(args.run_root.resolve())
        print(json.dumps(result, indent=2, ensure_ascii=False))
        return 0
    if args.command == "supersede-replay-attempt":
        result = supersede_invalid_replay_attempt(args.run_root.resolve(), reason=args.reason)
        print(json.dumps(result, indent=2, ensure_ascii=False))
        return 0
    if args.command == "record-transition":
        result = record_transition(
            run_root=args.run_root.resolve(),
            decision_id=args.decision_id,
            trajectory_id=args.trajectory_id,
            step_index=args.step_index,
            source_state_id=args.source_state_id,
            target_state_id=args.target_state_id,
            action_id=args.action_id,
            rollback_status=args.rollback_status,
            accept_state=args.accept_state,
        )
        print(json.dumps(result, indent=2, ensure_ascii=False))
        return 0
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
