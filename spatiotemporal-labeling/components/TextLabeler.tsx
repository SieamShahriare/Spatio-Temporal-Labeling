'use client';

import { useState, useCallback } from 'react';
import { Span } from '@/lib/types';

interface Props {
  stemText: string;
  spans: Span[];
  onAddSpan: (labelType: 'Event' | 'Time', spanText: string, charStart: number, charEnd: number) => void;
  onDeleteSpan: (spanId: number) => void;
}

interface Segment {
  text: string;
  start: number;
  end: number;
  spans: Span[];
}

function getSegments(text: string, spans: Span[]): Segment[] {
  if (spans.length === 0) return [{ text, start: 0, end: text.length, spans: [] }];

  const boundaries = new Set<number>([0, text.length]);
  for (const s of spans) {
    boundaries.add(s.char_start);
    boundaries.add(s.char_end);
  }
  const sorted = Array.from(boundaries).sort((a, b) => a - b);

  return sorted.slice(0, -1).map((start, idx) => {
    const end = sorted[idx + 1];
    const covering = spans.filter(s => s.char_start <= start && s.char_end >= end);
    return { text: text.slice(start, end), start, end, spans: covering };
  });
}

const LABEL_COLORS: Record<string, { bg: string; border: string; text: string }> = {
  Event: { bg: '#dbeafe', border: '#3b82f6', text: '#1d4ed8' },
  Time:  { bg: '#fed7aa', border: '#f97316', text: '#c2410c' },
};

export default function TextLabeler({ stemText, spans, onAddSpan, onDeleteSpan }: Props) {
  const [pendingType, setPendingType] = useState<'Event'>('Event');
  const [hoveredSegment, setHoveredSegment] = useState<string | null>(null);

  const handleMouseUp = useCallback(() => {
    const selection = window.getSelection();
    if (!selection || selection.isCollapsed) return;

    const range = selection.getRangeAt(0);
    const container = document.getElementById('text-labeler-content');
    if (!container || !container.contains(range.commonAncestorContainer)) return;

    const preRange = document.createRange();
    preRange.setStart(container, 0);
    preRange.setEnd(range.startContainer, range.startOffset);
    const charStart = preRange.toString().length;
    const trimmedLength = range.toString().trim().length;
    const charEnd = charStart + trimmedLength;
    const spanText = range.toString().trim();

    if (!spanText) return;
    selection.removeAllRanges();
    onAddSpan(pendingType, spanText, charStart, charEnd);
  }, [pendingType, onAddSpan]);

  const segments = getSegments(stemText, spans);

  const getHoverActions = (seg: Segment) => {
    return seg.spans.map((s) => ({
      id: s.id,
      label: `${s.seq_label} (${s.label_type})`,
      action: () => onDeleteSpan(s.id),
    }));
  };

  return (
    <div>
      {/* Label type picker */}
      <div style={{ display: 'flex', gap: 8, marginBottom: 12 }}>
        <span style={{ fontSize: 13, color: 'var(--text-muted)', alignSelf: 'center' }}>Label as:</span>
        {(['Event'] as const).map(type => (
          <button
            key={type}
            onClick={() => setPendingType(type)}
            style={{
              padding: '4px 14px',
              borderRadius: 6,
              border: `2px solid ${pendingType === type ? LABEL_COLORS[type].border : 'var(--border-input)'}`,
              background: pendingType === type ? LABEL_COLORS[type].bg : 'var(--surface)',
              color: pendingType === type ? LABEL_COLORS[type].text : 'var(--text-primary)',
              fontWeight: pendingType === type ? 600 : 400,
              cursor: 'pointer',
              fontSize: 13,
            }}
          >
            {type}
          </button>
        ))}
        <span style={{ fontSize: 12, color: 'var(--text-disabled)', alignSelf: 'center', marginLeft: 4 }}>
          — select text below to label
        </span>
      </div>

      {/* Text display */}
      <div
        id="text-labeler-content"
        onMouseUp={handleMouseUp}
        style={{
          padding: 16,
          border: '1px solid var(--border)',
          borderRadius: 8,
          lineHeight: 2,
          fontSize: 15,
          cursor: 'text',
          userSelect: 'text',
          background: 'var(--surface-alt)',
        }}
      >
        {segments.map((seg) => {
          if (seg.spans.length === 0) {
            return <span key={`${seg.start}-${seg.end}`}>{seg.text}</span>;
          }
          const s = seg.spans[0];
          const colors = LABEL_COLORS[s.label_type];
          const segKey = `${seg.start}-${seg.end}`;
          const isHovered = hoveredSegment === segKey;
          const actions = getHoverActions(seg);

          return (
            <mark
              key={segKey}
              onMouseEnter={() => setHoveredSegment(segKey)}
              onMouseLeave={() => setHoveredSegment(null)}
              title={actions.length === 1 ? `${s.seq_label}: ${s.span_text}` : undefined}
              style={{
                background: colors.bg,
                color: colors.text,
                borderBottom: `2px solid ${colors.border}`,
                borderRadius: 3,
                padding: '1px 2px',
                position: 'relative',
                display: 'inline-flex',
                alignItems: 'center',
                gap: 4,
                cursor: 'default',
              }}
            >
              <span>{seg.text}</span>
              {isHovered && (
                <span
                  style={{
                    display: 'inline-flex',
                    alignItems: 'center',
                    gap: 2,
                    position: 'relative',
                    verticalAlign: 'middle',
                    lineHeight: 1,
                  }}
                >
                  {actions.length === 1 ? (
                    <button
                      onClick={(e) => { e.stopPropagation(); actions[0].action(); }}
                      onMouseDown={(e) => e.preventDefault()}
                      title="Remove span"
                      style={{
                        border: 'none',
                        background: colors.border,
                        color: '#fff',
                        borderRadius: '50%',
                        width: 14,
                        height: 14,
                        cursor: 'pointer',
                        fontSize: 11,
                        lineHeight: 1,
                        display: 'inline-flex',
                        alignItems: 'center',
                        justifyContent: 'center',
                        padding: 0,
                        flexShrink: 0,
                      }}
                    >
                      ×
                    </button>
                  ) : (
                    <span
                      style={{ position: 'relative', display: 'inline-flex' }}
                      onMouseDown={(e) => e.preventDefault()}
                    >
                      <button
                        title="Multiple labels here"
                        style={{
                          border: 'none',
                          background: colors.border,
                          color: '#fff',
                          borderRadius: '50%',
                          width: 14,
                          height: 14,
                          cursor: 'pointer',
                          fontSize: 10,
                          lineHeight: 1,
                          display: 'inline-flex',
                          alignItems: 'center',
                          justifyContent: 'center',
                          padding: 0,
                          flexShrink: 0,
                        }}
                      >
                        …
                      </button>
                      <span
                        style={{
                          display: 'none',
                          position: 'absolute',
                          bottom: '100%',
                          right: 0,
                          background: '#1f2937',
                          color: '#fff',
                          borderRadius: 6,
                          padding: '4px 0',
                          minWidth: 140,
                          boxShadow: '0 4px 12px rgba(0,0,0,0.25)',
                          zIndex: 50,
                          flexDirection: 'column',
                          gap: 0,
                        }}
                        className="hover-actions-dropdown"
                      >
                        {actions.map((a) => (
                          <button
                            key={a.id}
                            onClick={() => a.action()}
                            style={{
                              display: 'block',
                              width: '100%',
                              border: 'none',
                              background: 'transparent',
                              color: '#f3f4f6',
                              cursor: 'pointer',
                              fontSize: 12,
                              textAlign: 'left',
                              padding: '4px 10px',
                            }}
                            onMouseEnter={(ev) => {
                              const btn = ev.currentTarget as HTMLButtonElement;
                              if (btn) btn.style.background = '#374151';
                            }}
                            onMouseLeave={(ev) => {
                              const btn = ev.currentTarget as HTMLButtonElement;
                              if (btn) btn.style.background = 'transparent';
                            }}
                          >
                            Remove {a.label}
                          </button>
                        ))}
                      </span>
                    </span>
                  )}
                </span>
              )}
            </mark>
          );
        })}
      </div>

      {/* Span list */}
      {spans.length > 0 && (
        <div style={{ marginTop: 12 }}>
          <div style={{ fontSize: 12, fontWeight: 600, color: 'var(--text-muted)', marginBottom: 6 }}>
            LABELED SPANS
          </div>
          <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6 }}>
            {spans.map(s => {
              const colors = LABEL_COLORS[s.label_type];
              return (
                <div
                  key={s.id}
                  style={{
                    display: 'flex',
                    alignItems: 'center',
                    gap: 6,
                    padding: '3px 8px',
                    borderRadius: 20,
                    background: colors.bg,
                    border: `1px solid ${colors.border}`,
                    fontSize: 13,
                  }}
                >
                  <span style={{ fontWeight: 700, color: colors.text }}>{s.seq_label}</span>
                  <span style={{ color: '#374151', maxWidth: 160, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                    &ldquo;{s.span_text}&rdquo;
                  </span>
                  <button
                    onClick={() => onDeleteSpan(s.id)}
                    style={{
                      border: 'none',
                      background: 'none',
                      cursor: 'pointer',
                      color: 'var(--text-disabled)',
                      padding: 0,
                      lineHeight: 1,
                      fontSize: 14,
                    }}
                    title="Remove span"
                  >
                    ×
                  </button>
                </div>
              );
            })}
          </div>
        </div>
      )}
    </div>
  );
}
