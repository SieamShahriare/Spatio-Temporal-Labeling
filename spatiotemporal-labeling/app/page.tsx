'use client';

import { useState, useEffect } from 'react';
import { useRouter } from 'next/navigation';
import { createSession, listSessions, deleteSession, exportCsvUrl, exportJsonUrl } from '@/lib/api';
import { Session } from '@/lib/types';

export default function LandingPage() {
  const router = useRouter();
  const [username, setUsername] = useState('');
  const [stemText, setStemText] = useState('');
  const [sessions, setSessions] = useState<Session[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [fetching, setFetching] = useState(true);
  const [mounted, setMounted] = useState(false);

  useEffect(() => {
    setMounted(true);
    listSessions()
      .then(setSessions)
      .catch(() => setSessions([]))
      .finally(() => setFetching(false));
  }, []);

  if (!mounted) {
    return <div style={{ minHeight: '100vh', background: '#f9fafb' }} />;
  }

  const handleStart = async () => {
    if (!username.trim()) { setError('Please enter a username.'); return; }
    if (!stemText.trim()) { setError('Please paste a stem text.'); return; }
    setError('');
    setLoading(true);
    try {
      const { session_id } = await createSession(username.trim(), stemText.trim());
      router.push(`/annotate/${session_id}`);
    } catch (e: any) {
      setError(e.message ?? 'Failed to create session.');
    } finally {
      setLoading(false);
    }
  };

  const handleDelete = async (id: number) => {
    if (!confirm('Delete this session?')) return;
    await deleteSession(id).catch(() => {});
    setSessions(s => s.filter(x => x.id !== id));
  };

  return (
    <main style={{ maxWidth: 720, margin: '0 auto', padding: '40px 20px', fontFamily: 'system-ui, sans-serif' }}>
      <h1 style={{ fontSize: 22, fontWeight: 700, marginBottom: 4 }}>
        Spatiotemporal Annotation Tool
      </h1>
      <p style={{ fontSize: 14, color: '#6b7280', marginBottom: 32 }}>
        Label event and time spans in text, arrange them on a timeline, and compute Allen's Interval Algebra relations.
      </p>

      {/* New session form */}
      <section style={{ background: '#fff', border: '1px solid #e5e7eb', borderRadius: 10, padding: 24, marginBottom: 32 }}>
        <h2 style={{ fontSize: 16, fontWeight: 600, marginBottom: 16 }}>Start New Annotation</h2>
        <div style={{ marginBottom: 14 }}>
          <label style={{ display: 'block', fontSize: 13, fontWeight: 500, marginBottom: 4 }}>
            Username
          </label>
          <input
            id="username-input"
            type="text"
            value={username}
            onChange={e => setUsername(e.target.value)}
            placeholder="e.g. alice"
            style={{
              width: '100%',
              padding: '8px 12px',
              border: '1px solid #d1d5db',
              borderRadius: 6,
              fontSize: 14,
              boxSizing: 'border-box',
            }}
          />
        </div>
        <div style={{ marginBottom: 16 }}>
          <label style={{ display: 'block', fontSize: 13, fontWeight: 500, marginBottom: 4 }}>
            Stem Text
          </label>
          <textarea
            id="stem-text-input"
            value={stemText}
            onChange={e => setStemText(e.target.value)}
            rows={5}
            placeholder="Paste the passage to annotate here…"
            style={{
              width: '100%',
              padding: '8px 12px',
              border: '1px solid #d1d5db',
              borderRadius: 6,
              fontSize: 14,
              resize: 'vertical',
              boxSizing: 'border-box',
            }}
          />
        </div>
        {error && <p style={{ color: '#dc2626', fontSize: 13, marginBottom: 10 }}>{error}</p>}
        <button
          id="start-labeling-btn"
          onClick={handleStart}
          disabled={loading}
          style={{
            padding: '9px 20px',
            background: loading ? '#9ca3af' : '#2563eb',
            color: '#fff',
            border: 'none',
            borderRadius: 6,
            cursor: loading ? 'not-allowed' : 'pointer',
            fontWeight: 600,
            fontSize: 14,
          }}
        >
          {loading ? 'Creating…' : 'Start Labeling →'}
        </button>
      </section>

      {/* Export links */}
      <section style={{ marginBottom: 32 }}>
        <h2 style={{ fontSize: 16, fontWeight: 600, marginBottom: 10 }}>Export Completed Annotations</h2>
        <div style={{ display: 'flex', gap: 10 }}>
          <a
            href={exportCsvUrl()}
            download
            style={{
              padding: '7px 16px',
              background: '#f0fdf4',
              border: '1px solid #86efac',
              borderRadius: 6,
              color: '#15803d',
              fontWeight: 500,
              fontSize: 13,
              textDecoration: 'none',
            }}
          >
            ↓ Download CSV
          </a>
          <a
            href={exportJsonUrl()}
            download
            style={{
              padding: '7px 16px',
              background: '#eff6ff',
              border: '1px solid #93c5fd',
              borderRadius: 6,
              color: '#1d4ed8',
              fontWeight: 500,
              fontSize: 13,
              textDecoration: 'none',
            }}
          >
            ↓ Download JSON
          </a>
        </div>
      </section>

      {/* Session list */}
      <section>
        <h2 style={{ fontSize: 16, fontWeight: 600, marginBottom: 10 }}>Past Sessions</h2>
        {fetching ? (
          <p style={{ color: '#9ca3af', fontSize: 14 }}>Loading…</p>
        ) : sessions.length === 0 ? (
          <p style={{ color: '#9ca3af', fontSize: 14 }}>No sessions yet.</p>
        ) : (
          <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 13 }}>
            <thead>
              <tr style={{ background: '#f9fafb' }}>
                <th style={thStyle}>ID</th>
                <th style={thStyle}>Username</th>
                <th style={thStyle}>Text Preview</th>
                <th style={thStyle}>Status</th>
                <th style={thStyle}>Created</th>
                <th style={thStyle}>Actions</th>
              </tr>
            </thead>
            <tbody>
              {sessions.map(s => (
                <tr key={s.id} style={{ borderBottom: '1px solid #f3f4f6' }}>
                  <td style={tdStyle}>{s.id}</td>
                  <td style={tdStyle}>{s.username}</td>
                  <td style={{ ...tdStyle, maxWidth: 200, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                    {s.stem_text.slice(0, 60)}{s.stem_text.length > 60 ? '…' : ''}
                  </td>
                  <td style={tdStyle}>
                    <span style={{
                      padding: '2px 8px',
                      borderRadius: 20,
                      fontSize: 11,
                      fontWeight: 600,
                      background: s.status === 'done' ? '#dcfce7' : '#fef9c3',
                      color: s.status === 'done' ? '#15803d' : '#92400e',
                    }}>
                      {s.status}
                    </span>
                  </td>
                  <td style={tdStyle}>{new Date(s.created_at).toLocaleDateString()}</td>
                  <td style={tdStyle}>
                    <button
                      onClick={() => router.push(`/annotate/${s.id}`)}
                      style={btnStyle('#eff6ff', '#1d4ed8')}
                    >
                      Open
                    </button>
                    {' '}
                    <button
                      onClick={() => handleDelete(s.id)}
                      style={btnStyle('#fef2f2', '#dc2626')}
                    >
                      Delete
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </section>
    </main>
  );
}

const thStyle: React.CSSProperties = {
  padding: '8px 10px',
  textAlign: 'left',
  fontWeight: 600,
  color: '#6b7280',
  borderBottom: '1px solid #e5e7eb',
};

const tdStyle: React.CSSProperties = {
  padding: '8px 10px',
  color: '#374151',
};

const btnStyle = (bg: string, color: string): React.CSSProperties => ({
  padding: '3px 10px',
  background: bg,
  color,
  border: `1px solid ${color}`,
  borderRadius: 4,
  cursor: 'pointer',
  fontSize: 12,
  fontWeight: 500,
});
