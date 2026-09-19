'use client';

import { AgreementDetails, GroupMemberOut, GroupTaskStatus } from '@/lib/types';

interface Props {
  status: GroupTaskStatus;
  krippendorffAlpha: number | null;
  cohensKappaAvg: number | null;
  fleissKappa: number | null;
  acceptanceThreshold: number;
  agreementDetails: AgreementDetails | null;
  members: GroupMemberOut[];
}

const STATUS_META: Record<GroupTaskStatus, { label: string; bg: string; color: string }> = {
  event_pending: { label: 'Awaiting Events', bg: 'var(--surface-alt)', color: 'var(--text-muted)' },
  timelines_pending: { label: 'Timelines In Progress', bg: 'var(--warning-bg)', color: 'var(--warning-text)' },
  computing: { label: 'Computing Agreement', bg: 'var(--warning-bg)', color: 'var(--warning-text)' },
  accepted: { label: 'Accepted', bg: 'var(--success-bg)', color: 'var(--success)' },
  accepted_flagged: { label: 'Accepted (Flagged)', bg: 'var(--warning-bg)', color: 'var(--warning-text)' },
  adjudication: { label: 'Needs Adjudication', bg: 'var(--error-bg)', color: 'var(--error)' },
  rejected: { label: 'Rejected', bg: 'var(--error-bg)', color: 'var(--error)' },
};

function ScoreCard({ label, value, hint }: { label: string; value: number | null; hint: string }) {
  const color = value === null ? 'var(--text-disabled)' : value >= 0.8 ? 'var(--success)' : value >= 0.6 ? '#f59e0b' : value >= 0.4 ? '#f59e0b' : 'var(--error)';
  return (
    <div style={{ flex: '1 1 160px', background: 'var(--surface)', border: '1px solid var(--border)', borderRadius: 10, padding: 16 }}>
      <div style={{ fontSize: 11, color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: '0.05em', marginBottom: 6 }}>{label}</div>
      <div style={{ fontSize: 26, fontWeight: 700, color, fontFamily: 'monospace' }}>
        {value === null ? '—' : value.toFixed(3)}
      </div>
      <div style={{ fontSize: 11, color: 'var(--text-disabled)', marginTop: 4 }}>{hint}</div>
    </div>
  );
}

export default function AgreementDashboard({
  status, krippendorffAlpha, cohensKappaAvg, fleissKappa, acceptanceThreshold, agreementDetails, members,
}: Props) {
  const meta = STATUS_META[status] ?? STATUS_META.event_pending;
  const memberById = new Map(members.map(m => [m.user_id, m]));

  return (
    <div>
      <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 16 }}>
        <span style={{ padding: '4px 12px', borderRadius: 20, fontSize: 12, fontWeight: 600, background: meta.bg, color: meta.color }}>
          {meta.label}
        </span>
        <span style={{ fontSize: 12, color: 'var(--text-disabled)' }}>
          Acceptance threshold: κ/α ≥ {acceptanceThreshold.toFixed(2)}
        </span>
      </div>

      <div style={{ display: 'flex', gap: 12, flexWrap: 'wrap', marginBottom: 20 }}>
        <ScoreCard label="Krippendorff's α (primary)" value={krippendorffAlpha} hint="Timeline positions, 3+ raters" />
        <ScoreCard label="Cohen's κ (avg pairwise)" value={cohensKappaAvg} hint="Allen relations, pairwise" />
        <ScoreCard label="Fleiss' κ" value={fleissKappa} hint="Allen relations, multi-rater" />
      </div>

      {agreementDetails && (
        <div style={{ background: 'var(--surface)', border: '1px solid var(--border)', borderRadius: 10, overflow: 'hidden' }}>
          <div style={{ padding: '10px 14px', background: 'var(--surface-alt)', borderBottom: '1px solid var(--border)', fontWeight: 600, fontSize: 12 }}>
            PER-EVENT TIMELINE POSITIONS
          </div>
          <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 12 }}>
            <thead>
              <tr style={{ background: 'var(--surface-alt)' }}>
                <th style={{ textAlign: 'left', padding: '8px 12px', color: 'var(--text-muted)' }}>Event (span id)</th>
                {agreementDetails.member_ids.map(mid => (
                  <th key={mid} style={{ textAlign: 'left', padding: '8px 12px', color: 'var(--text-muted)' }}>
                    {memberById.get(mid)?.username ?? `Annotator ${mid}`}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {Object.entries(agreementDetails.per_event).map(([spanId, byMember]) => (
                <tr key={spanId} style={{ borderTop: '1px solid var(--border)' }}>
                  <td style={{ padding: '8px 12px', fontFamily: 'monospace' }}>#{spanId}</td>
                  {agreementDetails.member_ids.map(mid => {
                    const pos = byMember[String(mid)];
                    return (
                      <td key={mid} style={{ padding: '8px 12px', fontFamily: 'monospace' }}>
                        {pos ? `${pos[0].toFixed(1)} – ${pos[1].toFixed(1)}` : '—'}
                      </td>
                    );
                  })}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
