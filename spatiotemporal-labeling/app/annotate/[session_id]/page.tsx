'use client';

import { useEffect, useState, useCallback, useRef } from 'react';
import { useParams, useRouter } from 'next/navigation';
import TextLabeler from '@/components/TextLabeler';
import Timeline from '@/components/Timeline';
import AllenMatrix from '@/components/AllenMatrix';
import LabeledText from '@/components/LabeledText';
import {
  getSession, createSpan, deleteSpan, updateSpan,
  getMatrix, saveMatrix, overrideMatrix, updateSessionStatus,
  extractEvents
} from '@/lib/api';
import { Session, Span, MatrixData } from '@/lib/types';

export default function AnnotatePage() {
  const { session_id } = useParams<{ session_id: string }>();
  const sessionId = parseInt(session_id);
  const router = useRouter();

  const [session, setSession] = useState<Session | null>(null);
  const [spans, setSpans] = useState<Span[]>([]);
  const [matrixData, setMatrixData] = useState<MatrixData | null>(null);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [extracting, setExtracting] = useState(false);
  const [skippedCount, setSkippedCount] = useState(0);
  const [error, setError] = useState('');
  const [step, setStep] = useState(1); // 1=text, 2=timeline, 3=matrix
  const debounceRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const [mounted, setMounted] = useState(false);

  // Load session on mount
  useEffect(() => {
    setMounted(true);
    getSession(sessionId)
      .then((data: Session) => {
        setSession(data);
        setSpans(data.spans ?? []);
        setLoading(false);
      })
      .catch(() => { setError('Failed to load session.'); setLoading(false); });
  }, [sessionId]);

  // Recompute matrix whenever we switch to step 3
  useEffect(() => {
    if (step === 3 && spans.length > 0) {
      getMatrix(sessionId)
        .then(setMatrixData)
        .catch(() => setMatrixData(null));
    }
  }, [step, sessionId, spans]);

  // Add span
  const handleAddSpan = useCallback(async (
    labelType: 'Event' | 'Time',
    spanText: string,
    charStart: number,
    charEnd: number
  ) => {
    try {
      const newSpan: Span = await createSpan(sessionId, {
        label_type: labelType,
        span_text: spanText,
        char_start: charStart,
        char_end: charEnd,
        tl_start: 10,
        tl_end: 30,
      });
      setSpans(prev => [...prev, newSpan]);
    } catch (e: any) {
      setError(e.message ?? 'Failed to create span.');
    }
  }, [sessionId]);

  // Delete span
  const handleDeleteSpan = useCallback(async (spanId: number) => {
    await deleteSpan(spanId).catch(() => {});
    setSpans(prev => prev.filter(s => s.id !== spanId));
    setMatrixData(null);
  }, []);

  const handleExtractEvents = useCallback(async (text: string) => {
    if (!session) return;
    setExtracting(true);
    setSkippedCount(0);
    setError('');
    try {
      const result: { events: { label_type: string; span_text: string; char_start: number; char_end: number; tl_start: number; tl_end: number; source: string }[]; skipped: { text: string; reason: string }[] } = await extractEvents(text);
      const events = result.events;
      const skippedFromApi = result.skipped ?? [];
      setSkippedCount(skippedFromApi.length);

      const existingCharRanges: [number, number][] = spans
        .filter(s => s.source !== 'llm')
        .map(s => [s.char_start, s.char_end]);

      setSpans(prev => prev.filter(s => s.source !== 'llm'));

      const accepted = events.filter(ev => {
        return !existingCharRanges.some(([s, e]) => {
          return ev.char_start < e && ev.char_end > s;
        });
      });

      const createdSpans: Span[] = [];
      for (const ev of accepted) {
        try {
          const created = await createSpan(sessionId, {
            label_type: ev.label_type,
            span_text: ev.span_text,
            char_start: ev.char_start,
            char_end: ev.char_end,
            tl_start: ev.tl_start,
            tl_end: ev.tl_end,
            source: ev.source,
          });
          createdSpans.push(created);
        } catch {
          /* skip individual failures */
        }
      }
      if (createdSpans.length > 0) {
        setSpans(prev => [...prev.filter(s => s.source !== 'llm'), ...createdSpans]);
      }
    } catch (e: unknown) {
      const msg = e instanceof Error ? e.message : 'LLM extraction failed.';
      setError(msg);
    } finally {
      setExtracting(false);
    }
  }, [sessionId, session, spans]);

  // Update span positions (debounced)
  const handleUpdateSpan = useCallback((spanId: number, tlStart: number, tlEnd: number) => {
    setSpans(prev => prev.map(s => s.id === spanId ? { ...s, tl_start: tlStart, tl_end: tlEnd } : s));
    if (debounceRef.current) clearTimeout(debounceRef.current);
    debounceRef.current = setTimeout(async () => {
      try {
        await updateSpan(spanId, tlStart, tlEnd);
      } catch (e: any) {
        setError(e.message ?? 'Failed to update span.');
      }
    }, 400);
  }, []);

  // Save & recompute matrix
  const handleSaveMatrix = useCallback(async () => {
    setSaving(true);
    try {
      const result = await saveMatrix(sessionId);
      const full = await getMatrix(sessionId);
      setMatrixData(full);
    } catch (e: any) {
      setError(e.message ?? 'Failed to save matrix.');
    } finally {
      setSaving(false);
    }
  }, [sessionId]);

  // Override a matrix cell
  const handleOverride = useCallback(async (i: number, j: number, code: number) => {
    try {
      const result = await overrideMatrix(sessionId, i, j, code);
      // Refresh matrix
      const full = await getMatrix(sessionId);
      setMatrixData(full);
    } catch (e: any) {
      setError(e.message ?? 'Failed to override cell.');
    }
  }, [sessionId]);

  // Mark done and exit
  const handleMarkDone = async () => {
    if (!confirm('Mark this session as done and return to landing page?')) return;
    try {
      await handleSaveMatrix();
      await updateSessionStatus(sessionId, 'done');
      router.push('/');
    } catch (e: any) {
      setError(e.message ?? 'Failed to mark done.');
    }
  };

  if (!mounted) return <div style={{ minHeight: '100vh', background: 'var(--background-page)' }} />;
  if (loading) return <div style={{ padding: 40, fontFamily: 'system-ui', color: 'var(--text-muted)' }}>Loading session…</div>;
  if (!session) return <div style={{ padding: 40, fontFamily: 'system-ui', color: 'var(--error)' }}>{error || 'Session not found.'}</div>;

  return (
    <>
      <main style={{ maxWidth: 900, margin: '0 auto', padding: '32px 20px', fontFamily: 'system-ui, sans-serif' }}>
        {/* Header */}
      <div style={{ display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between', marginBottom: 24 }}>
        <div>
          <button
            onClick={() => router.push('/')}
            style={{ background: 'none', border: 'none', cursor: 'pointer', color: 'var(--text-muted)', fontSize: 13, padding: 0, marginBottom: 6 }}
          >
            ← Back to Landing
          </button>
          <h1 style={{ fontSize: 18, fontWeight: 700, margin: 0 }}>
            Session #{session.id} — {session.username}
          </h1>
          <p style={{ fontSize: 13, color: 'var(--text-muted)', margin: '2px 0 0' }}>
            Status: <strong>{session.status}</strong>
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
          ✓ Mark Done &amp; Exit
        </button>
      </div>

      {error && (
        <div style={{ background: 'var(--error-bg)', border: '1px solid var(--error-border)', borderRadius: 6, padding: '8px 12px', marginBottom: 16, fontSize: 13, color: 'var(--error)' }}>
          {error}
          <button onClick={() => setError('')} style={{ marginLeft: 8, background: 'none', border: 'none', cursor: 'pointer', color: 'var(--text-disabled)' }}>×</button>
        </div>
      )}

        {/* Step tabs */}
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

        {/* Stem text (always visible collapsed) */}
        <div style={{ background: 'var(--surface-alt)', border: '1px solid var(--border)', borderRadius: 8, padding: 12, marginBottom: 20, fontSize: 14, color: 'var(--text-primary)' }}>
          <strong style={{ fontSize: 12, color: 'var(--text-muted)', display: 'block', marginBottom: 4 }}>STEM TEXT</strong>
          {session.stem_text}
        </div>

        {/* Step 1: Text Labeler */}
        {step === 1 && (
          <section style={sectionStyle}>
            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 12 }}>
              <h2 style={sectionTitle}>Text Labeling</h2>
              <button onClick={() => setStep(2)} style={nextBtnStyle}>
                Next: Timeline →
              </button>
            </div>
            <TextLabeler
              stemText={session.stem_text}
              spans={spans}
              onAddSpan={handleAddSpan}
              onDeleteSpan={handleDeleteSpan}
              onExtractEvents={handleExtractEvents}
              extracting={extracting}
              skippedCount={skippedCount}
            />
          </section>
        )}
      </main>

      {/* Step 2: Timeline */}
      {step === 2 && (
        <section style={sectionStyle}>
          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 12, maxWidth: 1200, margin: '0 auto 12px', padding: '0 24px' }}>
            <h2 style={sectionTitle}>Timeline Editor</h2>
            <div style={{ display: 'flex', gap: 8 }}>
              <button onClick={() => setStep(1)} style={prevBtnStyle}>← Back</button>
              <button onClick={() => setStep(3)} style={nextBtnStyle}>Next: Matrix →</button>
            </div>
          </div>
          <p style={{ fontSize: 13, color: 'var(--text-muted)', marginBottom: 12, maxWidth: 1200, margin: '0 auto 12px', padding: '0 24px' }}>
            Drag blocks to set positions (0–100 scale). Use the left/right handles to resize. Use manual inputs for precise values.
          </p>
          <div style={{ display: 'flex', gap: 24, alignItems: 'flex-start', maxWidth: 1800, margin: '0 auto' }}>
            <div style={{ flex: '1 1 65%', minWidth: 0, padding: '0 24px' }}>
              <Timeline spans={spans.filter(s => s.label_type === 'Event')} onUpdateSpan={handleUpdateSpan} />
            </div>
            <div style={{ flex: '1 1 35%', minWidth: 280, maxHeight: '85vh', overflowY: 'auto', border: '1px solid var(--border)', borderRadius: 8, padding: 16, background: 'var(--surface-alt)' }}>
              <div style={{ fontSize: 12, fontWeight: 600, color: 'var(--text-muted)', marginBottom: 8 }}>STEM TEXT</div>
              <LabeledText stemText={session.stem_text} spans={spans} />
            </div>
          </div>
        </section>
      )}

      {/* Step 3: Matrix */}
      {step === 3 && (
        <section style={sectionStyle}>
          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 12, maxWidth: 1200, margin: '0 auto 12px', padding: '0 24px' }}>
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
          <div style={{ display: 'flex', gap: 24, alignItems: 'flex-start', maxWidth: 1800, margin: '0 auto', padding: '0 24px' }}>
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
              <LabeledText stemText={session.stem_text} spans={spans} />
            </div>
          </div>
        </section>
      )}
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
