// TypeScript types for Spatiotemporal Annotator

export interface User {
  id: number;
  email: string;
  username: string;
  created_at: string;
}

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
  seq_label: string;
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
  matrix_json: string;
  span_order: string;
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

// ====== Auth types ======

export interface SignupRequest {
  email: string;
  password: string;
  username: string;
}

export interface LoginRequest {
  email: string;
  password: string;
}

export interface AuthMeResponse {
  user: User;
  csrf_token: string;
}

// ====== Stems types ======

export type StemState = 'available' | 'booked' | 'completed';

export interface StemOut {
  id: number;
  text: string;
  word_count: number;
  state: StemState;
  booked_by: { id: number; username: string } | null;
  locked_until: string | null;
  completed_by: { id: number; username: string } | null;
  completed_at: string | null;
}

export interface StemsListResponse {
  items: StemOut[];
  total: number;
  page: number;
  page_size: number;
}

export interface StemsImportResponse {
  created: number;
  skipped: number;
}

// ====== Batch types ======

export type BatchStatus = 'active' | 'released' | 'expired';

export interface BatchOut {
  id: number;
  name: string;
  owner_id: number;
  owner_username: string;
  created_at: string;
  locked_at: string;
  expires_at: string;
  rebook_count: number;
  status: BatchStatus;
  remaining_seconds: number;
  progress: { done: number; total: number };
}

export interface BatchStemOut {
  id: number;
  stem_id: number;
  stem_text: string;
  word_count: number;
  status: string;
  completed_by: { id: number; username: string } | null;
  completed_at: string | null;
  updated_at: string | null;
}

export interface BatchDetailOut extends BatchOut {
  stems: BatchStemOut[];
}

// ====== Batch-stem annotation types ======

export interface BatchSpanOut {
  id: number;
  batch_stem_id: number;
  session_id: number;
  label_type: 'Event' | 'Time';
  seq_label: string;
  span_text: string;
  char_start: number;
  char_end: number;
  tl_start: number;
  tl_end: number;
  source: 'manual' | 'llm';
  created_at: string;
}

export interface BatchStemDetail {
  id: number;
  batch_id: number;
  stem_id: number;
  stem_text: string;
  word_count: number;
  status: string;
  completed_by: number | null;
  completed_at: string | null;
  updated_at: string | null;
  spans: BatchSpanOut[];
  expires_at: string;
}

export interface SkippedEvent {
  text: string;
  reason: string;
}

export interface ExtractEventsResponse {
  events: Array<{ span_text: string; char_start: number; char_end: number }>;
  skipped: Array<{ text: string; reason: string }>;
}

export interface ExtractTimelineResponse {
  updated: Array<{ span_id: number; seq_label: string; span_text: string; tl_start: number; tl_end: number }>;
  skipped: Array<{ text: string; reason: string }>;
}

