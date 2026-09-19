"""
Unit tests for backend/agreement.py — pure-Python inter-annotator agreement metrics.
No DB or live server required. Run with: python3 tests/test_agreement.py
"""
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agreement import (
    cohen_kappa_score,
    average_cohens_kappa,
    fleiss_kappa,
    krippendorff_alpha_interval,
    classify_agreement,
    compute_agreement,
)


def check(label, cond):
    status = "PASS" if cond else "FAIL"
    print(f"  [{status}] {label}")
    if not cond:
        raise AssertionError(label)


def test_cohen_kappa_perfect_agreement():
    print("1. Cohen's kappa — perfect agreement")
    y1 = [1, 2, 3, 1, 2, 3]
    y2 = [1, 2, 3, 1, 2, 3]
    check("kappa == 1.0", cohen_kappa_score(y1, y2) == 1.0)


def test_cohen_kappa_no_agreement():
    print("2. Cohen's kappa — chance-level / negative agreement")
    y1 = [1, 1, 1, 2, 2, 2]
    y2 = [2, 2, 2, 1, 1, 1]
    kappa = cohen_kappa_score(y1, y2)
    check("kappa < 0 (systematic disagreement)", kappa < 0)


def test_average_cohens_kappa():
    print("3. Average pairwise Cohen's kappa over 3 identical matrices")
    m = [[0, 1, 2], [-1, 0, 3], [-2, -3, 0]]
    avg = average_cohens_kappa([m, m, m])
    check("avg == 1.0 for identical matrices", avg == 1.0)


def test_fleiss_kappa_perfect():
    print("4. Fleiss' kappa — perfect agreement across 3 raters")
    m = [[0, 1, 2], [-1, 0, 3], [-2, -3, 0]]
    kappa = fleiss_kappa([m, m, m])
    check("fleiss kappa == 1.0", kappa == 1.0)


def test_fleiss_kappa_disagreement():
    print("5. Fleiss' kappa — disagreement lowers score")
    m1 = [[0, 1], [-1, 0]]
    m2 = [[0, -1], [1, 0]]
    m3 = [[0, 2], [-2, 0]]
    kappa = fleiss_kappa([m1, m2, m3])
    check("fleiss kappa < 1.0", kappa < 1.0)


def test_krippendorff_alpha_perfect():
    print("6. Krippendorff's alpha (interval) — identical annotators")
    data = [[10.0, 30.0, 50.0], [10.0, 30.0, 50.0], [10.0, 30.0, 50.0]]
    alpha = krippendorff_alpha_interval(data)
    check("alpha == 1.0", alpha == 1.0)


def test_krippendorff_alpha_disagreement():
    print("7. Krippendorff's alpha (interval) — spread-out values lower alpha")
    data = [[10.0, 30.0], [50.0, 70.0], [90.0, 5.0]]
    alpha = krippendorff_alpha_interval(data)
    check("alpha < 1.0", alpha < 1.0)


def test_classify_agreement_thresholds():
    print("8. classify_agreement bucket boundaries")
    check("0.85 -> accepted", classify_agreement(0.85) == "accepted")
    check("0.70 -> accepted_flagged", classify_agreement(0.70) == "accepted_flagged")
    check("0.50 -> adjudication", classify_agreement(0.50) == "adjudication")
    check("0.20 -> rejected", classify_agreement(0.20) == "rejected")
    check("None -> unknown", classify_agreement(None) == "unknown")


def test_compute_agreement_end_to_end():
    print("9. compute_agreement — 3 annotators, 2 events, near-identical positions")
    positions = {
        1: {101: (10.0, 30.0), 102: (40.0, 60.0)},
        2: {101: (11.0, 31.0), 102: (39.0, 61.0)},
        3: {101: (9.0, 29.0), 102: (41.0, 59.0)},
    }
    matrix = [[0, 1], [-1, 0]]  # E1 precedes E2 for all three
    matrices = {1: matrix, 2: matrix, 3: matrix}
    result = compute_agreement(positions, matrices, threshold=0.60)
    check("krippendorff_alpha is high (>0.9)", result["krippendorff_alpha"] > 0.9)
    check("cohens_kappa_avg == 1.0 (identical matrices)", result["cohens_kappa_avg"] == 1.0)
    check("fleiss_kappa == 1.0 (identical matrices)", result["fleiss_kappa"] == 1.0)
    check("status == accepted", result["status"] == "accepted")
    check("agreement_details has per_event for both spans", set(result["agreement_details"]["per_event"].keys()) == {"101", "102"})


def run_all():
    tests = [
        test_cohen_kappa_perfect_agreement,
        test_cohen_kappa_no_agreement,
        test_average_cohens_kappa,
        test_fleiss_kappa_perfect,
        test_fleiss_kappa_disagreement,
        test_krippendorff_alpha_perfect,
        test_krippendorff_alpha_disagreement,
        test_classify_agreement_thresholds,
        test_compute_agreement_end_to_end,
    ]
    for t in tests:
        t()
    print("\nAll agreement.py tests passed.")


if __name__ == "__main__":
    run_all()
