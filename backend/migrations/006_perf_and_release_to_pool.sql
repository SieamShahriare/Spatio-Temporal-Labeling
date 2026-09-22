-- ============================================================================
-- 006_perf_and_release_to_pool.sql
-- 1. Performance indexes for batch_stems, spans, and batches
-- 2. Update stem_reviews check constraint to allow 'release_to_pool'
-- ============================================================================

BEGIN;

-- 1. Performance indexes to eliminate sequential table scans
CREATE INDEX IF NOT EXISTS idx_batch_stems_stem_status ON batch_stems(stem_id, status);
CREATE INDEX IF NOT EXISTS idx_spans_batch_stem ON spans(batch_stem_id);
CREATE INDEX IF NOT EXISTS idx_spans_session ON spans(session_id);
CREATE INDEX IF NOT EXISTS idx_batches_status_expires ON batches(status, expires_at);

-- 2. Update stem_reviews decision constraint to include 'release_to_pool'
ALTER TABLE stem_reviews DROP CONSTRAINT IF EXISTS stem_reviews_decision_check;
ALTER TABLE stem_reviews ADD CONSTRAINT stem_reviews_decision_check 
    CHECK (decision IN ('accept', 're-evaluate', 'blacklist', 'release_to_pool'));

COMMIT;
