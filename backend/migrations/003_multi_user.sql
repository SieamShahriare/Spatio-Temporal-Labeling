-- ============================================================================
-- 003_multi_user — Multi-user auth, stems pool, batches, batch_stems
-- ============================================================================

-- Users
CREATE TABLE IF NOT EXISTS users (
    id            SERIAL PRIMARY KEY,
    email         TEXT NOT NULL UNIQUE,
    username      TEXT NOT NULL,
    password_hash TEXT NOT NULL,
    created_at    TIMESTAMPTZ DEFAULT now()
);

-- Stems pool
CREATE TABLE IF NOT EXISTS stems (
    id          SERIAL PRIMARY KEY,
    text        TEXT NOT NULL,
    word_count  INT NOT NULL DEFAULT 0,
    created_at  TIMESTAMPTZ DEFAULT now(),
    source      TEXT DEFAULT 'manual'
);

-- Batches
CREATE TABLE IF NOT EXISTS batches (
    id          SERIAL PRIMARY KEY,
    name        TEXT NOT NULL,
    owner_id    INT NOT NULL REFERENCES users(id),
    created_at  TIMESTAMPTZ DEFAULT now(),
    locked_at   TIMESTAMPTZ DEFAULT now(),
    expires_at  TIMESTAMPTZ NOT NULL,
    rebook_count INT NOT NULL DEFAULT 0,
    status      TEXT NOT NULL DEFAULT 'active'  -- 'active' | 'released' | 'expired'
);

-- Batch-stem join with per-stem annotation state
CREATE TABLE IF NOT EXISTS batch_stems (
    id            SERIAL PRIMARY KEY,
    batch_id      INT NOT NULL REFERENCES batches(id) ON DELETE CASCADE,
    stem_id       INT NOT NULL REFERENCES stems(id) ON DELETE CASCADE,
    status        TEXT NOT NULL DEFAULT 'not_started', -- 'not_started' | 'in_progress' | 'done'
    completed_by  INT REFERENCES users(id),
    completed_at  TIMESTAMPTZ,
    updated_at    TIMESTAMPTZ DEFAULT now(),
    UNIQUE(batch_id, stem_id)
);

-- Auth sessions (httpOnly cookie sessions)
CREATE TABLE IF NOT EXISTS auth_sessions (
    id          SERIAL PRIMARY KEY,
    user_id     INT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    token       TEXT NOT NULL UNIQUE,
    csrf_token  TEXT NOT NULL,
    created_at  TIMESTAMPTZ DEFAULT now(),
    expires_at  TIMESTAMPTZ NOT NULL
);

-- Index for fast session lookup by token
CREATE INDEX IF NOT EXISTS idx_auth_sessions_token ON auth_sessions(token);

-- Index for fast batch ownership lookups
CREATE INDEX IF NOT EXISTS idx_batches_owner ON batches(owner_id);

-- Index for batch_stems by batch
CREATE INDEX IF NOT EXISTS idx_batch_stems_batch ON batch_stems(batch_id);

-- Partial unique index to enforce one active lock per stem at the DB level
-- (kept commented because PostgreSQL partial indexes cannot use subqueries;
--  serializable FOR UPDATE in the booking transaction enforces the same invariant.)
-- CREATE UNIQUE INDEX IF NOT EXISTS idx_batch_stems_active_lock
--     ON batch_stems(stem_id)
--     WHERE EXISTS (
--         SELECT 1 FROM batches b
--         WHERE b.id = batch_stems.batch_id
--           AND b.expires_at > now()
--           AND b.status = 'active'
--     );

-- Extend spans with batch_stem_id (nullable for old session-based spans)
ALTER TABLE spans
    ADD COLUMN IF NOT EXISTS batch_stem_id INT REFERENCES batch_stems(id) ON DELETE CASCADE;

-- Extend relations with batch_stem_id
ALTER TABLE relations
    ADD COLUMN IF NOT EXISTS batch_stem_id INT REFERENCES batch_stems(id) ON DELETE CASCADE;
