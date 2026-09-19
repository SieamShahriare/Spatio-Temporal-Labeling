'use client';

import { useEffect } from 'react';
import { useParams, useRouter } from 'next/navigation';
import Annotator from '@/components/Annotator';
import { useBatchStemSource } from '@/lib/annotationSources';
import { useAuth } from '@/lib/AuthContext';

// Thin wrapper: all annotation UI lives in the shared <Annotator> component.
// See context/group_workflow_redesign.md §7 — this and the group-annotate
// route render the exact same component so they can never drift apart.
export default function AnnotateBatchStemPage() {
  const params = useParams<{ batch_id: string; stem_id: string }>();
  const batchId = parseInt(params.batch_id);
  const stemId = parseInt(params.stem_id);
  const router = useRouter();
  const { user, loading: authLoading } = useAuth();
  const source = useBatchStemSource(batchId, stemId);

  useEffect(() => {
    if (!authLoading && !user) {
      router.replace('/login');
    }
  }, [user, authLoading, router]);

  if (authLoading || !user) {
    return <div style={{ minHeight: '100vh', background: 'var(--background-page)' }} />;
  }

  return <Annotator source={source} />;
}
