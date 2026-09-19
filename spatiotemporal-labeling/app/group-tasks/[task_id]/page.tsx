'use client';

import { useCallback, useEffect, useState } from 'react';
import { useParams, useRouter } from 'next/navigation';
import { getGroupTask, decideGroupTask, listUsers, reassignGroupMember } from '@/lib/api';
import { GroupTaskDetailOut, GroupTaskStatus, GroupTaskDecision as Decision, UserBrief } from '@/lib/types';
import { useAuth } from '@/lib/AuthContext';
import AgreementDashboard, { OUTCOME_META } from '@/components/AgreementDashboard';

const STATUS_META: Record<GroupTaskStatus, { label: string; bg: string; color: string }> = {
  event_pending: { label: 'Awaiting Events', bg: 'var(--surface-alt)', color: 'var(--text-muted)' },
  timelines_pending: { label: 'Timelines In Progress', bg: 'var(--warning-bg)', color: 'var(--warning-text)' },
  computed: { label: 'Computed', bg: 'var(--info-bg)', color: 'var(--info)' },
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
  const [allUsers, setAllUsers] = useState<UserBrief[]>([]);
  const [reassigningMemberId, setReassigningMemberId] = useState<number | null>(null);
  const [reassignTarget, setReassignTarget] = useState<number | ''>('');
  const [reassigning, setReassigning] = useState(false);

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
    listUsers().then(setAllUsers).catch(() => {});
  }, [load, user]);

  const handleReassign = async (memberId: number) => {
    if (!reassignTarget) return;
    if (!confirm('Reassign this role? The new person starts with a clean slate; any work already done under this slot stays attached to the record.')) return;
    setReassigning(true);
    try {
      const updated = await reassignGroupMember(taskId, memberId, Number(reassignTarget));
      setTask(updated);
      setReassigningMemberId(null);
      setReassignTarget('');
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : 'Failed to reassign.');
    } finally {
      setReassigning(false);
    }
  };

  const handleDecision = async (decision: Decision | null) => {
    const label = decision ? OUTCOME_META[decision].label : 'reopen (clear decision)';
    if (!confirm(`Set this task's decision to "${label}"?`)) return;
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
  // D1: editing is always open, gated only by a finalized decision. D6: any
  // non-participant (not just the person who ran the distribution) can decide.
  const canAnnotate = !!myMember && task.decision === null;
  const canSeeScoresAndDecide = !task.scores_hidden;
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
            {myMember?.role === 'event_annotator'
              ? (myMember.status === 'pending' ? 'Mark Events →' : 'Continue / Revise Events →')
              : (myMember?.status === 'submitted' ? 'Review / Revise Timeline →' : 'Position Timeline →')}
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
          {task.decision && (
            <span style={{ padding: '4px 12px', borderRadius: 20, fontSize: 12, fontWeight: 600, background: 'var(--surface-alt)', color: 'var(--text-primary)', border: '1px solid var(--border-input)' }}>
              Decision locked — editing frozen
            </span>
          )}
          {myMember && (
            <span style={{ fontSize: 12, color: 'var(--text-disabled)' }}>
              Scores are hidden from you while you&apos;re a participant on this task.
            </span>
          )}
        </div>
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(200px, 1fr))', gap: 12 }}>
          {task.members.map(m => {
            const otherRoleUserIds = new Set(task.members.filter(o => o.id !== m.id).map(o => o.user_id));
            const eligible = allUsers.filter(u => u.id !== m.user_id && !otherRoleUserIds.has(u.id));
            const isReassigning = reassigningMemberId === m.id;
            return (
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
                  background: m.status === 'submitted' ? 'var(--success-bg)' : m.status === 'in_progress' ? 'var(--warning-bg)' : 'var(--surface-alt)',
                  color: m.status === 'submitted' ? 'var(--success)' : m.status === 'in_progress' ? 'var(--warning-text)' : 'var(--text-muted)',
                }}>
                  {m.status.replace('_', ' ')}
                </span>
                {m.reassigned_from && (
                  <div style={{ fontSize: 10, color: 'var(--text-disabled)', marginTop: 4 }}>reassigned</div>
                )}

                {m.status !== 'submitted' && !task.decision && (
                  isReassigning ? (
                    <div style={{ marginTop: 8, display: 'flex', flexDirection: 'column', gap: 6 }}>
                      <select
                        value={reassignTarget}
                        onChange={e => setReassignTarget(e.target.value ? Number(e.target.value) : '')}
                        style={{ fontSize: 12, padding: '4px 6px', borderRadius: 4, border: '1px solid var(--border-input)' }}
                      >
                        <option value="">Reassign to…</option>
                        {eligible.map(u => (
                          <option key={u.id} value={u.id}>{u.username}</option>
                        ))}
                      </select>
                      <div style={{ display: 'flex', gap: 6 }}>
                        <button
                          onClick={() => handleReassign(m.id)}
                          disabled={!reassignTarget || reassigning}
                          style={{ fontSize: 11, padding: '3px 10px', background: '#2563eb', color: '#fff', border: 'none', borderRadius: 4, cursor: (!reassignTarget || reassigning) ? 'not-allowed' : 'pointer' }}
                        >
                          {reassigning ? 'Saving…' : 'Confirm'}
                        </button>
                        <button
                          onClick={() => { setReassigningMemberId(null); setReassignTarget(''); }}
                          style={{ fontSize: 11, padding: '3px 10px', background: 'var(--surface-alt)', color: 'var(--text-primary)', border: '1px solid var(--border-input)', borderRadius: 4, cursor: 'pointer' }}
                        >
                          Cancel
                        </button>
                      </div>
                    </div>
                  ) : (
                    <button
                      onClick={() => { setReassigningMemberId(m.id); setReassignTarget(''); }}
                      style={{ marginTop: 8, fontSize: 11, padding: '3px 10px', background: 'none', color: 'var(--text-muted)', border: '1px solid var(--border-input)', borderRadius: 4, cursor: 'pointer' }}
                    >
                      Reassign
                    </button>
                  )
                )}
              </div>
            );
          })}
        </div>
      </div>

      {canSeeScoresAndDecide && hasScores && (
        <div style={{ marginBottom: 20 }}>
          <AgreementDashboard
            outcome={task.outcome}
            decision={task.decision}
            scoresStale={task.scores_stale}
            krippendorffAlpha={task.krippendorff_alpha}
            cohensKappaAvg={task.cohens_kappa_avg}
            fleissKappa={task.fleiss_kappa}
            acceptanceThreshold={task.acceptance_threshold}
            agreementDetails={task.agreement_details}
            members={task.members}
          />
        </div>
      )}

      {canSeeScoresAndDecide && (
        <div style={{ background: 'var(--surface)', border: '1px solid var(--border)', borderRadius: 10, padding: 20 }}>
          <div style={{ fontSize: 12, fontWeight: 600, color: 'var(--text-muted)', marginBottom: 10 }}>
            MANUAL DECISION — any non-participant may set or clear this
          </div>
          <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
            {(['accepted', 'accepted_flagged', 'adjudication', 'rejected'] as const).map(d => (
              <button
                key={d}
                onClick={() => handleDecision(d)}
                disabled={deciding || task.decision === d}
                style={{
                  padding: '8px 14px',
                  background: task.decision === d ? 'var(--text-disabled)' : 'var(--surface-alt)',
                  color: 'var(--text-primary)',
                  border: '1px solid var(--border-input)',
                  borderRadius: 6,
                  cursor: (deciding || task.decision === d) ? 'not-allowed' : 'pointer',
                  fontWeight: 500,
                  fontSize: 12,
                }}
              >
                {OUTCOME_META[d].label}
              </button>
            ))}
            {task.decision && (
              <button
                onClick={() => handleDecision(null)}
                disabled={deciding}
                style={{
                  padding: '8px 14px', background: 'var(--error-bg)', color: 'var(--error)',
                  border: '1px solid var(--error-border)', borderRadius: 6,
                  cursor: deciding ? 'not-allowed' : 'pointer', fontWeight: 500, fontSize: 12,
                }}
              >
                Reopen (clear decision)
              </button>
            )}
          </div>
        </div>
      )}
    </main>
  );
}
