#!/usr/bin/env python3
"""Validate and render the offline feedback-loop experiment contract."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from jinja2 import Environment, meta

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

from master_regimes.feedback_loop import (  # noqa: E402
    load_yaml,
    render_dry_run_plan,
    validate_authoritative_rq_h_text,
    validate_dry_run_plan,
    validate_intervention_catalog,
    validate_pressure_domain_manifest,
    validate_query_trajectory_manifest,
    write_dry_run_plan,
)


def _check(name: str, errors: list[str]) -> dict[str, Any]:
    return {"name": name, "passed": not errors, "errors": errors}


def _validate_schema(path: Path) -> list[str]:
    errors: list[str] = []
    try:
        schema = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return [f"invalid JSON schema: {exc}"]
    if schema.get("$schema") != "https://json-schema.org/draft/2020-12/schema":
        errors.append("decision schema must use JSON Schema 2020-12")
    definitions = schema.get("$defs", {})
    if not {"base", "decision", "outcome"}.issubset(definitions):
        errors.append("decision schema needs base, decision and outcome definitions")
    schema_text = path.read_text(encoding="utf-8")
    for field in (
        "history_cutoff_utc",
        "locked_pre_execution",
        "expected_end_to_end_impact",
        "known_risks",
        "rollback_plan",
        "outcome_label",
    ):
        if field not in schema_text:
            errors.append(f"decision schema does not mention {field}")
    return errors


def _validate_rollback_document(path: Path, catalog: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    text = path.read_text(encoding="utf-8")
    for token in (
        "pre-action snapshot",
        "FDW server",
        "Mrežni edge",
        "Fail-closed",
    ):
        if token not in text:
            errors.append(f"rollback checklist is missing {token!r}")
    for action in catalog["interventions"]:
        if not action["rollback"].get("verify_command"):
            errors.append(f"{action['id']}: rollback verification is missing")
    return errors


def _validate_query_corpus_references(manifest: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    for trajectory in manifest.get("trajectories", []):
        trajectory_id = trajectory.get("id", "<unknown>")
        suite_path = ROOT / str(trajectory.get("suite", ""))
        if not suite_path.is_file():
            errors.append(f"{trajectory_id}: missing query suite {suite_path}")
            continue
        suite = load_yaml(suite_path)
        templates = suite.get("templates", {})
        template_ids = [trajectory.get("baseline_template_id")]
        template_ids.extend(trajectory.get("reviewed_equivalent_template_ids", []))
        for template_id in template_ids:
            if template_id not in templates:
                errors.append(f"{trajectory_id}: unknown template {template_id!r}")
                continue
            template_path = suite_path.parents[1] / str(templates[template_id].get("file", ""))
            if not template_path.is_file():
                errors.append(
                    f"{trajectory_id}: missing SQL template for {template_id!r}: {template_path}"
                )
                continue
            template_text = template_path.read_text(encoding="utf-8")
            required_parameters = meta.find_undeclared_variables(Environment().parse(template_text))
            bindings = set(trajectory.get("parameter_bindings", {}))
            missing_parameters = required_parameters - bindings
            if missing_parameters:
                errors.append(
                    f"{trajectory_id}: template {template_id!r} needs missing "
                    f"bindings {sorted(missing_parameters)}"
                )
    return errors


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--experiment-dir",
        type=Path,
        default=ROOT / "experiments/feedback-loop-v1",
    )
    parser.add_argument(
        "--thesis-root",
        type=Path,
        default=ROOT.parent / "master-regimes-thesis",
    )
    parser.add_argument("--report", type=Path)
    args = parser.parse_args()

    experiment_dir = args.experiment_dir.resolve()
    report_path = (args.report or experiment_dir / "dry_run_validation.json").resolve()
    domain_manifest = load_yaml(experiment_dir / "pressure_domain_manifest.yaml")
    intervention_catalog = load_yaml(experiment_dir / "intervention_catalog.yaml")
    trajectory_manifest = load_yaml(experiment_dir / "query_trajectory_manifest.yaml")

    checks: list[dict[str, Any]] = []
    checks.append(
        _check(
            "pressure_domain_manifest",
            validate_pressure_domain_manifest(domain_manifest),
        )
    )
    checks.append(
        _check(
            "intervention_catalog",
            validate_intervention_catalog(intervention_catalog),
        )
    )
    checks.append(
        _check(
            "query_trajectory_manifest",
            validate_query_trajectory_manifest(
                trajectory_manifest,
                intervention_catalog,
            ),
        )
    )
    checks.append(
        _check(
            "query_corpus_references",
            _validate_query_corpus_references(trajectory_manifest),
        )
    )
    checks.append(
        _check(
            "decision_log_schema",
            _validate_schema(experiment_dir / "schemas/decision_log.schema.json"),
        )
    )
    checks.append(
        _check(
            "rollback_contract",
            _validate_rollback_document(
                experiment_dir / "rollback_checklist.md",
                intervention_catalog,
            ),
        )
    )

    fixed_text = (experiment_dir / "RQ_H_MAPPING.md").read_text(encoding="utf-8")
    rq_h_errors = validate_authoritative_rq_h_text(fixed_text)
    thesis_intro = args.thesis_root / "manuscript/chapters/01-uvod.tex"
    if not thesis_intro.is_file():
        rq_h_errors.append(f"missing thesis intro: {thesis_intro}")
    else:
        rq_h_errors.extend(
            f"thesis intro: {error}"
            for error in validate_authoritative_rq_h_text(thesis_intro.read_text(encoding="utf-8"))
        )
    checks.append(_check("authoritative_rq_h_unchanged", rq_h_errors))

    plan = render_dry_run_plan(trajectory_manifest)
    plan_path = experiment_dir / "dry_run_plan.csv"
    write_dry_run_plan(plan, plan_path)
    checks.append(_check("dry_run_plan", validate_dry_run_plan(plan, trajectory_manifest)))

    expected_count = sum(bool(row["included_in_expected_count"]) for row in plan)
    payload = {
        "contract_version": "feedback-loop-offline-gate-v1",
        "status": "PASS" if all(check["passed"] for check in checks) else "FAIL",
        "live_sql_executed": False,
        "dataset_reload_required": False,
        "colocation_change_required": False,
        "shard_placement_change_required": False,
        "index_change_required": False,
        "domain_count": len(domain_manifest["domains"]),
        "trajectory_count": len(trajectory_manifest["trajectories"]),
        "intervention_count": len(intervention_catalog["interventions"]),
        "expected_execution_count": expected_count,
        "maximum_execution_count": len(plan),
        "maximum_total_wall_clock_budget_seconds": trajectory_manifest["experiment"][
            "maximum_total_wall_clock_budget_seconds"
        ],
        "checks": checks,
    }
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    print(report_path)
    return 0 if payload["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
