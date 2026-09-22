'use client';

import React, { useState } from 'react';

interface MethodologyGuideProps {
  isOpen: boolean;
  onClose: () => void;
}

export default function MethodologyGuide({ isOpen, onClose }: MethodologyGuideProps) {
  const [tab, setTab] = useState<'rules' | 'checklist' | 'examples' | 'pitfalls'>('rules');

  if (!isOpen) return null;

  return (
    <div style={{
      position: 'fixed',
      inset: 0,
      background: 'rgba(0,0,0,0.6)',
      display: 'flex',
      alignItems: 'center',
      justifyContent: 'center',
      zIndex: 1000,
      backdropFilter: 'blur(2px)',
    }}>
      <div style={{
        background: 'var(--surface)',
        border: '1px solid var(--border)',
        borderRadius: 12,
        width: '90%',
        maxWidth: 860,
        maxHeight: '90vh',
        display: 'flex',
        flexDirection: 'column',
        boxShadow: '0 20px 25px -5px rgba(0, 0, 0, 0.3), 0 10px 10px -5px rgba(0, 0, 0, 0.2)',
        overflow: 'hidden',
      }}>
        {/* Header */}
        <div style={{
          padding: '16px 24px',
          borderBottom: '1px solid var(--border)',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
          background: 'var(--surface-alt)',
        }}>
          <div>
            <h2 style={{ fontSize: 17, fontWeight: 700, margin: 0, color: 'var(--text-primary)' }}>
              Event Timeline Sequencing Methodology
            </h2>
            <p style={{ fontSize: 12, color: 'var(--text-muted)', margin: '2px 0 0' }}>
              Point vs. Span: Consistent Rules for Narrative Events on a Timeline
            </p>
          </div>
          <button
            onClick={onClose}
            style={{
              background: 'none',
              border: 'none',
              fontSize: 22,
              cursor: 'pointer',
              color: 'var(--text-muted)',
              lineHeight: 1,
              padding: 4,
            }}
          >
            ×
          </button>
        </div>

        {/* Navigation Tabs */}
        <div style={{
          display: 'flex',
          borderBottom: '1px solid var(--border)',
          background: 'var(--surface)',
          padding: '0 24px',
        }}>
          {[
            { id: 'rules', label: '1. The Core Rule' },
            { id: 'checklist', label: '2. Review Checklist' },
            { id: 'examples', label: '3. Worked Examples' },
            { id: 'pitfalls', label: '4. Common Pitfalls' },
          ].map(t => (
            <button
              key={t.id}
              onClick={() => setTab(t.id as typeof tab)}
              style={{
                padding: '12px 16px',
                border: 'none',
                background: 'none',
                cursor: 'pointer',
                fontSize: 13,
                fontWeight: tab === t.id ? 700 : 500,
                color: tab === t.id ? '#2563eb' : 'var(--text-muted)',
                borderBottom: tab === t.id ? '2px solid #2563eb' : '2px solid transparent',
                marginBottom: -1,
              }}
            >
              {t.label}
            </button>
          ))}
        </div>

        {/* Body Content */}
        <div style={{ padding: '20px 24px', overflowY: 'auto', fontSize: 14, lineHeight: 1.6 }}>
          {tab === 'rules' && (
            <div>
              <div style={{
                background: '#eff6ff',
                border: '1px solid #bfdbfe',
                borderRadius: 8,
                padding: 16,
                marginBottom: 20,
                color: '#1e3a8a',
              }}>
                <strong style={{ display: 'block', marginBottom: 6, fontSize: 15 }}>The Core Distinction: Action vs. State</strong>
                <ul style={{ margin: 0, paddingLeft: 20 }}>
                  <li style={{ marginBottom: 6 }}>
                    <strong>POINT:</strong> If it describes a <em>single occurrence</em> — an action that happened once, at one time — <strong>even if that action has lasting consequences</strong>.
                    <div style={{ fontSize: 12, color: '#3b82f6', marginTop: 2 }}>
                      Examples: <em>moved, arrived, called, bought, died, decided, told, scattered, walked, graduated, started</em>.
                    </div>
                  </li>
                  <li>
                    <strong>SPAN:</strong> ONLY if the text itself explicitly frames it as a <em>duration or a continuing/recurring state</em>.
                    <div style={{ fontSize: 12, color: '#3b82f6', marginTop: 2 }}>
                      Explicit cues: <em>&ldquo;for X years&rdquo;, &ldquo;since&rdquo;, &ldquo;still&rdquo;, &ldquo;every year&rdquo;, &ldquo;over the next two days&rdquo;, &ldquo;never&rdquo;, &ldquo;always&rdquo;, or stated start-and-end</em>.
                    </div>
                  </li>
                </ul>
              </div>

              <h3 style={{ fontSize: 15, fontWeight: 700, margin: '16px 0 8px' }}>The Primary Test to Ask:</h3>
              <p style={{ margin: '0 0 12px', fontStyle: 'italic', background: 'var(--surface-alt)', padding: 10, borderRadius: 6, borderLeft: '4px solid #2563eb' }}>
                &ldquo;Is this sentence describing an action, or a state?&rdquo;
              </p>
              <p style={{ margin: 0, color: 'var(--text-muted)', fontSize: 13 }}>
                Plot the action where it happened, not where its effects still linger — and only stretch an event into a span when the text itself describes a duration, not when you can imagine one.
              </p>
            </div>
          )}

          {tab === 'checklist' && (
            <div>
              <h3 style={{ fontSize: 15, fontWeight: 700, marginBottom: 12 }}>Step-by-Step Evaluation Checklist</h3>
              <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
                {[
                  {
                    num: '1',
                    title: 'Find the Main Verb',
                    desc: 'Is it an action verb (moved, told, bought, died, arrived) or a state description (had been, still, since, every)?',
                  },
                  {
                    num: '2',
                    title: 'Action → Point',
                    desc: 'Place it as a narrow point (equal or near-equal start/end) at the exact moment it occurred in story time, however far in the past.',
                  },
                  {
                    num: '3',
                    title: 'State → Check Explicit Durational Language',
                    desc: 'Look for "for X years", "since", "still", "never", "always", "every". If present → Span bounded by the textual range. If absent → Point.',
                  },
                  {
                    num: '4',
                    title: 'Compound Sentences (Action + Later Reveal)',
                    desc: 'Do not merge a one-time past action and the later moment it was revealed into one wide span! Represent as separate point-events or pick the salient moment.',
                  },
                  {
                    num: '5',
                    title: 'Deep-Past Background Facts',
                    desc: 'Sequence background facts (e.g. grandfather’s past, building construction) as early points or narrow spans near 0. Only extend towards the present if the text explicitly uses continuing language (e.g., "still stood").',
                  },
                  {
                    num: '6',
                    title: 'When Unsure: Default to Point',
                    desc: 'Spans should be the exception justified by explicit textual language, never the default assumption.',
                  },
                ].map(item => (
                  <div key={item.num} style={{ display: 'flex', gap: 12, padding: 12, background: 'var(--surface-alt)', borderRadius: 8 }}>
                    <div style={{
                      width: 28,
                      height: 28,
                      borderRadius: 14,
                      background: '#2563eb',
                      color: '#fff',
                      display: 'flex',
                      alignItems: 'center',
                      justifyContent: 'center',
                      fontWeight: 700,
                      fontSize: 13,
                      flexShrink: 0,
                    }}>
                      {item.num}
                    </div>
                    <div>
                      <div style={{ fontWeight: 600, fontSize: 14, color: 'var(--text-primary)' }}>{item.title}</div>
                      <div style={{ fontSize: 13, color: 'var(--text-muted)', marginTop: 2 }}>{item.desc}</div>
                    </div>
                  </div>
                ))}
              </div>
            </div>
          )}

          {tab === 'examples' && (
            <div>
              <h3 style={{ fontSize: 15, fontWeight: 700, marginBottom: 12 }}>Worked Examples from the Methodology</h3>
              <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 13 }}>
                <thead>
                  <tr style={{ background: 'var(--surface-alt)' }}>
                    <th style={{ padding: '8px 12px', textAlign: 'left', borderBottom: '1px solid var(--border)' }}>Sentence</th>
                    <th style={{ padding: '8px 12px', textAlign: 'left', borderBottom: '1px solid var(--border)', width: 110 }}>Verdict</th>
                    <th style={{ padding: '8px 12px', textAlign: 'left', borderBottom: '1px solid var(--border)' }}>Why</th>
                  </tr>
                </thead>
                <tbody>
                  {[
                    {
                      sentence: '"Her father had died when she was two."',
                      verdict: 'Point',
                      color: '#2563eb',
                      why: 'One-time action; depth in the past does not change this.',
                    },
                    {
                      sentence: '"The tournament had been held every year for as long as anyone could remember."',
                      verdict: 'Span',
                      color: '#d97706',
                      why: 'Recurring pattern, explicitly unbounded ("as long as anyone could remember").',
                    },
                    {
                      sentence: '"She had not slept since leaving the previous night."',
                      verdict: 'Span',
                      color: '#d97706',
                      why: 'The not-sleeping is itself durational content — describing a state, not an action.',
                    },
                    {
                      sentence: '"A professor she had met at a seminar six months before the trip."',
                      verdict: 'Point',
                      color: '#2563eb',
                      why: 'A single meeting. "Six months before" only tells you when the point falls, not that it is a duration.',
                    },
                    {
                      sentence: '"The shop had been open since 1987 and was finally closing."',
                      verdict: 'Span',
                      color: '#d97706',
                      why: 'Continuing state with an explicit start ("since 1987") and real end.',
                    },
                    {
                      sentence: '"He had started a part-time job at a pharmacy."',
                      verdict: 'Point',
                      color: '#2563eb',
                      why: 'Starting a job is a one-time action, even though the job continued — unless text separately says "and still works there".',
                    },
                    {
                      sentence: '"She had lived in Kuala Lumpur for two years on a work visa."',
                      verdict: 'Span',
                      color: '#d97706',
                      why: 'Explicit stated duration ("for two years"), with a real end when she leaves.',
                    },
                  ].map((row, i) => (
                    <tr key={i} style={{ borderBottom: '1px solid var(--border)' }}>
                      <td style={{ padding: '8px 12px', color: 'var(--text-primary)', fontStyle: 'italic' }}>{row.sentence}</td>
                      <td style={{ padding: '8px 12px' }}>
                        <span style={{
                          padding: '2px 8px',
                          borderRadius: 4,
                          fontWeight: 700,
                          fontSize: 11,
                          background: row.verdict === 'Point' ? '#dbeafe' : '#fef3c7',
                          color: row.color,
                        }}>
                          {row.verdict}
                        </span>
                      </td>
                      <td style={{ padding: '8px 12px', color: 'var(--text-muted)' }}>{row.why}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}

          {tab === 'pitfalls' && (
            <div>
              <h3 style={{ fontSize: 15, fontWeight: 700, marginBottom: 12 }}>Critical Failure Modes to Reject</h3>
              <div style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
                <div style={{
                  padding: 14,
                  borderRadius: 8,
                  background: '#fef2f2',
                  border: '1px solid #fecaca',
                  color: '#991b1b',
                }}>
                  <strong style={{ fontSize: 14, display: 'block', marginBottom: 4 }}>
                    Trap 1: &ldquo;Consequences are still true, so let&apos;s span it to the end&rdquo;
                  </strong>
                  <p style={{ margin: '0 0 6px', fontSize: 13 }}>
                    <em>Example:</em> &ldquo;Imran had moved away from Wari to Mirpur eight months ago for his new job.&rdquo;
                  </p>
                  <div style={{ fontSize: 12, lineHeight: 1.5 }}>
                    <strong>Wrong:</strong> Spanning to present because &ldquo;he still lives there.&rdquo;<br />
                    <strong>Correct:</strong> Point at 8 months before present. Moving happened once, on one day. The consequence is not what is being plotted unless the text explicitly says &ldquo;he continues to live there&rdquo;.
                  </div>
                </div>

                <div style={{
                  padding: 14,
                  borderRadius: 8,
                  background: '#fef2f2',
                  border: '1px solid #fecaca',
                  color: '#991b1b',
                }}>
                  <strong style={{ fontSize: 14, display: 'block', marginBottom: 4 }}>
                    Trap 2: Merging Compound Action + Later Reveal
                  </strong>
                  <p style={{ margin: '0 0 6px', fontSize: 13 }}>
                    <em>Example:</em> &ldquo;He had already wired money for the wedding five weeks ago but kept it secret to surprise everyone [revealed tonight].&rdquo;
                  </p>
                  <div style={{ fontSize: 12, lineHeight: 1.5 }}>
                    <strong>Wrong:</strong> Merging wiring and revealing into a single 5-week span.<br />
                    <strong>Correct:</strong> Split into two points or choose the salient moment. Truth persisting across a gap does not make the action durational.
                  </div>
                </div>

                <div style={{
                  padding: 14,
                  borderRadius: 8,
                  background: '#fef2f2',
                  border: '1px solid #fecaca',
                  color: '#991b1b',
                }}>
                  <strong style={{ fontSize: 14, display: 'block', marginBottom: 4 }}>
                    Trap 3: Stretching Deep-Past Background Facts to the Present
                  </strong>
                  <div style={{ fontSize: 12, lineHeight: 1.5 }}>
                    Background facts (e.g. &ldquo;photograph taken in 1971 found in a box today&rdquo;) are points at discovery, not spans spanning 50 years to the past.
                  </div>
                </div>
              </div>
            </div>
          )}
        </div>

        {/* Footer */}
        <div style={{
          padding: '12px 24px',
          borderTop: '1px solid var(--border)',
          display: 'flex',
          justifyContent: 'flex-end',
          background: 'var(--surface-alt)',
        }}>
          <button
            onClick={onClose}
            style={{
              padding: '6px 18px',
              background: '#2563eb',
              color: '#fff',
              border: 'none',
              borderRadius: 6,
              cursor: 'pointer',
              fontWeight: 600,
              fontSize: 13,
            }}
          >
            Got it, Close
          </button>
        </div>
      </div>
    </div>
  );
}
