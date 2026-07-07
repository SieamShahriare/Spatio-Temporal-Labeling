'use client';

import { useEffect, useState } from 'react';
import { useParams, useRouter } from 'next/navigation';
import { getBatch, releaseBatch, rebookBatch, exportBatchCsv, exportBatchJson } from '@/lib/api';
import { BatchDetailOut } from '@/lib/types';
import { useAuth } from '@/lib/AuthContext';

function Countdown({ expiresAt }: { expiresAt: string }) {
  const [remaining, setRemaining] = useState(() => {
    return Math.max(0, Math.floor((new Date(expiresAt).getTime() - Date.now()) / 1000));
  });

  useEffect(() => {
    const tick = setInterval(() => {
      setRemaining(Math.max(0, Math.floor((new Date(expiresAt).getTime() - Date.now()) / 1000)));
    }, 1000);
    return () => clearInterval(tick);
  }, [expiresAt]);

  const h = Math.floor(remaining / 3600);
  const m = Math.floor((remaining % 3600) / 60);
  const s = remaining % 60;
  const isUrgent = remaining > 0 && remaining <= 15 * 60;
  const color = remaining <= 0 ? 'var(--error)' : isUrgent ? '#f59e0b' : 'var(--text-primary)';

  return (
    <span style={{ color, fontFamily: 'monospace', fontWeight: 600, fontSize: 14 }}>
      {remaining <= 0 ? 'EXPIRED' : `${h}h ${m}m ${s}s remaining`}
    </span>
  );
}

export default function BatchDetailPage() {
  const params = useParams<{ id: string }>();
  const batchId = parseInt(params.id);
  const router = useRouter();
  const { user, loading: authLoading } = useAuth();
  const [batch, setBatch] = useState<BatchDetailOut | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [rebooking, setRebooking] = useState(false);
  const [releasing, setReleasing] = useState(false);
  const [lockDialog, setLockDialog] = useState(false);
  const [isLocked, setIsLocked] = useState(false);
  const [isExpired, setIsExpired] = useState(true);
  const [pct, setPct] = useState(0);

  useEffect(() => {
    if (!authLoading && !user) {
      router.replace('/login');
    }
  }, [user, authLoading, router]);

  useEffect(() => {
    if (!user) return;
    let cancelled = false;
    const load = async () => {
      setLoading(true);
      setError('');
      try {
        const data = await getBatch(batchId);
        if (cancelled) return;
        setBatch(data);
        const r = Math.max(0, Math.floor((new Date(data.expires_at).getTime() - Date.now()) / 1000));
        const locked = data.status === 'active' && r > 0;
        setIsLocked(locked);
        setIsExpired(!locked);
        setPct(data.progress.total > 0 ? Math.round((data.progress.done / data.progress.total) * 100) : 0);
        if (locked && r > 0 && r <= 15 * 60) {
          setLockDialog(true);
        }
      } catch (e: unknown) {
        if (!cancelled) {
          setError(e instanceof Error ? e.message : 'Failed to load batch.');
        }
      } finally {
        if (!cancelled) setLoading(false);
      }
    };
    load();
    return () => { cancelled = true; };
  }, [batchId, user, router]);

  const handleRelease = async () => {
    if (!confirm('Release this lock? All unfinished stems will return to the pool immediately.')) return;
    setReleasing(true);
    try {
      await releaseBatch(batchId);
      if (batch) setBatch({ ...batch, status: 'released', expires_at: new Date().toISOString() });
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : 'Release failed.');
    } finally {
      setReleasing(false);
    }
  };

  const handleRebook = async () => {
    setRebooking(true);
    try {
      const res = await rebookBatch(batchId);
      if (batch) {
        const newExpires = new Date(Date.now() + res.remaining_seconds * 1000).toISOString();
        setBatch({ ...batch, expires_at: newExpires, rebook_count: batch.rebook_count + 1 });
      }
      setLockDialog(false);
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : 'Re-book failed.');
    } finally {
      setRebooking(false);
    }
  };

  if (authLoading) {
    return <div style={{ minHeight: '100vh', background: 'var(--background-page)' }} />;
  }

  if (loading) {
    return (
      <main style={{ maxWidth: 900, margin: '0 auto', padding: 40, fontFamily: 'system-ui', color: 'var(--text-muted)' }}>
        Loading batch…
      </main>
    );
  }

  if (!batch) {
    return (
      <main style={{ maxWidth: 900, margin: '0 auto', padding: 40, fontFamily: 'system-ui', color: 'var(--error)' }}>
        {error || 'Batch not found.'}
      </main>
    );
  }

  return (
    <main style={{ maxWidth: 900, margin: '0 auto', padding: '32px 20px', fontFamily: 'system-ui, sans-serif' }}>
      <div style={{ display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between', marginBottom: 24 }}>
        <div>
          <button
            onClick={() => router.push('/')}
            style={{ background: 'none', border: 'none', cursor: 'pointer', color: 'var(--text-muted)', fontSize: 13, padding: 0, marginBottom: 6 }}
          >
            ← Dashboard
          </button>
          <h1 style={{ fontSize: 18, fontWeight: 700, margin: 0 }}>{batch.name}</h1>
          <p style={{ fontSize: 13, color: 'var(--text-muted)', margin: '4px 0 0' }}>
            Batch #{batch.id} · by {batch.owner_username}
          </p>
        </div>
        <div style={{ display: 'flex', gap: 8 }}>
          <a
            href={exportBatchCsv(batch.id)}
            download
            style={{ ...btnStyle('var(--surface)', 'var(--text-primary)'), textDecoration: 'none' }}
          >
            CSV
          </a>
          <a
            href={exportBatchJson(batch.id)}
            download
            style={{ ...btnStyle('var(--surface)', 'var(--text-primary)'), textDecoration: 'none' }}
          >
            JSON
          </a>
        </div>
      </div>

      {error && (
        <div style={{
          background: 'var(--error-bg)',
          border: '1px solid var(--error-border)',
          borderRadius: 6,
          padding: '8px 12px',
          marginBottom: 16,
          fontSize: 13,
          color: 'var(--error)',
          display: 'flex',
          justifyContent: 'space-between',
          alignItems: 'center',
        }}>
          <span>{error}</span>
          <button onClick={() => setError('')} style={{ background: 'none', border: 'none', cursor: 'pointer', color: 'var(--text-disabled)', fontSize: 16 }}>×</button>
        </div>
      )}

      <div style={{
        background: 'var(--surface)',
        border: '1px solid var(--border)',
        borderRadius: 10,
        padding: 20,
        marginBottom: 20,
      }}>
        <div style={{ display: 'flex', gap: 16, flexWrap: 'wrap', alignItems: 'center' }}>
          <div style={{ flex: '1 1 200px' }}>
            <div style={{ fontSize: 12, color: 'var(--text-muted)', marginBottom: 4 }}>STATUS</div>
            <span style={{
              padding: '4px 12px',
              borderRadius: 20,
              fontSize: 12,
              fontWeight: 600,
              background: batch.status === 'active' ? 'var(--warning-bg)' : batch.status === 'released' ? 'var(--info-bg)' : 'var(--error-bg)',
              color: batch.status === 'active' ? 'var(--warning-text)' : batch.status === 'released' ? 'var(--info)' : 'var(--error)',
            }}>
              {batch.status.toUpperCase()}
            </span>
          </div>
          <div style={{ flex: '1 1 200px' }}>
            <div style={{ fontSize: 12, color: 'var(--text-muted)', marginBottom: 4 }}>LOCK EXPIRES</div>
            {isLocked ? <Countdown expiresAt={batch.expires_at} /> : <span style={{ color: 'var(--error)', fontWeight: 600 }}>EXPIRED / RELEASED</span>}
          </div>
          <div style={{ flex: '1 1 200px' }}>
            <div style={{ fontSize: 12, color: 'var(--text-muted)', marginBottom: 4 }}>PROGRESS</div>
            <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
              <div style={{ flex: 1, height: 8, background: 'var(--border)', borderRadius: 4, overflow: 'hidden' }}>
                <div style={{ width: `${pct}%`, height: '100%', background: '#2563eb', borderRadius: 4 }} />
              </div>
              <span style={{ fontSize: 12, fontWeight: 600, fontFamily: 'monospace' }}>{batch.progress.done}/{batch.progress.total}</span>
            </div>
          </div>
          <div style={{ flex: '1 1 200px' }}>
            <div style={{ fontSize: 12, color: 'var(--text-muted)', marginBottom: 4 }}>RE-BOOKS</div>
            <span style={{ fontWeight: 600, fontFamily: 'monospace' }}>{batch.rebook_count}/2</span>
          </div>
        </div>

        {isLocked && (
          <div style={{ marginTop: 16, display: 'flex', gap: 8, flexWrap: 'wrap' }}>
            <button
              onClick={() => setLockDialog(true)}
              style={btnStyle('#f59e0b', '#000')}
            >
              Re-book Lock
            </button>
            <button
              onClick={handleRelease}
              disabled={releasing}
              style={{
                ...btnStyle('#dc2626', '#fff'),
                opacity: releasing ? 0.5 : 1,
              }}
            >
              {releasing ? 'Releasing…' : 'Release Lock Now'}
            </button>
            <button
              onClick={() => router.push(`/annotate/${batch.id}`)}
              style={btnStyle('#2563eb', '#fff')}
            >
              Open Annotator
            </button>
          </div>
        )}

        {isExpired && batch.status !== 'released' && (
          <div style={{ marginTop: 16, padding: '10px 14px', background: 'var(--warning-bg)', borderRadius: 6, fontSize: 13, color: 'var(--warning-text)' }}>
            This batch&apos;s lock has expired. Stems have returned to the pool. Completed work is still viewable.
          </div>
        )}
      </div>

      <div style={{
        background: 'var(--surface)',
        border: '1px solid var(--border)',
        borderRadius: 10,
        overflow: 'hidden',
      }}>
        <div style={{ padding: '12px 16px', background: 'var(--surface-alt)', borderBottom: '1px solid var(--border)', fontWeight: 600, fontSize: 13 }}>
          STEMS ({batch.progress.done}/{batch.progress.total} done)
        </div>
        <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 13 }}>
          <thead>
            <tr style={{ background: 'var(--surface-alt)' }}>
              <th style={th}>ID</th>
              <th style={{ ...th, flex: 1 }}>Text</th>
              <th style={th}>Status</th>
              <th style={th}>Action</th>
            </tr>
          </thead>
          <tbody>
            {batch.stems.map(bs => (
              <tr key={bs.id} style={{ borderBottom: '1px solid var(--border)' }}>
                <td style={td}>{bs.stem_id}</td>
                <td style={{ ...td, maxWidth: 400, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                  {bs.stem_text.slice(0, 100)}{bs.stem_text.length > 100 ? '…' : ''}
                </td>
                <td style={td}>
                  <span style={{
                    padding: '2px 8px',
                    borderRadius: 20,
                    fontSize: 11,
                    fontWeight: 600,
                    background: bs.status === 'done' ? 'var(--success-bg)' : bs.status === 'in_progress' ? 'var(--warning-bg)' : 'var(--surface-alt)',
                    color: bs.status === 'done' ? 'var(--success)' : bs.status === 'in_progress' ? 'var(--warning-text)' : 'var(--text-muted)',
                  }}>
                    {bs.status.replace('_', ' ')}
                  </span>
                </td>
                <td style={td}>
                  <button
                    onClick={() => {
                      if (isExpired && bs.status !== 'done') {
                        alert('This batch has expired. You can only review completed stems.');
                        return;
                      }
                      router.push(`/annotate/${batch.id}/${bs.stem_id}`);
                    }}
                    style={btnStyle('#2563eb', '#fff')}
                  >
                    {bs.status === 'done' ? 'Review' : bs.status === 'in_progress' ? 'Continue' : 'Start'}
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {lockDialog && (
        <div style={{
          position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.6)', display: 'flex', alignItems: 'center', justifyContent: 'center', zIndex: 100,
        }}>
          <div style={{
            background: 'var(--surface)',
            border: '1px solid var(--border)',
            borderRadius: 12,
            padding: 24,
            maxWidth: 440,
            width: '90%',
          }}>
            <h2 style={{ fontSize: 16, fontWeight: 700, marginBottom: 8 }}>Lock Expiring Soon</h2>
            <p style={{ fontSize: 13, color: 'var(--text-muted)', marginBottom: 8 }}>
              Your lock expires in <strong><Countdown expiresAt={batch.expires_at} /></strong>.
            </p>
            <p style={{ fontSize: 13, color: 'var(--text-muted)', marginBottom: 16 }}>
              {batch.progress.total - batch.progress.done} stem{batch.progress.total - batch.progress.done !== 1 ? 's' : ''} unfinished. Release to return them to the pool, or re-book for another 6 hours (max 2 re-books).
            </p>
            <div style={{ display: 'flex', gap: 8, justifyContent: 'flex-end' }}>
              <button onClick={() => setLockDialog(false)} style={btnStyle('var(--surface)', 'var(--text-primary)')}>
                Dismiss
              </button>
              <button onClick={handleRelease} disabled={releasing} style={btnStyle('#dc2626', '#fff')}>
                Release Now
              </button>
              <button onClick={handleRebook} disabled={rebooking || batch.rebook_count >= 2} style={btnStyle('#f59e0b', '#000')}>
                {rebooking ? 'Re-booking…' : `Re-book (${batch.rebook_count}/2)`}
              </button>
            </div>
          </div>
        </div>
      )}
    </main>
  );
}

const th: React.CSSProperties = {
  padding: '10px',
  textAlign: 'left',
  fontWeight: 600,
  color: 'var(--text-muted)',
  borderBottom: '1px solid var(--border)',
  fontSize: 12,
};

const td: React.CSSProperties = {
  padding: '10px',
  color: 'var(--text-primary)',
  verticalAlign: 'middle',
};

function btnStyle(bg: string, color: string): React.CSSProperties {
  return {
    padding: '5px 12px',
    background: bg,
    color,
    border: 'none',
    borderRadius: 6,
    cursor: 'pointer',
    fontWeight: 500,
    fontSize: 12,
  };
}
