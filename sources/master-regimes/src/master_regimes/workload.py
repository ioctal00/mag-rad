from __future__ import annotations

import csv
import json
from itertools import product
from pathlib import Path
from typing import Any

from .config import load_yaml, stable_slug

MANIFEST_METADATA_FIELDS = [
    "logical_question_id",
    "execution_strategy",
    "execution_scope",
    "target_scope",
    "component_match_id",
    "expected_regime_targets",
    "runtime_sensitivity",
    "required_dataset_capabilities",
    "distribution_key_usage",
    "intervention_roles",
]


def _param_product(parameters: dict[str, list[Any]]) -> list[dict[str, Any]]:
    if not parameters:
        return [{}]
    keys = list(parameters)
    return [
        dict(zip(keys, values, strict=True))
        for values in product(*(parameters[k] for k in keys))
    ]


def _manifest_metadata_value(value: Any) -> str:
    if value in ("", None):
        return ""
    if isinstance(value, list):
        return ",".join(str(item) for item in value)
    if isinstance(value, dict):
        return json.dumps(value, sort_keys=True, separators=(",", ":"))
    return str(value)


def render_workload(*, registry_path: Path, output_dir: Path, max_instances: int | None) -> Path:
    from jinja2 import Environment, FileSystemLoader, StrictUndefined

    registry = load_yaml(registry_path)
    templates = registry.get("templates", {})
    if not isinstance(templates, dict):
        raise ValueError("workloads registry must contain a templates mapping")

    output_dir.mkdir(parents=True, exist_ok=True)
    template_search_paths = [registry_path.parent]
    if registry_path.parent.name == "suites":
        template_search_paths.append(registry_path.parent.parent)
    env = Environment(
        loader=FileSystemLoader([str(path) for path in template_search_paths]),
        undefined=StrictUndefined,
        autoescape=False,
    )

    manifest_rows: list[dict[str, str]] = []
    generated = 0
    for template_id, spec in templates.items():
        file_name = str(spec["file"])
        params = _param_product(dict(spec.get("parameters", {})))
        for index, values in enumerate(params, start=1):
            if max_instances is not None and generated >= max_instances:
                break
            suffix = "__".join(
                f"{stable_slug(str(k))}-{stable_slug(str(v))}" for k, v in values.items()
            )
            instance_id = f"{template_id}__{suffix or f'case-{index:03d}'}"
            rendered = env.get_template(file_name).render(**values)
            rendered_path = output_dir / f"{instance_id}.sql"
            rendered_path.write_text(rendered.strip() + "\n", encoding="utf-8")
            manifest_rows.append(
                {
                    "instance_id": instance_id,
                    "template_id": str(template_id),
                    "param_json": json.dumps(values, sort_keys=True),
                    "rendered_sql_path": str(rendered_path),
                    "expected_shape_tags": ",".join(spec.get("expected_pressure_tags", [])),
                    **{
                        field: _manifest_metadata_value(spec.get(field))
                        for field in MANIFEST_METADATA_FIELDS
                    },
                }
            )
            generated += 1
        if max_instances is not None and generated >= max_instances:
            break

    manifest_path = output_dir / "instance_manifest.csv"
    with manifest_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=[
                "instance_id",
                "template_id",
                "param_json",
                "rendered_sql_path",
                "expected_shape_tags",
                *MANIFEST_METADATA_FIELDS,
            ],
        )
        writer.writeheader()
        writer.writerows(manifest_rows)
    return manifest_path
