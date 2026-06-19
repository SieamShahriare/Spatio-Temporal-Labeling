'use client';

import { useState } from 'react';
import { MatrixData, ALLEN_RELATIONS, ALLEN_CODES, SpanOrder } from '@/lib/types';

interface Props {
  matrixData: MatrixData;
  onOverride: (i: number, j: number, code: number) => void;
  onSave: () => void;
}

const cellBg = (code: number): string => {
  if (code === 0) return '#f3f4f6';
  if (code > 0) return '#eff6ff';
  return '#fff7ed';
};

const cellColor = (code: number): string => {
  if (code === 0) return '#9ca3af';
  if (code > 0) return '#1d4ed8';
  return '#c2410c';
};

export default function AllenMatrix({ matrixData, onOverride, onSave }: Props) {
  const [unlocked, setUnlocked] = useState(false);
  const { matrix, span_order, violations } = matrixData;
  const n = span_order.length;

  if (n === 0) {
    return (
      <div style={{ padding: 24, textAlign: 'center', color: '#9ca3af', fontSize: 14 }}>
        No spans yet. Add spans and save the matrix to see relations.
      </div>
    );
  }

  return (
    <div>
      {/* Violations banner */}
      {violations.length > 0 && (
        <div
          style={{
            background: '#fef2f2',
            border: '1px solid #fca5a5',
            borderRadius: 6,
            padding: '8px 12px',
            marginBottom: 12,
            fontSize: 13,
          }}
        >
          <strong style={{ color: '#dc2626' }}>⚠ Transitivity violations detected:</strong>
          <ul style={{ margin: '4px 0 0 16px', padding: 0, color: '#b91c1c' }}>
            {violations.map((v, i) => <li key={i}>{v.message}</li>)}
          </ul>
        </div>
      )}

      {/* Controls */}
      <div style={{ display: 'flex', gap: 8, marginBottom: 12, alignItems: 'center' }}>
        <button
          onClick={() => setUnlocked(u => !u)}
          style={{
            padding: '6px 14px',
            borderRadius: 6,
            border: `1px solid ${unlocked ? '#f97316' : '#d1d5db'}`,
            background: unlocked ? '#fff7ed' : '#fff',
            color: unlocked ? '#c2410c' : '#374151',
            cursor: 'pointer',
            fontSize: 13,
            fontWeight: 500,
          }}
        >
          {unlocked ? '🔓 Matrix Unlocked (editing)' : '🔒 Unlock Matrix for Review'}
        </button>
        <button
          onClick={onSave}
          style={{
            padding: '6px 14px',
            borderRadius: 6,
            border: '1px solid #3b82f6',
            background: '#eff6ff',
            color: '#1d4ed8',
            cursor: 'pointer',
            fontSize: 13,
            fontWeight: 500,
          }}
        >
          ↻ Recompute from Timeline
        </button>
        <span style={{ fontSize: 12, color: '#9ca3af' }}>
          Diagonal locked to 0. Lower triangle = inverse of upper.
        </span>
      </div>

      {/* Matrix table */}
      <div style={{ overflowX: 'auto' }}>
        <table style={{ borderCollapse: 'collapse', fontSize: 13 }}>
          <thead>
            <tr>
              <th style={{ width: 48, padding: 4, background: '#f9fafb', border: '1px solid #e5e7eb' }} />
              {span_order.map(s => (
                <th
                  key={s.id}
                  style={{
                    padding: '4px 8px',
                    background: '#f9fafb',
                    border: '1px solid #e5e7eb',
                    fontWeight: 700,
                    color: '#374151',
                    minWidth: 52,
                  }}
                >
                  {s.seq_label}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {span_order.map((row, i) => (
              <tr key={row.id}>
                <td
                  style={{
                    padding: '4px 8px',
                    background: '#f9fafb',
                    border: '1px solid #e5e7eb',
                    fontWeight: 700,
                    color: '#374151',
                  }}
                >
                  {row.seq_label}
                </td>
                {span_order.map((col, j) => {
                  const code = matrix[i]?.[j] ?? 0;
                  const isDiag = i === j;
                  const rel = ALLEN_RELATIONS[code];

                  if (isDiag) {
                    return (
                      <td
                        key={col.id}
                        style={{
                          padding: '4px 8px',
                          border: '1px solid #e5e7eb',
                          background: '#f3f4f6',
                          textAlign: 'center',
                          color: '#9ca3af',
                          fontWeight: 700,
                        }}
                      >
                        0
                      </td>
                    );
                  }

                  return (
                    <td
                      key={col.id}
                      style={{
                        padding: '2px 4px',
                        border: '1px solid #e5e7eb',
                        background: cellBg(code),
                        textAlign: 'center',
                      }}
                    >
                      {unlocked ? (
                        <select
                          value={code}
                          onChange={e => onOverride(i, j, parseInt(e.target.value))}
                          style={{
                            border: 'none',
                            background: 'transparent',
                            fontSize: 12,
                            color: cellColor(code),
                            fontWeight: 600,
                            cursor: 'pointer',
                            width: '100%',
                          }}
                        >
                          {ALLEN_CODES.map(c => {
                            const r = ALLEN_RELATIONS[c];
                            return (
                              <option key={c} value={c}>
                                {c > 0 ? '+' : ''}{c} ({r?.symbol ?? c})
                              </option>
                            );
                          })}
                        </select>
                      ) : (
                        <span
                          style={{
                            fontWeight: 700,
                            color: cellColor(code),
                            display: 'block',
                          }}
                          title={rel?.name ?? String(code)}
                        >
                          {code > 0 ? '+' : ''}{code}
                          <span style={{ fontSize: 10, fontWeight: 400, display: 'block', color: '#9ca3af' }}>
                            {rel?.symbol}
                          </span>
                        </span>
                      )}
                    </td>
                  );
                })}
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {/* Legend */}
      <div style={{ marginTop: 12, fontSize: 11, color: '#9ca3af' }}>
        <strong>Legend:</strong>{' '}
        {ALLEN_CODES.map(c => {
          const r = ALLEN_RELATIONS[c];
          return (
            <span key={c} style={{ marginRight: 8 }}>
              <strong style={{ color: c > 0 ? '#1d4ed8' : '#c2410c' }}>
                {c > 0 ? '+' : ''}{c}
              </strong>
              {' '}={' '}
              {r?.symbol} ({r?.name})
            </span>
          );
        })}
      </div>
    </div>
  );
}
