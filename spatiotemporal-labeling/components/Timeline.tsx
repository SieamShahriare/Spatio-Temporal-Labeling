'use client';

import { useRef, useState, useCallback, useEffect, useMemo } from 'react';
import { Span } from '@/lib/types';

interface Props {
  spans: Span[];
  onUpdateSpan: (spanId: number, tlStart: number, tlEnd: number) => void;
  onExtractTimeline?: () => Promise<void>;
  extractingTimeline?: boolean;
}

const TRACK_HEIGHT = 40;
const TRACK_GAP = 8;
const LABEL_WIDTH = 220;
const MIN_WIDTH = 5;
const TIMELINE_MIN = 0;
const TIMELINE_MAX = 100;

const COLORS = {
  Event: { bg: '#3b82f6', border: '#1d4ed8', text: '#fff' },
  Time:  { bg: '#f97316', border: '#c2410c', text: '#fff' },
};

export default function Timeline({ spans, onUpdateSpan, onExtractTimeline, extractingTimeline = false }: Props) {
  const containerRef = useRef<HTMLDivElement>(null);
  const [trackWidthPx, setTrackWidthPx] = useState<number>(760);
  const [dragging, setDragging] = useState<{
    spanId: number;
    mode: 'move' | 'resize-left' | 'resize-right';
    startX: number;
    origStart: number;
    origEnd: number;
  } | null>(null);
  const [localSpans, setLocalSpans] = useState<Span[]>(spans);

  useEffect(() => { setLocalSpans(spans); }, [spans]);

  const pxPerUnit = useMemo(() => trackWidthPx / (TIMELINE_MAX - TIMELINE_MIN), [trackWidthPx]);

  useEffect(() => {
    const el = containerRef.current;
    if (!el) return;
    const measure = () => {
      const w = el.clientWidth - LABEL_WIDTH;
      setTrackWidthPx(w > 0 ? w : 760);
    };
    measure();
    const ro = new ResizeObserver(measure);
    ro.observe(el);
    return () => ro.disconnect();
  }, []);

  const onMouseDown = useCallback((e: React.MouseEvent, spanId: number, mode: 'move' | 'resize-left' | 'resize-right') => {
    e.preventDefault();
    const span = localSpans.find(s => s.id === spanId)!;
    setDragging({ spanId, mode, startX: e.clientX, origStart: span.tl_start, origEnd: span.tl_end });
  }, [localSpans]);

  useEffect(() => {
    if (!dragging) return;
    const onMove = (e: MouseEvent) => {
      const dx = e.clientX - dragging.startX;
      const dUnits = dx / pxPerUnit;
      setLocalSpans(prev => prev.map(s => {
        if (s.id !== dragging.spanId) return s;
        let start = s.tl_start;
        let end = s.tl_end;
        if (dragging.mode === 'move') {
          const len = dragging.origEnd - dragging.origStart;
          start = Math.max(TIMELINE_MIN, Math.min(TIMELINE_MAX - len, dragging.origStart + dUnits));
          end = start + len;
        } else if (dragging.mode === 'resize-left') {
          start = Math.max(TIMELINE_MIN, Math.min(dragging.origEnd - MIN_WIDTH, dragging.origStart + dUnits));
        } else {
          end = Math.min(TIMELINE_MAX, Math.max(dragging.origStart + MIN_WIDTH, dragging.origEnd + dUnits));
        }
        return { ...s, tl_start: Math.round(start * 10) / 10, tl_end: Math.round(end * 10) / 10 };
      }));
    };
    const onUp = () => {
      if (dragging) {
        const updated = localSpans.find(s => s.id === dragging.spanId);
        if (updated) onUpdateSpan(updated.id, updated.tl_start, updated.tl_end);
      }
      setDragging(null);
    };
    window.addEventListener('mousemove', onMove);
    window.addEventListener('mouseup', onUp);
    return () => {
      window.removeEventListener('mousemove', onMove);
      window.removeEventListener('mouseup', onUp);
    };
  }, [dragging, localSpans, onUpdateSpan, pxPerUnit]);

  const handleManualChange = (spanId: number, field: 'tl_start' | 'tl_end', raw: string) => {
    const val = parseFloat(raw);
    if (isNaN(val)) return;
    setLocalSpans(prev => prev.map(s => s.id === spanId ? { ...s, [field]: val } : s));
  };

  const handleManualBlur = (spanId: number) => {
    const s = localSpans.find(x => x.id === spanId);
    if (s) onUpdateSpan(s.id, s.tl_start, s.tl_end);
  };

  if (localSpans.length === 0) {
    return (
      <div style={{ padding: 24, textAlign: 'center', color: 'var(--text-disabled)', fontSize: 14 }}>
        No events labeled yet. Label events in Step 1 to populate the timeline.
      </div>
    );
  }

  const totalHeight = localSpans.length * (TRACK_HEIGHT + TRACK_GAP) + 8;
  const ticks = Array.from({ length: 11 }, (_, i) => i * 10);

  return (
    <div>
      <div style={{ display: 'flex', justifyContent: 'flex-end', marginBottom: 8 }}>
        {onExtractTimeline && (
          <button
            onClick={onExtractTimeline}
            disabled={extractingTimeline}
            style={{
              padding: '4px 14px',
              borderRadius: 6,
              border: `1px solid ${extractingTimeline ? 'var(--text-disabled)' : 'var(--info-border)'}`,
              background: extractingTimeline ? 'var(--text-disabled)' : 'var(--info-bg)',
              color: extractingTimeline ? '#fff' : 'var(--info)',
              fontWeight: 600,
              cursor: extractingTimeline ? 'not-allowed' : 'pointer',
              fontSize: 12,
            }}
          >
            {extractingTimeline ? 'Setting positions…' : 'Use LLM'}
          </button>
        )}
      </div>

      <div ref={containerRef} style={{ overflowX: 'auto' }}>
        <div style={{ display: 'flex', marginLeft: LABEL_WIDTH, marginBottom: 2 }}>
          {ticks.map(t => (
            <div
              key={t}
              style={{
                flex: t === 100 ? 0 : 1,
                minWidth: trackWidthPx / 10,
                fontSize: 10,
                color: 'var(--text-disabled)',
                borderLeft: '1px solid var(--border)',
                paddingLeft: 2,
              }}
            >
              {t}
            </div>
          ))}
        </div>

        <div style={{ position: 'relative', height: totalHeight }}>
          {localSpans.map((span, idx) => {
            const colors = COLORS[span.label_type as keyof typeof COLORS] ?? COLORS.Event;
            const top = idx * (TRACK_HEIGHT + TRACK_GAP);
            const leftPx = (span.tl_start / (TIMELINE_MAX - TIMELINE_MIN)) * trackWidthPx;
            const widthPx = Math.max(MIN_WIDTH * pxPerUnit, ((span.tl_end - span.tl_start) / (TIMELINE_MAX - TIMELINE_MIN)) * trackWidthPx) - 16;

            return (
              <div key={span.id} style={{ position: 'absolute', top, left: 0, right: 0, height: TRACK_HEIGHT }}>
                <div style={{
                  position: 'absolute', left: 0, top: 0, bottom: 0, width: LABEL_WIDTH,
                  display: 'flex', alignItems: 'center', gap: 6,
                  padding: '0 8px', overflow: 'hidden',
                }}>
                  <span style={{ fontWeight: 700, color: colors.bg, flexShrink: 0 }}>
                    {span.seq_label}{span.source === 'llm' ? ' [auto]' : ''}
                  </span>
                  <span style={{ color: '#6b7280', fontWeight: 400, fontSize: 11, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                    {span.span_text}
                  </span>
                </div>

                <div style={{ position: 'absolute', left: LABEL_WIDTH, right: 0, top: 0, bottom: 0 }}>
                  <div style={{
                    position: 'absolute', inset: 0,
                    background: 'var(--surface-alt)',
                    border: '1px solid var(--border)',
                    borderRadius: 4,
                  }} />

                  <div
                    onMouseDown={e => onMouseDown(e, span.id, 'move')}
                    title={`${span.seq_label}: ${span.span_text} [${span.tl_start}–${span.tl_end}]`}
                    style={{
                      position: 'absolute',
                      left: leftPx,
                      width: Math.max(5, widthPx),
                      height: TRACK_HEIGHT,
                      background: colors.bg,
                      borderRadius: 4,
                      cursor: dragging?.spanId === span.id ? 'grabbing' : 'grab',
                      display: 'flex',
                      alignItems: 'center',
                      justifyContent: 'center',
                      gap: 4,
                      fontSize: 10,
                      color: colors.text,
                      fontWeight: 600,
                      userSelect: 'none',
                      boxShadow: dragging?.spanId === span.id ? '0 2px 8px rgba(0,0,0,0.2)' : 'none',
                      transition: dragging ? 'none' : 'box-shadow 0.1s',
                      overflow: 'hidden',
                      whiteSpace: 'nowrap',
                      padding: '0 10px',
                      zIndex: 1,
                    }}
                  >
                    <span style={{ pointerEvents: 'none', flexShrink: 0 }}>
                      {span.seq_label}{span.source === 'llm' ? ' [auto]' : ''}
                    </span>
                    <div
                      onMouseDown={e => { e.stopPropagation(); onMouseDown(e, span.id, 'resize-left'); }}
                      style={{
                        position: 'absolute', left: 0, top: 0, width: 8, height: '100%',
                        cursor: 'ew-resize', background: 'rgba(255,255,255,0.3)',
                        borderRadius: '4px 0 0 4px',
                      }}
                    />
                    <div
                      onMouseDown={e => { e.stopPropagation(); onMouseDown(e, span.id, 'resize-right'); }}
                      style={{
                        position: 'absolute', right: 0, top: 0, width: 8, height: '100%',
                        cursor: 'ew-resize', background: 'rgba(255,255,255,0.3)',
                        borderRadius: '0 4px 4px 0',
                      }}
                    />
                  </div>
                </div>
              </div>
            );
          })}
        </div>
      </div>

      <div style={{ marginTop: 16 }}>
        <div style={{ fontSize: 12, fontWeight: 600, color: 'var(--text-muted)', marginBottom: 6 }}>
          MANUAL POSITION INPUTS
        </div>
        <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
          {localSpans.map(span => (
            <div key={span.id} style={{ display: 'flex', alignItems: 'center', gap: 8, fontSize: 13 }}>
              <span style={{ width: 168, fontWeight: 700, color: COLORS[span.label_type as keyof typeof COLORS]?.bg ?? 'var(--text-secondary)', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                {span.seq_label} {span.source === 'llm' && '[auto]'}{span.span_text}
              </span>
              <label style={{ color: 'var(--text-muted)' }}>Start:</label>
              <input
                type="number" min={0} max={100} step={0.1}
                value={span.tl_start}
                onChange={e => handleManualChange(span.id, 'tl_start', e.target.value)}
                onBlur={() => handleManualBlur(span.id)}
                style={{ width: 70, padding: '2px 6px', border: '1px solid var(--border-input)', borderRadius: 4, fontSize: 13 }}
              />
              <label style={{ color: 'var(--text-muted)' }}>End:</label>
              <input
                type="number" min={0} max={100} step={0.1}
                value={span.tl_end}
                onChange={e => handleManualChange(span.id, 'tl_end', e.target.value)}
                onBlur={() => handleManualBlur(span.id)}
                style={{ width: 70, padding: '2px 6px', border: '1px solid var(--border-input)', borderRadius: 4, fontSize: 13 }}
              />
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
