from __future__ import annotations

from itertools import product
from typing import Any

from .config import stable_slug

EXPANDABLE_CELL_FIELDS = ("dataset_profile_id", "runtime_config_id")


def _as_values(value: Any) -> list[Any]:
    return value if isinstance(value, list) else [value]


def expand_corpus_cells(cells: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Expand compact corpus cells into concrete executable cells.

    A clean-run manifest can keep one logical cell readable while asking for the
    same cell over multiple dataset/runtime segments:

    dataset_profile_id: [pilot-balanced-v1, pilot-skew-heavy-v1]
    runtime_config_id: [fetch_small, fetch_large]

    The execution backend still receives concrete cells with scalar
    dataset/runtime IDs, so segment grouping stays explicit and restart-safe.
    """

    expanded: list[dict[str, Any]] = []
    for cell in cells:
        value_lists = [_as_values(cell.get(field, "")) for field in EXPANDABLE_CELL_FIELDS]
        needs_suffix = any(len(values) > 1 for values in value_lists)
        for values in product(*value_lists):
            concrete = dict(cell)
            suffix_parts: list[str] = []
            for field, value in zip(EXPANDABLE_CELL_FIELDS, values, strict=True):
                concrete[field] = value
                if needs_suffix:
                    field_slug = stable_slug(
                        field.replace("_profile_id", "").replace("_config_id", "")
                    )
                    value_slug = stable_slug(str(value))
                    suffix_parts.append(f"{field_slug}-{value_slug}")
            if suffix_parts:
                concrete["corpus_cell_id"] = "__".join(
                    [stable_slug(str(cell["corpus_cell_id"])), *suffix_parts]
                )
            expanded.append(concrete)
    return expanded
