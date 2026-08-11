from __future__ import annotations

import argparse
import json
from collections import defaultdict
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_STATE = (
    REPO_ROOT
    / "generated/pressure-raw-runs/batch-000-collection-smoke/run/status.json"
)


def load_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"Expected JSON object in {path}")
    return value


def query_collection_manifests(artifact: Path) -> list[Path]:
    return [
        path
        for path in artifact.rglob("execution_manifest.json")
        if path.parent.parent.name == "query-collections"
    ]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--state", type=Path, default=DEFAULT_STATE)
    parser.add_argument(
        "--out",
        type=Path,
        default=REPO_ROOT / "analysis/reports/pressure-raw-v1-collection-smoke",
    )
    args = parser.parse_args()
    state = load_json(args.state.resolve())
    artifacts = [
        Path(segment["artifact"])
        for segment in state.get("segments", {}).values()
        if segment.get("status") == "completed" and segment.get("artifact")
    ]
    errors: list[str] = []
    warnings: list[str] = []
    collection_manifests: list[tuple[Path, dict[str, Any]]] = []
    for artifact in artifacts:
        if not artifact.exists():
            errors.append(f"missing segment artifact: {artifact}")
            continue
        if not any(artifact.rglob("_index/query_runs.csv")):
            errors.append(f"raw index missing: {artifact}")
        for manifest_path in query_collection_manifests(artifact):
            collection_manifests.append((manifest_path, load_json(manifest_path)))

    if len(collection_manifests) != 30:
        errors.append(
            f"query collection count={len(collection_manifests)}, expected 30"
        )

    pair_rows: dict[str, list[dict[str, Any]]] = defaultdict(list)
    complete_plan_count = 0
    telemetry_count = 0
    signature_count = 0
    no_result_rows_count = 0
    legacy_signature_pointer_count = 0
    for manifest_path, manifest in collection_manifests:
        metadata = manifest.get("execution_metadata") or {}
        pair_id = str(metadata.get("pair_id", ""))
        if not pair_id:
            errors.append(f"pair_id missing: {manifest_path}")
        pair_rows[pair_id].append(
            {
                "variant": metadata.get("variant", ""),
                "repeat_id": metadata.get("repeat_id", ""),
                "manifest": str(manifest_path),
                "signature": "",
            }
        )
        signature = manifest.get("result_signature") or {}
        signature_path = manifest_path.parent / str(signature.get("artifact", ""))
        if signature.get("status") == "completed" and not signature_path.exists():
            coordinator = str(manifest.get("coordinator", ""))
            artifact_rel = (manifest.get("local_artifacts") or {}).get(
                coordinator, ""
            )
            candidates = list(
                (manifest_path.parent / str(artifact_rel)).glob(
                    "results/*.result-signature.json"
                )
            )
            if len(candidates) == 1:
                signature_path = candidates[0]
                legacy_signature_pointer_count += 1
        if signature.get("status") == "completed" and signature_path.exists():
            payload = load_json(signature_path)
            pair_rows[pair_id][-1]["signature"] = payload.get("multiset_sha256", "")
            signature_count += 1
            if payload.get("database_result_rows_stored") is False:
                no_result_rows_count += 1
        else:
            errors.append(f"result signature incomplete: {manifest_path}")

        coordinator = str(manifest.get("coordinator", ""))
        artifact_rel = (manifest.get("local_artifacts") or {}).get(coordinator, "")
        node_root = manifest_path.parent / str(artifact_rel)
        if any(node_root.glob("plans/*.explain.json")):
            complete_plan_count += 1
        else:
            errors.append(f"main JSON plan missing: {manifest_path}")
        if (node_root / "metrics/os_summary.json").exists():
            telemetry_count += 1
        else:
            errors.append(f"OS telemetry missing: {manifest_path}")

    for pair_id, rows in pair_rows.items():
        variants = {str(row["variant"]) for row in rows}
        if variants != {"mitigated", "stressed"}:
            errors.append(f"{pair_id}: variants={sorted(variants)}")
        if len(rows) != 6:
            errors.append(f"{pair_id}: execution count={len(rows)}, expected 6")
        signatures = {str(row["signature"]) for row in rows if row["signature"]}
        if len(signatures) != 1:
            manifests = [load_json(Path(str(row["manifest"]))) for row in rows]
            anchored = all(
                "as_of_unix" in (manifest.get("variables") or [])
                or any(
                    str(value).startswith("as_of_unix=")
                    for value in (manifest.get("variables") or [])
                )
                for manifest in manifests
            )
            message = f"{pair_id}: result signatures differ or are missing"
            if anchored:
                errors.append(message)
            else:
                warnings.append(
                    message
                    + "; legacy smoke used moving now(), fixed by the "
                    "versioned as_of_unix contract"
                )

    remote_artifacts = [
        path
        for path in artifacts
        if "remote_path" in path.name or "remote_path" in str(path)
    ]
    network_measurements = [
        path
        for artifact in remote_artifacts
        for path in artifact.rglob("network_profile_measurement.json")
    ]
    if not network_measurements:
        errors.append("remote smoke has no measured network profile")
    for measurement_path in network_measurements:
        measurement = load_json(measurement_path)
        if measurement.get("status") != "completed":
            errors.append(f"network measurement incomplete: {measurement_path}")
            continue
        regional_measurements = measurement.get("measurements") or {}
        if set(regional_measurements) != {"eu-coord-1", "us-coord-1"}:
            errors.append(
                f"network measurement region coverage incomplete: {measurement_path}"
            )
        for region, values in regional_measurements.items():
            if float(values.get("achieved_receiver_bits_per_second") or 0) <= 0:
                errors.append(
                    f"measured receiver bandwidth missing for {region}: "
                    f"{measurement_path}"
                )
    network_interventions = [
        load_json(path)
        for artifact in remote_artifacts
        for path in artifact.rglob("network_intervention_manifest.json")
    ]
    actions = {
        (str(item.get("action")), str(item.get("status")))
        for item in network_interventions
    }
    if ("apply", "ok") not in actions or ("reset", "ok") not in actions:
        errors.append(f"network apply/reset evidence incomplete: {sorted(actions)}")
    if legacy_signature_pointer_count:
        warnings.append(
            f"{legacy_signature_pointer_count} legacy manifests used a stale "
            "result-signature pointer; artifacts were present and future pointers "
            "use the remote SQL stem"
        )

    report = {
        "status": (
            "failed"
            if errors
            else ("ok_with_legacy_warnings" if warnings else "ok")
        ),
        "segment_artifact_count": len(artifacts),
        "query_collection_count": len(collection_manifests),
        "pair_count": len(pair_rows),
        "main_plan_count": complete_plan_count,
        "os_telemetry_count": telemetry_count,
        "result_signature_count": signature_count,
        "legacy_result_signature_pointer_count": legacy_signature_pointer_count,
        "no_database_result_rows_count": no_result_rows_count,
        "network_measurement_count": len(network_measurements),
        "warnings": warnings,
        "errors": errors,
    }
    args.out.mkdir(parents=True, exist_ok=True)
    report_path = args.out / "smoke_validation_report.json"
    report_path.write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(report_path)
    return 0 if not errors else 1


if __name__ == "__main__":
    raise SystemExit(main())
