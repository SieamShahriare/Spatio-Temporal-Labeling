'use client';

import { useEffect, useState, useCallback } from 'react';
import { useRouter } from 'next/navigation';
import TextLabeler from '@/components/TextLabeler';
import Timeline from '@/components/Timeline';
import AllenMatrix from '@/components/AllenMatrix';
import LabeledText from '@/components/LabeledText';
import type { AnnotationSource } from '@/lib/annotationSources';

interface Props {
  source: AnnotationSource;
}

// The one 3-step annotation UI used by both the solo batch flow and the
// group-task flow. Role/capability differences come entirely from `source`;
// this component never special-cases batch vs. group.
// See context/group_workflow_redesign.md §7.
export default function Annotator({ source }: Props) {
  const router = useRouter();
  const firstStep = source.visibleSteps[0] ?? 1;
  const [step, setStep] = useState(firstStep);
  const [error, setError] = useState('');
  const [submitting, setSubmitting] = useState(false);
  const [extracting, setExtracting] = useState(false);
  const [extractingTimeline, setExtractingTimeline] = useState(false);
  const [extractingBoth, setExtractingBoth] = useState(false);
  const [skippedCount, setSkippedCount] = useState(0);
  const [timelineSkippedCount, setTimelineSkippedCount] = useState(0);

  // If the role only exposes a subset of steps, never leave `step` pointing
  // at a hidden one.
  useEffect(() => {
    if (!source.visibleSteps.includes(step)) {
      // eslint-disable-next-line react-hooks/set-state-in-effect
      setStep(source.visibleSteps[0] ?? 1);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [source.visibleSteps.join(',')]);

  useEffect(() => {
    if (step === 3 && source.spans.length > 0) {
      source.loadMatrix().catch(() => {});
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [step, source.spans.length]);

  const handleError = useCallback((e: unknown, fallback: string) => {
    const msg = e instanceof Error ? e.message : fallback;
    setError(msg);
    if (msg.includes('423') || msg.includes('Lock expired')) {
      setTimeout(() => router.replace('/'), 2000);
    }
  }, [router]);

  const handleAddSpan = useCallback(async (labelType: 'Event' | 'Time', text: string, charStart: number, charEnd: number) => {
    try {
      await source.addSpan(labelType, text, charStart, charEnd);
    } catch (e) {
      handleError(e, 'Failed to create span.');
    }
  }, [source, handleError]);

  const handleDeleteSpan = useCallback(async (spanId: number) => {
    try {
      await source.deleteSpan(spanId);
    } catch (e) {
      handleError(e, 'Failed to delete span.');
    }
  }, [source, handleError]);

  const handleUpdateSpan = useCallback((spanId: number, tlStart: number, tlEnd: number) => {
    source.updateSpanPosition(spanId, tlStart, tlEnd).catch(e => handleError(e, 'Failed to update span.'));
  }, [source, handleError]);

  const handleSaveMatrix = useCallback(async () => {
    setSubmitting(true);
    try {
      await source.saveMatrix();
    } catch (e) {
      handleError(e, 'Failed to save matrix.');
    } finally {
      setSubmitting(false);
    }
  }, [source, handleError]);

  const handleOverride = useCallback(async (i: number, j: number, code: number) => {
    try {
      await source.overrideMatrix(i, j, code);
    } catch (e) {
      handleError(e, 'Failed to override cell.');
    }
  }, [source, handleError]);

  const handleExtractEvents = useCallback(async (text: string) => {
    if (!source.llm?.extractEvents) return;
    setExtracting(true); setSkippedCount(0); setError('');
    try {
      const result = await source.llm.extractEvents(text);
      setSkippedCount(result.skippedCount);
    } catch (e) {
      handleError(e, 'LLM extraction failed.');
    } finally {
      setExtracting(false);
    }
  }, [source, handleError]);

  const handleExtractTimeline = useCallback(async () => {
    if (!source.llm?.extractTimeline) return;
    setExtractingTimeline(true); setTimelineSkippedCount(0); setError('');
    try {
      const result = await source.llm.extractTimeline();
      setTimelineSkippedCount(result.skippedCount);
    } catch (e) {
      handleError(e, 'Failed to set timeline positions.');
    } finally {
      setExtractingTimeline(false);
    }
  }, [source, handleError]);

  const handleLabelAndTimeline = useCallback(async () => {
    if (!source.llm?.labelAndTimeline) return;
    setExtractingBoth(true); setSkippedCount(0); setTimelineSkippedCount(0); setError('');
    try {
      const result = await source.llm.labelAndTimeline();
      setSkippedCount(result.skippedCount);
      setTimelineSkippedCount(result.timelineSkippedCount);
    } catch (e) {
      handleError(e, 'LLM labeling failed.');
    } finally {
      setExtractingBoth(false);
    }
  }, [source, handleError]);

  const handleSubmit = async () => {
    if (source.submitConfirm && !confirm(source.submitConfirm)) return;
    setSubmitting(true);
    try {
      await source.onSubmit();
    } catch (e) {
      handleError(e, 'Failed to submit.');
      setSubmitting(false);
    }
  };

  if (source.loading) {
    return <main style={{ padding: 40, fontFamily: 'system-ui', color: 'var(--text-muted)' }}>Loading…</main>;
  }
  if (source.loadError && !source.stemText) {
    return <main style={{ padding: 40, fontFamily: 'system-ui', color: 'var(--error)' }}>{source.loadError}</main>;
  }

  const stepLabels: Record<number, string> = { 1: 'Label Text', 2: 'Timeline', 3: 'Matrix' };
  const eventSpans = source.spans.filter(s => s.label_type === 'Event');

  return (
    <main style={{ maxWidth: 1400, margin: '0 auto', padding: '32px 20px', fontFamily: 'system-ui, sans-serif' }}>
      <div style={{ display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between', marginBottom: 24, gap: 16, flexWrap: 'wrap' }}>
        <div>
          <button
            onClick={source.onBack}
            style={{ background: 'none', border: 'none', cursor: 'pointer', color: 'var(--text-muted)', fontSize: 13, padding: 0, marginBottom: 6 }}
          >
            {source.backLabel}
          </button>
          <h1 style={{ fontSize: 18, fontWeight: 700, margin: 0 }}>{source.title}</h1>
          {source.subtitle && (
            <p style={{ fontSize: 13, color: 'var(--text-muted)', margin: '2px 0 0' }}>{source.subtitle}</p>
          )}
        </div>
        <div style={{ display: 'flex', flexDirection: 'column', gap: 8, alignItems: 'flex-end' }}>
          <button
            onClick={handleSubmit}
            disabled={submitting}
            style={{
              padding: '8px 16px', background: submitting ? 'var(--text-disabled)' : '#15803d', color: '#fff',
              border: 'none', borderRadius: 6, cursor: submitting ? 'not-allowed' : 'pointer', fontWeight: 600, fontSize: 13,
            }}
          >
            {submitting ? 'Submitting…' : source.submitLabel}
          </button>
          {source.llm?.labelAndTimeline && (
            <button
              onClick={handleLabelAndTimeline}
              disabled={extractingBoth}
              style={{
                padding: '8px 16px', background: extractingBoth ? 'var(--text-disabled)' : '#2563eb', color: '#fff',
                border: 'none', borderRadius: 6, cursor: extractingBoth ? 'not-allowed' : 'pointer', fontWeight: 600, fontSize: 13,
              }}
            >
              {extractingBoth ? 'Processing…' : 'Use LLM to label events and detect timeline (recommended)'}
            </button>
          )}
        </div>
      </div>

      {error && (
        <div style={{
          background: 'var(--error-bg)', border: '1px solid var(--error-border)', borderRadius: 6, padding: '8px 12px',
          marginBottom: 16, fontSize: 13, color: 'var(--error)', display: 'flex', justifyContent: 'space-between', alignItems: 'center',
        }}>
          <span>{error}</span>
          <button onClick={() => setError('')} style={{ marginLeft: 8, background: 'none', border: 'none', cursor: 'pointer', color: 'var(--text-disabled)' }}>×</button>
        </div>
      )}

      {source.visibleSteps.length > 1 && (
        <div style={{ display: 'flex', gap: 0, marginBottom: 24, borderBottom: '2px solid var(--border)' }}>
          {source.visibleSteps.map(n => (
            <button
              key={n}
              onClick={() => setStep(n)}
              style={{
                padding: '8px 20px', border: 'none', background: 'none', cursor: 'pointer', fontSize: 14,
                fontWeight: step === n ? 700 : 400, color: step === n ? '#2563eb' : 'var(--text-muted)',
                borderBottom: step === n ? '2px solid #2563eb' : '2px solid transparent', marginBottom: -2,
              }}
            >
              Step {n}: {stepLabels[n]}
            </button>
          ))}
        </div>
      )}

      <div style={{ background: 'var(--surface-alt)', border: '1px solid var(--border)', borderRadius: 8, padding: 12, marginBottom: 20, fontSize: 14, color: 'var(--text-primary)' }}>
        <strong style={{ fontSize: 12, color: 'var(--text-muted)', display: 'block', marginBottom: 4 }}>STEM TEXT</strong>
        {source.stemText || <span style={{ color: 'var(--text-disabled)' }}>—</span>}
      </div>

      {step === 1 && (
        <section style={sectionStyle}>
          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 12 }}>
            <h2 style={sectionTitle}>Text Labeling</h2>
            {source.visibleSteps.includes(2) && (
              <button onClick={() => setStep(2)} style={nextBtnStyle}>Next: Timeline →</button>
            )}
          </div>
          {source.canEditEvents ? (
            <TextLabeler
              stemText={source.stemText}
              spans={source.spans}
              onAddSpan={handleAddSpan}
              onDeleteSpan={handleDeleteSpan}
              onExtractEvents={source.llm?.extractEvents ? handleExtractEvents : undefined}
              extracting={extracting}
              skippedCount={skippedCount}
            />
          ) : (
            <>
              <p style={{ fontSize: 12, color: 'var(--text-disabled)', marginBottom: 8 }}>
                Read-only — events are set by the event annotator.
              </p>
              <LabeledText stemText={source.stemText} spans={source.spans} />
            </>
          )}
        </section>
      )}

      {step === 2 && source.visibleSteps.includes(2) && (
        <section style={sectionStyle}>
          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 12 }}>
            <h2 style={sectionTitle}>Timeline Editor</h2>
            <div style={{ display: 'flex', gap: 8 }}>
              <button onClick={() => setStep(1)} style={prevBtnStyle}>← Back</button>
              {source.visibleSteps.includes(3) && (
                <button onClick={() => setStep(3)} style={nextBtnStyle}>Next: Matrix →</button>
              )}
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
                spans={eventSpans}
                onUpdateSpan={handleUpdateSpan}
                onExtractTimeline={source.llm?.extractTimeline ? handleExtractTimeline : undefined}
                extractingTimeline={extractingTimeline}
              />
            </div>
            <div style={{ flex: '1 1 35%', minWidth: 280, maxHeight: '85vh', overflowY: 'auto', border: '1px solid var(--border)', borderRadius: 8, padding: 16, background: 'var(--surface-alt)' }}>
              <div style={{ fontSize: 12, fontWeight: 600, color: 'var(--text-muted)', marginBottom: 8 }}>STEM TEXT</div>
              <LabeledText stemText={source.stemText} spans={source.spans} />
            </div>
          </div>
        </section>
      )}

      {step === 3 && source.visibleSteps.includes(3) && (
        <section style={sectionStyle}>
          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 12 }}>
            <h2 style={sectionTitle}>Allen&apos;s Relation Matrix</h2>
            <div style={{ display: 'flex', gap: 8 }}>
              <button onClick={() => setStep(2)} style={prevBtnStyle}>← Back</button>
              <button
                onClick={handleSaveMatrix}
                disabled={submitting}
                style={{
                  padding: '6px 14px', background: submitting ? 'var(--text-disabled)' : '#2563eb', color: '#fff',
                  border: 'none', borderRadius: 6, cursor: submitting ? 'not-allowed' : 'pointer', fontSize: 13, fontWeight: 500,
                }}
              >
                {submitting ? 'Saving…' : '↻ Save & Recompute'}
              </button>
            </div>
          </div>
          <div style={{ display: 'flex', gap: 24, alignItems: 'flex-start' }}>
            <div style={{ flex: '1 1 65%', minWidth: 0 }}>
              {source.matrixData ? (
                <AllenMatrix matrixData={source.matrixData} onOverride={handleOverride} onSave={handleSaveMatrix} />
              ) : (
                <div style={{ padding: 24, textAlign: 'center' }}>
                  <p style={{ color: 'var(--text-muted)', fontSize: 14 }}>
                    {source.spans.length === 0
                      ? 'Add spans in Step 1 first.'
                      : 'Click "Save & Recompute" to generate the matrix.'}
                  </p>
                  {source.spans.length > 0 && (
                    <button onClick={handleSaveMatrix} style={{ ...nextBtnStyle, marginTop: 12 }}>Save &amp; Recompute</button>
                  )}
                </div>
              )}
            </div>
            <div style={{ flex: '1 1 35%', minWidth: 280, maxHeight: '85vh', overflowY: 'auto', border: '1px solid var(--border)', borderRadius: 8, padding: 16, background: 'var(--surface-alt)' }}>
              <div style={{ fontSize: 12, fontWeight: 600, color: 'var(--text-muted)', marginBottom: 8 }}>STEM TEXT</div>
              <LabeledText stemText={source.stemText} spans={source.spans} />
            </div>
          </div>
        </section>
      )}
    </main>
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
