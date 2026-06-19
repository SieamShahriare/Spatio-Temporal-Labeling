"""
Transitivity validation for Allen's Interval Algebra.
Detects cells where the override contradicts what other relations imply.
"""

from allen.relations import INVERSES


def transitivity_check(matrix: list, span_labels: list) -> list:
    """
    Given an N x N matrix of Allen relation codes and the corresponding span labels,
    returns a list of violation dicts: {i, j, expected_set, actual}
    This is a simplified check — it flags cells where the relation is inconsistent
    with the inverse rule (matrix[i][j] should equal inverse of matrix[j][i]).
    """
    n = len(matrix)
    violations = []
    for i in range(n):
        for j in range(n):
            if i == j:
                continue
            val = matrix[i][j]
            inv_val = matrix[j][i]
            expected_inv = INVERSES.get(val)
            if expected_inv is not None and inv_val != expected_inv:
                violations.append({
                    "i": i,
                    "j": j,
                    "label_i": span_labels[i] if i < len(span_labels) else str(i),
                    "label_j": span_labels[j] if j < len(span_labels) else str(j),
                    "value": val,
                    "inverse_actual": inv_val,
                    "inverse_expected": expected_inv,
                    "message": (
                        f"matrix[{span_labels[i]}][{span_labels[j]}]={val} "
                        f"but matrix[{span_labels[j]}][{span_labels[i]}]={inv_val} "
                        f"(expected {expected_inv})"
                    )
                })
    return violations
