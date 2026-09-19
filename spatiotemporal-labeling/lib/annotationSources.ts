'use client';

// Data-source adapters for the shared <Annotator> component.
// See context/group_workflow_redesign.md §7.1 for the design: one annotator
// UI, two adapters (solo batch-stem vs. group-task), so the batch and group
// flows can never drift apart again.

import { useCallback, useEffect, useRef, useState } from 'react';
import { useRouter } from 'next/navigation';
import {
  getBatchStem, listBatchSpans, createBatchSpan, updateBatchSpan, deleteBatchSpan,
  getBatchMatrix, saveBatchMatrix, overrideBatchMatrix, markBatchStemDone,
  extractEvents, extractTimeline, llmLabelAndTimeline,
  getGroupTask, listGroupEvents, createGroupEvent, deleteGroupEvent, submitGroupEvents,
  getMyTimeline, upsertMyTimeline, submitGroupTimeline, llmExtractMyTimeline,
  getMyMatrix, saveMyMatrix, overrideMyMatrix,
} from '@/lib/api';
import {
  BatchStemDetail, Span, MatrixData,
  ExtractEventsResponse, ExtractTimelineResponse, LLMLabelAndTimelineResponse,
  GroupTaskDetailOut, GroupEventSpanOut, MyTimelineResponse,
} from '@/lib/types';

export interface LLMOps {
  extractEvents?(text: string): Promise<{ skippedCount: number }>;
  extractTimeline?(): Promise<{ skippedCount: number }>;
  labelAndTimeline?(): Promise<{ skippedCount: number; timelineSkippedCount: number }>;
}

export interface AnnotationSource {
  title: string;
  subtitle?: string;
  backLabel: string;
  onBack: () => void;

  loading: boolean;
  loadError: string;
  stemText: string;
  spans: Span[];

  canEditEvents: boolean;
  canEditTimeline: boolean;
  visibleSteps: number[];

  addSpan(labelType: 'Event' | 'Time', text: string, charStart: number, charEnd: number): Promise<void>;
  deleteSpan(spanId: number): Promise<void>;
  updateSpanPosition(spanId: number, tlStart: number, tlEnd: number): Promise<void>;

  matrixData: MatrixData | null;
  loadMatrix(): Promise<void>;
  saveMatrix(): Promise<void>;
  overrideMatrix(i: number, j: number, code: number): Promise<void>;

  llm?: LLMOps;

  submitLabel: string;
  submitConfirm?: string;
  onSubmit(): Promise<void>;

  /** True once the role/participant is known but has nothing to do yet
   * (e.g. a timeline annotator whose task is still awaiting events). The
   * component renders spans/matrix as empty in this case anyway, but a
   * source may use this to tailor its title/subtitle. */
  notReady?: boolean;
}

function eventSpanToSpan(e: GroupEventSpanOut, tlStart = 10, tlEnd = 30): Span {
  return {
    id: e.id, session_id: 0, label_type: 'Event', seq_label: e.seq_label,
    span_text: e.span_text, char_start: e.char_start, char_end: e.char_end,
    tl_start: tlStart, tl_end: tlEnd, source: 'manual', created_at: e.created_at,
  };
}

// ---------------------------------------------------------------------------
// Batch-stem adapter (the original solo 3-step flow)
// ---------------------------------------------------------------------------

export function useBatchStemSource(batchId: number, stemId: number): AnnotationSource {
  const router = useRouter();
  const [stem, setStem] = useState<BatchStemDetail | null>(null);
  const [spans, setSpans] = useState<Span[]>([]);
  const [matrixData, setMatrixData] = useState<MatrixData | null>(null);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState('');
  const debounceRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      setLoading(true);
      setLoadError('');
      try {
        const data: BatchStemDetail = await getBatchStem(stemId);
        if (cancelled) return;
        setStem(data);
        const sp = await listBatchSpans(stemId);
        if (cancelled) return;
        setSpans(sp);
      } catch (e: unknown) {
        if (cancelled) return;
        const msg = e instanceof Error ? e.message : 'Failed to load stem.';
        setLoadError(msg);
        if (msg.includes('423') || msg.includes('Lock expired')) {
          setTimeout(() => router.replace('/'), 2000);
        }
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => { cancelled = true; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [stemId]);

  const addSpan = useCallback(async (labelType: 'Event' | 'Time', text: string, charStart: number, charEnd: number) => {
    const newSpan = await createBatchSpan(stemId, {
      label_type: labelType, span_text: text, char_start: charStart, char_end: charEnd, tl_start: 10, tl_end: 30,
    });
    setSpans(prev => [...prev, newSpan]);
  }, [stemId]);

  const deleteSpan = useCallback(async (spanId: number) => {
    await deleteBatchSpan(stemId, spanId);
    setSpans(prev => prev.filter(s => s.id !== spanId));
    setMatrixData(null);
  }, [stemId]);

  const updateSpanPosition = useCallback((spanId: number, tlStart: number, tlEnd: number): Promise<void> => {
    setSpans(prev => prev.map(s => s.id === spanId ? { ...s, tl_start: tlStart, tl_end: tlEnd } : s));
    if (debounceRef.current) clearTimeout(debounceRef.current);
    return new Promise<void>((resolve, reject) => {
      debounceRef.current = setTimeout(async () => {
        try {
          await updateBatchSpan(stemId, spanId, tlStart, tlEnd);
          resolve();
        } catch (e) {
          reject(e);
        }
      }, 400);
    });
  }, [stemId]);

  const loadMatrix = useCallback(async () => {
    try {
      setMatrixData(await getBatchMatrix(stemId));
    } catch {
      setMatrixData(null);
    }
  }, [stemId]);

  const saveMatrix = useCallback(async () => {
    await saveBatchMatrix(stemId);
    setMatrixData(await getBatchMatrix(stemId));
  }, [stemId]);

  const overrideMatrix = useCallback(async (i: number, j: number, code: number) => {
    await overrideBatchMatrix(stemId, i, j, code);
    setMatrixData(await getBatchMatrix(stemId));
  }, [stemId]);

  const onSubmit = useCallback(async () => {
    await saveBatchMatrix(stemId);
    await markBatchStemDone(stemId);
    router.push(`/batches/${batchId}`);
  }, [stemId, batchId, router]);

  return {
    title: stem ? `Stem #${stem.stem_id} — Batch #${batchId}` : 'Loading…',
    subtitle: stem ? `Status: ${stem.status.replace('_', ' ')}` : undefined,
    backLabel: '← Back to Batch',
    onBack: () => router.push(`/batches/${batchId}`),
    loading, loadError,
    stemText: stem?.stem_text ?? '',
    spans,
    canEditEvents: true,
    canEditTimeline: true,
    visibleSteps: [1, 2, 3],
    addSpan, deleteSpan, updateSpanPosition,
    matrixData, loadMatrix, saveMatrix, overrideMatrix,
    llm: {
      extractEvents: async (text: string) => {
        const result: ExtractEventsResponse = await extractEvents(text);
        for (const event of result.events) {
          const newSpan = await createBatchSpan(stemId, {
            label_type: 'Event', span_text: event.span_text,
            char_start: event.char_start, char_end: event.char_end, source: 'llm',
          });
          setSpans(prev => [...prev, newSpan]);
        }
        return { skippedCount: result.skipped.length };
      },
      extractTimeline: async () => {
        const result: ExtractTimelineResponse = await extractTimeline(-stemId);
        if (result.updated?.length) {
          setSpans(prev => prev.map(s => {
            const upd = result.updated.find(u => u.span_id === s.id);
            return upd ? { ...s, tl_start: upd.tl_start, tl_end: upd.tl_end, source: 'llm' as const } : s;
          }));
        }
        return { skippedCount: result.skipped?.length ?? 0 };
      },
      labelAndTimeline: async () => {
        const result: LLMLabelAndTimelineResponse = await llmLabelAndTimeline(stemId, stem?.stem_text ?? '');
        setSpans(await listBatchSpans(stemId));
        return { skippedCount: result.skipped_events.length, timelineSkippedCount: result.timeline_skipped?.length ?? 0 };
      },
    },
    submitLabel: '✓ Mark Done & Return',
    onSubmit,
  };
}

// ---------------------------------------------------------------------------
// Group-task adapter — role-gated per context/group_workflow_redesign.md §7.2
// ---------------------------------------------------------------------------

export function useGroupTaskSource(taskId: number, currentUserId: number | null): AnnotationSource {
  const router = useRouter();
  const [task, setTask] = useState<GroupTaskDetailOut | null>(null);
  const [events, setEvents] = useState<GroupEventSpanOut[]>([]);
  const [timelineSpans, setTimelineSpans] = useState<Span[]>([]);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState('');
  const [matrixData, setMatrixData] = useState<MatrixData | null>(null);

  const myMember = task?.members.find(m => m.user_id === currentUserId) ?? null;
  const role = myMember?.role ?? null;
  const isTimelineAnnotator = role === 'timeline_annotator';

  const load = useCallback(async () => {
    setLoading(true);
    setLoadError('');
    try {
      const t: GroupTaskDetailOut = await getGroupTask(taskId);
      setTask(t);
    } catch (e: unknown) {
      setLoadError(e instanceof Error ? e.message : 'Failed to load group task.');
    } finally {
      setLoading(false);
    }
  }, [taskId]);

  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect
    load();
  }, [load]);

  useEffect(() => {
    if (!task || !role) return;
    let cancelled = false;
    (async () => {
      try {
        if (role === 'event_annotator') {
          const evs = await listGroupEvents(taskId);
          if (!cancelled) setEvents(evs);
        } else {
          const myTl: MyTimelineResponse = await getMyTimeline(taskId);
          if (cancelled) return;
          setTimelineSpans(myTl.positions.map(p => ({
            id: p.span_id, session_id: 0, label_type: 'Event', seq_label: p.seq_label,
            span_text: p.span_text, char_start: 0, char_end: 0,
            tl_start: p.tl_start, tl_end: p.tl_end, source: 'manual', created_at: '',
          })));
        }
      } catch (e: unknown) {
        setLoadError(e instanceof Error ? e.message : 'Failed to load annotation data.');
      }
    })();
    return () => { cancelled = true; };
  }, [task, role, taskId]);

  const addSpan = useCallback(async (_labelType: 'Event' | 'Time', text: string, charStart: number, charEnd: number) => {
    const created = await createGroupEvent(taskId, { span_text: text, char_start: charStart, char_end: charEnd });
    setEvents(prev => [...prev, created]);
  }, [taskId]);

  const deleteSpan = useCallback(async (spanId: number) => {
    await deleteGroupEvent(taskId, spanId);
    setEvents(prev => prev.filter(e => e.id !== spanId));
  }, [taskId]);

  const updateSpanPosition = useCallback(async (spanId: number, tlStart: number, tlEnd: number) => {
    setTimelineSpans(prev => prev.map(s => s.id === spanId ? { ...s, tl_start: tlStart, tl_end: tlEnd } : s));
    await upsertMyTimeline(taskId, [{ span_id: spanId, tl_start: tlStart, tl_end: tlEnd }]);
  }, [taskId]);

  const loadMatrix = useCallback(async () => {
    if (!isTimelineAnnotator) return;
    try {
      const result = await getMyMatrix(taskId);
      setMatrixData({ matrix: result.matrix, span_order: result.span_order, violations: result.violations });
    } catch {
      setMatrixData(null);
    }
  }, [taskId, isTimelineAnnotator]);

  const saveMatrix = useCallback(async () => {
    await saveMyMatrix(taskId);
    await loadMatrix();
  }, [taskId, loadMatrix]);

  const overrideMatrix = useCallback(async (i: number, j: number, code: number) => {
    await overrideMyMatrix(taskId, i, j, code);
    await loadMatrix();
  }, [taskId, loadMatrix]);

  const onSubmit = useCallback(async () => {
    if (isTimelineAnnotator) {
      await upsertMyTimeline(taskId, timelineSpans.map(s => ({ span_id: s.id, tl_start: s.tl_start, tl_end: s.tl_end })));
      await submitGroupTimeline(taskId);
    } else {
      await submitGroupEvents(taskId);
    }
    router.push(`/group-tasks/${taskId}`);
  }, [taskId, isTimelineAnnotator, timelineSpans, router]);

  const stemText = task?.stem_text ?? '';
  const spans = isTimelineAnnotator ? timelineSpans : events.map(e => eventSpanToSpan(e));

  return {
    title: isTimelineAnnotator ? 'Position Timeline' : 'Mark Events',
    subtitle: task ? `Group task #${task.id} · ${task.status.replace('_', ' ')}${myMember ? ` · you: ${myMember.status}` : ''}` : undefined,
    backLabel: `← Task #${taskId}`,
    onBack: () => router.push(`/group-tasks/${taskId}`),
    loading, loadError,
    stemText,
    spans,
    canEditEvents: role === 'event_annotator',
    canEditTimeline: isTimelineAnnotator,
    visibleSteps: isTimelineAnnotator ? [1, 2, 3] : [1],
    addSpan, deleteSpan, updateSpanPosition,
    matrixData, loadMatrix, saveMatrix, overrideMatrix,
    llm: isTimelineAnnotator
      ? {
          extractTimeline: async () => {
            const result: ExtractTimelineResponse = await llmExtractMyTimeline(taskId);
            if (result.updated?.length) {
              setTimelineSpans(prev => prev.map(s => {
                const upd = result.updated.find(u => u.span_id === s.id);
                return upd ? { ...s, tl_start: upd.tl_start, tl_end: upd.tl_end, source: 'llm' as const } : s;
              }));
            }
            return { skippedCount: result.skipped?.length ?? 0 };
          },
        }
      : {
          extractEvents: async (text: string) => {
            const result: ExtractEventsResponse = await extractEvents(text);
            for (const event of result.events) {
              const created = await createGroupEvent(taskId, {
                span_text: event.span_text, char_start: event.char_start, char_end: event.char_end,
              });
              setEvents(prev => [...prev, created]);
            }
            return { skippedCount: result.skipped.length };
          },
        },
    submitLabel: isTimelineAnnotator ? 'Submit Timeline' : `Submit Events (${events.length})`,
    submitConfirm: isTimelineAnnotator
      ? "Submit your timeline? You will not be able to see the other annotators’ work."
      : 'Submit events? They will become visible, read-only, to the 3 timeline annotators.',
    onSubmit,
    notReady: !myMember,
  };
}
