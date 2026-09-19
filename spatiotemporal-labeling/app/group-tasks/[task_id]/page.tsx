'use client';

import { useCallback, useEffect, useState } from 'react';
import { useParams, useRouter } from 'next/navigation';
import { getGroupTask, decideGroupTask } from '@/lib/api';
import { GroupTaskDetailOut, GroupTaskStatus } from '@/lib/types';
import { useAuth } from '@/lib/AuthContext';
import AgreementDashboard from '@/components/AgreementDashboard';

const STATUS_META: Record<GroupTaskStatus, { label: string; bg: string; color: string }> = {
  event_pending: { label: 'Awaiting Events', bg: 'var(--surface-alt)', color: 'var(--text-muted)' },
  timelines_pending: { label: 'Timelines In Progress', bg: 'var(--warning-bg)', color: 'var(--warning-text)' },
  computing: { label: 'Computing', bg: 'var(--warning-bg)', color: 'var(--warning-text)' },
  accepted: { label: 'Accepted', bg: 'var(--success-bg)', color: 'var(--success)' },
  accepted_flagged: { label: 'Accepted (Flagged)', bg: 'var(--warning-bg)', color: 'var(--warning-text)' },
  adjudication: { label: 'Needs Adjudication', bg: 'var(--error-bg)', color: 'var(--error)' },
  rejected: { label: 'Rejected', bg: 'var(--error-bg)', color: 'var(--error)' },
};

const ROLE_LABEL = (role: string, idx: number | null) =>
  role === 'event_annotator' ? 'Event Annotator' : `Timeline Annotator #${idx}`;

export default function GroupTaskDetailPage() {
  const params = useParams<{ task_id: string }>();
  const taskId = parseInt(params.task_id);
  const router = useRouter();
  const { user, loading: authLoading } = useAuth();
  const [task, setTask] = useState<GroupTaskDetailOut | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [deciding, setDeciding] = useState(false);

  useEffect(() => {
    if (!authLoading && !user) router.replace('/login');
  }, [user, authLoading, router]);

  const load = useCallback(async () => {
    setLoading(true);
    setError('');
    try {
      const data = await getGroupTask(taskId);
      setTask(data);
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : 'Failed to load group task.');
    } finally {
      setLoading(false);
    }
  }, [taskId]);

  useEffect(() => {
    if (!user) return;
    // eslint-disable-next-line react-hooks/set-state-in-effect
    load();
  }, [load, user]);

  const handleDecision = async (decision: string) => {
    if (!confirm(`Set this task's status to "${decision}"?`)) return;
    setDeciding(true);
    try {
      const updated = await decideGroupTask(taskId, decision);
      setTask(updated);
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : 'Failed to update decision.');
    } finally {
      setDeciding(false);
    }
  };

  if (authLoading || loading) {
    return <div style={{ minHeight: '100vh', background: 'var(--background-page)' }} />;
  }

  if (!task) {
    return (
      <main style={{ maxWidth: 900, margin: '0 auto', padding: 40, fontFamily: 'system-ui', color: 'var(--error)' }}>
        {error || 'Group task not found.'}
      </main>
    );
  }

  const myMember = task.members.find(m => m.user_id === user?.id);
  const isCreator = task.created_by === user?.id;
  const canAnnotate = myMember && myMember.status !== 'done' && (
    (myMember.role === 'event_annotator' && task.status === 'event_pending') ||
    (myMember.role === 'timeline_annotator' && task.status === 'timelines_pending')
  );
  const meta = STATUS_META[task.status] ?? STATUS_META.event_pending;
  const hasScores = task.krippendorff_alpha !== null;

  return (
    <main style={{ maxWidth: 900, margin: '0 auto', padding: '32px 20px', fontFamily: 'system-ui, sans-serif' }}>
      <button
        onClick={() => router.push('/group-tasks')}
        style={{ background: 'none', border: 'none', cursor: 'pointer', color: 'var(--text-muted)', fontSize: 13, padding: 0, marginBottom: 6 }}
      >
        ← Group Tasks
      </button>
      <div style={{ display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between', marginBottom: 20, gap: 16, flexWrap: 'wrap' }}>
        <div>
          <h1 style={{ fontSize: 18, fontWeight: 700, margin: 0 }}>Group Task #{task.id}</h1>
          <p style={{ fontSize: 13, color: 'var(--text-muted)', margin: '4px 0 0', maxWidth: 560 }}>
            {task.stem_text}
          </p>
        </div>
        {canAnnotate && (
          <button
            onClick={() => router.push(`/group-annotate/${task.id}`)}
            style={{ padding: '10px 18px', background: '#2563eb', color: '#fff', border: 'none', borderRadius: 6, cursor: 'pointer', fontWeight: 600, fontSize: 13, whiteSpace: 'nowrap' }}
          >
            {myMember?.role === 'event_annotator' ? 'Mark Events →' : 'Position Timeline →'}
          </button>
        )}
      </div>

      {error && (
        <div style={{ background: 'var(--error-bg)', border: '1px solid var(--error-border)', borderRadius: 6, padding: '8px 12px', marginBottom: 16, fontSize: 13, color: 'var(--error)' }}>
          {error}
        </div>
      )}

      <div style={{ background: 'var(--surface)', border: '1px solid var(--border)', borderRadius: 10, padding: 20, marginBottom: 20 }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 16 }}>
          <span style={{ padding: '4px 12px', borderRadius: 20, fontSize: 12, fontWeight: 600, background: meta.bg, color: meta.color }}>
            {meta.label}
          </span>
        </div>
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(200px, 1fr))', gap: 12 }}>
          {task.members.map(m => (
            <div key={m.id} style={{ border: '1px solid var(--border)', borderRadius: 8, padding: 12 }}>
              <div style={{ fontSize: 11, color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: '0.03em', marginBottom: 4 }}>
                {ROLE_LABEL(m.role, m.annotator_index)}
              </div>
              <div style={{ fontWeight: 600, fontSize: 14, marginBottom: 4 }}>{m.username}</div>
              <span style={{
                padding: '2px 8px',
                borderRadius: 20,
                fontSize: 11,
                fontWeight: 600,
                background: m.status === 'done' ? 'var(--success-bg)' : m.status === 'in_progress' ? 'var(--warning-bg)' : 'var(--surface-alt)',
                color: m.status === 'done' ? 'var(--success)' : m.status === 'in_progress' ? 'var(--warning-text)' : 'var(--text-muted)',
              }}>
                {m.status.replace('_', ' ')}
              </span>
            </div>
          ))}
        </div>
      </div>

      {hasScores && (
        <div style={{ marginBottom: 20 }}>
          <AgreementDashboard
            status={task.status}
            krippendorffAlpha={task.krippendorff_alpha}
            cohensKappaAvg={task.cohens_kappa_avg}
            fleissKappa={task.fleiss_kappa}
            acceptanceThreshold={task.acceptance_threshold}
            agreementDetails={task.agreement_details}
            members={task.members}
          />
        </div>
      )}

      {isCreator && hasScores && (
        <div style={{ background: 'var(--surface)', border: '1px solid var(--border)', borderRadius: 10, padding: 20 }}>
          <div style={{ fontSize: 12, fontWeight: 600, color: 'var(--text-muted)', marginBottom: 10 }}>
            CREATOR OVERRIDE
          </div>
          <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
            {(['accepted', 'accepted_flagged', 'adjudication', 'rejected'] as const).map(d => (
              <button
                key={d}
                onClick={() => handleDecision(d)}
                disabled={deciding || task.status === d}
                style={{
                  padding: '8px 14px',
                  background: task.status === d ? 'var(--text-disabled)' : 'var(--surface-alt)',
                  color: 'var(--text-primary)',
                  border: '1px solid var(--border-input)',
                  borderRadius: 6,
                  cursor: (deciding || task.status === d) ? 'not-allowed' : 'pointer',
                  fontWeight: 500,
                  fontSize: 12,
                }}
              >
                {STATUS_META[d].label}
              </button>
            ))}
          </div>
        </div>
      )}
    </main>
  );
}
