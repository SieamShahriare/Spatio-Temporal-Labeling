'use client';

import { useState } from 'react';
import { MatrixData, ALLEN_RELATIONS, ALLEN_CODES, SpanOrder } from '@/lib/types';

interface Props {
  matrixData: MatrixData;
  onOverride: (i: number, j: number, code: number) => void;
  onSave: () => void;
}

const cellBg = (code: number): string => {
  if (code === 0) return 'var(--surface-alt)';
  if (code > 0) return 'var(--info-bg)';
  return 'var(--negative-bg)';
};

const cellColor = (code: number): string => {
  if (code === 0) return 'var(--text-disabled)';
  if (code > 0) return 'var(--info)';
  return 'var(--negative)';
};

export default function AllenMatrix({ matrixData, onOverride, onSave }: Props) {
  const [unlocked, setUnlocked] = useState(false);
  const { matrix, span_order, violations } = matrixData;
  const n = span_order.length;

  if (n === 0) {
    return (
      <div style={{ padding: 24, textAlign: 'center', color: 'var(--text-disabled)', fontSize: 14 }}>
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
               background: 'var(--error-bg)',
               border: '1px solid var(--error-border)',
               borderRadius: 6,
               padding: '8px 12px',
               marginBottom: 12,
               fontSize: 13,
             }}
        >
          <strong style={{ color: 'var(--error)' }}>⚠ Transitivity violations detected:</strong>
          <ul style={{ margin: '4px 0 0 16px', padding: 0, color: 'var(--error)' }}>
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
               border: `1px solid ${unlocked ? '#f97316' : 'var(--border-input)'}`,
               background: unlocked ? 'var(--negative-bg)' : 'var(--surface)',
               color: unlocked ? 'var(--negative)' : 'var(--text-primary)',
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
               border: '1px solid var(--info-border)',
               background: 'var(--info-bg)',
               color: 'var(--info)',
               cursor: 'pointer',
               fontSize: 13,
               fontWeight: 500,
             }}
        >
          ↻ Recompute from Timeline
        </button>
        <span style={{ fontSize: 12, color: 'var(--text-disabled)' }}>
          Diagonal locked to 0. Lower triangle = inverse of upper.
        </span>
      </div>

      {/* Matrix table */}
      <div style={{ overflowX: 'auto' }}>
        <table style={{ borderCollapse: 'collapse', fontSize: 13 }}>
          <thead>
          <tr>
            <th style={{ width: 48, padding: 4, background: 'var(--surface-alt)', border: '1px solid var(--border)' }} />
            {span_order.map(s => (
              <th
                key={s.id}
                style={{
                  padding: '4px 8px',
                  background: 'var(--surface-alt)',
                  border: '1px solid var(--border)',
                  fontWeight: 700,
                  color: 'var(--text-primary)',
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
                      background: 'var(--surface-alt)',
                      border: '1px solid var(--border)',
                      fontWeight: 700,
                      color: 'var(--text-primary)',
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
                        border: '1px solid var(--border)',
                        background: 'var(--surface-alt)',
                        textAlign: 'center',
                        color: 'var(--text-disabled)',
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
                           border: '1px solid var(--border)',
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
                           <span style={{ fontSize: 10, fontWeight: 400, display: 'block', color: 'var(--text-disabled)' }}>
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
      <div style={{ marginTop: 12, fontSize: 11, color: 'var(--text-disabled)' }}>
        <strong>Legend:</strong>{' '}
        {ALLEN_CODES.map(c => {
          const r = ALLEN_RELATIONS[c];
          return (
            <span key={c} style={{ marginRight: 8 }}>
              <strong style={{ color: c > 0 ? 'var(--info)' : 'var(--negative)' }}>
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
