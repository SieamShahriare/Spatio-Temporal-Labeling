'use client';

import { useEffect } from 'react';
import { useParams, useRouter } from 'next/navigation';
import Annotator from '@/components/Annotator';
import { useGroupTaskSource } from '@/lib/annotationSources';
import { useAuth } from '@/lib/AuthContext';

// Thin wrapper — see app/annotate/[batch_id]/[stem_id]/page.tsx for the
// sibling batch route; both render the same <Annotator> component.
export default function GroupAnnotatePage() {
  const params = useParams<{ task_id: string }>();
  const taskId = parseInt(params.task_id);
  const router = useRouter();
  const { user, loading: authLoading } = useAuth();
  const source = useGroupTaskSource(taskId, user?.id ?? null);

  useEffect(() => {
    if (!authLoading && !user) {
      router.replace('/login');
    }
  }, [user, authLoading, router]);

  if (authLoading || !user) {
    return <div style={{ minHeight: '100vh', background: 'var(--background-page)' }} />;
  }

  if (!source.loading && source.notReady) {
    return (
      <main style={{ maxWidth: 700, margin: '0 auto', padding: 40, fontFamily: 'system-ui' }}>
        <p style={{ color: 'var(--text-muted)' }}>You are not a participant in this group task.</p>
        <button
          onClick={() => router.push(`/group-tasks/${taskId}`)}
          style={{ background: 'none', border: 'none', cursor: 'pointer', color: 'var(--text-muted)', fontSize: 13, padding: 0 }}
        >
          View task details →
        </button>
      </main>
    );
  }

  return <Annotator source={source} />;
}
