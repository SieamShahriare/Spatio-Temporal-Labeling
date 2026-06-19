"""
Allen's Interval Algebra relation computation module.
Encodes the 13 Allen relations as signed integers.
"""

RELATIONS = {
    'precedes':       +1,
    'meets':          +2,
    'overlaps':       +3,
    'starts':         +4,
    'during':         +5,
    'finishes':       +6,
    'equals':         +7,
    'preceded-by':    -1,
    'met-by':         -2,
    'overlapped-by':  -3,
    'started-by':     -4,
    'contains':       -5,
    'finished-by':    -6,
}

RELATION_NAMES = {v: k for k, v in RELATIONS.items()}

INVERSES = {
    +1: -1,  -1: +1,
    +2: -2,  -2: +2,
    +3: -3,  -3: +3,
    +4: -4,  -4: +4,
    +5: -5,  -5: +5,
    +6: -6,  -6: +6,
    +7: +7,  # equals is its own inverse
}

RELATION_SYMBOLS = {
    +1: '<',
    +2: 'm',
    +3: 'o',
    +4: 's',
    +5: 'd',
    +6: 'f',
    +7: '=',
    -1: '>',
    -2: 'mi',
    -3: 'oi',
    -4: 'si',
    -5: 'di',
    -6: 'fi',
     0: '—',
}


def compute_relation(a_start: float, a_end: float, b_start: float, b_end: float, tol: float = 0.01) -> int:
    """
    Returns the Allen relation code for interval A vs interval B.
    tol is a tolerance for floating-point comparisons.
    """
    def eq(x, y): return abs(x - y) <= tol

    if eq(a_start, b_start) and eq(a_end, b_end): return +7   # equals
    if eq(a_end, b_start):                          return +2   # meets
    if eq(b_end, a_start):                          return -2   # met-by
    if a_end < b_start - tol:                       return +1   # precedes
    if b_end < a_start - tol:                       return -1   # preceded-by
    if eq(a_start, b_start) and a_end < b_end:      return +4   # starts
    if eq(a_start, b_start) and a_end > b_end:      return -4   # started-by
    if eq(a_end, b_end) and a_start > b_start:      return +6   # finishes
    if eq(a_end, b_end) and a_start < b_start:      return -6   # finished-by
    if a_start > b_start and a_end < b_end:         return +5   # during
    if a_start < b_start and a_end > b_end:         return -5   # contains
    if a_start < b_start and a_end > b_start:       return +3   # overlaps
    if b_start < a_start and b_end > a_start:       return -3   # overlapped-by
    return +3  # fallback


def build_matrix(spans: list) -> list:
    """
    Given a list of spans [{'tl_start': float, 'tl_end': float}],
    returns the N x N Allen relation matrix.
    """
    n = len(spans)
    matrix = [[0] * n for _ in range(n)]
    for i in range(n):
        for j in range(n):
            if i == j:
                matrix[i][j] = 0
            elif i < j:
                code = compute_relation(
                    spans[i]['tl_start'], spans[i]['tl_end'],
                    spans[j]['tl_start'], spans[j]['tl_end']
                )
                matrix[i][j] = code
                matrix[j][i] = INVERSES[code]
    return matrix
