'use client';

import { useEffect, useState, useCallback, useRef } from 'react';
import { useParams, useRouter, useSearchParams } from 'next/navigation';
import TextLabeler from '@/components/TextLabeler';
import Timeline from '@/components/Timeline';
import AllenMatrix from '@/components/AllenMatrix';
import LabeledText from '@/components/LabeledText';
import ReviewControls from '@/components/ReviewControls';
import MethodologyGuide from '@/components/MethodologyGuide';
import {
  getBatchStem,
  listBatchSpans,
  createBatchSpan,
  updateBatchSpan,
  deleteBatchSpan,
  getBatchMatrix,
  saveBatchMatrix,
  overrideBatchMatrix,
  submitBatchStemForReview,
  reviewBatchStem,
  getStemReviews,
  extractEvents,
  extractTimeline,
  llmLabelAndTimeline,
  updateBatchStemText,
} from '@/lib/api';
import { BatchStemDetail, BatchSpanOut, MatrixData, ExtractEventsResponse, ExtractTimelineResponse, LLMLabelAndTimelineResponse, StemReview } from '@/lib/types';
import { useAuth } from '@/lib/AuthContext';

export default function AnnotateBatchStemPage() {
  const params = useParams<{ batch_id: string; stem_id: string }>();
  const searchParams = useSearchParams();
  const batchId = parseInt(params.batch_id);
  const stemId = parseInt(params.stem_id);
  const router = useRouter();
  const { user, loading: authLoading } = useAuth();
  const isBrowser = typeof window !== 'undefined';

  const [stem, setStem] = useState<BatchStemDetail | null>(null);
  const [spans, setSpans] = useState<BatchSpanOut[]>([]);
  const [matrixData, setMatrixData] = useState<MatrixData | null>(null);
  const [reviews, setReviews] = useState<StemReview[]>([]);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [reviewing, setReviewing] = useState(false);
  const [isEditingStem, setIsEditingStem] = useState(false);
  const [stemEditText, setStemEditText] = useState('');
  const [savingStem, setSavingStem] = useState(false);
  const [successMessage, setSuccessMessage] = useState('');
  const [showAnnotatorGuide, setShowAnnotatorGuide] = useState(false);
  const [extracting, setExtracting] = useState(false);
  const [extractingTimeline, setExtractingTimeline] = useState(false);
  const [extractingBoth, setExtractingBoth] = useState(false);
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
        try {
          const revs = await getStemReviews(stemId);
          if (!cancelled) setReviews(revs);
        } catch {
          // ignore review fetch error for non-reviewers
        }
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
      const updatedSpans = await listBatchSpans(stemId);
      setSpans(updatedSpans);
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
        source: 'llm',
      });
          created.push(newSpan);
        } catch (spanErr: unknown) {
          const detail = spanErr instanceof Error ? spanErr.message : 'Failed to create span.';
          setError(prev => `${prev}\nSpan error: event=${JSON.stringify(event)} error=${detail}`.trim());
        }
      }
      if (created.length > 0) {
        const updatedSpans = await listBatchSpans(stemId);
        setSpans(updatedSpans);
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
      const result: ExtractTimelineResponse = await extractTimeline(-stemId);
      if (result.updated && result.updated.length > 0) {
        setSpans(prev => prev.map(s => {
          const upd = result.updated.find((u) => u.span_id === s.id);
          return upd ? { ...s, tl_start: upd.tl_start, tl_end: upd.tl_end, source: 'llm' as const } : s;
        }));
      }
      setTimelineSkippedCount(result.skipped?.length || 0);
    } catch (e: unknown) {
      const msg = e instanceof Error ? e.message : 'Failed to set timeline positions.';
      setError(msg);
    } finally {
      setExtractingTimeline(false);
    }
  }, [stemId]);

  const handleLLMLabelAndTimeline = useCallback(async () => {
    setExtractingBoth(true);
    setSkippedCount(0);
    setTimelineSkippedCount(0);
    setError('');
    try {
      const result: LLMLabelAndTimelineResponse = await llmLabelAndTimeline(stemId, stem!.stem_text);
      setSkippedCount(result.skipped_events.length);
      setTimelineSkippedCount(result.timeline_skipped?.length || 0);
      const updatedSpans = await listBatchSpans(stemId);
      setSpans(updatedSpans);
    } catch (e: unknown) {
      const msg = e instanceof Error ? e.message : 'LLM labeling failed.';
      setError(msg);
    } finally {
      setExtractingBoth(false);
    }
  }, [stemId, stem]);

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

  const handleSubmitForReview = useCallback(async () => {
    const eventCount = spans.filter(s => s.label_type === 'Event').length;
    if (eventCount === 0) {
      setError('Please label at least one Event span before submitting for review.');
      return;
    }
    const isResubmit = stem?.status === 're-evaluate';
    const confirmMsg = isResubmit
      ? 'Resubmit this stem for reviewer evaluation?'
      : 'Submit this stem for review? A reviewer will evaluate your event and timeline annotations.';
    if (!confirm(confirmMsg)) return;
    setSaving(true);
    try {
      await submitBatchStemForReview(stemId);
      router.push(`/batches/${batchId}`);
    } catch (e: unknown) {
      const msg = e instanceof Error ? e.message : 'Failed to submit for review.';
      setError(msg);
      if (msg.includes('423') || msg.includes('Lock expired')) {
        setTimeout(() => router.replace('/'), 2000);
      }
    } finally {
      setSaving(false);
    }
  }, [stem, stemId, batchId, spans, router]);

  const handleReview = useCallback(async (decision: 'accept' | 're-evaluate' | 'blacklist' | 'release_to_pool', comment?: string) => {
    setReviewing(true);
    setError('');
    try {
      await reviewBatchStem(stemId, { decision, comment });
      router.push('/reviews');
    } catch (e: unknown) {
      const msg = e instanceof Error ? e.message : 'Review action failed.';
      setError(msg);
    } finally {
      setReviewing(false);
    }
  }, [stemId, router]);

  const handleStartEditStem = useCallback(() => {
    if (!stem) return;
    setStemEditText(stem.stem_text);
    setIsEditingStem(true);
    setError('');
    setSuccessMessage('');
  }, [stem]);

  const handleCancelEditStem = useCallback(() => {
    setIsEditingStem(false);
    setStemEditText('');
  }, []);

  const handleSaveStemText = useCallback(async () => {
    const trimmed = stemEditText.trim();
    if (!trimmed) {
      setError('Stem text cannot be empty.');
      return;
    }
    if (trimmed === stem?.stem_text) {
      setIsEditingStem(false);
      return;
    }
    if (spans.length > 0) {
      const confirmed = confirm(
        'Modifying the stem text will reset all existing Event and Timeline annotations for this stem because text offsets change. Do you want to proceed?'
      );
      if (!confirmed) return;
    }

    setSavingStem(true);
    setError('');
    try {
      const res = await updateBatchStemText(stemId, trimmed);
      setStem(prev => prev ? { ...prev, stem_text: res.stem_text, word_count: res.word_count } : prev);
      setSpans([]);
      setMatrixData(null);
      setIsEditingStem(false);
      setSuccessMessage('Stem text updated successfully. Existing annotations were reset.');
      setTimeout(() => setSuccessMessage(''), 4000);
    } catch (e: unknown) {
      const msg = e instanceof Error ? e.message : 'Failed to update stem text.';
      setError(msg);
    } finally {
      setSavingStem(false);
    }
  }, [stemEditText, stem, spans.length, stemId]);

  const isReviewMode = searchParams?.get('mode') === 'review' || user?.role === 'reviewer';
  const isReadOnly = !isReviewMode && (stem?.status === 'pending-review' || stem?.status === 'done' || stem?.status === 'blacklisted');

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
      <main style={{ maxWidth: 1400, margin: '0 auto', padding: '32px 20px', fontFamily: 'system-ui, sans-serif' }}>
        {/* Reviewer Controls if in Review Mode */}
        {isReviewMode && (
          <ReviewControls
            stemId={stemId}
            batchId={batchId}
            annotatorUsername={stem.owner_username}
            status={stem.status}
            reviews={reviews}
            onReview={handleReview}
            submitting={reviewing}
          />
        )}

        {/* Annotator Feedback Banner when Re-evaluation is requested */}
        {!isReviewMode && stem.status === 're-evaluate' && stem.latest_review && (
          <div style={{
            background: '#fef3c7',
            border: '1px solid #fde68a',
            borderRadius: 10,
            padding: 16,
            marginBottom: 20,
            color: '#92400e',
          }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 6 }}>
              <strong style={{ fontSize: 14, display: 'flex', alignItems: 'center', gap: 6 }}>
                ⚠️ Reviewer Feedback (Re-evaluation Requested):
              </strong>
              <span style={{ fontSize: 12, color: '#b45309' }}>
                by {stem.latest_review.reviewer_username} · {new Date(stem.latest_review.created_at).toLocaleString()}
              </span>
            </div>
            <div style={{
              whiteSpace: 'pre-wrap',
              fontSize: 13,
              background: 'rgba(255,255,255,0.7)',
              padding: 12,
              borderRadius: 6,
              color: '#78350f',
              border: '1px solid rgba(217, 119, 6, 0.2)',
            }}>
              {stem.latest_review.comment}
            </div>
            <p style={{ margin: '8px 0 0', fontSize: 12, color: '#92400e' }}>
              Please update your Event/Time labels, Timeline positions, or Allen Matrix according to the guidance above, then click <strong>&ldquo;Resubmit for Review&rdquo;</strong>.
            </p>
          </div>
        )}

        {/* Status notice banners */}
        {!isReviewMode && stem.status === 'pending-review' && (
          <div style={{
            background: '#f3e8ff',
            border: '1px solid #e9d5ff',
            borderRadius: 8,
            padding: '12px 16px',
            marginBottom: 20,
            color: '#6b21a8',
            fontSize: 13,
            display: 'flex',
            alignItems: 'center',
            gap: 8,
          }}>
            <span style={{ fontSize: 16 }}>🕒</span>
            <div>
              <strong>Pending Review:</strong> This stem has been submitted for review. It is preserved and read-only until evaluated by a reviewer.
            </div>
          </div>
        )}

        {!isReviewMode && stem.status === 'done' && (
          <div style={{
            background: '#f0fdf4',
            border: '1px solid #bbf7d0',
            borderRadius: 8,
            padding: '12px 16px',
            marginBottom: 20,
            color: '#166534',
            fontSize: 13,
            display: 'flex',
            alignItems: 'center',
            gap: 8,
          }}>
            <span style={{ fontSize: 16 }}>✓</span>
            <div>
              <strong>Approved (Done):</strong> This annotation has been accepted by the reviewer.
            </div>
          </div>
        )}

        {!isReviewMode && stem.status === 'blacklisted' && (
          <div style={{
            background: '#fef2f2',
            border: '1px solid #fecaca',
            borderRadius: 8,
            padding: '12px 16px',
            marginBottom: 20,
            color: '#991b1b',
            fontSize: 13,
          }}>
            <strong>⊘ Blacklisted / Unannotable:</strong> Reason: {stem.blacklist_reason || 'Marked as unannotable.'}
          </div>
        )}

        <div style={{ display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between', marginBottom: 24 }}>
          <div>
            <button
              onClick={() => router.push(isReviewMode ? '/reviews' : `/batches/${batchId}`)}
              style={{ background: 'none', border: 'none', cursor: 'pointer', color: 'var(--text-muted)', fontSize: 13, padding: 0, marginBottom: 6 }}
            >
              {isReviewMode ? '← Back to Review Queue' : '← Back to Batch'}
            </button>
            <h1 style={{ fontSize: 18, fontWeight: 700, margin: 0 }}>
              Stem #{stem.stem_id} — Batch #{batchId}
            </h1>
            <p style={{ fontSize: 13, color: 'var(--text-muted)', margin: '2px 0 0' }}>
              Status: <strong>{stem.status.replace('_', ' ')}</strong>
            </p>
          </div>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 8, alignItems: 'flex-end' }}>
            <div style={{ display: 'flex', gap: 8 }}>
              <button
                onClick={() => setShowAnnotatorGuide(true)}
                style={{
                  padding: '8px 14px',
                  background: 'var(--surface-alt)',
                  border: '1px solid var(--border)',
                  borderRadius: 6,
                  cursor: 'pointer',
                  fontSize: 13,
                  fontWeight: 600,
                  color: '#2563eb',
                }}
              >
                📖 Methodology Guide
              </button>

              {!isReviewMode && !isReadOnly && (
                <button
                  onClick={handleSubmitForReview}
                  disabled={saving}
                  style={{
                    padding: '8px 16px',
                    background: stem.status === 're-evaluate' ? '#d97706' : '#15803d',
                    color: '#fff',
                    border: 'none',
                    borderRadius: 6,
                    cursor: saving ? 'not-allowed' : 'pointer',
                    fontWeight: 600,
                    fontSize: 13,
                  }}
                >
                  {saving ? 'Submitting…' : stem.status === 're-evaluate' ? 'Resubmit for Review →' : 'Submit for Review →'}
                </button>
              )}
            </div>

            {!isReadOnly && (
              <button
                onClick={handleLLMLabelAndTimeline}
                disabled={extractingBoth}
                style={{
                  padding: '8px 16px',
                  background: extractingBoth ? 'var(--text-disabled)' : '#2563eb',
                  color: '#fff',
                  border: 'none',
                  borderRadius: 6,
                  cursor: extractingBoth ? 'not-allowed' : 'pointer',
                  fontWeight: 600,
                  fontSize: 13,
                }}
              >
                {extractingBoth ? 'Processing…' : 'Use LLM to label events and detect timeline (recommended)'}
              </button>
            )}
          </div>
        </div>

        <MethodologyGuide isOpen={showAnnotatorGuide} onClose={() => setShowAnnotatorGuide(false)} />

        {successMessage && (
          <div style={{
            background: 'var(--success-bg)',
            border: '1px solid var(--success)',
            borderRadius: 6,
            padding: '8px 12px',
            marginBottom: 16,
            fontSize: 13,
            color: 'var(--success)',
            display: 'flex',
            justifyContent: 'space-between',
            alignItems: 'center',
          }}>
            <span>✓ {successMessage}</span>
            <button onClick={() => setSuccessMessage('')} style={{ marginLeft: 8, background: 'none', border: 'none', cursor: 'pointer', color: 'var(--text-disabled)' }}>×</button>
          </div>
        )}

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

        <div style={{
          background: 'var(--surface-alt)',
          border: '1px solid var(--border)',
          borderRadius: 8,
          padding: 16,
          marginBottom: 20,
          fontSize: 14,
          color: 'var(--text-primary)',
        }}>
          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 8 }}>
            <strong style={{ fontSize: 12, color: 'var(--text-muted)', letterSpacing: '0.05em' }}>
              STEM TEXT {stem.word_count ? `(${stem.word_count} words)` : ''}
            </strong>
            {!isReadOnly && !isEditingStem && (
              <button
                onClick={handleStartEditStem}
                style={{
                  background: 'none',
                  border: '1px solid var(--border)',
                  borderRadius: 4,
                  padding: '4px 10px',
                  cursor: 'pointer',
                  fontSize: 12,
                  fontWeight: 600,
                  color: '#2563eb',
                  display: 'flex',
                  alignItems: 'center',
                  gap: 4,
                }}
                title="Edit stem text"
              >
                ✏️ Edit Stem
              </button>
            )}
          </div>

          {isEditingStem ? (
            <div>
              <textarea
                value={stemEditText}
                onChange={e => setStemEditText(e.target.value)}
                disabled={savingStem}
                rows={5}
                style={{
                  width: '100%',
                  padding: 10,
                  borderRadius: 6,
                  border: '1px solid var(--border-input)',
                  fontFamily: 'inherit',
                  fontSize: 14,
                  lineHeight: 1.5,
                  background: 'var(--surface)',
                  color: 'var(--text-primary)',
                  boxSizing: 'border-box',
                }}
              />
              <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginTop: 6, fontSize: 12, color: 'var(--text-muted)' }}>
                <span>
                  {stemEditText.trim().length} chars · {stemEditText.trim() ? stemEditText.trim().split(/\s+/).length : 0} words
                </span>
                {spans.length > 0 && (
                  <span style={{ color: '#d97706', fontWeight: 600 }}>
                    ⚠️ Modifying text will reset {spans.length} existing annotation span{spans.length > 1 ? 's' : ''}.
                  </span>
                )}
              </div>
              <div style={{ display: 'flex', gap: 8, marginTop: 10, justifyContent: 'flex-end' }}>
                <button
                  onClick={handleCancelEditStem}
                  disabled={savingStem}
                  style={{
                    padding: '6px 12px',
                    borderRadius: 6,
                    border: '1px solid var(--border-input)',
                    background: 'var(--surface)',
                    cursor: savingStem ? 'not-allowed' : 'pointer',
                    fontSize: 13,
                    color: 'var(--text-primary)',
                  }}
                >
                  Cancel
                </button>
                <button
                  onClick={handleSaveStemText}
                  disabled={savingStem}
                  style={{
                    padding: '6px 14px',
                    borderRadius: 6,
                    border: 'none',
                    background: '#2563eb',
                    color: '#fff',
                    cursor: savingStem ? 'not-allowed' : 'pointer',
                    fontSize: 13,
                    fontWeight: 600,
                  }}
                >
                  {savingStem ? 'Saving…' : 'Save Changes'}
                </button>
              </div>
            </div>
          ) : (
            <div style={{ whiteSpace: 'pre-wrap', lineHeight: 1.6 }}>{stem.stem_text}</div>
          )}
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
                  readOnly={isReadOnly}
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
                {!isReadOnly && (
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
                )}
              </div>
            </div>
            <div style={{ display: 'flex', gap: 24, alignItems: 'flex-start' }}>
              <div style={{ flex: '1 1 65%', minWidth: 0 }}>
                {matrixData ? (
                  <AllenMatrix
                    matrixData={matrixData}
                    onOverride={handleOverride}
                    onSave={handleSaveMatrix}
                    readOnly={isReadOnly}
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
