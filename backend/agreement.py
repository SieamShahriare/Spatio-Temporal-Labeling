"""
Inter-annotator agreement metrics for the group annotation workflow.

Pure-Python implementations (no numpy/scikit-learn) of:
  - Cohen's kappa (pairwise, averaged across annotator pairs)
  - Fleiss' kappa (native multi-rater extension)
  - Krippendorff's alpha (interval data) — primary acceptance metric

See context/cohen_kappa.md for the design rationale.
"""
from itertools import combinations
from typing import Dict, List, Optional, Tuple

Matrix = List[List[int]]


def cohen_kappa_score(y1: List[int], y2: List[int]) -> float:
    """Cohen's kappa for two equal-length sequences of categorical labels."""
    n = len(y1)
    if n == 0:
        return 1.0
    categories = sorted(set(y1) | set(y2))
    idx = {c: i for i, c in enumerate(categories)}
    k = len(categories)
    confusion = [[0] * k for _ in range(k)]
    for a, b in zip(y1, y2):
        confusion[idx[a]][idx[b]] += 1
    po = sum(confusion[i][i] for i in range(k)) / n
    row_sums = [sum(row) for row in confusion]
    col_sums = [sum(confusion[i][j] for i in range(k)) for j in range(k)]
    pe = sum(row_sums[i] * col_sums[i] for i in range(k)) / (n * n)
    if pe == 1.0:
        return 1.0
    return (po - pe) / (1 - pe)


def average_cohens_kappa(matrices: List[Matrix]) -> Optional[float]:
    """Average pairwise Cohen's kappa over the upper triangle of N x N Allen matrices."""
    if len(matrices) < 2:
        return None
    kappas = []
    for m1, m2 in combinations(matrices, 2):
        flat1, flat2 = [], []
        n = len(m1)
        for i in range(n):
            for j in range(i + 1, n):
                flat1.append(m1[i][j])
                flat2.append(m2[i][j])
        if not flat1:
            continue
        if len(set(flat1 + flat2)) > 1:
            kappas.append(cohen_kappa_score(flat1, flat2))
        else:
            kappas.append(1.0)  # trivial perfect agreement
    return sum(kappas) / len(kappas) if kappas else None


def fleiss_kappa(matrices: List[Matrix]) -> Optional[float]:
    """Native multi-rater Fleiss' kappa over the upper triangle of N x N Allen matrices."""
    r = len(matrices)
    if r < 2:
        return None
    n = len(matrices[0])
    items = [(i, j) for i in range(n) for j in range(i + 1, n)]
    if not items:
        return None

    categories = sorted({m[i][j] for m in matrices for (i, j) in items})
    cat_idx = {c: k for k, c in enumerate(categories)}
    n_items = len(items)
    counts = [[0] * len(categories) for _ in range(n_items)]
    for it_idx, (i, j) in enumerate(items):
        for m in matrices:
            counts[it_idx][cat_idx[m[i][j]]] += 1

    p_i = []
    for row in counts:
        total_sq = sum(c * c for c in row)
        p_i.append((total_sq - r) / (r * (r - 1)))
    p_bar = sum(p_i) / n_items

    p_j = [sum(counts[it][k] for it in range(n_items)) / (n_items * r) for k in range(len(categories))]
    p_e_bar = sum(p * p for p in p_j)

    if p_e_bar == 1.0:
        return 1.0
    return (p_bar - p_e_bar) / (1 - p_e_bar)


def krippendorff_alpha_interval(data: List[List[Optional[float]]]) -> Optional[float]:
    """
    Krippendorff's alpha for interval data.
    data: list of n_annotators rows, each a list of n_items values (None = missing).
    """
    n_annotators = len(data)
    n_items = len(data[0]) if n_annotators else 0

    do_sum, do_count = 0.0, 0
    for k in range(n_items):
        values = [row[k] for row in data if row[k] is not None]
        if len(values) < 2:
            continue
        for c, d in combinations(values, 2):
            do_sum += (c - d) ** 2
            do_count += 1
    if do_count == 0:
        return None
    d_o = do_sum / do_count

    all_values = [v for row in data for v in row if v is not None]
    de_sum, de_count = 0.0, 0
    for c, d in combinations(all_values, 2):
        de_sum += (c - d) ** 2
        de_count += 1
    if de_count == 0:
        return 1.0
    d_e = de_sum / de_count

    if d_e == 0:
        return 1.0
    return 1 - d_o / d_e


def classify_agreement(alpha: Optional[float], threshold: float = 0.60) -> str:
    """Map a primary agreement score to an acceptance bucket."""
    if alpha is None:
        return "unknown"
    if alpha >= 0.80:
        return "accepted"
    if alpha >= threshold:
        return "accepted_flagged"
    if alpha >= 0.40:
        return "adjudication"
    return "rejected"


def compute_agreement(
    positions: Dict[int, Dict[int, Tuple[float, float]]],
    matrices: Dict[int, Matrix],
    threshold: float = 0.60,
) -> dict:
    """
    positions: {member_id: {span_id: (tl_start, tl_end)}}
    matrices:  {member_id: N x N Allen relation matrix}, all sharing the same span order.
    """
    member_ids = sorted(positions.keys())
    span_ids = sorted({sid for m in positions.values() for sid in m.keys()})

    data_matrix = []
    for mid in member_ids:
        row = []
        for sid in span_ids:
            pos = positions[mid].get(sid)
            row.append(pos[0] if pos else None)
        for sid in span_ids:
            pos = positions[mid].get(sid)
            row.append(pos[1] if pos else None)
        data_matrix.append(row)

    alpha = krippendorff_alpha_interval(data_matrix)
    matrix_list = [matrices[mid] for mid in member_ids if mid in matrices]
    kappa_avg = average_cohens_kappa(matrix_list)
    fleiss = fleiss_kappa(matrix_list)

    per_event = {
        str(sid): {str(mid): list(positions[mid][sid]) for mid in member_ids if sid in positions[mid]}
        for sid in span_ids
    }

    return {
        "krippendorff_alpha": alpha,
        "cohens_kappa_avg": kappa_avg,
        "fleiss_kappa": fleiss,
        "status": classify_agreement(alpha, threshold),
        "agreement_details": {
            "member_ids": member_ids,
            "per_event": per_event,
        },
    }
