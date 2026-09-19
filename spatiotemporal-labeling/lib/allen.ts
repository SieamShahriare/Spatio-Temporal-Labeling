// Client-side mirror of backend/allen/relations.py — used only for a live preview
// of the Allen matrix while a timeline annotator is positioning events. The
// authoritative matrix is always (re)computed server-side on submit.

export const INVERSES: Record<number, number> = {
  1: -1, [-1]: 1,
  2: -2, [-2]: 2,
  3: -3, [-3]: 3,
  4: -4, [-4]: 4,
  5: -5, [-5]: 5,
  6: -6, [-6]: 6,
  7: 7,
};

export function computeRelation(aStart: number, aEnd: number, bStart: number, bEnd: number, tol = 0.01): number {
  const eq = (x: number, y: number) => Math.abs(x - y) <= tol;

  if (eq(aStart, bStart) && eq(aEnd, bEnd)) return 7;
  if (eq(aEnd, bStart)) return 2;
  if (eq(bEnd, aStart)) return -2;
  if (aEnd < bStart - tol) return 1;
  if (bEnd < aStart - tol) return -1;
  if (eq(aStart, bStart) && aEnd < bEnd) return 4;
  if (eq(aStart, bStart) && aEnd > bEnd) return -4;
  if (eq(aEnd, bEnd) && aStart > bStart) return 6;
  if (eq(aEnd, bEnd) && aStart < bStart) return -6;
  if (aStart > bStart && aEnd < bEnd) return 5;
  if (aStart < bStart && aEnd > bEnd) return -5;
  if (aStart < bStart && aEnd > bStart) return 3;
  if (bStart < aStart && bEnd > aStart) return -3;
  return 3;
}

export function buildMatrix(spans: Array<{ tl_start: number; tl_end: number }>): number[][] {
  const n = spans.length;
  const matrix: number[][] = Array.from({ length: n }, () => Array(n).fill(0));
  for (let i = 0; i < n; i++) {
    for (let j = i + 1; j < n; j++) {
      const code = computeRelation(spans[i].tl_start, spans[i].tl_end, spans[j].tl_start, spans[j].tl_end);
      matrix[i][j] = code;
      matrix[j][i] = INVERSES[code];
    }
  }
  return matrix;
}
