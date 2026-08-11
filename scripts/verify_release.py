#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import hashlib
import ipaddress
import io
import json
import re
import tarfile
from pathlib import Path

MANIFEST = Path("artifacts/release-manifest.json")
CLAIM_MAP = Path("artifacts/claim-evidence-map.json")
THESIS_PATHS = Path("config/thesis-paths.txt")
FORBIDDEN_RESULT_NAMES = (
    "query_results",
    "result_rows",
    "result_set",
    "database_rows",
)
PUBLIC_TEXT_SUFFIXES = {".csv", ".json", ".md", ".sql", ".txt", ".yaml", ".yml"}


def digest(path: Path) -> str:
    value = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            value.update(chunk)
    return value.hexdigest()


def verify_hashes(root: Path) -> None:
    manifest_path = root / MANIFEST
    if not manifest_path.exists():
        raise ValueError("Nedostaje release manifest. Pokrenuti `make release-manifest`.")
    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    rows = payload["files"]
    if int(payload["file_count"]) != len(rows):
        raise ValueError("Manifest file_count nije konzistentan")
    for index, row in enumerate(rows, start=1):
        path = root / row["path"]
        if not path.is_file():
            raise ValueError(f"Nedostaje manifest fajl: {row['path']}")
        if path.stat().st_size != int(row["size"]):
            raise ValueError(f"Velicina se razlikuje: {row['path']}")
        if digest(path) != row["sha256"]:
            raise ValueError(f"SHA-256 se razlikuje: {row['path']}")
        if index % 500 == 0:
            print(f"[verify] hashes {index}/{len(rows)}", flush=True)
    print(f"[verify] hashes PASS ({len(rows)} files)")


def archive_csv_rows(
    archive: tarfile.TarFile,
    logical_run_id: str,
    filename: str,
) -> int:
    exact = f"{logical_run_id}/_index/{filename}"
    suffix = f"/{exact}"
    candidates = [
        member
        for member in archive.getmembers()
        if member.name == exact or member.name.endswith(suffix)
    ]
    if len(candidates) != 1:
        raise ValueError(
            f"{logical_run_id}: expected one {filename}, got {len(candidates)}"
        )
    handle = archive.extractfile(candidates[0])
    if handle is None:
        raise ValueError(f"Cannot read {candidates[0].name}")
    return max(sum(1 for _ in io.TextIOWrapper(handle, encoding="utf-8")) - 1, 0)


def verify_archives(root: Path, spec: dict) -> None:
    mapping = {
        "query_runs": "query_runs.csv",
        "execution_features": "execution_features.csv",
        "region_fragments": "region_fragments.csv",
        "worker_task_fragments": "worker_task_fragments.csv",
        "remote_edge_observations": "remote_edge_observations.csv",
    }
    for logical_run_id, expected in spec["logical_runs"].items():
        path = root / "artifacts" / "logical-indexes" / f"{logical_run_id}.tar.gz"
        if not path.exists():
            raise ValueError(f"Nedostaje logical archive: {path}")
        with tarfile.open(path, "r:gz") as archive:
            for member in archive.getmembers():
                parts = Path(member.name).parts
                if (
                    Path(member.name).is_absolute()
                    or ".." in parts
                    or member.issym()
                    or member.islnk()
                ):
                    raise ValueError(f"Nesiguran archive member: {member.name}")
            for key, filename in mapping.items():
                if key not in expected:
                    continue
                observed = archive_csv_rows(archive, logical_run_id, filename)
                if observed != int(expected[key]):
                    raise ValueError(
                        f"{logical_run_id}/{filename}: "
                        f"expected={expected[key]} observed={observed}"
                    )
        print(f"[verify] logical index PASS {logical_run_id}")

    for path in sorted((root / "artifacts" / "raw-attempts").glob("*.tar.gz")):
        with tarfile.open(path, "r:gz") as archive:
            for member in archive.getmembers():
                name = member.name.lower()
                if (
                    Path(member.name).is_absolute()
                    or ".." in Path(member.name).parts
                    or member.issym()
                    or member.islnk()
                ):
                    raise ValueError(f"Nesiguran raw archive member: {member.name}")
                if any(token in Path(name).name for token in FORBIDDEN_RESULT_NAMES):
                    raise ValueError(
                        f"Moguci database result rows u arhivi: {member.name}"
                    )
        print(f"[verify] raw archive PASS {path.name}")


def csv_rows(path: Path) -> int:
    with path.open("rb") as handle:
        return max(sum(1 for _ in handle) - 1, 0)


def verify_comparative_fcm(root: Path, spec: dict) -> None:
    model = spec["comparative_fcm"]
    model_dir = root / "artifacts" / "results" / "semantic-v2-model-freeze"
    centers = model_dir / "cluster_centers_k4.csv"
    memberships = model_dir / "baseline_memberships_k4.csv"
    if csv_rows(centers) != int(model["primary_k"]):
        raise ValueError("K4 center count mismatch")
    if csv_rows(memberships) != int(model["training_rows"]):
        raise ValueError("K4 membership row count mismatch")
    header = centers.open(encoding="utf-8").readline().strip().split(",")
    if len(header) - 1 != int(model["feature_count"]):
        raise ValueError("Final feature count mismatch")
    semantic_rows = csv_rows(
        root
        / "artifacts"
        / "features"
        / "clean-run-v1-semantic-v2"
        / "execution_features_all.csv"
    )
    if semantic_rows != int(model["training_rows"]):
        raise ValueError("Final semantic feature row count mismatch")
    print("[verify] comparative FCM PASS")


def read_csv_rows(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def verify_nested_checksums(root: Path) -> None:
    path = root / "checksums.sha256"
    for line in path.read_text(encoding="utf-8").splitlines():
        checksum, relative = line.split("  ", maxsplit=1)
        candidate = root / relative
        if not candidate.is_file() or digest(candidate) != checksum:
            raise ValueError(f"Nested checksum mismatch: {root.name}/{relative}")


def verify_no_local_paths(root: Path) -> None:
    for path in root.rglob("*"):
        if not path.is_file() or path.suffix.lower() not in PUBLIC_TEXT_SUFFIXES:
            continue
        if "/home/" in path.read_text(encoding="utf-8"):
            raise ValueError(f"Public artifact contains a local path: {path}")


def verify_archive_has_no_local_paths(path: Path) -> None:
    with tarfile.open(path, "r:gz") as archive:
        for member in archive.getmembers():
            if not member.isfile() or Path(member.name).suffix.lower() not in PUBLIC_TEXT_SUFFIXES:
                continue
            handle = archive.extractfile(member)
            if handle is not None and b"/home/" in handle.read():
                raise ValueError(
                    f"Public archive member contains a local path: {member.name}"
                )


def verify_actionability(root: Path, spec: dict) -> None:
    package = root / "artifacts/results/pressure-actionability-v1"
    verify_nested_checksums(package)
    verify_no_local_paths(package)
    verify_no_local_paths(
        root / "artifacts/rendered-corpora/pressure-raw-v1-n3-colocation-holdout"
    )
    verify_archive_has_no_local_paths(
        root
        / "artifacts/logical-indexes/pressure-raw-v1-n3-colocation-holdout.tar.gz"
    )
    curated = json.loads(
        (package / "curation_manifest.json").read_text(encoding="utf-8")
    )
    source = json.loads(
        (package / "source_release_manifest.json").read_text(encoding="utf-8")
    )
    expected_evidence = spec["actionability_evidence"]
    evidence = curated["evidence"]
    for key, expected in expected_evidence.items():
        evidence_key = "n3_no_refit_verified" if key == "n3_no_refit" else key
        if evidence.get(evidence_key) != expected:
            raise ValueError(
                f"Actionability evidence mismatch {key}: "
                f"expected={expected} observed={evidence.get(evidence_key)}"
            )
    if curated["source_evidence_generation_commit"] != source[
        "evidence_generation_commit"
    ]:
        raise ValueError("Curated actionability provenance is inconsistent")

    model_spec = spec["primary_actionability_model"]
    benchmark = json.loads(
        (package / "ranking/benchmark_manifest.json").read_text(encoding="utf-8")
    )
    expected_estimators = {
        "median_baseline",
        "ridge",
        "elastic_net",
        "shallow_gradient_boosting",
    }
    if set(benchmark["benchmark_estimators"]) != expected_estimators:
        raise ValueError("Unexpected Plan 41 robustness benchmark estimators")
    benchmark_contract = {
        "mitigation_action": model_spec["mitigation_action"],
        "primary_estimator": model_spec["estimator"],
        "pair_count": model_spec["training_pairs"],
        "selected_feature_count": model_spec["feature_count"],
        "selected_feature_view": model_spec["feature_view"],
    }
    for key, expected in benchmark_contract.items():
        if benchmark.get(key) != expected:
            raise ValueError(
                f"Ranking benchmark mismatch {key}: "
                f"expected={expected} observed={benchmark.get(key)}"
            )
    if benchmark.get("raw_sql_in_model") is not False:
        raise ValueError("Raw SQL must not enter the actionability regressor")

    summary = read_csv_rows(package / "ranking/ranking_summary.csv")
    observed_estimators = {row["model"] for row in summary}
    if observed_estimators != expected_estimators:
        raise ValueError("Ranking summary does not cover every frozen estimator")
    ablation = read_csv_rows(package / "ranking/feature_view_ablation.csv")
    if not ablation or not all(row["decision"] == "extended" for row in ablation):
        raise ValueError("Core-vs-extended ablation did not select extended features")

    eligibility = json.loads(
        (package / "eligibility/eligibility_manifest.json").read_text(
            encoding="utf-8"
        )
    )
    controlled = eligibility.get("controlled_validation", {})
    if (
        controlled.get("gate") != "GO"
        or eligibility.get("mitigation_action") != model_spec["mitigation_action"]
        or eligibility.get("model_invocation_requires_candidate") is not True
        or eligibility.get("workload_wide_safety_proven") is not False
    ):
        raise ValueError("Deterministic colocation eligibility gate is not GO")

    freeze = json.loads(
        (package / "n3_freeze/freeze_manifest.json").read_text(encoding="utf-8")
    )
    n3 = json.loads(
        (package / "n3_result/analysis_manifest.json").read_text(encoding="utf-8")
    )
    if freeze.get("no_refit") is not True or n3.get("no_refit_verified") is not True:
        raise ValueError("N=3 no-refit contract is not verified")
    before = n3.get("model_sha256_before")
    if before != n3.get("model_sha256_after") or before != freeze["source_sha256"][
        "model"
    ]:
        raise ValueError("Frozen N=3 model hash changed")
    if n3.get("execution_count") != 96 or n3.get("pair_count") != 16:
        raise ValueError("Unexpected N=3 execution or pair count")
    if set(n3.get("regions", [])) != {"eu", "us", "apac"}:
        raise ValueError("N=3 evidence does not contain the expected regions")
    if n3.get("technical_gate") != "GO" or n3.get("ranking_support") != "SUPPORTED":
        raise ValueError("N=3 technical or ranking gate failed")
    metrics = n3["ranking_metrics"]
    rule = n3["ranking_support_rule"]
    for metric, threshold in (
        ("spearman", "minimum_spearman"),
        ("kendall", "minimum_kendall"),
        ("ndcg_at_5", "minimum_ndcg_at_5"),
        ("top5_recall", "minimum_top5_recall"),
    ):
        if float(metrics[metric]) < float(rule[threshold]):
            raise ValueError(f"N=3 ranking threshold failed: {metric}")
    if n3.get("outside_training_p99_count") != 16 or float(metrics["r2"]) >= 0:
        raise ValueError("N=3 coverage/calibration limitation is not preserved")
    expected_scope = (
        "descriptive_ranking_on_16_out_of_coverage_n3_pairs_"
        "not_production_generalization"
    )
    if n3.get("interpretation_scope") != expected_scope:
        raise ValueError("N=3 interpretation is not bounded to the observed OOD pairs")
    bootstrap = read_csv_rows(package / "n3_result/n3_bootstrap_intervals.csv")
    if (
        {row["metric"] for row in bootstrap} != {"spearman", "ndcg_at_5"}
        or any(int(row["valid_resamples"]) != 10_000 for row in bootstrap)
        or any(
            row["method"] != "placement_stratified_pair_bootstrap_percentile"
            for row in bootstrap
        )
    ):
        raise ValueError("N=3 bootstrap evidence is incomplete")
    placements = read_csv_rows(package / "n3_result/n3_metrics_by_placement.csv")
    if (
        {row["placement_profile"] for row in placements}
        != {"balanced", "apac_dominant"}
        or any(int(float(row["pair_count"])) != 8 for row in placements)
    ):
        raise ValueError("N=3 placement-stratified evidence is incomplete")
    pair_ranking = read_csv_rows(package / "n3_result/n3_pair_ranking.csv")
    if len(pair_ranking) != 16 or any(
        row["outside_training_p99"] != "True" for row in pair_ranking
    ):
        raise ValueError("N=3 full ranking does not preserve all OOD pairs")
    print("[verify] Plan 41 actionability and N=3 evidence PASS")


def verify_claim_map(root: Path) -> None:
    path = root / CLAIM_MAP
    payload = json.loads(path.read_text(encoding="utf-8"))
    claims = payload.get("claims", [])
    if not claims:
        raise ValueError("Claim-evidence mapa nema tvrdnji")
    for claim in claims:
        evidence = claim.get("evidence", [])
        if not evidence:
            raise ValueError(f"Tvrdnja nema dokaz: {claim.get('claim_id')}")
        for relative in evidence:
            candidate = root / relative
            if not candidate.is_file():
                raise ValueError(
                    f"Nedostaje dokaz za {claim.get('claim_id')}: {relative}"
                )
    print(f"[verify] claim-evidence map PASS ({len(claims)} claims)")


def verify_retrieval_density_audit(root: Path, spec: dict) -> None:
    contract = spec["retrieval_density_audit"]
    release = root / contract["release"]
    verify_nested_checksums(release)

    manifest = json.loads(
        (release / "analysis_manifest.json").read_text(encoding="utf-8")
    )
    expected_manifest = {
        "complete_case_count": contract["complete_state_count"],
        "complete_action_outcome_count": contract["complete_action_outcome_count"],
        "sql_executions_performed": contract["sql_executions_performed"],
        "state_representation_refit_on_confirmatory_data": contract[
            "representation_refit"
        ],
    }
    for key, expected in expected_manifest.items():
        if manifest.get(key) != expected:
            raise ValueError(
                f"Retrieval-density manifest mismatch {key}: "
                f"expected={expected} observed={manifest.get(key)}"
            )

    comparison = read_csv_rows(release / "prior_panel_memory_comparison.csv")
    all_prior = next(
        row for row in comparison if row["memory_scope"] == "all_prior_panels"
    )
    if (
        int(all_prior["memory_size"]) != contract["prior_state_count"]
        or int(all_prior["recommendation_count"])
        != contract["all_prior_coverage_count"]
        or int(all_prior["candidate_correct_count"])
        != contract["all_prior_candidate_correct_count"]
    ):
        raise ValueError("All-prior retrieval sensitivity differs from the release contract")

    broad = read_csv_rows(release / "broad_corpus_action_matrix_audit.csv")
    if (
        len(broad) != 1
        or int(broad[0]["physical_execution_count"]) != 2607
        or int(broad[0]["controlled_pair_count"]) != 418
        or int(broad[0]["complete_three_target_action_matrix_count"]) != 0
    ):
        raise ValueError("Broad-corpus action-matrix audit is inconsistent")

    required = (
        "README.md",
        "01-learning-coverage-curve.md",
        "02-neighbor-consistency.md",
        "03-state-response-geometry.md",
        "source/116_retrieval_density_geometry_audit.py",
        "inputs/reference/episodes.csv",
        "inputs/final-dba/observed_episode_states.csv",
        "inputs/topology/episode_states.csv",
    )
    missing = [path for path in required if not (release / path).is_file()]
    if missing:
        raise ValueError(f"Retrieval-density audit is incomplete: {missing}")
    print("[verify] retrieval-density sensitivity PASS")


def verify_action_selection_sample_size_audit(root: Path, spec: dict) -> None:
    contract = spec["action_selection_sample_size_audit"]
    release = root / contract["release"]
    verify_nested_checksums(release)

    metrics = read_csv_rows(release / "confirmatory_top1_uncertainty.csv")
    by_mode = {row["mode"]: row for row in metrics}
    prequential = by_mode["prequential_full_feedback"]
    observed = {
        "decision_count": int(prequential["decision_count"]),
        "recommendation_count": int(prequential["recommendation_count"]),
        "correct_recommendation_count": int(
            prequential["correct_recommendation_count"]
        ),
    }
    expected = {
        "decision_count": contract["confirmatory_sql_decision_count"],
        "recommendation_count": contract["prequential_recommendation_count"],
        "correct_recommendation_count": contract["prequential_correct_count"],
    }
    if observed != expected:
        raise ValueError(
            "Action-selection denominator mismatch: "
            f"expected={expected} observed={observed}"
        )

    units = read_csv_rows(release / "experimental_units.csv")
    confirmatory = next(
        row for row in units
        if row["evidence_block"] == "confirmatory new-query panel"
    )
    if (
        int(confirmatory["physical_executions"])
        != contract["confirmatory_physical_execution_count"]
        or int(confirmatory["temporal_decisions"])
        != contract["confirmatory_sql_decision_count"]
        or int(confirmatory["distinct_sql_units"])
        != contract["confirmatory_sql_decision_count"]
    ):
        raise ValueError("Confirmatory execution and decision units are inconsistent")

    paired = json.loads(
        (release / "paired_comparison.json").read_text(encoding="utf-8")
    )
    if (
        paired["confirmatory_physical_executions"]
        != contract["confirmatory_physical_execution_count"]
        or paired["confirmatory_sql_shapes"]
        != contract["confirmatory_sql_decision_count"]
        or paired["prequential_total_correct"]
        != contract["prequential_correct_count"]
    ):
        raise ValueError("Paired action-selection comparison is inconsistent")

    print("[verify] action-selection denominator and uncertainty PASS")


def verify_thesis_paths(root: Path, spec: dict) -> None:
    provenance = spec.get("thesis_reference_artifacts", {})
    if (
        provenance.get("source_repository") != "master-regimes"
        or not re.fullmatch(r"[0-9a-f]{40}", provenance.get("source_commit", ""))
        or provenance.get("path_manifest") != THESIS_PATHS.as_posix()
        or provenance.get("sanitized_for_public_release") is not True
    ):
        raise ValueError("Provenance artefakata koje rukopis navodi nije potpun")
    references = [
        line.strip()
        for line in (root / THESIS_PATHS).read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    ]
    if not references:
        raise ValueError("Lista putanja iz rukopisa je prazna")
    for relative in references:
        candidate = root / relative.rstrip("/")
        expected_directory = relative.endswith("/")
        if expected_directory and not candidate.is_dir():
            raise ValueError(f"Nedostaje direktorij naveden u rukopisu: {relative}")
        if not expected_directory and not candidate.is_file():
            raise ValueError(f"Nedostaje datoteka navedena u rukopisu: {relative}")
    verify_nested_checksums(root / "releases/rq-alignment-v1")
    verify_nested_checksums(root / "releases/rq-alignment-v2")
    verify_nested_checksums(root / "releases/fcm-f21-development-v1")
    verify_nested_checksums(root / "releases/model-lineage-audit-v1")
    verify_nested_checksums(root / "releases/feedback-loop-analysis-v1")
    for relative in ("analysis", "configs", "experiments", "releases"):
        public_root = root / relative
        verify_no_local_paths(public_root)
        for path in public_root.rglob("*"):
            if not path.is_file() or path.suffix.lower() not in PUBLIC_TEXT_SUFFIXES:
                continue
            text = path.read_text(encoding="utf-8")
            for value in re.findall(r"\b(?:\d{1,3}\.){3}\d{1,3}\b", text):
                try:
                    address = ipaddress.ip_address(value)
                except ValueError:
                    continue
                if address.is_private:
                    raise ValueError(f"Javni artefakt sadrzi privatnu IP adresu: {path}")
    print(f"[verify] thesis paths PASS ({len(references)} references)")


def verify_representative_cases(root: Path) -> None:
    examples = root / "examples"
    expected = {"CASE-AGG-01", "CASE-JOIN-01", "CASE-WAN-01"}
    observed = {path.name for path in examples.glob("CASE-*") if path.is_dir()}
    if observed != expected:
        raise ValueError(
            f"Representative case set mismatch: expected={expected} observed={observed}"
        )

    for case_id in expected:
        case = examples / case_id
        for name in ("README.md", "manifest.json", "metrics.csv"):
            if not (case / name).is_file():
                raise ValueError(f"Missing representative artifact: {case_id}/{name}")
        manifest = json.loads((case / "manifest.json").read_text(encoding="utf-8"))
        hashes = manifest.get("result_hashes", {})
        if manifest.get("case_id") != case_id or not hashes.get("multiset_sha256"):
            raise ValueError(f"Invalid representative manifest: {case_id}")
        time_contract = manifest.get("dataset_time_contract", {})
        if (
            time_contract.get("base_time_unix") != 1782864000
            or time_contract.get("generated_lookback_days") != 30
            or time_contract.get("wall_clock_functions_allowed_in_measured_sql") is not False
        ):
            raise ValueError(f"Invalid dataset time contract: {case_id}")

    q08_catalog = examples / "Q08-NEIGHBORS"
    expected_queries = {
        "q03_event_recent",
        "q04_event_oldest",
        "q05_event_deviation",
        "q06_tenant_sum",
        "q07_tenant_count",
        "q08_tenant_avg",
    }
    for name in (
        "README.md",
        "manifest.json",
        "query-index.csv",
        "q08_neighbors.csv",
        "q08_action_rankings.csv",
        "q08_failure_analysis.json",
    ):
        if not (q08_catalog / name).is_file():
            raise ValueError(f"Missing q08 query-catalog artifact: {name}")
    observed_queries = {
        path.stem for path in (q08_catalog / "queries").glob("*.sql")
    }
    if observed_queries != expected_queries:
        raise ValueError(
            "Q08 query-catalog mismatch: "
            f"expected={expected_queries} observed={observed_queries}"
        )
    q08_manifest = json.loads(
        (q08_catalog / "manifest.json").read_text(encoding="utf-8")
    )
    if (
        q08_manifest.get("catalog_id") != "Q08-NEIGHBORS"
        or q08_manifest.get("target_query_id") != "q08_tenant_avg"
    ):
        raise ValueError("Invalid Q08 neighbor-catalog manifest")
    if q08_manifest.get("dataset_time_contract", {}).get("base_time_unix") != 1782864000:
        raise ValueError("Invalid Q08 dataset time contract")
    q08_rows = read_csv_rows(q08_catalog / "query-index.csv")
    if not q08_rows or any(not row.get("cutoff_offset_days") for row in q08_rows):
        raise ValueError("Q08 query catalog lacks relative cutoff offsets")

    plan_boundaries = examples / "PLAN-SOURCE-01"
    required_plan_files = {
        "README.md",
        "manifest.json",
        "gac-plan.json",
        "gac-query.sql",
        "regional-plan.json",
        "regional-query.sql",
    }
    missing_plan_files = sorted(
        name for name in required_plan_files if not (plan_boundaries / name).is_file()
    )
    if missing_plan_files:
        raise ValueError(
            f"Missing plan-boundary artifacts: {missing_plan_files}"
        )
    plan_manifest = json.loads(
        (plan_boundaries / "manifest.json").read_text(encoding="utf-8")
    )
    if (
        plan_manifest.get("artifact_id") != "PLAN-SOURCE-01"
        or plan_manifest.get("scope", {}).get("plans_belong_to_same_execution")
        is not False
        or plan_manifest.get("scope", {}).get(
            "supports_numerical_experimental_claims"
        )
        is not False
    ):
        raise ValueError("Invalid plan-boundary scope contract")
    for name, expected_hash in plan_manifest.get("files", {}).items():
        candidate = plan_boundaries / name
        if not candidate.is_file() or digest(candidate) != expected_hash:
            raise ValueError(f"Plan-boundary checksum mismatch: {name}")

    checksum_path = examples / "checksums.sha256"
    for line in checksum_path.read_text(encoding="utf-8").splitlines():
        checksum, relative = line.split("  ", maxsplit=1)
        candidate = examples / relative
        if not candidate.is_file() or digest(candidate) != checksum:
            raise ValueError(f"Representative checksum mismatch: {relative}")

    verify_no_local_paths(examples)
    for path in examples.rglob("*"):
        if not path.is_file() or path.suffix.lower() not in PUBLIC_TEXT_SUFFIXES:
            continue
        text = path.read_text(encoding="utf-8")
        for candidate in re.findall(r"\b(?:\d{1,3}\.){3}\d{1,3}\b", text):
            try:
                address = ipaddress.ip_address(candidate)
            except ValueError:
                continue
            if address.is_private:
                raise ValueError(
                    f"Representative artifact contains a private IP: {path}"
                )
    print(f"[verify] representative cases PASS ({len(expected)} cases)")


def verify_scope(root: Path) -> None:
    generated_markdown = list((root / "artifacts" / "results").rglob("*.md"))
    if generated_markdown:
        names = ", ".join(str(path.relative_to(root)) for path in generated_markdown)
        raise ValueError(f"Generated Markdown reporti nisu dozvoljeni: {names}")
    forbidden_release_files = []
    ignored_release_parts = {
        ".pytest_cache",
        ".ruff_cache",
        ".venv",
        "__pycache__",
        "generated",
        "tmp",
    }
    for base in (root / "artifacts", root / "sources"):
        for pattern in ("*.tex", "*.pdf"):
            for path in base.rglob(pattern):
                relative = path.relative_to(base)
                if ignored_release_parts.intersection(relative.parts):
                    continue
                forbidden_release_files.append(path)
    if forbidden_release_files:
        names = ", ".join(
            str(path.relative_to(root)) for path in forbidden_release_files
        )
        raise ValueError(f"Rukopisni/PDF izlazi nisu dozvoljeni: {names}")

    source_root = root / "sources"
    source_docs = list(source_root.glob("*/docs"))
    if source_docs:
        names = ", ".join(str(path.relative_to(root)) for path in source_docs)
        raise ValueError(f"Source docs direktoriji nisu dozvoljeni: {names}")
    source_markdown = []
    for path in source_root.rglob("*.md"):
        relative = path.relative_to(source_root)
        if ignored_release_parts.intersection(relative.parts):
            continue
        if len(relative.parts) == 2 and relative.name == "README.md":
            continue
        source_markdown.append(path)
    if source_markdown:
        names = ", ".join(str(path.relative_to(root)) for path in source_markdown)
        raise ValueError(f"Source narativni Markdown nije dozvoljen: {names}")

    forbidden_dirs = [
        root / "sources" / "master-regimes" / "analysis" / "notebooks",
        *list((root / "sources").rglob("llmcontext")),
        *list((root / "sources").rglob(".vscode")),
        *list((root / "sources").rglob("common-scripts-archive")),
    ]
    for path in forbidden_dirs:
        if path.exists():
            raise ValueError(f"Iskljuceni source scope je prisutan: {path}")

    agent_dir = root / "sources/master-regimes/analysis/scripts/agent"
    published_model_lineage_scripts = {
        "17_m0_reduced_fuzzy_clustering.py",
        *{
            path.name
            for number in range(61, 70)
            for path in agent_dir.glob(f"{number}_*.py")
        },
    }
    allowed_agent_names = {
        path.name
        for number in range(74, 117)
        for path in agent_dir.glob(f"{number}_*.py")
    } | published_model_lineage_scripts
    observed_agent_names = {
        path.name for path in agent_dir.glob("*") if path.is_file()
    }
    if observed_agent_names != allowed_agent_names:
        raise ValueError(
            "Final source snapshot contains scripts outside the published "
            "F19/F21 lineage and pipeline scope"
        )
    print("[verify] curated scope PASS")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path(__file__).parents[1])
    return parser.parse_args()


def main() -> int:
    root = parse_args().root.resolve()
    spec = json.loads(
        (root / "config" / "release-spec.json").read_text(encoding="utf-8")
    )
    verify_hashes(root)
    verify_archives(root, spec)
    verify_comparative_fcm(root, spec)
    verify_actionability(root, spec)
    verify_action_selection_sample_size_audit(root, spec)
    verify_retrieval_density_audit(root, spec)
    verify_claim_map(root)
    verify_thesis_paths(root, spec)
    verify_representative_cases(root)
    verify_scope(root)
    print("[verify] RELEASE PACKAGE PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
