// API helper — all calls go to NEXT_PUBLIC_API_URL (FastAPI backend)

const BASE = process.env.NEXT_PUBLIC_API_URL ?? 'http://localhost:8000';

async function apiFetch(path: string, options?: RequestInit) {
  const res = await fetch(`${BASE}${path}`, {
    headers: { 'Content-Type': 'application/json', ...options?.headers },
    ...options,
  });
  if (!res.ok) {
    const text = await res.text();
    throw new Error(`API ${res.status}: ${text}`);
  }
  if (res.status === 204) return null;
  return res.json();
}

// Sessions
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

// Spans
export const createSpan = (sessionId: number, data: {
  label_type: string;
  span_text: string;
  char_start: number;
  char_end: number;
  tl_start?: number;
  tl_end?: number;
  source?: string;
}) => apiFetch(`/sessions/${sessionId}/spans`, { method: 'POST', body: JSON.stringify(data) });

export const extractEvents = (text: string) =>
  apiFetch('/api/extract-events', { method: 'POST', body: JSON.stringify({ text }) });

export const extractTimeline = (sessionId: number) =>
  apiFetch('/api/extract-timeline', { method: 'POST', body: JSON.stringify({ session_id: sessionId }) });

export const updateSpan = (spanId: number, tl_start: number, tl_end: number) =>
  apiFetch(`/spans/${spanId}`, { method: 'PATCH', body: JSON.stringify({ tl_start, tl_end }) });

export const deleteSpan = (spanId: number) =>
  apiFetch(`/spans/${spanId}`, { method: 'DELETE' });

// Matrix
export const getMatrix = (sessionId: number) =>
  apiFetch(`/sessions/${sessionId}/matrix`);

export const saveMatrix = (sessionId: number) =>
  apiFetch(`/sessions/${sessionId}/matrix/save`, { method: 'POST' });

export const overrideMatrix = (sessionId: number, i: number, j: number, relation_code: number) =>
  apiFetch(`/sessions/${sessionId}/matrix/override`, {
    method: 'PATCH',
    body: JSON.stringify({ i, j, relation_code }),
  });

// Export URLs (direct links, not fetched)
export const exportCsvUrl = () => `${BASE}/export/csv`;
export const exportJsonUrl = () => `${BASE}/export/json`;

export const exportSessionJson = async (sessionId: number) => {
  const res = await fetch(`${BASE}/sessions/${sessionId}/export`);
  if (!res.ok) throw new Error(`API ${res.status}`);
  return res.blob();
};
