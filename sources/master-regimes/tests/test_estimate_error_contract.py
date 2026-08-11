import math

from master_regimes.extract.query_sweep_index import (
    _largest_abs_signed as index_largest_abs_signed,
)
from master_regimes.extract.query_sweep_index import (
    _rows_estimate_error_log as index_rows_estimate_error_log,
)
from master_regimes.feature_matrix import (
    _largest_abs_signed as matrix_largest_abs_signed,
)
from master_regimes.feature_matrix import (
    _rows_estimate_error_log as matrix_rows_estimate_error_log,
)


def test_estimate_error_is_signed_natural_log_ratio() -> None:
    row = {"actual_rows": 2, "plan_rows": 199}
    expected = math.log(3 / 200)

    assert math.isclose(matrix_rows_estimate_error_log(row), expected)
    assert math.isclose(index_rows_estimate_error_log(row), expected)
    assert expected < 0


def test_largest_absolute_selection_preserves_sign() -> None:
    values = [1.5, -4.2, 3.0]

    assert matrix_largest_abs_signed(values) == -4.2
    assert index_largest_abs_signed(values) == -4.2
