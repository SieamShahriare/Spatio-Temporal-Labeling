'use client';

import { useEffect, useState } from 'react';
import { useRouter } from 'next/navigation';
import { listBatches, getBatch, releaseBatch, rebookBatch, exportBatchCsv, exportBatchJson, exportBatchStemJson, listMyTasks } from '@/lib/api';
import { BatchOut, BatchDetailOut, MyTaskOut } from '@/lib/types';
import { useAuth } from '@/lib/AuthContext';

function formatCountdown(seconds: number): string {
  if (seconds <= 0) return 'Expired';
  const h = Math.floor(seconds / 3600);
  const m = Math.floor((seconds % 3600) / 60);
  const s = seconds % 60;
  if (h > 0) return `${h}h ${m}m`;
  if (m > 0) return `${m}m ${s}s`;
  return `${s}s`;
}

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

  const isUrgent = remaining > 0 && remaining <= 15 * 60;
  const color = remaining <= 0 ? 'var(--error)' : isUrgent ? '#f59e0b' : 'var(--text-primary)';

  return <span style={{ color, fontFamily: 'monospace', fontWeight: 600 }}>{formatCountdown(remaining)}</span>;
}

export default function DashboardPage() {
  const router = useRouter();
  const { user, loading: authLoading, logout } = useAuth();
  const [batches, setBatches] = useState<BatchOut[]>([]);
  const [myTasks, setMyTasks] = useState<MyTaskOut[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [expanded, setExpanded] = useState<number | null>(null);
  const [detail, setDetail] = useState<BatchDetailOut | null>(null);
  const [detailLoading, setDetailLoading] = useState(false);
  const [rebooking, setRebooking] = useState(false);

  useEffect(() => {
    if (!authLoading && !user) {
      router.replace('/login');
    }
  }, [user, authLoading, router]);

  useEffect(() => {
    if (!user) return;
    let cancelled = false;
    (async () => {
      try {
        const [data, tasks] = await Promise.all([listBatches(), listMyTasks()]);
        if (!cancelled) {
          setBatches(data);
          setMyTasks(tasks);
        }
      } catch (e: unknown) {
        if (!cancelled) setError(e instanceof Error ? e.message : 'Failed to load batches.');
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => { cancelled = true; };
  }, [user]);

  const handleLogout = async () => {
    await logout();
  };

  const handleRelease = async (id: number) => {
    if (!confirm('Release this lock? Stems will return to the pool immediately.')) return;
    try {
      await releaseBatch(id);
      setBatches(prev => prev.map(b => b.id === id ? { ...b, status: 'released', expires_at: new Date().toISOString() } : b));
      if (expanded === id) setExpanded(null);
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : 'Failed to release.');
    }
  };

  const handleExpand = async (id: number) => {
    if (expanded === id) {
      setExpanded(null);
      return;
    }
    setDetailLoading(true);
    try {
      const d = await getBatch(id);
      setDetail(d);
      setExpanded(id);
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : 'Failed to load batch detail.');
    } finally {
      setDetailLoading(false);
    }
  };

  const handleRebook = async (id: number) => {
    setRebooking(true);
    try {
      const res = await rebookBatch(id);
      const now = Date.now();
      const newExpires = new Date(now + res.remaining_seconds * 1000).toISOString();
      setBatches(prev => prev.map(b => b.id === id ? { ...b, expires_at: newExpires, rebook_count: b.rebook_count + 1 } : b));
      if (detail && detail.id === id) {
        setDetail({ ...detail, expires_at: newExpires, rebook_count: detail.rebook_count + 1 });
      }
    } catch (e: unknown) {
      const msg = e instanceof Error ? e.message : 'Re-book failed.';
      setError(msg);
    } finally {
      setRebooking(false);
    }
  };

  const activeBatches = batches.filter(b => b.status === 'active');
  const pastBatches = batches.filter(b => b.status !== 'active');

  if (authLoading) {
    return <div style={{ minHeight: '100vh', background: 'var(--background-page)' }} />;
  }

  return (
    <main style={{ maxWidth: 960, margin: '0 auto', padding: '32px 20px', fontFamily: 'system-ui, sans-serif' }}>
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 32, gap: 24 }}>
        <div>
          <h1 style={{ fontSize: 22, fontWeight: 700, margin: 0 }}>
            Dashboard
          </h1>
          <p style={{ fontSize: 13, color: 'var(--text-muted)', margin: '4px 0 0' }}>
            Welcome, {user?.username}
          </p>
        </div>
        <div style={{ display: 'flex', gap: 8 }}>
          <button
            onClick={() => router.push('/stems')}
            style={{
              padding: '8px 16px',
              background: '#2563eb',
              color: '#fff',
              border: 'none',
              borderRadius: 6,
              cursor: 'pointer',
              fontWeight: 600,
              fontSize: 13,
            }}
          >
            + Build Batch
          </button>
          <button
            onClick={() => router.push('/group-tasks')}
            style={{
              padding: '8px 16px',
              background: 'var(--surface)',
              color: 'var(--text-primary)',
              border: '1px solid var(--border-input)',
              borderRadius: 6,
              cursor: 'pointer',
              fontWeight: 500,
              fontSize: 13,
            }}
          >
            Group Tasks
          </button>
          <button
            onClick={handleLogout}
            style={{
              padding: '8px 16px',
              background: 'var(--surface)',
              color: 'var(--text-primary)',
              border: '1px solid var(--border-input)',
              borderRadius: 6,
              cursor: 'pointer',
              fontWeight: 500,
              fontSize: 13,
            }}
          >
            Logout
          </button>
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

      {myTasks.length > 0 && (
        <div style={{ marginBottom: 32 }}>
          <h2 style={{ fontSize: 14, fontWeight: 700, margin: '0 0 12px' }}>
            My Assigned Tasks ({myTasks.filter(t => !t.blocked).length} ready{myTasks.some(t => t.blocked) ? `, ${myTasks.filter(t => t.blocked).length} waiting` : ''})
          </h2>
          <div style={{ background: 'var(--surface)', border: '1px solid var(--border)', borderRadius: 10, overflow: 'hidden' }}>
            {[...myTasks].sort((a, b) => Number(a.blocked) - Number(b.blocked)).map((t, idx) => (
              <div
                key={t.member_id}
                onClick={() => router.push(t.blocked ? `/group-tasks/${t.task_id}` : `/group-annotate/${t.task_id}`)}
                style={{
                  display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 12, padding: '12px 16px',
                  borderTop: idx > 0 ? '1px solid var(--border)' : 'none',
                  cursor: 'pointer', opacity: t.blocked ? 0.6 : 1,
                }}
              >
                <div style={{ minWidth: 0 }}>
                  <div style={{ fontSize: 13, fontWeight: 600 }}>
                    {t.role === 'event_annotator' ? 'Event Annotator' : `Timeline Annotator #${t.annotator_index}`}
                    {' · '}
                    <span style={{ fontWeight: 400, color: 'var(--text-muted)' }}>Task #{t.task_id}</span>
                  </div>
                  <div style={{ fontSize: 12, color: 'var(--text-disabled)', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', maxWidth: 480 }}>
                    {t.blocked ? t.blocked_reason : t.stem_text}
                  </div>
                </div>
                <span style={{
                  padding: '2px 10px', borderRadius: 20, fontSize: 11, fontWeight: 600, whiteSpace: 'nowrap',
                  background: t.blocked ? 'var(--surface-alt)' : t.member_status === 'submitted' ? 'var(--success-bg)' : 'var(--warning-bg)',
                  color: t.blocked ? 'var(--text-muted)' : t.member_status === 'submitted' ? 'var(--success)' : 'var(--warning-text)',
                }}>
                  {t.blocked ? 'waiting' : t.member_status.replace('_', ' ')}
                </span>
              </div>
            ))}
          </div>
        </div>
      )}

      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(220px, 1fr))', gap: 16, marginBottom: 32 }}>
        <div style={{ background: 'var(--surface)', border: '1px solid var(--border)', borderRadius: 10, padding: 20 }}>
          <div style={{ fontSize: 12, color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: '0.05em', marginBottom: 8 }}>My Batches</div>
          <div style={{ fontSize: 28, fontWeight: 700 }}>{batches.length}</div>
        </div>
        <div style={{ background: 'var(--surface)', border: '1px solid var(--border)', borderRadius: 10, padding: 20 }}>
          <div style={{ fontSize: 12, color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: '0.05em', marginBottom: 8 }}>Active Locks</div>
          <div style={{ fontSize: 28, fontWeight: 700, color: '#f59e0b' }}>{activeBatches.length}</div>
        </div>
        <div style={{ background: 'var(--surface)', border: '1px solid var(--border)', borderRadius: 10, padding: 20 }}>
          <div style={{ fontSize: 12, color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: '0.05em', marginBottom: 8 }}>Past / Released</div>
          <div style={{ fontSize: 28, fontWeight: 700 }}>{pastBatches.length}</div>
        </div>
      </div>

      {loading ? (
        <p style={{ color: 'var(--text-muted)' }}>Loading…</p>
      ) : activeBatches.length === 0 && pastBatches.length === 0 ? (
        <div style={{
          background: 'var(--surface)',
          border: '1px solid var(--border)',
          borderRadius: 10,
          padding: 40,
          textAlign: 'center',
        }}>
          <p style={{ color: 'var(--text-muted)', marginBottom: 16 }}>You don&apos;t have any batches yet.</p>
          <button
            onClick={() => router.push('/stems')}
            style={{
              padding: '9px 20px',
              background: '#2563eb',
              color: '#fff',
              border: 'none',
              borderRadius: 6,
              cursor: 'pointer',
              fontWeight: 600,
              fontSize: 14,
            }}
          >
            Browse Stems & Build Batch
          </button>
        </div>
      ) : (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
          {activeBatches.length > 0 && (
            <section>
              <h2 style={{ fontSize: 16, fontWeight: 600, marginBottom: 12 }}>Active Batches</h2>
              <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
                {activeBatches.map(b => {
                  const isExpanded = expanded === b.id;
                  const detailData = isExpanded ? detail : null;
                  return (
                    <div
                      key={b.id}
                      style={{
                        background: 'var(--surface)',
                        border: '1px solid var(--border)',
                        borderRadius: 10,
                        overflow: 'hidden',
                      }}
                    >
                      <div
                        style={{
                          padding: 16,
                          display: 'flex',
                          alignItems: 'center',
                          justifyContent: 'space-between',
                          cursor: 'pointer',
                        }}
                        onClick={() => handleExpand(b.id)}
                      >
                        <div style={{ flex: 1, minWidth: 0 }}>
                          <div style={{ fontWeight: 600, fontSize: 14, marginBottom: 4 }}>
                            {b.name}
                            <span style={{
                              marginLeft: 8,
                              padding: '2px 8px',
                              borderRadius: 20,
                              fontSize: 11,
                              fontWeight: 600,
                              background: 'var(--warning-bg)',
                              color: 'var(--warning-text)',
                            }}>
                              {b.status}
                            </span>
                          </div>
                          <div style={{ fontSize: 12, color: 'var(--text-muted)', display: 'flex', gap: 12, flexWrap: 'wrap' }}>
                            <span>Lock: <Countdown expiresAt={b.expires_at} /></span>
                            <span>Progress: {b.progress.done}/{b.progress.total}</span>
                            <span>Re-books: {b.rebook_count}/2</span>
                          </div>
                        </div>
                        <div style={{ display: 'flex', gap: 6, marginLeft: 12 }}>
                          <button
                            onClick={(e) => { e.stopPropagation(); handleExpand(b.id); }}
                            style={btnStyle('#2563eb', '#fff')}
                          >
                            Open
                          </button>
                          <button
                            onClick={(e) => { e.stopPropagation(); handleExpand(b.id); }}
                            style={btnStyle('var(--surface)', 'var(--text-primary)')}
                          >
                            {isExpanded ? '▲' : '▼'}
                          </button>
                        </div>
                      </div>
                      {isExpanded && (
                        <div style={{
                          borderTop: '1px solid var(--border)',
                          padding: 16,
                          background: 'var(--surface-alt)',
                        }}>
                          {detailLoading ? (
                            <p style={{ color: 'var(--text-muted)', fontSize: 13 }}>Loading…</p>
                          ) : detailData ? (
                            <div>
                              <div style={{ display: 'flex', gap: 8, marginBottom: 12, flexWrap: 'wrap' }}>
                                <button
                                  onClick={() => {
                                    const first = detailData.stems?.[0];
                                    if (first) {
                                      router.push(`/batches/${detailData.id}`);
                                    }
                                  }}
                                  style={btnStyle('#2563eb', '#fff')}
                                >
                                  Open Annotator
                                </button>
                                <button
                                  onClick={() => handleRebook(detailData.id)}
                                  disabled={rebooking || detailData.rebook_count >= 2}
                                  style={{
                                    ...btnStyle('var(--surface)', 'var(--text-primary)'),
                                    opacity: (rebooking || detailData.rebook_count >= 2) ? 0.5 : 1,
                                  }}
                                >
                                  {rebooking ? 'Re-booking…' : `Re-book (${detailData.rebook_count}/2)`}
                                </button>
                                <button
                                  onClick={() => handleRelease(detailData.id)}
                                  style={btnStyle('#dc2626', '#fff')}
                                >
                                  Release Lock
                                </button>
                                <a
                                  href={exportBatchCsv(detailData.id)}
                                  download
                                  style={{ ...btnStyle('var(--surface)', 'var(--text-primary)'), textDecoration: 'none' }}
                                >
                                  CSV
                                </a>
                                <a
                                  href={exportBatchJson(detailData.id)}
                                  download
                                  style={{ ...btnStyle('var(--surface)', 'var(--text-primary)'), textDecoration: 'none' }}
                                >
                                  JSON
                                </a>
                              </div>
                              <div style={{ fontSize: 12, color: 'var(--text-muted)', marginBottom: 8, fontWeight: 600 }}>STEMS</div>
                              <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
                                {detailData.stems.map(bs => (
                                  <div
                                    key={bs.id}
                                    style={{
                                      display: 'flex',
                                      alignItems: 'center',
                                      justifyContent: 'space-between',
                                      padding: '8px 10px',
                                      background: 'var(--surface)',
                                      border: '1px solid var(--border)',
                                      borderRadius: 6,
                                      fontSize: 13,
                                    }}
                                  >
                                    <span style={{ flex: 1, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', marginRight: 8 }}>
                                      {bs.stem_text.slice(0, 80)}{bs.stem_text.length > 80 ? '…' : ''}
                                    </span>
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
                                    <button
                                      onClick={() => router.push(`/annotate/${detailData.id}/${bs.id}`)}
                                      style={{ ...btnStyle('#2563eb', '#fff'), marginLeft: 8, fontSize: 11, padding: '2px 10px' }}
                                    >
                                      {bs.status === 'done' ? 'Review' : bs.status === 'in_progress' ? 'Continue' : 'Start'}
                                    </button>
                                    <a
                                      href={exportBatchStemJson(bs.id)}
                                      download
                                      title="Download stem JSON"
                                      style={{ ...btnStyle('var(--surface-alt)', 'var(--text-primary)'), textDecoration: 'none', marginLeft: 6, fontSize: 11, padding: '2px 8px', display: 'inline-flex', alignItems: 'center', justifyContent: 'center', lineHeight: 1 }}
                                    >
                                      ⬇
                                    </a>
                                  </div>
                                ))}
                              </div>
                            </div>
                          ) : null}
                        </div>
                      )}
                    </div>
                  );
                })}
              </div>
            </section>
          )}

          {pastBatches.length > 0 && (
            <section>
              <h2 style={{ fontSize: 16, fontWeight: 600, marginBottom: 12 }}>Past / Released</h2>
              <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
                {pastBatches.map(b => (
                  <div
                    key={b.id}
                    style={{
                      background: 'var(--surface)',
                      border: '1px solid var(--border)',
                      borderRadius: 10,
                      padding: 16,
                      display: 'flex',
                      alignItems: 'center',
                      justifyContent: 'space-between',
                      opacity: 0.7,
                    }}
                  >
                    <div>
                      <div style={{ fontWeight: 600, fontSize: 14 }}>{b.name}</div>
                      <div style={{ fontSize: 12, color: 'var(--text-muted)', marginTop: 2 }}>
                        {b.progress.done}/{b.progress.total} done · {b.status}
                      </div>
                    </div>
        <div style={{ display: 'flex', gap: 8, marginLeft: 'auto' }}>
                      <a
                        href={exportBatchCsv(b.id)}
                        download
                        style={{ ...btnStyle('var(--surface)', 'var(--text-primary)'), textDecoration: 'none', fontSize: 12 }}
                      >
                        CSV
                      </a>
                      <a
                        href={exportBatchJson(b.id)}
                        download
                        style={{ ...btnStyle('var(--surface)', 'var(--text-primary)'), textDecoration: 'none', fontSize: 12 }}
                      >
                        JSON
                      </a>
                    </div>
                  </div>
                ))}
              </div>
            </section>
          )}
        </div>
      )}
    </main>
  );
}

function btnStyle(bg: string, color: string): React.CSSProperties {
  return {
    padding: '6px 14px',
    background: bg,
    color,
    border: 'none',
    borderRadius: 6,
    cursor: 'pointer',
    fontWeight: 500,
    fontSize: 13,
  };
}
