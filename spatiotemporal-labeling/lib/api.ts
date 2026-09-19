// API helper — all calls go to NEXT_PUBLIC_API_URL (FastAPI backend)

import type { LLMLabelAndTimelineResponse } from '@/lib/types';

const BASE = process.env.NEXT_PUBLIC_API_URL ?? 'http://localhost:8000';

let _csrfToken: string | null = null;

export function setCsrfToken(token: string) {
  _csrfToken = token;
}

export function getCsrfToken() {
  return _csrfToken;
}

async function apiFetch(path: string, options?: RequestInit) {
  const headers: Record<string, string> = {
    'Content-Type': 'application/json',
    ...(options?.headers ? (options.headers as Record<string, string>) : {}),
  };

  if (_csrfToken) {
    headers['X-CSRF-Token'] = _csrfToken;
  }

  const res = await fetch(`${BASE}${path}`, {
    ...options,
    headers,
    credentials: 'include',
  });

  if (!res.ok) {
    const text = await res.text();
    let detail = text;
    try {
      const parsed = JSON.parse(text);
      detail = typeof parsed.detail === 'string' ? parsed.detail : JSON.stringify(parsed.detail ?? text);
    } catch {
      // keep raw text
    }
    throw new Error(`API ${res.status}: ${detail}`);
  }
  if (res.status === 204) return null;
  return res.json();
}

// ====== Auth ======

export async function signup(data: { email: string; password: string; username: string }) {
  const res = await apiFetch('/auth/signup', {
    method: 'POST',
    body: JSON.stringify(data),
  });
  if (res.csrf_token) setCsrfToken(res.csrf_token);
  return res;
}

export async function login(data: { email: string; password: string }) {
  const res = await apiFetch('/auth/login', {
    method: 'POST',
    body: JSON.stringify(data),
  });
  if (res.csrf_token) setCsrfToken(res.csrf_token);
  return res;
}

export async function logout() {
  await apiFetch('/auth/logout', { method: 'POST' });
  _csrfToken = null;
}

export async function authMe() {
  const res = await apiFetch('/auth/me');
  if (res.csrf_token) setCsrfToken(res.csrf_token);
  return res;
}

// ====== Stems ======

export interface StemFilter {
  search?: string;
  status?: string;
  page?: number;
  page_size?: number;
}

export const listStems = (filter: StemFilter = {}) => {
  const params = new URLSearchParams();
  if (filter.search) params.set('search', filter.search);
  if (filter.status) params.set('status', filter.status);
  if (filter.page) params.set('page', String(filter.page));
  if (filter.page_size) params.set('page_size', String(filter.page_size));
  const qs = params.toString();
  return apiFetch(`/stems${qs ? `?${qs}` : ''}`);
};

export async function importStems(formData: FormData): Promise<{ created: number; skipped: number }> {
  const headers: Record<string, string> = {};
  if (_csrfToken) {
    headers['X-CSRF-Token'] = _csrfToken;
  }
  const res = await fetch(`${BASE}/stems/import`, {
    method: 'POST',
    body: formData,
    headers,
    credentials: 'include',
  });

  if (!res.ok) {
    const text = await res.text();
    let detail = text;
    try {
      const parsed = JSON.parse(text);
      detail = typeof parsed.detail === 'string' ? parsed.detail : JSON.stringify(parsed.detail ?? text);
    } catch {
      // keep raw text
    }
    throw new Error(`API ${res.status}: ${detail}`);
  }
  return res.json();
}

// ====== Batches ======

export const createBatch = (data: { name: string; stem_ids: number[] }) =>
  apiFetch('/batches', { method: 'POST', body: JSON.stringify(data) });

export const listBatches = () =>
  apiFetch('/batches');

export const getBatch = (id: number) =>
  apiFetch(`/batches/${id}`);

export const rebookBatch = (id: number) =>
  apiFetch(`/batches/${id}/rebook`, { method: 'POST' });

export const releaseBatch = (id: number) =>
  apiFetch(`/batches/${id}/release`, { method: 'POST' });

export const exportBatchCsv = (id: number) => `${BASE}/batches/${id}/export/csv`;
export const exportBatchJson = (id: number) => `${BASE}/batches/${id}/export/json`;
export const exportBatchStemJson = (batchStemId: number) =>
  `${BASE}/batch-stems/${batchStemId}/export/json`;

// ====== Batch-stem annotations ======

export const getBatchStem = (id: number) =>
  apiFetch(`/batch-stems/${id}`);

export const createBatchSpan = (batchStemId: number, data: {
  label_type: string;
  span_text: string;
  char_start: number;
  char_end: number;
  tl_start?: number;
  tl_end?: number;
  source?: string;
}) => apiFetch(`/batch-stems/${batchStemId}/spans`, { method: 'POST', body: JSON.stringify(data) });

export const listBatchSpans = (batchStemId: number) =>
  apiFetch(`/batch-stems/${batchStemId}/spans`);

export const updateBatchSpan = (batchStemId: number, spanId: number, tl_start: number, tl_end: number) =>
  apiFetch(`/batch-stems/${batchStemId}/spans/${spanId}`, { method: 'PATCH', body: JSON.stringify({ tl_start, tl_end }) });

export const deleteBatchSpan = (batchStemId: number, spanId: number) =>
  apiFetch(`/batch-stems/${batchStemId}/spans/${spanId}`, { method: 'DELETE' });

export const getBatchMatrix = (batchStemId: number) =>
  apiFetch(`/batch-stems/${batchStemId}/matrix`);

export const saveBatchMatrix = (batchStemId: number) =>
  apiFetch(`/batch-stems/${batchStemId}/matrix/save`, { method: 'POST' });

export const overrideBatchMatrix = (batchStemId: number, i: number, j: number, relation_code: number) =>
  apiFetch(`/batch-stems/${batchStemId}/matrix/override`, {
    method: 'PATCH',
    body: JSON.stringify({ i, j, relation_code }),
  });

export const markBatchStemDone = (batchStemId: number) =>
  apiFetch(`/batch-stems/${batchStemId}/mark-done`, { method: 'POST' });

// ====== Legacy (backward compat) ======

export const createSession = (username: string, stem_text: string) =>
  apiFetch('/sessions', { method: 'POST', body: JSON.stringify({ username, stem_text }) });

export const listSessions = (username?: string) =>
  apiFetch(username ? `/sessions?username=${encodeURIComponent(username)}` : '/sessions');

export const getSession = (id: number) =>
  apiFetch(`/sessions/${id}`);

export const updateSessionStatus = (id: number, status: string) =>
  apiFetch(`/sessions/${id}/status`, { method: 'PATCH', body: JSON.stringify({ status }) });

export const deleteSession = (id: number) =>
  apiFetch(`/sessions/${id}`, { method: 'DELETE' });

export const createSpan = (sessionId: number, data: {
  label_type: string;
  span_text: string;
  char_start: number;
  char_end: number;
  tl_start?: number;
  tl_end?: number;
  source?: string;
}) => apiFetch(`/sessions/${sessionId}/spans`, { method: 'POST', body: JSON.stringify(data) });

export const extractEvents = async (text: string): Promise<ExtractEventsResponse> => {
  const res = await apiFetch('/api/extract-events', {
    method: 'POST',
    body: JSON.stringify({ text }),
  });
  return res as ExtractEventsResponse;
};

export interface ExtractEventsResponse {
  events: Array<{ span_text: string; char_start: number; char_end: number }>;
  skipped: Array<{ text: string; reason: string }>;
}

export const extractTimeline = (sessionId: number) =>
  apiFetch('/api/extract-timeline', { method: 'POST', body: JSON.stringify({ session_id: sessionId }) });

export const llmLabelAndTimeline = async (batchStemId: number, text: string): Promise<LLMLabelAndTimelineResponse> => {
  const res = await apiFetch('/api/llm-label-and-timeline', {
    method: 'POST',
    body: JSON.stringify({ batch_stem_id: batchStemId, text }),
  });
  return res as LLMLabelAndTimelineResponse;
};

export const updateSpan = (spanId: number, tl_start: number, tl_end: number) =>
  apiFetch(`/spans/${spanId}`, { method: 'PATCH', body: JSON.stringify({ tl_start, tl_end }) });

export const deleteSpan = (spanId: number) =>
  apiFetch(`/spans/${spanId}`, { method: 'DELETE' });

// ====== Group annotation workflow (inter-annotator agreement) ======
// See context/group_workflow_redesign.md for the design.

export const listUsers = () => apiFetch('/users');

export const createGroupTask = (data: { stem_id: number; event_user_id: number; timeline_user_ids: number[] }) =>
  apiFetch('/group-tasks', { method: 'POST', body: JSON.stringify(data) });

export const distributeGroupTasks = (data: {
  stem_ids: number[];
  pool_user_ids?: number[];
  mode?: 'random' | 'manual';
  event_user_id?: number;
}) =>
  apiFetch('/group-tasks/distribute', { method: 'POST', body: JSON.stringify(data) });

export const listMyTasks = () => apiFetch('/my-tasks');

export const reassignGroupMember = (taskId: number, memberId: number, userId: number) =>
  apiFetch(`/group-tasks/${taskId}/members/${memberId}/reassign`, { method: 'POST', body: JSON.stringify({ user_id: userId }) });

export const listGroupTasks = () => apiFetch('/group-tasks');

export const getGroupTasksDashboard = () => apiFetch('/group-tasks/dashboard');

export const getGroupTask = (taskId: number) => apiFetch(`/group-tasks/${taskId}`);

export const listGroupEvents = (taskId: number) => apiFetch(`/group-tasks/${taskId}/events`);

export const createGroupEvent = (taskId: number, data: { span_text: string; char_start: number; char_end: number }) =>
  apiFetch(`/group-tasks/${taskId}/events`, { method: 'POST', body: JSON.stringify(data) });

export const deleteGroupEvent = (taskId: number, spanId: number) =>
  apiFetch(`/group-tasks/${taskId}/events/${spanId}`, { method: 'DELETE' });

export const submitGroupEvents = (taskId: number) =>
  apiFetch(`/group-tasks/${taskId}/submit-events`, { method: 'POST' });

export const getMyTimeline = (taskId: number) => apiFetch(`/group-tasks/${taskId}/my-timeline`);

export const upsertMyTimeline = (taskId: number, positions: Array<{ span_id: number; tl_start: number; tl_end: number; source?: string }>) =>
  apiFetch(`/group-tasks/${taskId}/my-timeline`, { method: 'PUT', body: JSON.stringify({ positions }) });

export const llmExtractMyTimeline = (taskId: number) =>
  apiFetch(`/group-tasks/${taskId}/my-timeline/llm-extract`, { method: 'POST' });

export const getMyMatrix = (taskId: number) => apiFetch(`/group-tasks/${taskId}/my-matrix`);

export const saveMyMatrix = (taskId: number) =>
  apiFetch(`/group-tasks/${taskId}/my-matrix/save`, { method: 'POST' });

export const overrideMyMatrix = (taskId: number, i: number, j: number, relation_code: number) =>
  apiFetch(`/group-tasks/${taskId}/my-matrix/override`, { method: 'PATCH', body: JSON.stringify({ i, j, relation_code }) });

export const submitGroupTimeline = (taskId: number) =>
  apiFetch(`/group-tasks/${taskId}/submit-timeline`, { method: 'POST' });

export const getGroupAgreement = (taskId: number) => apiFetch(`/group-tasks/${taskId}/agreement`);

export const getGroupRevisions = (taskId: number) => apiFetch(`/group-tasks/${taskId}/revisions`);

export const getGroupAgreementRuns = (taskId: number) => apiFetch(`/group-tasks/${taskId}/agreement-runs`);

export const decideGroupTask = (taskId: number, decision: string | null) =>
  apiFetch(`/group-tasks/${taskId}/accept`, { method: 'POST', body: JSON.stringify({ decision }) });
