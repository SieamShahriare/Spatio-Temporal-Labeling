'use client';

import { Span } from './types';

const PALETTE_SIZE = 24;
const HUES = [0, 40, 80, 120, 160, 200, 240, 280];
const LIGHTNESS_LEVELS = [38, 46, 54];

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

export function getPaletteIndex(span: Span): { h: number; l: number } {
  const base = `${span.label_type ?? 'span'}::${span.seq_label}::${span.span_text}`;
  const idx = hashString(base) % PALETTE_SIZE;
  const hueIndex = idx % HUES.length;
  const levelIndex = Math.floor(idx / HUES.length);
  return { h: HUES[hueIndex], l: LIGHTNESS_LEVELS[levelIndex] };
}

export function colorForSpan(span: Span, variant: 'dark' | 'light' = 'dark'): { bg: string; border: string; text: string } {
  const { h, l } = getPaletteIndex(span);
  const s = 68;

  if (variant === 'light') {
    const bg = hsl(h, 55, 88);
    const border = hsl(h, 55, 76);
    const text = hsl(h, 55, 18);
    return { bg, border, text };
  }

  const bg = hsl(h, s, l);
  const border = hsl(h, s, Math.max(l - 16, 20));
  return { bg, border, text: '#fff' };
}

export function darkColorForSpan(span: Span): { bg: string; border: string; text: string } {
  return colorForSpan(span, 'dark');
}

export function lightColorForSpan(span: Span): { bg: string; border: string; text: string } {
  return colorForSpan(span, 'light');
}

export function colorForType(labelType: 'Event' | 'Time'): { bg: string; border: string; text: string } {
  const fake = { label_type: labelType, seq_label: `${labelType[0]}1`, span_text: '' } as Span;
  return colorForSpan(fake, 'light');
}
