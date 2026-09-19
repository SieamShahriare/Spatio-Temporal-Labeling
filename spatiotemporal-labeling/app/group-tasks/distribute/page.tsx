'use client';

import { useEffect, useState } from 'react';
import { useRouter } from 'next/navigation';
import { listStems, listUsers, distributeGroupTasks } from '@/lib/api';
import { StemOut, UserBrief, DistributeResponse } from '@/lib/types';
import { useAuth } from '@/lib/AuthContext';

type Mode = 'random' | 'manual';

// Bulk allocation per context/group_workflow_redesign.md §3, extended with a
// manual mode: pin one fixed event annotator across the whole batch, and let
// the rest of the pool rotate through the 3 timeline slots (same shuffle/
// balance logic as random mode, just applied to pool-minus-that-person).
// Replaces one-task-at-a-time creation as the primary path; see
// app/group-tasks/create/page.tsx for that form, kept for now per spec §10.3.
export default function DistributeGroupTasksPage() {
  const router = useRouter();
  const { user, loading: authLoading } = useAuth();
  const [stems, setStems] = useState<StemOut[]>([]);
  const [users, setUsers] = useState<UserBrief[]>([]);
  const [selectedStemIds, setSelectedStemIds] = useState<Set<number>>(new Set());
  const [selectedUserIds, setSelectedUserIds] = useState<Set<number>>(new Set());
  const [mode, setMode] = useState<Mode>('random');
  const [eventUserId, setEventUserId] = useState<number | ''>('');
  const [loading, setLoading] = useState(true);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState('');
  const [result, setResult] = useState<DistributeResponse | null>(null);

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
        const items: StemOut[] = stemsRes.items ?? [];
        setStems(items);
        setUsers(usersRes ?? []);
        setSelectedUserIds(new Set((usersRes ?? []).map((u: UserBrief) => u.id)));
      } catch (e: unknown) {
        if (!cancelled) setError(e instanceof Error ? e.message : 'Failed to load stems/users.');
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => { cancelled = true; };
  }, [user]);

  const toggleStem = (id: number) => {
    setSelectedStemIds(prev => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id); else next.add(id);
      return next;
    });
  };

  const toggleUser = (id: number) => {
    setSelectedUserIds(prev => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id); else next.add(id);
      if (eventUserId !== '' && !next.has(eventUserId)) setEventUserId('');
      return next;
    });
  };

  const availableStems = stems.filter(s => s.state === 'available');
  const poolSize = selectedUserIds.size;
  const timelinePoolSize = mode === 'manual' && eventUserId !== '' ? poolSize - 1 : poolSize;

  const canSubmit = selectedStemIds.size > 0 && (
    mode === 'random' ? poolSize >= 4 : (eventUserId !== '' && timelinePoolSize >= 3)
  );

  const handleSubmit = async () => {
    if (!canSubmit) return;
    setSubmitting(true);
    setError('');
    try {
      const res: DistributeResponse = await distributeGroupTasks({
        stem_ids: Array.from(selectedStemIds),
        pool_user_ids: Array.from(selectedUserIds),
        mode,
        ...(mode === 'manual' ? { event_user_id: Number(eventUserId) } : {}),
      });
      setResult(res);
      setSelectedStemIds(new Set());
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : 'Distribution failed.');
    } finally {
      setSubmitting(false);
    }
  };

  if (authLoading || loading) {
    return <div style={{ minHeight: '100vh', background: 'var(--background-page)' }} />;
  }

  return (
    <main style={{ maxWidth: 800, margin: '0 auto', padding: '32px 20px', fontFamily: 'system-ui, sans-serif' }}>
      <button
        onClick={() => router.push('/group-tasks')}
        style={{ background: 'none', border: 'none', cursor: 'pointer', color: 'var(--text-muted)', fontSize: 13, padding: 0, marginBottom: 6 }}
      >
        ← Group Tasks
      </button>
      <h1 style={{ fontSize: 20, fontWeight: 700, margin: '0 0 4px' }}>Distribute Stems</h1>
      <p style={{ fontSize: 13, color: 'var(--text-muted)', margin: '0 0 20px' }}>
        Every selected stem gets 1 event annotator + 3 timeline annotators.
      </p>

      <div style={{ display: 'flex', gap: 0, marginBottom: 20, borderBottom: '2px solid var(--border)' }}>
        {(['random', 'manual'] as const).map(m => (
          <button
            key={m}
            onClick={() => setMode(m)}
            style={{
              padding: '8px 20px', border: 'none', background: 'none', cursor: 'pointer', fontSize: 14,
              fontWeight: mode === m ? 700 : 400, color: mode === m ? '#2563eb' : 'var(--text-muted)',
              borderBottom: mode === m ? '2px solid #2563eb' : '2px solid transparent', marginBottom: -2,
            }}
          >
            {m === 'random' ? 'Random' : 'Manual'}
          </button>
        ))}
      </div>

      {error && (
        <div style={{ background: 'var(--error-bg)', border: '1px solid var(--error-border)', borderRadius: 6, padding: '8px 12px', marginBottom: 16, fontSize: 13, color: 'var(--error)' }}>
          {error}
        </div>
      )}

      {result && (
        <div style={{ background: 'var(--success-bg)', border: '1px solid var(--border)', borderRadius: 6, padding: '12px 14px', marginBottom: 20, fontSize: 13 }}>
          <strong style={{ color: 'var(--success)' }}>
            Created {result.created_task_ids.length} group task{result.created_task_ids.length !== 1 ? 's' : ''}
          </strong>
          {' '}from a pool of {result.pool_size}.
          {result.skipped.length > 0 && (
            <div style={{ marginTop: 8, color: 'var(--text-muted)' }}>
              Skipped {result.skipped.length}: {result.skipped.map(s => `#${s.stem_id} (${s.reason})`).join(', ')}
            </div>
          )}
          <div style={{ marginTop: 10 }}>
            <button
              onClick={() => router.push('/group-tasks')}
              style={{ padding: '6px 14px', background: '#2563eb', color: '#fff', border: 'none', borderRadius: 6, cursor: 'pointer', fontWeight: 600, fontSize: 12 }}
            >
              View Group Tasks →
            </button>
          </div>
        </div>
      )}

      {mode === 'random' ? (
        <p style={{ fontSize: 12, color: 'var(--text-disabled)', marginBottom: 16, marginTop: -4 }}>
          All 4 roles are assigned automatically from the pool below (randomized pairings, balanced workload,
          re-shuffled every full cycle — see context/group_workflow_redesign.md §3).
        </p>
      ) : (
        <p style={{ fontSize: 12, color: 'var(--text-disabled)', marginBottom: 16, marginTop: -4 }}>
          The event annotator you pick below does event labeling on <strong>every</strong> selected stem.
          Everyone else in the pool rotates through the 3 timeline slots per stem, same balancing as random mode.
        </p>
      )}

      <div style={{ background: 'var(--surface)', border: '1px solid var(--border)', borderRadius: 10, padding: 20, marginBottom: 20 }}>
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 10 }}>
          <h2 style={{ fontSize: 14, fontWeight: 700, margin: 0 }}>Annotator Pool ({poolSize})</h2>
          <div style={{ display: 'flex', gap: 8 }}>
            <button onClick={() => setSelectedUserIds(new Set(users.map(u => u.id)))} style={linkBtn}>Select all</button>
            <button onClick={() => { setSelectedUserIds(new Set()); setEventUserId(''); }} style={linkBtn}>Clear</button>
          </div>
        </div>
        {mode === 'random' && poolSize < 4 && (
          <p style={{ fontSize: 12, color: 'var(--error)', marginBottom: 10 }}>
            At least 4 annotators are required. Below 5, tasks are scored automatically but have no manual accept/reject
            (see context/group_workflow_redesign.md §13).
          </p>
        )}
        {mode === 'manual' && timelinePoolSize < 3 && (
          <p style={{ fontSize: 12, color: 'var(--error)', marginBottom: 10 }}>
            At least 3 annotators besides the fixed event annotator are required for the timeline roles.
          </p>
        )}
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(180px, 1fr))', gap: 6, maxHeight: 220, overflowY: 'auto' }}>
          {users.map(u => (
            <label key={u.id} style={{ display: 'flex', alignItems: 'center', gap: 6, fontSize: 13, cursor: 'pointer' }}>
              <input type="checkbox" checked={selectedUserIds.has(u.id)} onChange={() => toggleUser(u.id)} />
              {u.username}
            </label>
          ))}
        </div>

        {mode === 'manual' && (
          <div style={{ marginTop: 14, paddingTop: 14, borderTop: '1px solid var(--border)' }}>
            <label style={{ display: 'block', fontSize: 12, fontWeight: 600, color: 'var(--text-muted)', marginBottom: 6 }}>
              Event Annotator (fixed for this whole batch)
            </label>
            <select
              value={eventUserId}
              onChange={e => setEventUserId(e.target.value ? Number(e.target.value) : '')}
              style={{ width: '100%', padding: '8px 10px', borderRadius: 6, border: '1px solid var(--border-input)', fontSize: 13, background: 'var(--surface)', color: 'var(--text-primary)' }}
            >
              <option value="">Select a user…</option>
              {users.filter(u => selectedUserIds.has(u.id)).map(u => (
                <option key={u.id} value={u.id}>{u.username}</option>
              ))}
            </select>
          </div>
        )}
      </div>

      <div style={{ background: 'var(--surface)', border: '1px solid var(--border)', borderRadius: 10, padding: 20, marginBottom: 20 }}>
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 10 }}>
          <h2 style={{ fontSize: 14, fontWeight: 700, margin: 0 }}>Stems ({selectedStemIds.size} selected)</h2>
          <div style={{ display: 'flex', gap: 8 }}>
            <button onClick={() => setSelectedStemIds(new Set(availableStems.map(s => s.id)))} style={linkBtn}>Select all available</button>
            <button onClick={() => setSelectedStemIds(new Set())} style={linkBtn}>Clear</button>
          </div>
        </div>
        <p style={{ fontSize: 12, color: 'var(--text-disabled)', marginBottom: 10 }}>
          A stem already used by another group task is skipped automatically at distribution time.
        </p>
        <div style={{ maxHeight: 360, overflowY: 'auto', display: 'flex', flexDirection: 'column', gap: 4 }}>
          {stems.map(s => (
            <label key={s.id} style={{ display: 'flex', alignItems: 'flex-start', gap: 8, fontSize: 13, padding: '6px 8px', borderRadius: 6, background: selectedStemIds.has(s.id) ? 'var(--surface-alt)' : 'transparent', cursor: 'pointer' }}>
              <input type="checkbox" checked={selectedStemIds.has(s.id)} onChange={() => toggleStem(s.id)} style={{ marginTop: 2 }} />
              <span>
                <span style={{ fontFamily: 'monospace', color: 'var(--text-disabled)' }}>#{s.id}</span>{' '}
                {s.text.slice(0, 90)}{s.text.length > 90 ? '…' : ''}
                {s.state !== 'available' && (
                  <span style={{ marginLeft: 6, fontSize: 11, color: 'var(--warning-text)' }}>({s.state})</span>
                )}
              </span>
            </label>
          ))}
        </div>
      </div>

      <button
        onClick={handleSubmit}
        disabled={!canSubmit || submitting}
        style={{
          padding: '10px 20px',
          background: (!canSubmit || submitting) ? 'var(--text-disabled)' : '#2563eb',
          color: '#fff', border: 'none', borderRadius: 6,
          cursor: (!canSubmit || submitting) ? 'not-allowed' : 'pointer', fontWeight: 600, fontSize: 14,
        }}
      >
        {submitting ? 'Distributing…' : `Distribute ${selectedStemIds.size} Stem${selectedStemIds.size !== 1 ? 's' : ''}`}
      </button>
    </main>
  );
}

const linkBtn: React.CSSProperties = {
  background: 'none',
  border: 'none',
  cursor: 'pointer',
  color: '#2563eb',
  fontSize: 12,
  padding: 0,
};
