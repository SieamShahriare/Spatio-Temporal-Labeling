'use client';

import { Span } from './types';

const HUE_STEP = 360 / 12;
const SATURATION = 65;

function hsl(h: number, s: number, l: number): string {
  return `hsl(${h}, ${s}%, ${l}%)`;
}

export function hashString(str: string): number {
  let hash = 0;
  for (let i = 0; i < str.length; i++) {
    hash = str.charCodeAt(i) + ((hash << 5) - hash);
  }
  return Math.abs(hash);
}

export function colorForSpan(span: Span, variant: 'dark' | 'light' = 'dark'): { bg: string; border: string; text: string } {
  const base = `${span.label_type ?? 'span'}::${span.seq_label}::${span.span_text}`;
  const h = (hashString(base) * HUE_STEP) % 360;
  if (variant === 'light') {
    const bg = hsl(h, SATURATION, 88);
    const border = hsl(h, SATURATION, 70);
    const text = hsl(h, SATURATION, 22);
    return { bg, border, text };
  }
  const bg = hsl(h, SATURATION, 48);
  const border = hsl(h, SATURATION, Math.max(48 - 16, 20));
  const text = '#fff';
  return { bg, border, text };
}

export function darkColorForSpan(span: Span): { bg: string; border: string; text: string } {
  return colorForSpan(span, 'dark');
}

export function lightColorForSpan(span: Span): { bg: string; border: string; text: string } {
  return colorForSpan(span, 'light');
}

export function colorForType(labelType: 'Event' | 'Time'): { bg: string; border: string; text: string } {
  return colorForSpan({ label_type: labelType, seq_label: `${labelType[0]}1`, span_text: '' } as Span, 'light');
}
