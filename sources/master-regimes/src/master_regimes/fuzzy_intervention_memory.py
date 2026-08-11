from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

import numpy as np
import pandas as pd


@dataclass(frozen=True)
class ActionEstimate:
    action: str
    prediction: float
    weighted_stddev: float
    effective_support: float
    observed_support: int
    status: str


def effective_sample_size(weights: np.ndarray) -> float:
    finite = np.asarray(weights, dtype=float)
    finite = finite[np.isfinite(finite) & (finite > 0.0)]
    if finite.size == 0:
        return 0.0
    denominator = float(np.sum(finite * finite))
    if denominator <= 0.0:
        return 0.0
    return float(np.sum(finite) ** 2 / denominator)


def fuzzy_episode_weights(
    query_membership: np.ndarray,
    historical_memberships: np.ndarray,
    *,
    fuzzifier: float,
) -> np.ndarray:
    if fuzzifier <= 1.0:
        raise ValueError("fuzzifier must be greater than 1")
    query = np.asarray(query_membership, dtype=float)
    history = np.asarray(historical_memberships, dtype=float)
    if query.ndim != 1 or history.ndim != 2:
        raise ValueError("query membership must be 1D and history must be 2D")
    if history.shape[1] != query.shape[0]:
        raise ValueError("query and historical memberships use different centers")
    return (history**fuzzifier) @ (query**fuzzifier)


def weighted_location_scale(
    values: np.ndarray,
    weights: np.ndarray,
) -> tuple[float, float]:
    observed = np.asarray(values, dtype=float)
    importance = np.asarray(weights, dtype=float)
    valid = np.isfinite(observed) & np.isfinite(importance) & (importance > 0.0)
    if not np.any(valid):
        return float("nan"), float("nan")
    observed = observed[valid]
    importance = importance[valid]
    importance = importance / importance.sum()
    location = float(np.sum(importance * observed))
    variance = float(np.sum(importance * (observed - location) ** 2))
    return location, float(np.sqrt(max(variance, 0.0)))


def estimate_actions(
    *,
    query_membership: np.ndarray,
    historical_memberships: np.ndarray,
    historical_actions: Iterable[str],
    historical_gains: np.ndarray,
    candidate_actions: Iterable[str],
    fuzzifier: float,
    minimum_observed_support: int,
    minimum_effective_support: float,
) -> list[ActionEstimate]:
    actions = np.asarray(list(historical_actions), dtype=object)
    gains = np.asarray(historical_gains, dtype=float)
    if len(actions) != len(gains) or len(actions) != len(historical_memberships):
        raise ValueError("historical action, gain and membership lengths differ")
    similarities = fuzzy_episode_weights(
        query_membership,
        historical_memberships,
        fuzzifier=fuzzifier,
    )
    estimates: list[ActionEstimate] = []
    for action in candidate_actions:
        selected = actions == action
        weights = similarities[selected]
        values = gains[selected]
        observed_support = int(np.isfinite(values).sum())
        effective_support = effective_sample_size(weights[np.isfinite(values)])
        location, scale = weighted_location_scale(values, weights)
        status = (
            "available"
            if observed_support >= minimum_observed_support
            and effective_support >= minimum_effective_support
            and np.isfinite(location)
            else "insufficient_local_evidence"
        )
        estimates.append(
            ActionEstimate(
                action=str(action),
                prediction=location,
                weighted_stddev=scale,
                effective_support=effective_support,
                observed_support=observed_support,
                status=status,
            )
        )
    return estimates


def fuzzy_transition_edges(
    *,
    before_memberships: np.ndarray,
    after_memberships: np.ndarray,
    actions: Iterable[str],
    gains: np.ndarray,
    fuzzifier: float,
) -> pd.DataFrame:
    before = np.asarray(before_memberships, dtype=float)
    after = np.asarray(after_memberships, dtype=float)
    action_values = np.asarray(list(actions), dtype=object)
    gain_values = np.asarray(gains, dtype=float)
    if before.shape != after.shape:
        raise ValueError("before and after memberships must have the same shape")
    if len(before) != len(action_values) or len(before) != len(gain_values):
        raise ValueError("transition inputs have different row counts")

    rows: list[dict[str, float | int | str]] = []
    for action in sorted(set(str(value) for value in action_values)):
        selected = action_values.astype(str) == action
        action_before = before[selected] ** fuzzifier
        action_after = after[selected] ** fuzzifier
        action_gains = gain_values[selected]
        for source in range(before.shape[1]):
            for destination in range(after.shape[1]):
                weights = action_before[:, source] * action_after[:, destination]
                location, scale = weighted_location_scale(action_gains, weights)
                weight_sum = float(np.sum(weights))
                if weight_sum <= 0.0:
                    continue
                rows.append(
                    {
                        "action": action,
                        "source_context": source,
                        "destination_context": destination,
                        "transition_weight": weight_sum,
                        "effective_support": effective_sample_size(weights),
                        "observed_support": int(np.sum(weights > 0.0)),
                        "gain_weighted_mean": location,
                        "gain_weighted_stddev": scale,
                    }
                )
    return pd.DataFrame(rows)
