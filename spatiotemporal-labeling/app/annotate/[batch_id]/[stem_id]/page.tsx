'use client';

import { useEffect, useState, useCallback, useRef } from 'react';
import { useParams, useRouter } from 'next/navigation';
import TextLabeler from '@/components/TextLabeler';
import Timeline from '@/components/Timeline';
import AllenMatrix from '@/components/AllenMatrix';
import LabeledText from '@/components/LabeledText';
import {
  getBatchStem,
  listBatchSpans,
  createBatchSpan,
  updateBatchSpan,
  deleteBatchSpan,
  getBatchMatrix,
  saveBatchMatrix,
  overrideBatchMatrix,
  markBatchStemDone,
  extractEvents,
} from '@/lib/api';
import { BatchStemDetail, BatchSpanOut, MatrixData, ExtractEventsResponse } from '@/lib/types';
import { useAuth } from '@/lib/AuthContext';

export default function AnnotateBatchStemPage() {
  const params = useParams<{ batch_id: string; stem_id: string }>();
  const batchId = parseInt(params.batch_id);
  const stemId = parseInt(params.stem_id);
  const router = useRouter();
  const { user, loading: authLoading } = useAuth();
  const isBrowser = typeof window !== 'undefined';

  const [stem, setStem] = useState<BatchStemDetail | null>(null);
  const [spans, setSpans] = useState<BatchSpanOut[]>([]);
  const [matrixData, setMatrixData] = useState<MatrixData | null>(null);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [extracting, setExtracting] = useState(false);
  const [extractingTimeline, setExtractingTimeline] = useState(false);
  const [skippedCount, setSkippedCount] = useState(0);
  const [timelineSkippedCount, setTimelineSkippedCount] = useState(0);
  const [error, setError] = useState('');
  const [step, setStep] = useState(1);
  const debounceRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const mountedRef = useRef(false);

  useEffect(() => { mountedRef.current = true; }, []);

  useEffect(() => {
    if (!authLoading && !user && isBrowser) {
      router.replace('/login');
    }
  }, [user, authLoading, router, isBrowser]);

  useEffect(() => {
    if (!user) return;
    let cancelled = false;
    const load = async () => {
      setLoading(true);
      setError('');
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
        setError(msg);
        if (msg.includes('423') || msg.includes('Lock expired')) {
          setTimeout(() => router.replace('/'), 2000);
        }
      } finally {
        if (!cancelled) setLoading(false);
      }
    };
    load();
    return () => { cancelled = true; };
  }, [stemId, user, router]);

  useEffect(() => {
    if (step === 3 && spans.length > 0 && isBrowser) {
      getBatchMatrix(stemId)
        .then(setMatrixData)
        .catch(() => setMatrixData(null));
    }
  }, [step, stemId, spans, isBrowser]);

  const handleAddSpan = useCallback(async (
    labelType: 'Event' | 'Time',
    spanText: string,
    charStart: number,
    charEnd: number
  ) => {
    try {
      const newSpan: BatchSpanOut = await createBatchSpan(stemId, {
        label_type: labelType,
        span_text: spanText,
        char_start: charStart,
        char_end: charEnd,
        tl_start: 10,
        tl_end: 30,
      });
      setSpans(prev => [...prev, newSpan]);
    } catch (e: unknown) {
      const msg = e instanceof Error ? e.message : 'Failed to create span.';
      setError(msg);
      if (msg.includes('423') || msg.includes('Lock expired')) {
        setTimeout(() => router.replace('/'), 2000);
      }
    }
  }, [stemId, router]);

  const handleDeleteSpan = useCallback(async (spanId: number) => {
    try {
      await deleteBatchSpan(stemId, spanId);
      setSpans(prev => prev.filter(s => s.id !== spanId));
      setMatrixData(null);
    } catch (e: unknown) {
      const msg = e instanceof Error ? e.message : 'Failed to delete span.';
      setError(msg);
    }
  }, [stemId]);

  const handleExtractEvents = useCallback(async (text: string) => {
    setExtracting(true);
    setSkippedCount(0);
    setError('');
    try {
      const result: ExtractEventsResponse = await extractEvents(text);
      const created: BatchSpanOut[] = [];
      for (const event of result.events) {
        try {
          const newSpan: BatchSpanOut = await createBatchSpan(stemId, {
            label_type: 'Event',
            span_text: event.span_text,
            char_start: event.char_start,
            char_end: event.char_end,
            tl_start: event.tl_start,
            tl_end: event.tl_end,
            source: 'llm',
          });
          created.push(newSpan);
        } catch (spanErr: unknown) {
          const detail = spanErr instanceof Error ? spanErr.message : 'Failed to create span.';
          setError(prev => `${prev}\nSpan error: event=${JSON.stringify(event)} error=${detail}`.trim());
        }
      }
      if (created.length > 0) {
        setSpans(prev => [...prev, ...created]);
      }
      setSkippedCount(result.skipped.length);
    } catch (e: unknown) {
      const msg = e instanceof Error ? e.message : 'LLM extraction failed.';
      setError(msg);
    } finally {
      setExtracting(false);
    }
  }, [stemId]);

  const handleExtractTimeline = useCallback(async () => {
    setExtractingTimeline(true);
    setTimelineSkippedCount(0);
    setError('');
    try {
      const updated = await listBatchSpans(stemId);
      setSpans(updated);
    } catch (e: unknown) {
      const msg = e instanceof Error ? e.message : 'Failed to set timeline positions.';
      setError(msg);
    } finally {
      setExtractingTimeline(false);
    }
  }, [stemId]);

  const handleUpdateSpan = useCallback((spanId: number, tlStart: number, tlEnd: number) => {
    setSpans(prev => prev.map(s => s.id === spanId ? { ...s, tl_start: tlStart, tl_end: tlEnd } : s));
    if (debounceRef.current) clearTimeout(debounceRef.current);
    debounceRef.current = setTimeout(async () => {
      try {
        await updateBatchSpan(stemId, spanId, tlStart, tlEnd);
      } catch (e: unknown) {
        const msg = e instanceof Error ? e.message : 'Failed to update span.';
        setError(msg);
      }
    }, 400);
  }, [stemId]);

  const handleSaveMatrix = useCallback(async () => {
    setSaving(true);
    try {
      await saveBatchMatrix(stemId);
      const full = await getBatchMatrix(stemId);
      setMatrixData(full);
    } catch (e: unknown) {
      const msg = e instanceof Error ? e.message : 'Failed to save matrix.';
      setError(msg);
    } finally {
      setSaving(false);
    }
  }, [stemId]);

  const handleOverride = useCallback(async (i: number, j: number, code: number) => {
    try {
      await overrideBatchMatrix(stemId, i, j, code);
      const full = await getBatchMatrix(stemId);
      setMatrixData(full);
    } catch (e: unknown) {
      const msg = e instanceof Error ? e.message : 'Failed to override cell.';
      setError(msg);
    }
  }, [stemId]);

  const handleMarkDone = async () => {
    if (!confirm('Mark this stem as done and return to batch detail?')) return;
    try {
      await saveBatchMatrix(stemId);
      await markBatchStemDone(stemId);
      router.push(`/batches/${batchId}`);
    } catch (e: unknown) {
      const msg = e instanceof Error ? e.message : 'Failed to mark done.';
      setError(msg);
      if (msg.includes('423') || msg.includes('Lock expired')) {
        setTimeout(() => router.replace('/'), 2000);
      }
    }
  };

  if (!isBrowser || authLoading) {
    return <div style={{ minHeight: '100vh', background: 'var(--background-page)' }} />;
  }
  if (loading) return (
    <main style={{ padding: 40, fontFamily: 'system-ui', color: 'var(--text-muted)' }}>Loading stem…</main>
  );
  if (!stem) return (
    <main style={{ padding: 40, fontFamily: 'system-ui', color: 'var(--error)' }}>{error || 'Stem not found.'}</main>
  );

  return (
    <>
      <main style={{ maxWidth: 900, margin: '0 auto', padding: '32px 20px', fontFamily: 'system-ui, sans-serif' }}>
        <div style={{ display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between', marginBottom: 24 }}>
          <div>
            <button
              onClick={() => router.push(`/batches/${batchId}`)}
              style={{ background: 'none', border: 'none', cursor: 'pointer', color: 'var(--text-muted)', fontSize: 13, padding: 0, marginBottom: 6 }}
            >
              ← Back to Batch
            </button>
            <h1 style={{ fontSize: 18, fontWeight: 700, margin: 0 }}>
              Stem #{stem.stem_id} — Batch #{batchId}
            </h1>
            <p style={{ fontSize: 13, color: 'var(--text-muted)', margin: '2px 0 0' }}>
              Status: <strong>{stem.status.replace('_', ' ')}</strong>
            </p>
          </div>
          <button
            onClick={handleMarkDone}
            style={{
              padding: '8px 16px',
              background: '#15803d',
              color: '#fff',
              border: 'none',
              borderRadius: 6,
              cursor: 'pointer',
              fontWeight: 600,
              fontSize: 13,
            }}
          >
            ✓ Mark Done &amp; Return
          </button>
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
            <button onClick={() => setError('')} style={{ marginLeft: 8, background: 'none', border: 'none', cursor: 'pointer', color: 'var(--text-disabled)' }}>×</button>
          </div>
        )}

        <div style={{ display: 'flex', gap: 0, marginBottom: 24, borderBottom: '2px solid var(--border)' }}>
          {[
            { n: 1, label: 'Step 1: Label Text' },
            { n: 2, label: 'Step 2: Timeline' },
            { n: 3, label: 'Step 3: Matrix' },
          ].map(s => (
            <button
              key={s.n}
              onClick={() => setStep(s.n)}
              style={{
                padding: '8px 20px',
                border: 'none',
                background: 'none',
                cursor: 'pointer',
                fontSize: 14,
                fontWeight: step === s.n ? 700 : 400,
                color: step === s.n ? '#2563eb' : 'var(--text-muted)',
                borderBottom: step === s.n ? '2px solid #2563eb' : '2px solid transparent',
                marginBottom: -2,
              }}
            >
              {s.label}
            </button>
          ))}
        </div>

        <div style={{ background: 'var(--surface-alt)', border: '1px solid var(--border)', borderRadius: 8, padding: 12, marginBottom: 20, fontSize: 14, color: 'var(--text-primary)' }}>
          <strong style={{ fontSize: 12, color: 'var(--text-muted)', display: 'block', marginBottom: 4 }}>STEM TEXT</strong>
          {stem.stem_text}
        </div>

        {step === 1 && (
          <section style={sectionStyle}>
            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 12 }}>
              <h2 style={sectionTitle}>Text Labeling</h2>
              <button onClick={() => setStep(2)} style={nextBtnStyle}>Next: Timeline →</button>
            </div>
            <TextLabeler
              stemText={stem.stem_text}
              spans={spans}
              onAddSpan={handleAddSpan}
              onDeleteSpan={handleDeleteSpan}
              onExtractEvents={handleExtractEvents}
              extracting={extracting}
              skippedCount={skippedCount}
            />
          </section>
        )}

        {step === 2 && (
          <section style={sectionStyle}>
            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 12 }}>
              <h2 style={sectionTitle}>Timeline Editor</h2>
              <div style={{ display: 'flex', gap: 8 }}>
                <button onClick={() => setStep(1)} style={prevBtnStyle}>← Back</button>
                <button onClick={() => setStep(3)} style={nextBtnStyle}>Next: Matrix →</button>
              </div>
            </div>
            <p style={{ fontSize: 13, color: 'var(--text-muted)', marginBottom: 12 }}>
              Drag blocks to set positions (0–100 scale). Use the left/right handles to resize. Use manual inputs for precise values.
            </p>
            {timelineSkippedCount > 0 && (
              <p style={{ fontSize: 12, color: 'var(--text-muted)', marginBottom: 8 }}>
                {timelineSkippedCount} event{timelineSkippedCount !== 1 ? 's' : ''} could not be positioned and were skipped.
              </p>
            )}
            <div style={{ display: 'flex', gap: 24, alignItems: 'flex-start' }}>
              <div style={{ flex: '1 1 65%', minWidth: 0 }}>
                <Timeline
                  spans={spans.filter(s => s.label_type === 'Event')}
                  onUpdateSpan={handleUpdateSpan}
                  onExtractTimeline={handleExtractTimeline}
                  extractingTimeline={extractingTimeline}
                />
              </div>
              <div style={{ flex: '1 1 35%', minWidth: 280, maxHeight: '85vh', overflowY: 'auto', border: '1px solid var(--border)', borderRadius: 8, padding: 16, background: 'var(--surface-alt)' }}>
                <div style={{ fontSize: 12, fontWeight: 600, color: 'var(--text-muted)', marginBottom: 8 }}>STEM TEXT</div>
                <LabeledText stemText={stem.stem_text} spans={spans} />
              </div>
            </div>
          </section>
        )}

        {step === 3 && (
          <section style={sectionStyle}>
            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 12 }}>
              <h2 style={sectionTitle}>Allen&apos;s Relation Matrix</h2>
              <div style={{ display: 'flex', gap: 8 }}>
                <button onClick={() => setStep(2)} style={prevBtnStyle}>← Back</button>
                <button
                  onClick={handleSaveMatrix}
                  disabled={saving}
                  style={{
                    padding: '6px 14px',
                    background: saving ? 'var(--text-disabled)' : '#2563eb',
                    color: '#fff',
                    border: 'none',
                    borderRadius: 6,
                    cursor: saving ? 'not-allowed' : 'pointer',
                    fontSize: 13,
                    fontWeight: 500,
                  }}
                >
                  {saving ? 'Saving…' : '↻ Save & Recompute'}
                </button>
              </div>
            </div>
            <div style={{ display: 'flex', gap: 24, alignItems: 'flex-start' }}>
              <div style={{ flex: '1 1 65%', minWidth: 0 }}>
                {matrixData ? (
                  <AllenMatrix
                    matrixData={matrixData}
                    onOverride={handleOverride}
                    onSave={handleSaveMatrix}
                  />
                ) : (
                  <div style={{ padding: 24, textAlign: 'center' }}>
                    <p style={{ color: 'var(--text-muted)', fontSize: 14 }}>
                      {spans.length === 0
                        ? 'Add spans in Step 1 first.'
                        : 'Click "Save & Recompute" to generate the matrix.'}
                    </p>
                    {spans.length > 0 && (
                      <button onClick={handleSaveMatrix} style={{ ...nextBtnStyle, marginTop: 12 }}>
                        Save &amp; Recompute
                      </button>
                    )}
                  </div>
                )}
              </div>
              <div style={{ flex: '1 1 35%', minWidth: 280, maxHeight: '85vh', overflowY: 'auto', border: '1px solid var(--border)', borderRadius: 8, padding: 16, background: 'var(--surface-alt)' }}>
                <div style={{ fontSize: 12, fontWeight: 600, color: 'var(--text-muted)', marginBottom: 8 }}>STEM TEXT</div>
                <LabeledText stemText={stem.stem_text} spans={spans} />
              </div>
            </div>
          </section>
        )}
      </main>
    </>
  );
}

const sectionStyle: React.CSSProperties = {
  background: 'var(--surface)',
  border: '1px solid var(--border)',
  borderRadius: 10,
  padding: 24,
};

const sectionTitle: React.CSSProperties = {
  fontSize: 15,
  fontWeight: 700,
  margin: 0,
  color: 'var(--text-primary)',
};

const nextBtnStyle: React.CSSProperties = {
  padding: '6px 14px',
  background: '#2563eb',
  color: '#fff',
  border: 'none',
  borderRadius: 6,
  cursor: 'pointer',
  fontSize: 13,
  fontWeight: 500,
};

const prevBtnStyle: React.CSSProperties = {
  padding: '6px 14px',
  background: 'var(--surface)',
  color: 'var(--text-primary)',
  border: '1px solid var(--border-input)',
  borderRadius: 6,
  cursor: 'pointer',
  fontSize: 13,
  fontWeight: 500,
};
