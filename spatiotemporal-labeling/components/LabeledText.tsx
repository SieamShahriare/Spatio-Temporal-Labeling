'use client';

import { Span } from '@/lib/types';
import { lightColorForSpan } from '@/lib/spanColors';

interface Segment {
  text: string;
  start: number;
  end: number;
  spans: Span[];
}

export function getSegments(text: string, spans: Span[]): Segment[] {
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

interface Props {
  stemText: string;
  spans: Span[];
  onDeleteSpan?: (spanId: number) => void;
  interactive?: boolean;
}

export default function LabeledText({ stemText, spans, onDeleteSpan, interactive = false }: Props) {
  const segments = getSegments(stemText, spans);

  return (
    <div
      style={{
        padding: 16,
        border: '1px solid var(--border)',
        borderRadius: 8,
        lineHeight: 2,
        fontSize: 14,
        background: 'var(--surface-alt)',
      }}
    >
      {segments.map((seg) => {
        if (seg.spans.length === 0) {
          return <span key={`${seg.start}-${seg.end}`}>{seg.text}</span>;
        }
        const s = seg.spans[0];
        const colors = lightColorForSpan(s);
        const segKey = `${seg.start}-${seg.end}`;

        return (
            <mark
              key={segKey}
              data-badge={seg.spans.length === 1 ? s.seq_label : ''}
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
                cursor: interactive ? 'default' : 'default',
              }}
            >
            <span>{seg.text}</span>
            {interactive && onDeleteSpan && (
              <span
                style={{
                  display: 'inline-flex',
                  alignItems: 'center',
                  gap: 2,
                  position: 'relative',
                  verticalAlign: 'middle',
                  lineHeight: 1,
                }}
                onMouseDown={(e) => e.preventDefault()}
              >
                <button
                  onClick={() => onDeleteSpan(s.id)}
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
              </span>
            )}
          </mark>
        );
      })}
    </div>
  );
}
