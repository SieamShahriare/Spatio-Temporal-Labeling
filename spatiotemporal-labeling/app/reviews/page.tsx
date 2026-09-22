'use client';

import { useEffect, useState } from 'react';
import { useRouter } from 'next/navigation';
import { listPendingReviews } from '@/lib/api';
import { PendingReviewItem } from '@/lib/types';
import { useAuth } from '@/lib/AuthContext';
import MethodologyGuide from '@/components/MethodologyGuide';

export default function ReviewQueuePage() {
  const router = useRouter();
  const { user, loading: authLoading } = useAuth();
  const [items, setItems] = useState<PendingReviewItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [search, setSearch] = useState('');
  const [showMethodology, setShowMethodology] = useState(false);

  useEffect(() => {
    if (!authLoading) {
      if (!user) {
        router.replace('/login');
      } else if (user.role !== 'reviewer' && user.role !== 'admin') {
        router.replace('/dashboard');
      }
    }
  }, [user, authLoading, router]);

  useEffect(() => {
    if (!user || (user.role !== 'reviewer' && user.role !== 'admin')) return;
    let cancelled = false;
    const fetchQueue = async () => {
      setLoading(true);
      setError('');
      try {
        const data = await listPendingReviews();
        if (!cancelled) setItems(data);
      } catch (e: unknown) {
        if (!cancelled) setError(e instanceof Error ? e.message : 'Failed to load review queue.');
      } finally {
        if (!cancelled) setLoading(false);
      }
    };
    fetchQueue();
    return () => { cancelled = true; };
  }, [user]);

  const filteredItems = items.filter(it => {
    if (!search.trim()) return true;
    const q = search.toLowerCase();
    return (
      it.stem_text.toLowerCase().includes(q) ||
      it.batch_name.toLowerCase().includes(q) ||
      it.annotator_username.toLowerCase().includes(q) ||
      String(it.stem_id).includes(q) ||
      String(it.batch_id).includes(q)
    );
  });

  if (authLoading) {
    return <div style={{ minHeight: '100vh', background: 'var(--background-page)' }} />;
  }

  if (!user || (user.role !== 'reviewer' && user.role !== 'admin')) {
    return null;
  }

  return (
    <main style={{ maxWidth: 1100, margin: '0 auto', padding: '32px 20px', fontFamily: 'system-ui, sans-serif' }}>
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 24 }}>
        <div>
          <button
            onClick={() => router.push('/dashboard')}
            style={{ background: 'none', border: 'none', cursor: 'pointer', color: 'var(--text-muted)', fontSize: 13, padding: 0, marginBottom: 6 }}
          >
            ← Dashboard
          </button>
          <h1 style={{ fontSize: 20, fontWeight: 700, margin: 0, color: 'var(--text-primary)' }}>
            Review Queue
          </h1>
          <p style={{ fontSize: 13, color: 'var(--text-muted)', margin: '4px 0 0' }}>
            {items.length} stem{items.length !== 1 ? 's' : ''} awaiting review · Evaluate against timeline sequencing methodology
          </p>
        </div>

        <button
          onClick={() => setShowMethodology(true)}
          style={{
            padding: '8px 16px',
            background: 'var(--surface-alt)',
            border: '1px solid var(--border)',
            borderRadius: 6,
            cursor: 'pointer',
            fontWeight: 600,
            fontSize: 13,
            color: '#2563eb',
            display: 'flex',
            alignItems: 'center',
            gap: 6,
          }}
        >
          📖 Methodology Guide
        </button>
      </div>

      <MethodologyGuide isOpen={showMethodology} onClose={() => setShowMethodology(false)} />

      {error && (
        <div style={{
          background: 'var(--error-bg)',
          border: '1px solid var(--error-border)',
          borderRadius: 6,
          padding: '8px 12px',
          marginBottom: 16,
          fontSize: 13,
          color: 'var(--error)',
          display: 'flex',
          justifyContent: 'space-between',
          alignItems: 'center',
        }}>
          <span>{error}</span>
          <button onClick={() => setError('')} style={{ background: 'none', border: 'none', cursor: 'pointer', color: 'var(--text-disabled)' }}>×</button>
        </div>
      )}

      <div style={{
        background: 'var(--surface)',
        border: '1px solid var(--border)',
        borderRadius: 10,
        padding: 16,
        marginBottom: 16,
        display: 'flex',
        gap: 12,
        alignItems: 'center',
      }}>
        <input
          type="text"
          value={search}
          onChange={e => setSearch(e.target.value)}
          placeholder="Search by text, batch name, annotator, or ID…"
          style={{
            flex: 1,
            padding: '8px 12px',
            border: '1px solid var(--border-input)',
            borderRadius: 6,
            fontSize: 14,
            background: 'var(--surface)',
            color: 'var(--text-primary)',
          }}
        />
        <span style={{ fontSize: 13, color: 'var(--text-muted)' }}>
          {filteredItems.length} of {items.length} shown
        </span>
      </div>

      <div style={{
        background: 'var(--surface)',
        border: '1px solid var(--border)',
        borderRadius: 10,
        overflow: 'hidden',
      }}>
        <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 13 }}>
          <thead>
            <tr style={{ background: 'var(--surface-alt)' }}>
              <th style={th}>Stem</th>
              <th style={th}>Batch</th>
              <th style={{ ...th, flex: 1 }}>Passage Preview</th>
              <th style={th}>Annotator</th>
              <th style={th}>Events</th>
              <th style={th}>Submitted</th>
              <th style={{ ...th, textAlign: 'right' }}>Action</th>
            </tr>
          </thead>
          <tbody>
            {loading ? (
              <tr><td colSpan={7} style={{ padding: 32, textAlign: 'center', color: 'var(--text-muted)' }}>Loading review queue…</td></tr>
            ) : filteredItems.length === 0 ? (
              <tr>
                <td colSpan={7} style={{ padding: 40, textAlign: 'center' }}>
                  <div style={{ fontSize: 24, marginBottom: 8 }}>🎉</div>
                  <div style={{ fontWeight: 600, color: 'var(--text-primary)' }}>No pending reviews!</div>
                  <div style={{ fontSize: 13, color: 'var(--text-muted)', marginTop: 4 }}>
                    {search ? 'No items match your search filter.' : 'All submitted stems have been reviewed.'}
                  </div>
                </td>
              </tr>
            ) : (
              filteredItems.map(item => (
                <tr key={item.batch_stem_id} style={{ borderBottom: '1px solid var(--border)' }}>
                  <td style={td}>
                    <strong>#{item.stem_id}</strong>
                  </td>
                  <td style={td}>
                    <span title={`Batch #${item.batch_id}`}>
                      {item.batch_name}
                    </span>
                  </td>
                  <td style={{ ...td, maxWidth: 360, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                    {item.stem_text.slice(0, 110)}{item.stem_text.length > 110 ? '…' : ''}
                  </td>
                  <td style={td}>
                    <span style={{ fontWeight: 500 }}>{item.annotator_username}</span>
                  </td>
                  <td style={td}>
                    <span style={{
                      padding: '2px 8px',
                      borderRadius: 12,
                      background: 'var(--surface-alt)',
                      fontWeight: 600,
                      fontSize: 12,
                    }}>
                      {item.event_count}
                    </span>
                  </td>
                  <td style={td}>
                    <span style={{ fontSize: 12, color: 'var(--text-muted)' }}>
                      {item.submitted_at ? new Date(item.submitted_at).toLocaleDateString() : 'N/A'}
                    </span>
                  </td>
                  <td style={{ ...td, textAlign: 'right' }}>
                    <button
                      onClick={() => router.push(`/annotate/${item.batch_id}/${item.batch_stem_id}?mode=review`)}
                      style={{
                        padding: '6px 14px',
                        background: '#2563eb',
                        color: '#fff',
                        border: 'none',
                        borderRadius: 6,
                        cursor: 'pointer',
                        fontWeight: 600,
                        fontSize: 12,
                      }}
                    >
                      Review →
                    </button>
                  </td>
                </tr>
              ))
            )}
          </tbody>
        </table>
      </div>
    </main>
  );
}

const th: React.CSSProperties = {
  padding: '10px 14px',
  textAlign: 'left',
  fontWeight: 600,
  color: 'var(--text-muted)',
  borderBottom: '1px solid var(--border)',
  fontSize: 12,
};

const td: React.CSSProperties = {
  padding: '12px 14px',
  color: 'var(--text-primary)',
  verticalAlign: 'middle',
};
