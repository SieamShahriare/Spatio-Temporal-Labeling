'use client';

import { useEffect, useState } from 'react';
import { useRouter } from 'next/navigation';
import { listStems, createBatch, importStems } from '@/lib/api';
import { StemOut, StemsListResponse } from '@/lib/types';
import { useAuth } from '@/lib/AuthContext';

type StatusFilter = 'all' | 'available' | 'booked' | 'completed' | 'mine';

const STATUS_OPTIONS: { value: StatusFilter; label: string }[] = [
  { value: 'all', label: 'All' },
  { value: 'available', label: 'Available' },
  { value: 'booked', label: 'Booked' },
  { value: 'completed', label: 'Completed' },
  { value: 'mine', label: 'Booked by me' },
];

function formatWhen(ts: string | null): string {
  if (!ts) return '';
  const d = new Date(ts);
  const now = new Date();
  const diffMs = d.getTime() - now.getTime();
  const diffMin = Math.round(diffMs / 60000);
  if (diffMin <= 0) return 'now';
  if (diffMin < 60) return `in ${diffMin}m`;
  const h = Math.floor(diffMin / 60);
  const m = diffMin % 60;
  return `in ${h}h ${m}m`;
}

function statusBadge(s: StemOut) {
  if (s.state === 'available') {
    return (
      <span style={{
        padding: '2px 8px',
        borderRadius: 20,
        fontSize: 11,
        fontWeight: 600,
        background: 'var(--success-bg)',
        color: 'var(--success)',
      }}>available</span>
    );
  }
  if (s.state === 'booked' && s.booked_by) {
    return (
      <span style={{
        padding: '2px 8px',
        borderRadius: 20,
        fontSize: 11,
        fontWeight: 600,
        background: 'var(--warning-bg)',
        color: 'var(--warning-text)',
      }}>
        Locked by {s.booked_by.username} · free {formatWhen(s.locked_until ?? null)}
      </span>
    );
  }
  if (s.state === 'completed' && s.completed_by) {
    return (
      <span style={{
        padding: '2px 8px',
        borderRadius: 20,
        fontSize: 11,
        fontWeight: 600,
        background: 'var(--success-bg)',
        color: 'var(--success)',
      }}>
        Done by {s.completed_by.username} · {s.completed_at ? new Date(s.completed_at).toLocaleDateString() : ''}
      </span>
    );
  }
  return <span style={{ fontSize: 11, color: 'var(--text-muted)' }}>{s.state}</span>;
}

function parseTextarea(text: string): string[] {
  if (!text.trim()) return [];
  return text.split(/\n\s*\n/).map(t => t.trim()).filter(t => t.length > 0);
}

function csvSplitLine(line: string): string[] {
  const result: string[] = [];
  let current = '';
  let inQuotes = false;
  for (let i = 0; i < line.length; i++) {
    const char = line[i];
    if (char === '"') {
      inQuotes = !inQuotes;
    } else if (char === ',' && !inQuotes) {
      result.push(current);
      current = '';
    } else {
      current += char;
    }
  }
  result.push(current);
  return result;
}

function parseFileContent(text: string, filename: string): string[] {
  const ext = filename.split('.').pop()?.toLowerCase() || '';
  if (ext === 'txt') {
    return parseTextarea(text);
  }
  if (ext === 'csv') {
    const textClean = text.replace(/^\uFEFF/, '');
    const lines = textClean.split(/\r?\n/);
    if (lines.length < 2) return [];
    const header = csvSplitLine(lines[0]).map(h => h.trim().toLowerCase());
    const textColumns = ['text', 'stem_text', 'stem', 'passage', 'content', 'story', 'description'];
    let textIdx = -1;
    for (const key of textColumns) {
      const idx = header.indexOf(key);
      if (idx !== -1) {
        textIdx = idx;
        break;
      }
    }
    if (textIdx === -1) return [];
    const results: string[] = [];
    for (let i = 1; i < lines.length; i++) {
      const trimmed = lines[i].trim();
      if (!trimmed) continue;
      const cols = csvSplitLine(trimmed);
      if (cols.length > textIdx) {
        const t = cols[textIdx].trim();
        if (t) results.push(t);
      }
    }
    return results;
  }
  if (ext === 'json') {
    try {
      const data = JSON.parse(text) as Array<string | { text?: string }>;
      if (!Array.isArray(data)) return [];
      return data.map((item) => {
        if (typeof item === 'string') return item.trim();
        if (item && typeof item.text === 'string') return item.text.trim();
        return '';
      }).filter((t): t is string => t.length > 0);
    } catch {
      return [];
    }
  }
  return [];
}

export default function StemsPage() {
  const router = useRouter();
  const { user, loading: authLoading } = useAuth();
  const [items, setItems] = useState<StemOut[]>([]);
  const [loading, setLoading] = useState(true);
  const [search, setSearch] = useState('');
  const [status, setStatus] = useState<StatusFilter>('all');
  const [page, setPage] = useState(1);
  const [total, setTotal] = useState(0);
  const [selected, setSelected] = useState<Set<number>>(new Set());
  const [batchName, setBatchName] = useState('');
  const [booking, setBooking] = useState(false);
  const [error, setError] = useState('');
  const [conflicts, setConflicts] = useState<Set<number>>(new Set());
  const [refreshKey, setRefreshKey] = useState(0);
  const [showImport, setShowImport] = useState(false);
  const [importText, setImportText] = useState('');
  const [importFile, setImportFile] = useState<File | null>(null);
  const [importParsed, setImportParsed] = useState<string[]>([]);
  const [importing, setImporting] = useState(false);

  const pageSize = 20;

  useEffect(() => {
    if (!authLoading && !user) {
      router.replace('/login');
    }
  }, [user, authLoading, router]);

  useEffect(() => {
    if (!user) return;
    let cancelled = false;
    (async () => {
      setLoading(true);
      setError('');
      try {
        const data: StemsListResponse = await listStems({ search, status, page });
        if (!cancelled) {
          setItems(data.items);
          setTotal(data.total);
          setPage(data.page);
          setSelected(prev => {
            // Keep selections across pages and filters; only drop stems that are no longer available.
            const next = new Set(prev);
            data.items.forEach(it => { if (it.state !== 'available') next.delete(it.id); });
            return next;
          });
        }
      } catch (e: unknown) {
        if (!cancelled) setError(e instanceof Error ? e.message : 'Failed to load stems.');
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => { cancelled = true; };
  }, [user, search, status, page, refreshKey]);

  const totalPages = Math.max(1, Math.ceil(total / pageSize));

  const toggleSelect = (id: number, available: boolean) => {
    if (!available) return;
    setSelected(prev => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id); else next.add(id);
      return next;
    });
  };

  const handleBook = async () => {
    if (selected.size === 0) return;
    if (!batchName.trim()) { setError('Please name your batch.'); return; }
    setBooking(true);
    setError('');
    try {
      await createBatch({ name: batchName.trim(), stem_ids: Array.from(selected) });
      setSelected(new Set());
      setBatchName('');
      router.push('/dashboard');
    } catch (e: unknown) {
      const msg = e instanceof Error ? e.message : 'Booking failed.';
      setError(msg);
      try {
        const parsed = JSON.parse(msg);
        if (Array.isArray(parsed.conflict_stem_ids)) {
          setConflicts(new Set(parsed.conflict_stem_ids));
        }
      } catch {
        // not a structured conflict
      }
      setTimeout(() => {
        setConflicts(new Set());
        setRefreshKey(k => k + 1);
      }, 2000);
    } finally {
      setBooking(false);
    }
  };

  const handleFileChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;
    setImportFile(file);
    const reader = new FileReader();
    reader.onload = (ev) => {
      const text = ev.target?.result as string;
      const parsed = parseFileContent(text, file.name);
      setImportParsed(parsed);
    };
    reader.readAsText(file);
  };

  const textareaTexts = parseTextarea(importText);
  const allImportTexts = [...textareaTexts, ...importParsed];

  const handleImport = async () => {
    if (allImportTexts.length === 0) return;
    setImporting(true);
    setError('');
    try {
      const formData = new FormData();
      if (textareaTexts.length > 0) {
        formData.append('texts', JSON.stringify(textareaTexts));
      }
      if (importFile) {
        formData.append('file', importFile);
      }
      const result = await importStems(formData);
      setShowImport(false);
      setImportText('');
      setImportFile(null);
      setImportParsed([]);
      setRefreshKey(k => k + 1);
      setError(`Imported: ${result.created} created, ${result.skipped} skipped`);
    } catch (e: unknown) {
      const msg = e instanceof Error ? e.message : 'Import failed.';
      setError(msg);
    } finally {
      setImporting(false);
    }
  };

  if (authLoading) {
    return <div style={{ minHeight: '100vh', background: 'var(--background-page)' }} />;
  }

  return (
    <main style={{ maxWidth: 1100, margin: '0 auto', padding: '32px 20px', fontFamily: 'system-ui, sans-serif' }}>
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 24 }}>
        <div>
          <button
            onClick={() => router.push('/')}
            style={{ background: 'none', border: 'none', cursor: 'pointer', color: 'var(--text-muted)', fontSize: 13, padding: 0, marginBottom: 6 }}
          >
            ← Dashboard
          </button>
          <h1 style={{ fontSize: 18, fontWeight: 700, margin: 0 }}>Stems Browser</h1>
           <p style={{ fontSize: 13, color: 'var(--text-muted)', margin: '2px 0 0' }}>
             {total} stems · select available stems to book them into a batch
          </p>
        </div>
        <button
          onClick={() => setShowImport(true)}
          style={{
            padding: '8px 16px',
            background: '#2563eb',
            color: '#fff',
            border: 'none',
            borderRadius: 6,
            cursor: 'pointer',
            fontWeight: 600,
            fontSize: 13,
          }}
        >
          Add stems
        </button>
      </div>

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
          <button onClick={() => setError('')} style={{ background: 'none', border: 'none', cursor: 'pointer', color: 'var(--text-disabled)', fontSize: 16 }}>×</button>
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
        flexWrap: 'wrap',
        alignItems: 'center',
      }}>
        <input
          type="text"
          value={search}
          onChange={e => { setSearch(e.target.value); setPage(1); }}
          placeholder="Search by text, id, who booked, or who completed…"
          style={{
            flex: '1 1 260px',
            padding: '8px 12px',
            border: '1px solid var(--border-input)',
            borderRadius: 6,
            fontSize: 14,
            boxSizing: 'border-box',
          }}
        />
        <select
          value={status}
          onChange={e => { setStatus(e.target.value as StatusFilter); setPage(1); }}
          style={{
            padding: '8px 12px',
            border: '1px solid var(--border-input)',
            borderRadius: 6,
            fontSize: 14,
            background: 'var(--surface)',
            color: 'var(--text-primary)',
          }}
        >
          {STATUS_OPTIONS.map(o => <option key={o.value} value={o.value}>{o.label}</option>)}
        </select>
        <div style={{ flex: '1 1 100%', display: 'flex', gap: 8, alignItems: 'center', flexWrap: 'wrap' }}>
          <input
            type="text"
            value={batchName}
            onChange={e => setBatchName(e.target.value)}
            placeholder="Batch name"
            style={{
              flex: '1 1 200px',
              padding: '8px 12px',
              border: '1px solid var(--border-input)',
              borderRadius: 6,
              fontSize: 14,
              boxSizing: 'border-box',
            }}
          />
          <button
            onClick={handleBook}
            disabled={booking || selected.size === 0}
            style={{
              padding: '8px 20px',
              background: booking || selected.size === 0 ? 'var(--text-disabled)' : '#2563eb',
              color: '#fff',
              border: 'none',
              borderRadius: 6,
              cursor: booking || selected.size === 0 ? 'not-allowed' : 'pointer',
              fontWeight: 600,
              fontSize: 13,
            }}
          >
            {booking ? 'Booking…' : `Book ${selected.size} stem${selected.size !== 1 ? 's' : ''}`}
          </button>
          <span style={{ fontSize: 12, color: 'var(--text-muted)' }}>
            {selected.size} selected
          </span>
        </div>
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
               <th style={th}>Select</th>
               <th style={th}>ID</th>
               <th style={{ ...th, flex: 1 }}>Preview</th>
               <th style={th}>Len</th>
               <th style={th}>Status</th>
             </tr>
           </thead>
           <tbody>
             {loading ? (
               <tr><td colSpan={5} style={{ padding: 24, textAlign: 'center', color: 'var(--text-muted)' }}>Loading…</td></tr>
             ) : items.length === 0 ? (
               <tr><td colSpan={5} style={{ padding: 24, textAlign: 'center', color: 'var(--text-muted)' }}>No stems found.</td></tr>
             ) : (
               items.map(s => {
                 const isAvailable = s.state === 'available';
                 const isConflict = conflicts.has(s.id);
                 return (
                   <tr
                     key={s.id}
                     style={{
                       borderBottom: '1px solid var(--border)',
                       background: isConflict ? 'var(--error-bg)' : undefined,
                     }}
                   >
                     <td style={{ ...td, padding: '6px 10px' }}>
                       <input
                         type="checkbox"
                         checked={selected.has(s.id)}
                         disabled={!isAvailable}
                         onChange={() => toggleSelect(s.id, isAvailable)}
                       />
                     </td>
                     <td style={td}>{s.id}</td>
                    <td style={{ ...td, maxWidth: 400, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                      {s.text.slice(0, 120)}{s.text.length > 120 ? '…' : ''}
                    </td>
                    <td style={td}>{s.word_count}</td>
                    <td style={td}>{statusBadge(s)}</td>
                  </tr>
                );
              })
            )}
          </tbody>
        </table>
      </div>

      {totalPages > 1 && (
        <div style={{ display: 'flex', gap: 8, justifyContent: 'center', marginTop: 16 }}>
          <button
            onClick={() => setPage(p => Math.max(1, p - 1))}
            disabled={page <= 1}
            style={btnStyle('var(--surface)', 'var(--text-primary)')}
          >
            ← Prev
          </button>
          <span style={{ fontSize: 13, color: 'var(--text-muted)', alignSelf: 'center' }}>Page {page} of {totalPages}</span>
          <button
            onClick={() => setPage(p => Math.min(totalPages, p + 1))}
            disabled={page >= totalPages}
            style={btnStyle('var(--surface)', 'var(--text-primary)')}
          >
            Next →
          </button>
        </div>
      )}

      {showImport && (
        <div style={{
          position: 'fixed',
          inset: 0,
          background: 'rgba(0,0,0,0.5)',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          zIndex: 1000,
        }}>
          <div style={{
            background: 'var(--surface)',
            border: '1px solid var(--border)',
            borderRadius: 10,
            padding: 24,
            width: '100%',
            maxWidth: 560,
            maxHeight: '90vh',
            overflow: 'auto',
          }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 16 }}>
              <h2 style={{ fontSize: 16, fontWeight: 700, margin: 0 }}>Add stems</h2>
              <button
                onClick={() => setShowImport(false)}
                style={{ background: 'none', border: 'none', cursor: 'pointer', fontSize: 18, color: 'var(--text-muted)' }}
              >×</button>
            </div>

            <textarea
              value={importText}
              onChange={e => setImportText(e.target.value)}
              placeholder="Paste passages here — separate each passage with a blank line."
              style={{
                width: '100%',
                minHeight: 140,
                padding: 10,
                border: '1px solid var(--border-input)',
                borderRadius: 6,
                fontSize: 13,
                fontFamily: 'system-ui, sans-serif',
                boxSizing: 'border-box',
                resize: 'vertical',
                marginBottom: 12,
              }}
            />

            <div style={{ marginBottom: 16 }}>
              <label style={{
                display: 'inline-block',
                padding: '8px 16px',
                background: 'var(--surface-alt)',
                border: '1px solid var(--border)',
                borderRadius: 6,
                cursor: 'pointer',
                fontSize: 13,
                fontWeight: 500,
              }}>
                {importFile ? `File: ${importFile.name}` : 'Choose file (.txt / .csv / .json)'}
                <input
                  type="file"
                  accept=".txt,.csv,.json"
                  onChange={handleFileChange}
                  style={{ display: 'none' }}
                />
              </label>
              {importFile && (
                <button
                  onClick={() => { setImportFile(null); setImportParsed([]); }}
                  style={{
                    marginLeft: 8,
                    background: 'none',
                    border: 'none',
                    cursor: 'pointer',
                    color: 'var(--text-muted)',
                    fontSize: 12,
                    textDecoration: 'underline',
                  }}
                >
                  Clear
                </button>
              )}
            </div>

            <div style={{
              background: 'var(--surface-alt)',
              border: '1px solid var(--border)',
              borderRadius: 6,
              padding: 12,
              marginBottom: 16,
              fontSize: 13,
            }}>
              <strong>{allImportTexts.length} stem{allImportTexts.length !== 1 ? 's' : ''} detected</strong>
              {allImportTexts.length > 0 && (
                <div style={{ marginTop: 8, color: 'var(--text-muted)' }}>
                  {allImportTexts.slice(0, 3).map((t, i) => (
                    <div key={i} style={{ marginBottom: 4, whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>
                      {i + 1}. {t.slice(0, 80)}{t.length > 80 ? '…' : ''}
                    </div>
                  ))}
                  {allImportTexts.length > 3 && (
                    <div style={{ color: 'var(--text-muted)' }}>…and {allImportTexts.length - 3} more</div>
                  )}
                </div>
              )}
            </div>

            <div style={{ display: 'flex', gap: 8, justifyContent: 'flex-end' }}>
              <button
                onClick={() => setShowImport(false)}
                disabled={importing}
                style={btnStyle('var(--surface)', 'var(--text-primary)')}
              >
                Cancel
              </button>
              <button
                onClick={handleImport}
                disabled={importing || allImportTexts.length === 0}
                style={{
                  padding: '8px 20px',
                  background: importing || allImportTexts.length === 0 ? 'var(--text-disabled)' : '#2563eb',
                  color: '#fff',
                  border: 'none',
                  borderRadius: 6,
                  cursor: importing || allImportTexts.length === 0 ? 'not-allowed' : 'pointer',
                  fontWeight: 600,
                  fontSize: 13,
                }}
              >
                {importing ? 'Importing…' : `Import ${allImportTexts.length} stem${allImportTexts.length !== 1 ? 's' : ''}`}
              </button>
            </div>
          </div>
        </div>
      )}
    </main>
  );
}

const th: React.CSSProperties = {
  padding: '10px',
  textAlign: 'left',
  fontWeight: 600,
  color: 'var(--text-muted)',
  borderBottom: '1px solid var(--border)',
  fontSize: 12,
};

const td: React.CSSProperties = {
  padding: '10px',
  color: 'var(--text-primary)',
  verticalAlign: 'middle',
};

const btnStyle = (bg: string, color: string): React.CSSProperties => ({
  padding: '6px 14px',
  background: bg,
  color,
  border: 'none',
  borderRadius: 6,
  cursor: 'pointer',
  fontWeight: 500,
  fontSize: 13,
});
