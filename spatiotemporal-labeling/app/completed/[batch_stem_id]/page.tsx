'use client';

import { useEffect, useState } from 'react';
import { useParams, useRouter } from 'next/navigation';
import { useAuth } from '@/lib/AuthContext';
import { getBatchStem, listBatchSpans, getBatchMatrix, exportBatchStemJson, getStemReviews } from '@/lib/api';
import { BatchStemDetail, BatchSpanOut, MatrixData, StemReview } from '@/lib/types';
import LabeledText from '@/components/LabeledText';
import Timeline from '@/components/Timeline';
import AllenMatrix from '@/components/AllenMatrix';
import { colorForSpan } from '@/lib/spanColors';

export default function CompletedStemViewPage() {
  const params = useParams<{ batch_stem_id: string }>();
  const batchStemId = parseInt(params.batch_stem_id);
  const router = useRouter();
  const { user, loading: authLoading } = useAuth();

  const [stem, setStem] = useState<BatchStemDetail | null>(null);
  const [spans, setSpans] = useState<BatchSpanOut[]>([]);
  const [matrixData, setMatrixData] = useState<MatrixData | null>(null);
  const [reviews, setReviews] = useState<StemReview[]>([]);
  const [loading, setLoading] = useState<boolean>(true);
  const [error, setError] = useState<string>('');
  const [activeTab, setActiveTab] = useState<'overview' | 'timeline' | 'matrix'>('overview');

  useEffect(() => {
    if (!authLoading && !user) {
      router.replace('/login');
      return;
    }
    if (!batchStemId) return;

    let cancelled = false;
    const load = async () => {
      setLoading(true);
      setError('');
      try {
        const [stemData, spanList, matData, revList] = await Promise.all([
          getBatchStem(batchStemId),
          listBatchSpans(batchStemId),
          getBatchMatrix(batchStemId).catch(() => null),
          getStemReviews(batchStemId).catch(() => []),
        ]);
        if (cancelled) return;
        setStem(stemData);
        setSpans(spanList);
        setMatrixData(matData);
        setReviews(revList);
      } catch (e: unknown) {
        if (cancelled) return;
        setError(e instanceof Error ? e.message : 'Failed to load completed stem details.');
      } finally {
        if (!cancelled) setLoading(false);
      }
    };
    load();
    return () => { cancelled = true; };
  }, [batchStemId, user, authLoading, router]);

  if (authLoading) {
    return <div style={{ minHeight: '100vh', background: 'var(--background-page)' }} />;
  }

  if (loading) {
    return (
      <main style={{ maxWidth: 1000, margin: '60px auto', padding: 20, textAlign: 'center', color: 'var(--text-muted)', fontFamily: 'system-ui' }}>
        Loading completed stem annotation…
      </main>
    );
  }

  if (error || !stem) {
    return (
      <main style={{ maxWidth: 700, margin: '60px auto', padding: 24, textAlign: 'center', fontFamily: 'system-ui' }}>
        <div style={{ color: 'var(--error)', fontSize: 16, fontWeight: 600, marginBottom: 16 }}>
          {error || 'Stem annotation not found.'}
        </div>
        <button onClick={() => router.push('/completed')} style={btnStyle('var(--surface)', 'var(--text-primary)')}>
          ← Back to Completed Stems
        </button>
      </main>
    );
  }

  const eventSpans = spans.filter(s => s.label_type === 'Event');
  const timeSpans = spans.filter(s => s.label_type === 'Time');

  return (
    <main style={{ maxWidth: 1100, margin: '0 auto', padding: '28px 20px', fontFamily: 'system-ui, sans-serif' }}>
      {/* Navigation Breadcrumb */}
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 16, flexWrap: 'wrap', gap: 8 }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 8, fontSize: 13, color: 'var(--text-muted)' }}>
          <button
            onClick={() => router.push('/completed')}
            style={{ background: 'none', border: 'none', cursor: 'pointer', color: '#2563eb', padding: 0, fontWeight: 500 }}
          >
            ← Completed Stems
          </button>
          <span>/</span>
          <button
            onClick={() => router.push('/')}
            style={{ background: 'none', border: 'none', cursor: 'pointer', color: 'var(--text-muted)', padding: 0 }}
          >
            Dashboard
          </button>
          <span>/</span>
          <span>Stem #{stem.stem_id}</span>
        </div>

        <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
          <a
            href={exportBatchStemJson(batchStemId)}
            download
            style={{ ...btnStyle('var(--surface-alt)', 'var(--text-primary)'), textDecoration: 'none', fontSize: 12, padding: '6px 12px' }}
          >
            ⬇ Export JSON
          </a>
        </div>
      </div>

      {/* Read-Only Status Banner */}
      <div style={{
        background: '#f0fdf4',
        border: '1px solid #bbf7d0',
        borderRadius: 8,
        padding: '12px 18px',
        marginBottom: 20,
        color: '#166534',
        fontSize: 13,
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'space-between',
        flexWrap: 'wrap',
        gap: 12,
      }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
          <span style={{ fontSize: 18, color: '#16a34a' }}>✓</span>
          <div>
            <strong>Approved Annotation (Read-Only Mode)</strong>
            <div style={{ fontSize: 12, color: '#15803d', marginTop: 2 }}>
              This stem was completed by <strong>{stem.owner_username}</strong>
              {stem.reviewer_username ? ` and approved by reviewer ${stem.reviewer_username}` : ''}. All edits are locked.
            </div>
          </div>
        </div>

        <span style={{
          padding: '3px 10px',
          background: '#dcfce7',
          color: '#15803d',
          borderRadius: 16,
          fontWeight: 700,
          fontSize: 11,
          letterSpacing: '0.04em',
          textTransform: 'uppercase',
        }}>
          Finalized
        </span>
      </div>

      {/* Stem Metadata Header */}
      <div style={{
        background: 'var(--surface)',
        border: '1px solid var(--border)',
        borderRadius: 10,
        padding: '18px 20px',
        marginBottom: 20,
        display: 'grid',
        gridTemplateColumns: 'repeat(auto-fit, minmax(200px, 1fr))',
        gap: 16,
      }}>
        <div>
          <div style={{ fontSize: 11, color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: '0.04em' }}>Stem Information</div>
          <div style={{ fontSize: 15, fontWeight: 700, marginTop: 4 }}>Stem #{stem.stem_id}</div>
          <div style={{ fontSize: 12, color: 'var(--text-muted)', marginTop: 2 }}>{stem.word_count} words · Batch: {stem.batch_name}</div>
        </div>

        <div>
          <div style={{ fontSize: 11, color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: '0.04em' }}>Annotated By</div>
          <div style={{ fontSize: 14, fontWeight: 600, marginTop: 4 }}>{stem.owner_username}</div>
          <div style={{ fontSize: 12, color: 'var(--text-muted)', marginTop: 2 }}>
            {stem.completed_at ? new Date(stem.completed_at).toLocaleString() : '—'}
          </div>
        </div>

        <div>
          <div style={{ fontSize: 11, color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: '0.04em' }}>Reviewed &amp; Approved By</div>
          <div style={{ fontSize: 14, fontWeight: 600, marginTop: 4, color: '#16a34a' }}>
            ✓ {stem.reviewer_username || 'Reviewer'}
          </div>
          <div style={{ fontSize: 12, color: 'var(--text-muted)', marginTop: 2 }}>
            {stem.reviewed_at ? new Date(stem.reviewed_at).toLocaleString() : '—'}
          </div>
        </div>

        <div>
          <div style={{ fontSize: 11, color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: '0.04em' }}>Extracted Entities</div>
          <div style={{ fontSize: 14, fontWeight: 600, marginTop: 4 }}>
            {eventSpans.length} Events · {timeSpans.length} Times
          </div>
          <div style={{ fontSize: 12, color: 'var(--text-muted)', marginTop: 2 }}>
            {matrixData ? `${eventSpans.length}×${eventSpans.length} relation matrix` : 'No matrix'}
          </div>
        </div>
      </div>

      {/* Reviewer Comment / Feedback note if present */}
      {stem.latest_review?.comment && (
        <div style={{
          background: 'var(--surface-alt)',
          border: '1px solid var(--border)',
          borderRadius: 8,
          padding: '12px 16px',
          marginBottom: 20,
          fontSize: 13,
        }}>
          <strong style={{ color: '#8b5cf6' }}>Reviewer Note:</strong>
          <span style={{ marginLeft: 8, color: 'var(--text-primary)', fontStyle: 'italic' }}>
            &ldquo;{stem.latest_review.comment}&rdquo;
          </span>
          <span style={{ fontSize: 11, color: 'var(--text-muted)', marginLeft: 8 }}>
            — {stem.latest_review.reviewer_username}
          </span>
        </div>
      )}

      {/* View Tabs */}
      <div style={{ display: 'flex', gap: 6, borderBottom: '1px solid var(--border)', marginBottom: 20 }}>
        <button
          onClick={() => setActiveTab('overview')}
          style={{
            ...tabBtnStyle(activeTab === 'overview'),
          }}
        >
          📄 Labeled Passage &amp; Spans ({spans.length})
        </button>
        <button
          onClick={() => setActiveTab('timeline')}
          style={{
            ...tabBtnStyle(activeTab === 'timeline'),
          }}
        >
          ⏱️ Visual Timeline
        </button>
        <button
          onClick={() => setActiveTab('matrix')}
          style={{
            ...tabBtnStyle(activeTab === 'matrix'),
          }}
        >
          📊 Allen Relation Matrix
        </button>
      </div>

      {/* Tab 1: Overview & Labeled Text */}
      {activeTab === 'overview' && (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 20 }}>
          {/* Labeled Stem Card */}
          <div style={{
            background: 'var(--surface)',
            border: '1px solid var(--border)',
            borderRadius: 10,
            padding: 20,
          }}>
            <h3 style={{ fontSize: 14, fontWeight: 700, margin: '0 0 12px', color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: '0.04em' }}>
              Stem Passage with Identified Spans
            </h3>
            <div style={{ fontSize: 15, lineHeight: 1.8 }}>
              <LabeledText stemText={stem.stem_text} spans={spans} interactive={false} />
            </div>
          </div>

          {/* Spans Summary Table */}
          <div style={{
            background: 'var(--surface)',
            border: '1px solid var(--border)',
            borderRadius: 10,
            overflow: 'hidden',
          }}>
            <div style={{ padding: '12px 16px', background: 'var(--surface-alt)', borderBottom: '1px solid var(--border)', fontWeight: 600, fontSize: 13 }}>
              Annotated Spans ({spans.length})
            </div>
            <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 13 }}>
              <thead>
                <tr style={{ background: 'var(--surface)', borderBottom: '1px solid var(--border)' }}>
                  <th style={th}>Label</th>
                  <th style={th}>Type</th>
                  <th style={{ ...th, flex: 1 }}>Span Text</th>
                  <th style={th}>Char Offset</th>
                  <th style={th}>Timeline Range</th>
                </tr>
              </thead>
              <tbody>
                {spans.map(s => {
                  const colors = colorForSpan(s);
                  return (
                    <tr key={s.id} style={{ borderBottom: '1px solid var(--border)' }}>
                      <td style={td}>
                        <span style={{
                          padding: '2px 8px',
                          borderRadius: 4,
                          fontSize: 12,
                          fontWeight: 700,
                          background: colors.bg,
                          color: colors.text,
                        }}>
                          {s.seq_label}
                        </span>
                      </td>
                      <td style={{ ...td, color: 'var(--text-muted)' }}>{s.label_type}</td>
                      <td style={{ ...td, fontWeight: 500 }}>&ldquo;{s.span_text}&rdquo;</td>
                      <td style={{ ...td, color: 'var(--text-muted)', fontFamily: 'monospace' }}>
                        [{s.char_start} – {s.char_end}]
                      </td>
                      <td style={{ ...td, color: 'var(--text-muted)', fontFamily: 'monospace' }}>
                        [{s.tl_start} – {s.tl_end}]
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {/* Tab 2: Visual Timeline */}
      {activeTab === 'timeline' && (
        <div style={{ display: 'flex', gap: 20, alignItems: 'flex-start', flexWrap: 'wrap' }}>
          <div style={{
            flex: '1 1 60%',
            minWidth: 320,
            background: 'var(--surface)',
            border: '1px solid var(--border)',
            borderRadius: 10,
            padding: 20,
          }}>
            <h3 style={{ fontSize: 14, fontWeight: 700, margin: '0 0 16px', color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: '0.04em' }}>
              Read-Only Event Timeline [0–100 Scale]
            </h3>
            {eventSpans.length === 0 ? (
              <p style={{ color: 'var(--text-muted)', fontSize: 13 }}>No event spans to display on the timeline.</p>
            ) : (
              <Timeline spans={eventSpans} readOnly={true} />
            )}
          </div>

          <div style={{
            flex: '1 1 35%',
            minWidth: 280,
            background: 'var(--surface-alt)',
            border: '1px solid var(--border)',
            borderRadius: 10,
            padding: 16,
            maxHeight: '75vh',
            overflowY: 'auto',
          }}>
            <div style={{ fontSize: 12, fontWeight: 700, color: 'var(--text-muted)', marginBottom: 10, textTransform: 'uppercase', letterSpacing: '0.04em' }}>
              Reference Passage
            </div>
            <LabeledText stemText={stem.stem_text} spans={spans} interactive={false} />
          </div>
        </div>
      )}

      {/* Tab 3: Allen's Relation Matrix */}
      {activeTab === 'matrix' && (
        <div style={{ display: 'flex', gap: 20, alignItems: 'flex-start', flexWrap: 'wrap' }}>
          <div style={{
            flex: '1 1 65%',
            minWidth: 320,
            background: 'var(--surface)',
            border: '1px solid var(--border)',
            borderRadius: 10,
            padding: 20,
          }}>
            <h3 style={{ fontSize: 14, fontWeight: 700, margin: '0 0 16px', color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: '0.04em' }}>
              Allen Interval Algebra Pairwise Matrix
            </h3>
            {matrixData ? (
              <AllenMatrix matrixData={matrixData} readOnly={true} />
            ) : (
              <p style={{ color: 'var(--text-muted)', fontSize: 13 }}>No relation matrix data available for this stem.</p>
            )}
          </div>

          <div style={{
            flex: '1 1 30%',
            minWidth: 260,
            background: 'var(--surface-alt)',
            border: '1px solid var(--border)',
            borderRadius: 10,
            padding: 16,
            maxHeight: '75vh',
            overflowY: 'auto',
          }}>
            <div style={{ fontSize: 12, fontWeight: 700, color: 'var(--text-muted)', marginBottom: 10, textTransform: 'uppercase', letterSpacing: '0.04em' }}>
              Reference Passage
            </div>
            <LabeledText stemText={stem.stem_text} spans={spans} interactive={false} />
          </div>
        </div>
      )}
    </main>
  );
}

function tabBtnStyle(active: boolean): React.CSSProperties {
  return {
    padding: '10px 18px',
    background: 'none',
    border: 'none',
    borderBottom: active ? '2px solid #2563eb' : '2px solid transparent',
    color: active ? '#2563eb' : 'var(--text-muted)',
    fontWeight: active ? 700 : 500,
    fontSize: 14,
    cursor: 'pointer',
    transition: 'all 0.15s ease',
  };
}

const th: React.CSSProperties = {
  padding: '10px 14px',
  textAlign: 'left',
  fontWeight: 600,
  fontSize: 12,
  color: 'var(--text-muted)',
};

const td: React.CSSProperties = {
  padding: '12px 14px',
  verticalAlign: 'middle',
};

function btnStyle(bg: string, color: string): React.CSSProperties {
  return {
    padding: '7px 14px',
    background: bg,
    color,
    border: '1px solid var(--border-input)',
    borderRadius: 6,
    cursor: 'pointer',
    fontWeight: 500,
    fontSize: 13,
    display: 'inline-flex',
    alignItems: 'center',
    gap: 4,
  };
}
