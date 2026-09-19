'use client';

import { useEffect, useState } from 'react';
import { useRouter } from 'next/navigation';
import { listGroupTasks, getGroupTasksDashboard } from '@/lib/api';
import { GroupTaskOut, GroupTaskStatus } from '@/lib/types';
import { useAuth } from '@/lib/AuthContext';
import { OUTCOME_META } from '@/components/AgreementDashboard';

const STATUS_META: Record<GroupTaskStatus, { label: string; bg: string; color: string }> = {
  event_pending: { label: 'Awaiting Events', bg: 'var(--surface-alt)', color: 'var(--text-muted)' },
  timelines_pending: { label: 'Timelines In Progress', bg: 'var(--warning-bg)', color: 'var(--warning-text)' },
  computed: { label: 'Computed', bg: 'var(--info-bg)', color: 'var(--info)' },
};

// The dashboard endpoint buckets by outcome once one exists, else by workflow
// status — so this card grid keys off either vocabulary.
const CARD_META: Record<string, { label: string; bg: string; color: string }> = {
  ...STATUS_META,
  ...OUTCOME_META,
};

export default function GroupTasksPage() {
  const router = useRouter();
  const { user, loading: authLoading, logout } = useAuth();
  const [tasks, setTasks] = useState<GroupTaskOut[]>([]);
  const [dashboard, setDashboard] = useState<{ by_status: Record<string, number>; completed_with_scores: number; avg_krippendorff_alpha: number | null } | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');

  useEffect(() => {
    if (!authLoading && !user) router.replace('/login');
  }, [user, authLoading, router]);

  useEffect(() => {
    if (!user) return;
    let cancelled = false;
    (async () => {
      try {
        const [taskList, dash] = await Promise.all([listGroupTasks(), getGroupTasksDashboard()]);
        if (cancelled) return;
        setTasks(taskList);
        setDashboard(dash);
      } catch (e: unknown) {
        if (!cancelled) setError(e instanceof Error ? e.message : 'Failed to load group tasks.');
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => { cancelled = true; };
  }, [user]);

  const myRole = (task: GroupTaskOut) => task.members.find(m => m.user_id === user?.id);

  if (authLoading) {
    return <div style={{ minHeight: '100vh', background: 'var(--background-page)' }} />;
  }

  return (
    <main style={{ maxWidth: 960, margin: '0 auto', padding: '32px 20px', fontFamily: 'system-ui, sans-serif' }}>
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 24, gap: 24 }}>
        <div>
          <button
            onClick={() => router.push('/')}
            style={{ background: 'none', border: 'none', cursor: 'pointer', color: 'var(--text-muted)', fontSize: 13, padding: 0, marginBottom: 6 }}
          >
            ← Dashboard
          </button>
          <h1 style={{ fontSize: 22, fontWeight: 700, margin: 0 }}>Group Annotation Tasks</h1>
          <p style={{ fontSize: 13, color: 'var(--text-muted)', margin: '4px 0 0' }}>
            Inter-annotator agreement (Cohen&apos;s κ / Krippendorff&apos;s α) workflow
          </p>
        </div>
        <div style={{ display: 'flex', gap: 8 }}>
          <button
            onClick={() => router.push('/group-tasks/distribute')}
            style={{ padding: '8px 16px', background: '#2563eb', color: '#fff', border: 'none', borderRadius: 6, cursor: 'pointer', fontWeight: 600, fontSize: 13 }}
          >
            Distribute Stems
          </button>
          <button
            onClick={() => logout()}
            style={{ padding: '8px 16px', background: 'var(--surface)', color: 'var(--text-primary)', border: '1px solid var(--border-input)', borderRadius: 6, cursor: 'pointer', fontWeight: 500, fontSize: 13 }}
          >
            Logout
          </button>
        </div>
      </div>

      {error && (
        <div style={{ background: 'var(--error-bg)', border: '1px solid var(--error-border)', borderRadius: 6, padding: '8px 12px', marginBottom: 16, fontSize: 13, color: 'var(--error)' }}>
          {error}
        </div>
      )}

      {dashboard && (
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(180px, 1fr))', gap: 16, marginBottom: 28 }}>
          {Object.entries(dashboard.by_status).map(([status, n]) => {
            const meta = CARD_META[status] ?? { label: status, bg: 'var(--surface-alt)', color: 'var(--text-muted)' };
            return (
              <div key={status} style={{ background: 'var(--surface)', border: '1px solid var(--border)', borderRadius: 10, padding: 16 }}>
                <div style={{ fontSize: 11, textTransform: 'uppercase', letterSpacing: '0.05em', marginBottom: 6, color: meta.color }}>{meta.label}</div>
                <div style={{ fontSize: 24, fontWeight: 700 }}>{n}</div>
              </div>
            );
          })}
          <div style={{ background: 'var(--surface)', border: '1px solid var(--border)', borderRadius: 10, padding: 16 }}>
            <div style={{ fontSize: 11, color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: '0.05em', marginBottom: 6 }}>Avg. Krippendorff&apos;s α</div>
            <div style={{ fontSize: 24, fontWeight: 700, fontFamily: 'monospace' }}>
              {dashboard.avg_krippendorff_alpha === null ? '—' : dashboard.avg_krippendorff_alpha.toFixed(3)}
            </div>
          </div>
        </div>
      )}

      {loading ? (
        <p style={{ color: 'var(--text-muted)' }}>Loading…</p>
      ) : tasks.length === 0 ? (
        <div style={{ background: 'var(--surface)', border: '1px solid var(--border)', borderRadius: 10, padding: 40, textAlign: 'center' }}>
          <p style={{ color: 'var(--text-muted)', marginBottom: 16 }}>No group annotation tasks yet.</p>
          <button
            onClick={() => router.push('/group-tasks/distribute')}
            style={{ padding: '9px 20px', background: '#2563eb', color: '#fff', border: 'none', borderRadius: 6, cursor: 'pointer', fontWeight: 600, fontSize: 14 }}
          >
            Distribute Stems
          </button>
        </div>
      ) : (
        <div style={{ background: 'var(--surface)', border: '1px solid var(--border)', borderRadius: 10, overflow: 'hidden' }}>
          <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 13 }}>
            <thead>
              <tr style={{ background: 'var(--surface-alt)' }}>
                <th style={th}>ID</th>
                <th style={th}>Stem</th>
                <th style={th}>Status</th>
                <th style={th}>Your Role</th>
                <th style={th}>Created</th>
              </tr>
            </thead>
            <tbody>
              {tasks.map(task => {
                const meta = STATUS_META[task.status] ?? STATUS_META.event_pending;
                const outcomeMeta = task.outcome ? OUTCOME_META[task.outcome] : null;
                const role = myRole(task);
                return (
                  <tr
                    key={task.id}
                    onClick={() => router.push(`/group-tasks/${task.id}`)}
                    style={{ borderBottom: '1px solid var(--border)', cursor: 'pointer' }}
                  >
                    <td style={td}>{task.id}</td>
                    <td style={{ ...td, maxWidth: 400, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                      {task.stem_text.slice(0, 100)}{task.stem_text.length > 100 ? '…' : ''}
                    </td>
                    <td style={td}>
                      <span style={{ padding: '2px 10px', borderRadius: 20, fontSize: 11, fontWeight: 600, background: meta.bg, color: meta.color }}>
                        {meta.label}
                      </span>
                      {outcomeMeta && (
                        <span style={{ marginLeft: 6, padding: '2px 10px', borderRadius: 20, fontSize: 11, fontWeight: 600, background: outcomeMeta.bg, color: outcomeMeta.color }}>
                          {outcomeMeta.label}
                        </span>
                      )}
                      {task.scores_stale && (
                        <span style={{ marginLeft: 6, fontSize: 11, color: 'var(--warning-text)' }} title="Someone edited after this was computed">
                          stale
                        </span>
                      )}
                    </td>
                    <td style={td}>
                      {role ? `${role.role === 'event_annotator' ? 'Event Annotator' : `Timeline Annotator #${role.annotator_index}`} (${role.status.replace('_', ' ')})` : task.created_by === user?.id ? 'Creator' : '—'}
                    </td>
                    <td style={td}>{new Date(task.created_at).toLocaleDateString()}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
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
