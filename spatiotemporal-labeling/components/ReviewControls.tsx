'use client';

import React, { useState } from 'react';
import { StemReview } from '@/lib/types';
import MethodologyGuide from './MethodologyGuide';

interface ReviewControlsProps {
  stemId: number;
  batchId: number;
  annotatorUsername?: string;
  status: string;
  reviews?: StemReview[];
  onReview: (decision: 'accept' | 're-evaluate' | 'blacklist' | 'release_to_pool', comment?: string) => Promise<void>;
  submitting: boolean;
}

const PRESET_FEEDBACK_TAGS = [
  'Action incorrectly marked as span (lasting consequence ≠ duration)',
  'State missing span duration (needs explicit durational bounds)',
  'Compound sentence (action + later reveal) merged into one span',
  'Deep-past background fact stretched to present without explicit cues',
  'Timeline order does not match story time chronology',
  'Allen relation matrix has transitivity violations',
];

export default function ReviewControls({
  stemId,
  batchId,
  annotatorUsername,
  status,
  reviews = [],
  onReview,
  submitting,
}: ReviewControlsProps) {
  const [showMethodology, setShowMethodology] = useState(false);
  const [showReevalModal, setShowReevalModal] = useState(false);
  const [showReleaseModal, setShowReleaseModal] = useState(false);
  const [showBlacklistModal, setShowBlacklistModal] = useState(false);
  const [showHistory, setShowHistory] = useState(false);

  const [comment, setComment] = useState('');
  const [releaseReason, setReleaseReason] = useState('');
  const [blacklistReason, setBlacklistReason] = useState('');
  const [selectedTags, setSelectedTags] = useState<string[]>([]);

  const toggleTag = (tag: string) => {
    setSelectedTags(prev => {
      const next = prev.includes(tag) ? prev.filter(t => t !== tag) : [...prev, tag];
      return next;
    });
  };

  const handleAccept = async () => {
    if (!confirm('Accept this annotation? It will be marked as Done.')) return;
    await onReview('accept');
  };

  const handleReevaluateSubmit = async () => {
    let fullComment = comment.trim();
    if (selectedTags.length > 0) {
      const tagsBlock = `Methodology issues noted:\n• ` + selectedTags.join('\n• ');
      fullComment = fullComment ? `${tagsBlock}\n\nNotes: ${fullComment}` : tagsBlock;
    }
    if (!fullComment) {
      alert('Please provide a comment or select at least one methodology issue tag.');
      return;
    }
    await onReview('re-evaluate', fullComment);
    setShowReevalModal(false);
    setComment('');
    setSelectedTags([]);
  };

  const handleReleaseSubmit = async () => {
    const reason = releaseReason.trim();
    if (!reason) {
      alert('Please provide a reason why this stem is being released for re-annotation by other annotators.');
      return;
    }
    if (!confirm('Clear all existing annotations for this stem and release it to the public pool so other annotators can try?')) return;
    await onReview('release_to_pool', reason);
    setShowReleaseModal(false);
    setReleaseReason('');
  };

  const handleBlacklistSubmit = async () => {
    const reason = blacklistReason.trim();
    if (!reason) {
      alert('Please specify why this stem is unannotable or should be blacklisted.');
      return;
    }
    if (!confirm('Blacklist this stem? It will be permanently removed from all batch booking pools.')) return;
    await onReview('blacklist', reason);
    setShowBlacklistModal(false);
    setBlacklistReason('');
  };

  return (
    <>
      <div style={{
        background: 'var(--surface)',
        border: '2px solid #8b5cf6',
        borderRadius: 10,
        padding: '16px 20px',
        marginBottom: 20,
        boxShadow: '0 4px 6px -1px rgba(139, 92, 246, 0.1)',
      }}>
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', flexWrap: 'wrap', gap: 12 }}>
          <div>
            <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
              <span style={{
                background: '#8b5cf6',
                color: '#fff',
                fontSize: 11,
                fontWeight: 700,
                textTransform: 'uppercase',
                padding: '2px 8px',
                borderRadius: 4,
                letterSpacing: '0.05em',
              }}>
                Review Mode
              </span>
              <h2 style={{ fontSize: 16, fontWeight: 700, margin: 0, color: 'var(--text-primary)' }}>
                Reviewing Stem #{stemId} · Batch #{batchId}
              </h2>
            </div>
            <p style={{ fontSize: 13, color: 'var(--text-muted)', margin: '4px 0 0' }}>
              Annotated by <strong>{annotatorUsername || 'Annotator'}</strong> · Current status: <strong>{status.replace('_', ' ')}</strong>
            </p>
          </div>

          <div style={{ display: 'flex', gap: 8, alignItems: 'center', flexWrap: 'wrap' }}>
            <button
              onClick={() => setShowMethodology(true)}
              style={{
                padding: '7px 12px',
                background: 'var(--surface-alt)',
                border: '1px solid var(--border)',
                borderRadius: 6,
                cursor: 'pointer',
                fontSize: 13,
                fontWeight: 600,
                color: '#2563eb',
                display: 'flex',
                alignItems: 'center',
                gap: 4,
              }}
            >
              📖 Methodology Guide
            </button>

            {reviews.length > 0 && (
              <button
                onClick={() => setShowHistory(true)}
                style={{
                  padding: '7px 12px',
                  background: 'var(--surface-alt)',
                  border: '1px solid var(--border)',
                  borderRadius: 6,
                  cursor: 'pointer',
                  fontSize: 13,
                  fontWeight: 500,
                  color: 'var(--text-primary)',
                }}
              >
                History ({reviews.length})
              </button>
            )}

            <button
              onClick={handleAccept}
              disabled={submitting}
              style={{
                padding: '7px 16px',
                background: '#15803d',
                color: '#fff',
                border: 'none',
                borderRadius: 6,
                cursor: submitting ? 'not-allowed' : 'pointer',
                fontWeight: 600,
                fontSize: 13,
              }}
            >
              ✓ Accept (Done)
            </button>

            <button
              onClick={() => setShowReevalModal(true)}
              disabled={submitting}
              style={{
                padding: '7px 14px',
                background: '#d97706',
                color: '#fff',
                border: 'none',
                borderRadius: 6,
                cursor: submitting ? 'not-allowed' : 'pointer',
                fontWeight: 600,
                fontSize: 13,
              }}
            >
              ↺ Request Re-evaluate
            </button>

            <button
              onClick={() => setShowReleaseModal(true)}
              disabled={submitting}
              style={{
                padding: '7px 14px',
                background: '#4b5563',
                color: '#fff',
                border: 'none',
                borderRadius: 6,
                cursor: submitting ? 'not-allowed' : 'pointer',
                fontWeight: 600,
                fontSize: 13,
                display: 'flex',
                alignItems: 'center',
                gap: 4,
              }}
              title="Clear failed annotations and release stem to the public pool for other annotators to try"
            >
              ↩ Release to Pool (Re-annotate)
            </button>

            <button
              onClick={() => setShowBlacklistModal(true)}
              disabled={submitting}
              style={{
                padding: '7px 12px',
                background: '#dc2626',
                color: '#fff',
                border: 'none',
                borderRadius: 6,
                cursor: submitting ? 'not-allowed' : 'pointer',
                fontWeight: 600,
                fontSize: 13,
              }}
            >
              ⊘ Blacklist
            </button>
          </div>
        </div>
      </div>

      {/* Methodology Guide Modal */}
      <MethodologyGuide isOpen={showMethodology} onClose={() => setShowMethodology(false)} />

      {/* Re-evaluate Modal */}
      {showReevalModal && (
        <div style={{
          position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.6)', display: 'flex', alignItems: 'center', justifyContent: 'center', zIndex: 1000,
        }}>
          <div style={{
            background: 'var(--surface)',
            border: '1px solid var(--border)',
            borderRadius: 12,
            padding: 24,
            maxWidth: 580,
            width: '90%',
            maxHeight: '90vh',
            overflowY: 'auto',
          }}>
            <h3 style={{ fontSize: 16, fontWeight: 700, margin: '0 0 8px', color: 'var(--text-primary)' }}>
              Request Re-evaluation
            </h3>
            <p style={{ fontSize: 13, color: 'var(--text-muted)', margin: '0 0 16px' }}>
              Provide feedback for the annotator based on the timeline methodology.
            </p>

            <div style={{ marginBottom: 16 }}>
              <label style={{ fontSize: 12, fontWeight: 600, color: 'var(--text-muted)', display: 'block', marginBottom: 6 }}>
                COMMON METHODOLOGY ISSUES (click to tag):
              </label>
              <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6 }}>
                {PRESET_FEEDBACK_TAGS.map(t => {
                  const active = selectedTags.includes(t);
                  return (
                    <button
                      key={t}
                      type="button"
                      onClick={() => toggleTag(t)}
                      style={{
                        padding: '4px 10px',
                        borderRadius: 16,
                        border: active ? '1px solid #2563eb' : '1px solid var(--border)',
                        background: active ? '#dbeafe' : 'var(--surface-alt)',
                        color: active ? '#1e40af' : 'var(--text-primary)',
                        fontSize: 12,
                        cursor: 'pointer',
                        textAlign: 'left',
                      }}
                    >
                      {active ? '✓ ' : '+ '}{t}
                    </button>
                  );
                })}
              </div>
            </div>

            <div style={{ marginBottom: 20 }}>
              <label style={{ fontSize: 12, fontWeight: 600, color: 'var(--text-muted)', display: 'block', marginBottom: 6 }}>
                DETAILED COMMENTS / GUIDANCE:
              </label>
              <textarea
                value={comment}
                onChange={e => setComment(e.target.value)}
                placeholder="Explain what needs to be changed (e.g., E2 'moved away' should be a Point at t=15, not a Span to t=100)..."
                rows={4}
                style={{
                  width: '100%',
                  padding: 10,
                  border: '1px solid var(--border-input)',
                  borderRadius: 6,
                  fontSize: 13,
                  fontFamily: 'inherit',
                  boxSizing: 'border-box',
                  background: 'var(--surface)',
                  color: 'var(--text-primary)',
                }}
              />
            </div>

            <div style={{ display: 'flex', gap: 8, justifyContent: 'flex-end' }}>
              <button
                onClick={() => { setShowReevalModal(false); setComment(''); setSelectedTags([]); }}
                style={{
                  padding: '7px 14px',
                  background: 'var(--surface)',
                  border: '1px solid var(--border)',
                  borderRadius: 6,
                  cursor: 'pointer',
                  fontSize: 13,
                }}
              >
                Cancel
              </button>
              <button
                onClick={handleReevaluateSubmit}
                disabled={submitting}
                style={{
                  padding: '7px 18px',
                  background: '#d97706',
                  color: '#fff',
                  border: 'none',
                  borderRadius: 6,
                  cursor: submitting ? 'not-allowed' : 'pointer',
                  fontWeight: 600,
                  fontSize: 13,
                }}
              >
                {submitting ? 'Submitting…' : 'Send Feedback for Re-evaluation'}
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Blacklist Modal */}
      {showBlacklistModal && (
        <div style={{
          position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.6)', display: 'flex', alignItems: 'center', justifyContent: 'center', zIndex: 1000,
        }}>
          <div style={{
            background: 'var(--surface)',
            border: '1px solid var(--border)',
            borderRadius: 12,
            padding: 24,
            maxWidth: 480,
            width: '90%',
          }}>
            <h3 style={{ fontSize: 16, fontWeight: 700, margin: '0 0 8px', color: '#dc2626' }}>
              Mark Stem as Bad / Unannotable
            </h3>
            <p style={{ fontSize: 13, color: 'var(--text-muted)', margin: '0 0 16px' }}>
              This will blacklist Stem #{stemId} and exclude it permanently from all future batches and pools.
            </p>

            <div style={{ marginBottom: 20 }}>
              <label style={{ fontSize: 12, fontWeight: 600, color: 'var(--text-muted)', display: 'block', marginBottom: 6 }}>
                REASON FOR BLACKLISTING:
              </label>
              <textarea
                value={blacklistReason}
                onChange={e => setBlacklistReason(e.target.value)}
                placeholder="Reason (e.g. Corrupted text, contains no temporal narrative events, OCR artifact)..."
                rows={3}
                style={{
                  width: '100%',
                  padding: 10,
                  border: '1px solid var(--border-input)',
                  borderRadius: 6,
                  fontSize: 13,
                  fontFamily: 'inherit',
                  boxSizing: 'border-box',
                  background: 'var(--surface)',
                  color: 'var(--text-primary)',
                }}
              />
            </div>

            <div style={{ display: 'flex', gap: 8, justifyContent: 'flex-end' }}>
              <button
                onClick={() => { setShowBlacklistModal(false); setBlacklistReason(''); }}
                style={{
                  padding: '7px 14px',
                  background: 'var(--surface)',
                  border: '1px solid var(--border)',
                  borderRadius: 6,
                  cursor: 'pointer',
                  fontSize: 13,
                }}
              >
                Cancel
              </button>
              <button
                onClick={handleBlacklistSubmit}
                disabled={submitting}
                style={{
                  padding: '7px 18px',
                  background: '#dc2626',
                  color: '#fff',
                  border: 'none',
                  borderRadius: 6,
                  cursor: submitting ? 'not-allowed' : 'pointer',
                  fontWeight: 600,
                  fontSize: 13,
                }}
              >
                {submitting ? 'Processing…' : 'Confirm Blacklist'}
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Release to Pool Modal */}
      {showReleaseModal && (
        <div style={{
          position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.6)', display: 'flex', alignItems: 'center', justifyContent: 'center', zIndex: 1000,
        }}>
          <div style={{
            background: 'var(--surface)',
            border: '1px solid var(--border)',
            borderRadius: 12,
            padding: 24,
            maxWidth: 520,
            width: '90%',
          }}>
            <h3 style={{ fontSize: 16, fontWeight: 700, margin: '0 0 8px', color: '#b45309' }}>
              Release Stem to Pool (Re-annotate)
            </h3>
            <p style={{ fontSize: 13, color: 'var(--text-muted)', margin: '0 0 12px' }}>
              If the current annotator failed to properly annotate this stem, you can release it back to the public pool.
            </p>
            <div style={{
              background: '#fef3c7',
              border: '1px solid #fde68a',
              borderRadius: 6,
              padding: '10px 12px',
              marginBottom: 16,
              fontSize: 12,
              color: '#92400e',
            }}>
              <strong>⚠️ Warning:</strong> This will delete all existing spans, timeline placements, and matrix relations for this stem. It will become immediately available in the public pool for other annotators to try.
            </div>

            <label style={{ fontSize: 12, fontWeight: 600, color: 'var(--text-muted)', display: 'block', marginBottom: 6 }}>
              REASON / FEEDBACK (Required):
            </label>
            <textarea
              value={releaseReason}
              onChange={e => setReleaseReason(e.target.value)}
              placeholder="Explain why the current annotation failed and what new annotators should focus on..."
              rows={3}
              style={{
                width: '100%',
                padding: '8px 12px',
                border: '1px solid var(--border-input)',
                borderRadius: 6,
                fontSize: 13,
                fontFamily: 'inherit',
                boxSizing: 'border-box',
                marginBottom: 16,
                resize: 'vertical',
              }}
            />

            <div style={{ display: 'flex', gap: 8, justifyContent: 'flex-end' }}>
              <button
                onClick={() => setShowReleaseModal(false)}
                disabled={submitting}
                style={{
                  padding: '7px 14px',
                  background: 'var(--surface-alt)',
                  border: '1px solid var(--border)',
                  borderRadius: 6,
                  cursor: 'pointer',
                  fontSize: 13,
                }}
              >
                Cancel
              </button>
              <button
                onClick={handleReleaseSubmit}
                disabled={submitting}
                style={{
                  padding: '7px 18px',
                  background: '#d97706',
                  color: '#fff',
                  border: 'none',
                  borderRadius: 6,
                  cursor: submitting ? 'not-allowed' : 'pointer',
                  fontWeight: 600,
                  fontSize: 13,
                }}
              >
                {submitting ? 'Releasing…' : 'Confirm & Release to Pool'}
              </button>
            </div>
          </div>
        </div>
      )}

      {/* History Modal */}
      {showHistory && (
        <div style={{
          position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.6)', display: 'flex', alignItems: 'center', justifyContent: 'center', zIndex: 1000,
        }}>
          <div style={{
            background: 'var(--surface)',
            border: '1px solid var(--border)',
            borderRadius: 12,
            padding: 24,
            maxWidth: 580,
            width: '90%',
            maxHeight: '80vh',
            overflowY: 'auto',
          }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 16 }}>
              <h3 style={{ fontSize: 16, fontWeight: 700, margin: 0 }}>Review History</h3>
              <button onClick={() => setShowHistory(false)} style={{ background: 'none', border: 'none', fontSize: 20, cursor: 'pointer' }}>×</button>
            </div>
            <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
              {reviews.map((r, i) => (
                <div key={r.id || i} style={{
                  padding: 12,
                  background: 'var(--surface-alt)',
                  border: '1px solid var(--border)',
                  borderRadius: 8,
                  fontSize: 13,
                }}>
                  <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 6 }}>
                    <span style={{
                      fontWeight: 700,
                      color: r.decision === 'accept' ? '#15803d' : r.decision === 'blacklist' ? '#dc2626' : r.decision === 'release_to_pool' ? '#4b5563' : '#d97706',
                      textTransform: 'uppercase',
                      fontSize: 12,
                    }}>
                      {r.decision.replace('_', ' ')}
                    </span>
                    <span style={{ fontSize: 11, color: 'var(--text-muted)' }}>
                      by {r.reviewer_username} · {new Date(r.created_at).toLocaleString()}
                    </span>
                  </div>
                  {r.comment && (
                    <div style={{ whiteSpace: 'pre-wrap', color: 'var(--text-primary)', marginTop: 4 }}>
                      {r.comment}
                    </div>
                  )}
                </div>
              ))}
            </div>
          </div>
        </div>
      )}
    </>
  );
}
