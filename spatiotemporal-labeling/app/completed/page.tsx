'use client';

import { useEffect, useState, useCallback } from 'react';
import { useRouter } from 'next/navigation';
import { useAuth } from '@/lib/AuthContext';
import { listCompletedStems, exportBatchStemJson } from '@/lib/api';
import { CompletedStemItem } from '@/lib/types';

export default function CompletedStemsPage() {
  const router = useRouter();
  const { user, loading: authLoading } = useAuth();

  const [items, setItems] = useState<CompletedStemItem[]>([]);
  const [total, setTotal] = useState<number>(0);
  const [page, setPage] = useState<number>(1);
  const [pageSize] = useState<number>(15);
  const [search, setSearch] = useState<string>('');
  const [searchInput, setSearchInput] = useState<string>('');
  const [loading, setLoading] = useState<boolean>(true);
  const [error, setError] = useState<string>('');

  const loadStems = useCallback(async () => {
    setLoading(true);
    setError('');
    try {
      const data = await listCompletedStems({ search, page, page_size: pageSize });
      setItems(data.items);
      setTotal(data.total);
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : 'Failed to load completed stems.');
    } finally {
      setLoading(false);
    }
  }, [search, page, pageSize]);

  useEffect(() => {
    if (!authLoading && !user) {
      router.replace('/login');
      return;
    }
    if (user) {
      loadStems();
    }
  }, [user, authLoading, loadStems, router]);

  const handleSearchSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    setPage(1);
    setSearch(searchInput);
  };

  const totalPages = Math.ceil(total / pageSize) || 1;

  if (authLoading) {
    return <div style={{ minHeight: '100vh', background: 'var(--background-page)' }} />;
  }

  return (
    <main style={{ maxWidth: 1200, margin: '0 auto', padding: '32px 20px', fontFamily: 'system-ui, sans-serif' }}>
      {/* Top Header */}
      <div style={{ display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between', marginBottom: 24, flexWrap: 'wrap', gap: 12 }}>
        <div>
          <div style={{ display: 'flex', gap: 12, alignItems: 'center', marginBottom: 6 }}>
            <button
              onClick={() => router.push('/')}
              style={{ background: 'none', border: 'none', cursor: 'pointer', color: 'var(--text-muted)', fontSize: 13, padding: 0 }}
            >
              ← Dashboard
            </button>
            <span style={{ color: 'var(--border)' }}>/</span>
            <span style={{ fontSize: 13, color: 'var(--text-muted)' }}>Completed Annotations</span>
          </div>
          <h1 style={{ fontSize: 22, fontWeight: 700, margin: 0, display: 'flex', alignItems: 'center', gap: 8 }}>
            <span style={{ color: '#16a34a' }}>✓</span> Completed Stems
          </h1>
          <p style={{ fontSize: 13, color: 'var(--text-muted)', margin: '4px 0 0' }}>
            Browse and inspect finalized, reviewer-approved stem annotations with full temporal graphs and matrices in read-only mode.
          </p>
        </div>

        <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
          <button
            onClick={() => router.push('/stems')}
            style={btnStyle('var(--surface)', 'var(--text-primary)')}
          >
            Stem Pool
          </button>
          {(user?.role === 'reviewer' || user?.role === 'admin') && (
            <button
              onClick={() => router.push('/reviews')}
              style={{ ...btnStyle('#8b5cf6', '#fff'), border: 'none' }}
            >
              📋 Review Queue
            </button>
          )}
        </div>
      </div>

      {error && (
        <div style={{
          background: 'var(--error-bg)',
          border: '1px solid var(--error-border)',
          borderRadius: 8,
          padding: '10px 16px',
          marginBottom: 16,
          fontSize: 13,
          color: 'var(--error)',
        }}>
          {error}
        </div>
      )}

      {/* Search & Stats Bar */}
      <div style={{
        display: 'flex',
        justifyContent: 'space-between',
        alignItems: 'center',
        flexWrap: 'wrap',
        gap: 12,
        marginBottom: 16,
        padding: '12px 16px',
        background: 'var(--surface)',
        border: '1px solid var(--border)',
        borderRadius: 8,
      }}>
        <form onSubmit={handleSearchSubmit} style={{ display: 'flex', gap: 8, flex: '1 1 300px' }}>
          <input
            type="text"
            value={searchInput}
            onChange={e => setSearchInput(e.target.value)}
            placeholder="Search completed stem text, annotator, reviewer, or batch..."
            style={{
              flex: 1,
              padding: '8px 12px',
              border: '1px solid var(--border-input)',
              borderRadius: 6,
              fontSize: 13,
            }}
          />
          <button
            type="submit"
            style={{
              padding: '8px 16px',
              background: '#2563eb',
              color: '#fff',
              border: 'none',
              borderRadius: 6,
              fontWeight: 600,
              fontSize: 13,
              cursor: 'pointer',
            }}
          >
            Search
          </button>
          {search && (
            <button
              type="button"
              onClick={() => { setSearchInput(''); setSearch(''); setPage(1); }}
              style={btnStyle('var(--surface-alt)', 'var(--text-primary)')}
            >
              Clear
            </button>
          )}
        </form>

        <div style={{ fontSize: 13, color: 'var(--text-muted)' }}>
          Total Completed: <strong style={{ color: 'var(--text-primary)' }}>{total}</strong> stem{total !== 1 ? 's' : ''}
        </div>
      </div>

      {/* Stems Table */}
      <div style={{
        background: 'var(--surface)',
        border: '1px solid var(--border)',
        borderRadius: 10,
        overflow: 'hidden',
      }}>
        <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 13 }}>
          <thead>
            <tr style={{ background: 'var(--surface-alt)', borderBottom: '1px solid var(--border)' }}>
              <th style={th}>Stem ID</th>
              <th style={{ ...th, flex: 1 }}>Stem Text Preview</th>
              <th style={th}>Annotations</th>
              <th style={th}>Annotator</th>
              <th style={th}>Approved By</th>
              <th style={th}>Actions</th>
            </tr>
          </thead>
          <tbody>
            {loading ? (
              <tr>
                <td colSpan={6} style={{ padding: 36, textAlign: 'center', color: 'var(--text-muted)' }}>
                  Loading completed stems…
                </td>
              </tr>
            ) : items.length === 0 ? (
              <tr>
                <td colSpan={6} style={{ padding: 40, textAlign: 'center', color: 'var(--text-muted)' }}>
                  {search ? 'No completed stems match your search.' : 'No completed stems yet. Annotations will appear here once approved by a reviewer.'}
                </td>
              </tr>
            ) : (
              items.map(item => (
                <tr key={item.batch_stem_id} style={{ borderBottom: '1px solid var(--border)' }}>
                  <td style={{ ...td, fontWeight: 600 }}>#{item.stem_id}</td>
                  <td style={{ ...td, maxWidth: 380 }}>
                    <div style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', fontWeight: 500 }}>
                      {item.stem_text}
                    </div>
                    <div style={{ fontSize: 11, color: 'var(--text-muted)', marginTop: 2 }}>
                      {item.word_count} words · Batch: {item.batch_name}
                    </div>
                  </td>
                  <td style={td}>
                    <div style={{ display: 'flex', gap: 6, alignItems: 'center' }}>
                      <span style={{
                        padding: '2px 8px',
                        borderRadius: 12,
                        fontSize: 11,
                        fontWeight: 600,
                        background: 'rgba(37, 99, 235, 0.12)',
                        color: '#2563eb',
                      }}>
                        {item.event_count} Events
                      </span>
                      {item.time_count > 0 && (
                        <span style={{
                          padding: '2px 8px',
                          borderRadius: 12,
                          fontSize: 11,
                          fontWeight: 600,
                          background: 'rgba(217, 119, 6, 0.12)',
                          color: '#d97706',
                        }}>
                          {item.time_count} Times
                        </span>
                      )}
                    </div>
                  </td>
                  <td style={td}>
                    <div style={{ fontWeight: 500 }}>{item.completed_by?.username ?? '—'}</div>
                    <div style={{ fontSize: 11, color: 'var(--text-muted)' }}>
                      {item.completed_at ? new Date(item.completed_at).toLocaleDateString() : ''}
                    </div>
                  </td>
                  <td style={td}>
                    <div style={{ fontWeight: 500, color: '#16a34a' }}>
                      ✓ {item.reviewer?.username ?? 'Reviewer'}
                    </div>
                    {item.latest_review?.comment && (
                      <div
                        style={{ fontSize: 11, color: 'var(--text-muted)', fontStyle: 'italic', maxWidth: 180, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}
                        title={`Reviewer comment: ${item.latest_review.comment}`}
                      >
                        &ldquo;{item.latest_review.comment}&rdquo;
                      </div>
                    )}
                  </td>
                  <td style={td}>
                    <div style={{ display: 'flex', gap: 6, alignItems: 'center' }}>
                      <button
                        onClick={() => router.push(`/completed/${item.batch_stem_id}`)}
                        style={{
                          padding: '5px 12px',
                          background: '#16a34a',
                          color: '#fff',
                          border: 'none',
                          borderRadius: 6,
                          fontSize: 12,
                          fontWeight: 600,
                          cursor: 'pointer',
                          display: 'inline-flex',
                          alignItems: 'center',
                          gap: 4,
                        }}
                      >
                        👁️ View
                      </button>
                      <a
                        href={exportBatchStemJson(item.batch_stem_id)}
                        download
                        title="Download JSON export"
                        style={{
                          ...btnStyle('var(--surface-alt)', 'var(--text-primary)'),
                          fontSize: 12,
                          textDecoration: 'none',
                          padding: '5px 10px',
                        }}
                      >
                        ⬇ JSON
                      </a>
                    </div>
                  </td>
                </tr>
              ))
            )}
          </tbody>
        </table>
      </div>

      {/* Pagination */}
      {totalPages > 1 && (
        <div style={{ display: 'flex', gap: 8, justifyContent: 'center', alignItems: 'center', marginTop: 20 }}>
          <button
            onClick={() => setPage(p => Math.max(1, p - 1))}
            disabled={page <= 1}
            style={btnStyle('var(--surface)', 'var(--text-primary)')}
          >
            ← Prev
          </button>
          <span style={{ fontSize: 13, color: 'var(--text-muted)' }}>
            Page {page} of {totalPages}
          </span>
          <button
            onClick={() => setPage(p => Math.min(totalPages, p + 1))}
            disabled={page >= totalPages}
            style={btnStyle('var(--surface)', 'var(--text-primary)')}
          >
            Next →
          </button>
        </div>
      )}
    </main>
  );
}

const th: React.CSSProperties = {
  padding: '10px 14px',
  textAlign: 'left',
  fontWeight: 600,
  fontSize: 12,
  color: 'var(--text-muted)',
  textTransform: 'uppercase',
  letterSpacing: '0.04em',
};

const td: React.CSSProperties = {
  padding: '12px 14px',
  verticalAlign: 'middle',
};

function btnStyle(bg: string, color: string): React.CSSProperties {
  return {
    padding: '7px 14px',
    background: bg,
    color,
    border: '1px solid var(--border-input)',
    borderRadius: 6,
    cursor: 'pointer',
    fontWeight: 500,
    fontSize: 13,
    display: 'inline-flex',
    alignItems: 'center',
    gap: 4,
  };
}
