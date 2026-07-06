// TypeScript types for Spatiotemporal Annotator

export interface Session {
  id: number;
  username: string;
  stem_text: string;
  status: 'in_progress' | 'done';
  completed_at: string | null;
  created_at: string;
  spans?: Span[];
  matrix_snapshot?: MatrixSnapshot | null;
}

export interface Span {
  id: number;
  session_id: number;
  label_type: 'Event' | 'Time';
  seq_label: string; // E1, E2, T1, T2...
  span_text: string;
  char_start: number;
  char_end: number;
  tl_start: number;
  tl_end: number;
  source: 'manual' | 'llm';
  created_at: string;
}

export interface MatrixSnapshot {
  id: number;
  session_id: number;
  matrix_json: string; // JSON string of number[][]
  span_order: string;  // JSON string of {id, seq_label}[]
  created_at: string;
  updated_at: string;
}

export interface SpanOrder {
  id: number;
  seq_label: string;
}

export interface MatrixData {
  matrix: number[][];
  span_order: SpanOrder[];
  violations: Violation[];
}

export interface Violation {
  i: number;
  j: number;
  label_i: string;
  label_j: string;
  value: number;
  inverse_actual: number;
  inverse_expected: number;
  message: string;
}

export const ALLEN_RELATIONS: Record<number, { name: string; symbol: string }> = {
  0:  { name: 'self',          symbol: '—'  },
  1:  { name: 'precedes',      symbol: '<'  },
  2:  { name: 'meets',         symbol: 'm'  },
  3:  { name: 'overlaps',      symbol: 'o'  },
  4:  { name: 'starts',        symbol: 's'  },
  5:  { name: 'during',        symbol: 'd'  },
  6:  { name: 'finishes',      symbol: 'f'  },
  7:  { name: 'equals',        symbol: '='  },
  [-1]: { name: 'preceded-by',   symbol: '>'  },
  [-2]: { name: 'met-by',        symbol: 'mi' },
  [-3]: { name: 'overlapped-by', symbol: 'oi' },
  [-4]: { name: 'started-by',    symbol: 'si' },
  [-5]: { name: 'contains',      symbol: 'di' },
  [-6]: { name: 'finished-by',   symbol: 'fi' },
};

export const ALLEN_CODES = [1, 2, 3, 4, 5, 6, 7, -1, -2, -3, -4, -5, -6];
