-- ============================================================================
-- 005_review_system.sql — User roles, stem reviews, blacklist/unannotable support,
-- and review status transitions (pending-review, done, re-evaluate, blacklisted)
-- ============================================================================

BEGIN;

-- 1. Add role to users table (default 'annotator')
ALTER TABLE users ADD COLUMN IF NOT EXISTS role TEXT NOT NULL DEFAULT 'annotator';
CREATE INDEX IF NOT EXISTS idx_users_role ON users(role);

-- 2. Add blacklisting/unannotable columns to stems table
ALTER TABLE stems ADD COLUMN IF NOT EXISTS is_blacklisted BOOLEAN DEFAULT FALSE;
ALTER TABLE stems ADD COLUMN IF NOT EXISTS blacklist_reason TEXT;
ALTER TABLE stems ADD COLUMN IF NOT EXISTS blacklisted_by INT REFERENCES users(id);
ALTER TABLE stems ADD COLUMN IF NOT EXISTS blacklisted_at TIMESTAMPTZ;
CREATE INDEX IF NOT EXISTS idx_stems_blacklisted ON stems(is_blacklisted);

-- 3. Add reviewer tracking to batch_stems table
ALTER TABLE batch_stems ADD COLUMN IF NOT EXISTS reviewer_id INT REFERENCES users(id);
ALTER TABLE batch_stems ADD COLUMN IF NOT EXISTS reviewed_at TIMESTAMPTZ;

-- 4. Create stem_reviews table for review feedback and history
CREATE TABLE IF NOT EXISTS stem_reviews (
    id            SERIAL PRIMARY KEY,
    batch_stem_id INT NOT NULL REFERENCES batch_stems(id) ON DELETE CASCADE,
    stem_id       INT NOT NULL REFERENCES stems(id) ON DELETE CASCADE,
    reviewer_id   INT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    decision      TEXT NOT NULL CHECK (decision IN ('accept', 're-evaluate', 'blacklist')),
    comment       TEXT,
    created_at    TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_stem_reviews_batch_stem ON stem_reviews(batch_stem_id);
CREATE INDEX IF NOT EXISTS idx_stem_reviews_stem ON stem_reviews(stem_id);
CREATE INDEX IF NOT EXISTS idx_stem_reviews_reviewer ON stem_reviews(reviewer_id);

COMMIT;
