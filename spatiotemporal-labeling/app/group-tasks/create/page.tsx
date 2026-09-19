'use client';

import { useEffect, useState } from 'react';
import { useRouter } from 'next/navigation';
import { listStems, listUsers, createGroupTask } from '@/lib/api';
import { StemOut, UserBrief } from '@/lib/types';
import { useAuth } from '@/lib/AuthContext';

export default function CreateGroupTaskPage() {
  const router = useRouter();
  const { user, loading: authLoading } = useAuth();
  const [stems, setStems] = useState<StemOut[]>([]);
  const [users, setUsers] = useState<UserBrief[]>([]);
  const [stemId, setStemId] = useState<number | ''>('');
  const [eventUserId, setEventUserId] = useState<number | ''>('');
  const [timelineUserIds, setTimelineUserIds] = useState<(number | '')[]>(['', '', '']);
  const [loading, setLoading] = useState(true);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState('');

  useEffect(() => {
    if (!authLoading && !user) router.replace('/login');
  }, [user, authLoading, router]);

  useEffect(() => {
    if (!user) return;
    let cancelled = false;
    (async () => {
      try {
        const [stemsRes, usersRes] = await Promise.all([listStems({ page_size: 100 }), listUsers()]);
        if (cancelled) return;
        setStems(stemsRes.items ?? []);
        setUsers(usersRes ?? []);
      } catch (e: unknown) {
        if (!cancelled) setError(e instanceof Error ? e.message : 'Failed to load stems/users.');
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => { cancelled = true; };
  }, [user]);

  const chosenIds = [eventUserId, ...timelineUserIds].filter(v => v !== '') as number[];
  const hasDuplicate = new Set(chosenIds).size !== chosenIds.length;
  const allChosen = eventUserId !== '' && timelineUserIds.every(v => v !== '') && stemId !== '';

  const handleSubmit = async () => {
    if (!allChosen || hasDuplicate) return;
    setSubmitting(true);
    setError('');
    try {
      const task = await createGroupTask({
        stem_id: Number(stemId),
        event_user_id: Number(eventUserId),
        timeline_user_ids: timelineUserIds.map(Number),
      });
      router.push(`/group-tasks/${task.id}`);
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : 'Failed to create group task.');
      setSubmitting(false);
    }
  };

  if (authLoading || loading) {
    return <div style={{ minHeight: '100vh', background: 'var(--background-page)' }} />;
  }

  return (
    <main style={{ maxWidth: 640, margin: '0 auto', padding: '32px 20px', fontFamily: 'system-ui, sans-serif' }}>
      <button
        onClick={() => router.push('/group-tasks')}
        style={{ background: 'none', border: 'none', cursor: 'pointer', color: 'var(--text-muted)', fontSize: 13, padding: 0, marginBottom: 6 }}
      >
        ← Group Tasks
      </button>
      <h1 style={{ fontSize: 20, fontWeight: 700, margin: '0 0 4px' }}>New Group Annotation Task</h1>
      <p style={{ fontSize: 13, color: 'var(--text-muted)', margin: '0 0 24px' }}>
        One event annotator marks the events; three timeline annotators independently position them.
        Agreement is computed automatically once all three submit.
      </p>

      {error && (
        <div style={{ background: 'var(--error-bg)', border: '1px solid var(--error-border)', borderRadius: 6, padding: '8px 12px', marginBottom: 16, fontSize: 13, color: 'var(--error)' }}>
          {error}
        </div>
      )}

      <div style={{ background: 'var(--surface)', border: '1px solid var(--border)', borderRadius: 10, padding: 20, display: 'flex', flexDirection: 'column', gap: 18 }}>
        <div>
          <label style={label}>Stem</label>
          <select value={stemId} onChange={e => setStemId(e.target.value ? Number(e.target.value) : '')} style={select}>
            <option value="">Select a stem…</option>
            {stems.map(s => (
              <option key={s.id} value={s.id}>
                #{s.id} — {s.text.slice(0, 70)}{s.text.length > 70 ? '…' : ''}
              </option>
            ))}
          </select>
        </div>

        <div>
          <label style={label}>Event Annotator (marks events, Step 1 only)</label>
          <select value={eventUserId} onChange={e => setEventUserId(e.target.value ? Number(e.target.value) : '')} style={select}>
            <option value="">Select a user…</option>
            {users.map(u => (
              <option key={u.id} value={u.id}>{u.username} ({u.email})</option>
            ))}
          </select>
        </div>

        {timelineUserIds.map((val, idx) => (
          <div key={idx}>
            <label style={label}>Timeline Annotator #{idx + 1} (independently positions events)</label>
            <select
              value={val}
              onChange={e => {
                const v = e.target.value ? Number(e.target.value) : '';
                setTimelineUserIds(prev => prev.map((p, i) => i === idx ? v : p));
              }}
              style={select}
            >
              <option value="">Select a user…</option>
              {users.map(u => (
                <option key={u.id} value={u.id}>{u.username} ({u.email})</option>
              ))}
            </select>
          </div>
        ))}

        {hasDuplicate && (
          <p style={{ fontSize: 12, color: 'var(--error)', margin: 0 }}>
            The event annotator and all timeline annotators must be distinct users.
          </p>
        )}

        <button
          onClick={handleSubmit}
          disabled={!allChosen || hasDuplicate || submitting}
          style={{
            padding: '10px 16px',
            background: (!allChosen || hasDuplicate) ? 'var(--text-disabled)' : '#2563eb',
            color: '#fff',
            border: 'none',
            borderRadius: 6,
            cursor: (!allChosen || hasDuplicate || submitting) ? 'not-allowed' : 'pointer',
            fontWeight: 600,
            fontSize: 14,
          }}
        >
          {submitting ? 'Creating…' : 'Create Group Task'}
        </button>
      </div>
    </main>
  );
}

const label: React.CSSProperties = {
  display: 'block',
  fontSize: 12,
  fontWeight: 600,
  color: 'var(--text-muted)',
  marginBottom: 6,
};

const select: React.CSSProperties = {
  width: '100%',
  padding: '8px 10px',
  borderRadius: 6,
  border: '1px solid var(--border-input)',
  fontSize: 13,
  background: 'var(--surface)',
  color: 'var(--text-primary)',
};
