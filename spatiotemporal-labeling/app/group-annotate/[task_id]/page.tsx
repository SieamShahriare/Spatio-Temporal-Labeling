'use client';

import { useEffect, useState, useCallback } from 'react';
import { useParams, useRouter } from 'next/navigation';
import TextLabeler from '@/components/TextLabeler';
import Timeline from '@/components/Timeline';
import LabeledText from '@/components/LabeledText';
import {
  getGroupTask,
  listGroupEvents,
  createGroupEvent,
  deleteGroupEvent,
  submitGroupEvents,
  getMyTimeline,
  upsertMyTimeline,
  submitGroupTimeline,
} from '@/lib/api';
import { GroupTaskDetailOut, GroupEventSpanOut, Span, ALLEN_RELATIONS } from '@/lib/types';
import { buildMatrix } from '@/lib/allen';
import { useAuth } from '@/lib/AuthContext';

function eventToSpanShape(e: GroupEventSpanOut, tlStart = 10, tlEnd = 30): Span {
  return {
    id: e.id,
    session_id: 0,
    label_type: 'Event',
    seq_label: e.seq_label,
    span_text: e.span_text,
    char_start: e.char_start,
    char_end: e.char_end,
    tl_start: tlStart,
    tl_end: tlEnd,
    source: 'manual',
    created_at: e.created_at,
  };
}

function MiniMatrix({ spans }: { spans: Span[] }) {
  if (spans.length < 2) return null;
  const matrix = buildMatrix(spans);
  return (
    <div style={{ overflowX: 'auto' }}>
      <table style={{ borderCollapse: 'collapse', fontSize: 12 }}>
        <thead>
          <tr>
            <th style={miniTh} />
            {spans.map(s => <th key={s.id} style={miniTh}>{s.seq_label}</th>)}
          </tr>
        </thead>
        <tbody>
          {spans.map((row, i) => (
            <tr key={row.id}>
              <th style={miniTh}>{row.seq_label}</th>
              {spans.map((col, j) => {
                const code = matrix[i][j];
                const info = ALLEN_RELATIONS[code];
                return (
                  <td key={col.id} style={{ ...miniTd, background: i === j ? 'var(--surface-alt)' : code > 0 ? 'var(--info-bg)' : code < 0 ? 'var(--negative-bg)' : 'var(--surface-alt)' }}>
                    {i === j ? '—' : info?.symbol ?? code}
                  </td>
                );
              })}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export default function GroupAnnotatePage() {
  const params = useParams<{ task_id: string }>();
  const taskId = parseInt(params.task_id);
  const router = useRouter();
  const { user, loading: authLoading } = useAuth();

  const [task, setTask] = useState<GroupTaskDetailOut | null>(null);
  const [events, setEvents] = useState<GroupEventSpanOut[]>([]);
  const [timelineSpans, setTimelineSpans] = useState<Span[]>([]);
  const [memberStatus, setMemberStatus] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [submitting, setSubmitting] = useState(false);

  useEffect(() => {
    if (!authLoading && !user) router.replace('/login');
  }, [user, authLoading, router]);

  const load = useCallback(async () => {
    setLoading(true);
    setError('');
    try {
      const t: GroupTaskDetailOut = await getGroupTask(taskId);
      setTask(t);
      const myMember = t.members.find(m => m.user_id === user?.id);
      if (!myMember) {
        setLoading(false);
        return;
      }
      if (myMember.role === 'event_annotator') {
        const evs = await listGroupEvents(taskId);
        setEvents(evs);
      } else {
        const myTl = await getMyTimeline(taskId);
        setMemberStatus(myTl.member_status);
        setTimelineSpans(myTl.positions.map((p: { span_id: number; seq_label: string; span_text: string; tl_start: number; tl_end: number }) => ({
          id: p.span_id,
          session_id: 0,
          label_type: 'Event',
          seq_label: p.seq_label,
          span_text: p.span_text,
          char_start: 0,
          char_end: 0,
          tl_start: p.tl_start,
          tl_end: p.tl_end,
          source: 'manual',
          created_at: '',
        })));
      }
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : 'Failed to load annotation task.');
    } finally {
      setLoading(false);
    }
  }, [taskId, user]);

  useEffect(() => {
    if (!user) return;
    // eslint-disable-next-line react-hooks/set-state-in-effect
    load();
  }, [load, user]);

  const myMember = task?.members.find(m => m.user_id === user?.id);

  const handleAddSpan = async (_labelType: 'Event' | 'Time', spanText: string, charStart: number, charEnd: number) => {
    try {
      const created = await createGroupEvent(taskId, { span_text: spanText, char_start: charStart, char_end: charEnd });
      setEvents(prev => [...prev, created]);
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : 'Failed to add event.');
    }
  };

  const handleDeleteSpan = async (spanId: number) => {
    try {
      await deleteGroupEvent(taskId, spanId);
      setEvents(prev => prev.filter(e => e.id !== spanId));
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : 'Failed to remove event.');
    }
  };

  const handleSubmitEvents = async () => {
    if (events.length < 2) return;
    if (!confirm('Submit events? They will be locked and visible read-only to the 3 timeline annotators.')) return;
    setSubmitting(true);
    try {
      await submitGroupEvents(taskId);
      router.push(`/group-tasks/${taskId}`);
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : 'Failed to submit events.');
      setSubmitting(false);
    }
  };

  const handleUpdateTimelineSpan = async (spanId: number, tlStart: number, tlEnd: number) => {
    setTimelineSpans(prev => prev.map(s => s.id === spanId ? { ...s, tl_start: tlStart, tl_end: tlEnd } : s));
    try {
      await upsertMyTimeline(taskId, [{ span_id: spanId, tl_start: tlStart, tl_end: tlEnd }]);
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : 'Failed to save timeline position.');
    }
  };

  const handleSubmitTimeline = async () => {
    if (!confirm('Submit your timeline? Once submitted you cannot change it, and you will not be able to see the other annotators’ work.')) return;
    setSubmitting(true);
    try {
      await upsertMyTimeline(taskId, timelineSpans.map(s => ({ span_id: s.id, tl_start: s.tl_start, tl_end: s.tl_end })));
      await submitGroupTimeline(taskId);
      router.push(`/group-tasks/${taskId}`);
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : 'Failed to submit timeline.');
      setSubmitting(false);
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

  if (!myMember) {
    return (
      <main style={{ maxWidth: 700, margin: '0 auto', padding: 40, fontFamily: 'system-ui' }}>
        <p style={{ color: 'var(--text-muted)' }}>You are not a participant in this group task.</p>
        <button onClick={() => router.push(`/group-tasks/${taskId}`)} style={linkBtn}>View task details →</button>
      </main>
    );
  }

  return (
    <main style={{ maxWidth: 900, margin: '0 auto', padding: '32px 20px', fontFamily: 'system-ui, sans-serif' }}>
      <button onClick={() => router.push(`/group-tasks/${taskId}`)} style={linkBtn}>← Task #{taskId}</button>
      <h1 style={{ fontSize: 18, fontWeight: 700, margin: '8px 0 4px' }}>
        {myMember.role === 'event_annotator' ? 'Step 1: Mark Events' : 'Step 2 & 3: Position Timeline'}
      </h1>
      <p style={{ fontSize: 13, color: 'var(--text-muted)', margin: '0 0 20px' }}>
        {myMember.role === 'event_annotator'
          ? 'Highlight every event span in the text. This is shared, read-only, with all 3 timeline annotators once you submit.'
          : 'Position each event independently on the 0–100 timeline. You cannot see the other annotators’ work.'}
      </p>

      {error && (
        <div style={{ background: 'var(--error-bg)', border: '1px solid var(--error-border)', borderRadius: 6, padding: '8px 12px', marginBottom: 16, fontSize: 13, color: 'var(--error)' }}>
          {error}
        </div>
      )}

      {myMember.role === 'event_annotator' ? (
        task.status !== 'event_pending' || myMember.status === 'done' ? (
          <div style={waitingBox}>Events already submitted. Waiting for the 3 timeline annotators to finish.</div>
        ) : (
          <>
            <TextLabeler
              stemText={task.stem_text}
              spans={events.map(e => eventToSpanShape(e))}
              onAddSpan={handleAddSpan}
              onDeleteSpan={handleDeleteSpan}
            />
            <div style={{ marginTop: 20, display: 'flex', justifyContent: 'flex-end' }}>
              <button
                onClick={handleSubmitEvents}
                disabled={events.length < 2 || submitting}
                style={{
                  padding: '10px 20px',
                  background: events.length < 2 ? 'var(--text-disabled)' : '#16a34a',
                  color: '#fff',
                  border: 'none',
                  borderRadius: 6,
                  cursor: events.length < 2 || submitting ? 'not-allowed' : 'pointer',
                  fontWeight: 600,
                  fontSize: 14,
                }}
              >
                {submitting ? 'Submitting…' : `Submit Events (${events.length})`}
              </button>
            </div>
          </>
        )
      ) : (
        memberStatus === 'done' ? (
          <div style={waitingBox}>You already submitted your timeline. Results will appear on the task page once everyone is done.</div>
        ) : task.status !== 'timelines_pending' ? (
          <div style={waitingBox}>Waiting for the event annotator to finish marking events.</div>
        ) : (
          <>
            <LabeledText stemText={task.stem_text} spans={timelineSpans} />
            <div style={{ marginTop: 20 }}>
              <Timeline spans={timelineSpans} onUpdateSpan={handleUpdateTimelineSpan} />
            </div>
            <div style={{ marginTop: 20 }}>
              <div style={{ fontSize: 12, fontWeight: 600, color: 'var(--text-muted)', marginBottom: 8 }}>
                LIVE PREVIEW — YOUR ALLEN MATRIX (not shared until agreement is computed)
              </div>
              <MiniMatrix spans={timelineSpans} />
            </div>
            <div style={{ marginTop: 20, display: 'flex', justifyContent: 'flex-end' }}>
              <button
                onClick={handleSubmitTimeline}
                disabled={submitting}
                style={{
                  padding: '10px 20px',
                  background: '#16a34a',
                  color: '#fff',
                  border: 'none',
                  borderRadius: 6,
                  cursor: submitting ? 'not-allowed' : 'pointer',
                  fontWeight: 600,
                  fontSize: 14,
                }}
              >
                {submitting ? 'Submitting…' : 'Submit Timeline'}
              </button>
            </div>
          </>
        )
      )}
    </main>
  );
}

const linkBtn: React.CSSProperties = {
  background: 'none',
  border: 'none',
  cursor: 'pointer',
  color: 'var(--text-muted)',
  fontSize: 13,
  padding: 0,
};

const waitingBox: React.CSSProperties = {
  background: 'var(--surface)',
  border: '1px solid var(--border)',
  borderRadius: 10,
  padding: 32,
  textAlign: 'center',
  color: 'var(--text-muted)',
  fontSize: 14,
};

const miniTh: React.CSSProperties = {
  padding: '4px 8px',
  fontSize: 11,
  color: 'var(--text-muted)',
  border: '1px solid var(--border)',
  background: 'var(--surface-alt)',
};

const miniTd: React.CSSProperties = {
  padding: '4px 8px',
  fontSize: 12,
  border: '1px solid var(--border)',
  textAlign: 'center',
  fontFamily: 'monospace',
};
