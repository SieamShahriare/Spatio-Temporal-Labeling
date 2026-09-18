-- ============================================================================
-- 004_fix_schema_and_orphans.sql — Fix schema, eliminate negative ID hack,
-- restore foreign keys with ON DELETE CASCADE, add check constraints and partial indexes.
-- ============================================================================

BEGIN;

-- 1. Recover orphan session IDs in annotation_sessions
INSERT INTO annotation_sessions (id, username, stem_text, status, created_at)
SELECT DISTINCT s_id, 'legacy_recovered', 'Recovered annotation session ' || s_id::text, 'done', now()
FROM (
    SELECT session_id AS s_id FROM spans WHERE session_id > 0
    UNION
    SELECT session_id AS s_id FROM relations WHERE session_id > 0
    UNION
    SELECT session_id AS s_id FROM matrix_snapshots WHERE session_id > 0
) combined
WHERE s_id NOT IN (SELECT id FROM annotation_sessions)
ON CONFLICT (id) DO NOTHING;

SELECT setval(
    pg_get_serial_sequence('annotation_sessions', 'id'),
    COALESCE((SELECT MAX(id) FROM annotation_sessions), 1)
);

-- 2. Extend matrix_snapshots with batch_stem_id
ALTER TABLE matrix_snapshots ADD COLUMN IF NOT EXISTS batch_stem_id INT;

-- 3. Make session_id nullable on spans, relations, matrix_snapshots
ALTER TABLE spans ALTER COLUMN session_id DROP NOT NULL;
ALTER TABLE relations ALTER COLUMN session_id DROP NOT NULL;
ALTER TABLE matrix_snapshots ALTER COLUMN session_id DROP NOT NULL;

-- 4. Migrate negative-ID pseudo-sessions to batch_stem_id
UPDATE matrix_snapshots
SET batch_stem_id = ABS(session_id),
    session_id = NULL
WHERE session_id < 0;

UPDATE spans
SET batch_stem_id = COALESCE(batch_stem_id, ABS(session_id)),
    session_id = NULL
WHERE session_id < 0;

UPDATE relations
SET batch_stem_id = COALESCE(batch_stem_id, ABS(session_id)),
    session_id = NULL
WHERE session_id < 0;

-- 5. Clean up old unique constraint on relations and create partial indexes
ALTER TABLE relations DROP CONSTRAINT IF EXISTS relations_session_id_span_i_id_span_j_id_key;

CREATE UNIQUE INDEX IF NOT EXISTS uq_relations_session
ON relations(session_id, span_i_id, span_j_id)
WHERE session_id IS NOT NULL;

CREATE UNIQUE INDEX IF NOT EXISTS uq_relations_batch_stem
ON relations(batch_stem_id, span_i_id, span_j_id)
WHERE batch_stem_id IS NOT NULL;

CREATE UNIQUE INDEX IF NOT EXISTS uq_matrix_snapshots_session
ON matrix_snapshots(session_id)
WHERE session_id IS NOT NULL;

CREATE UNIQUE INDEX IF NOT EXISTS uq_matrix_snapshots_batch_stem
ON matrix_snapshots(batch_stem_id)
WHERE batch_stem_id IS NOT NULL;

-- 6. Add Foreign Key constraints with ON DELETE CASCADE
ALTER TABLE spans DROP CONSTRAINT IF EXISTS spans_session_id_fkey;
ALTER TABLE spans
    ADD CONSTRAINT spans_session_id_fkey
    FOREIGN KEY (session_id) REFERENCES annotation_sessions(id) ON DELETE CASCADE;

ALTER TABLE spans DROP CONSTRAINT IF EXISTS spans_batch_stem_id_fkey;
ALTER TABLE spans
    ADD CONSTRAINT spans_batch_stem_id_fkey
    FOREIGN KEY (batch_stem_id) REFERENCES batch_stems(id) ON DELETE CASCADE;

ALTER TABLE relations DROP CONSTRAINT IF EXISTS relations_session_id_fkey;
ALTER TABLE relations
    ADD CONSTRAINT relations_session_id_fkey
    FOREIGN KEY (session_id) REFERENCES annotation_sessions(id) ON DELETE CASCADE;

ALTER TABLE relations DROP CONSTRAINT IF EXISTS relations_batch_stem_id_fkey;
ALTER TABLE relations
    ADD CONSTRAINT relations_batch_stem_id_fkey
    FOREIGN KEY (batch_stem_id) REFERENCES batch_stems(id) ON DELETE CASCADE;

ALTER TABLE matrix_snapshots DROP CONSTRAINT IF EXISTS matrix_snapshots_session_id_fkey;
ALTER TABLE matrix_snapshots
    ADD CONSTRAINT matrix_snapshots_session_id_fkey
    FOREIGN KEY (session_id) REFERENCES annotation_sessions(id) ON DELETE CASCADE;

ALTER TABLE matrix_snapshots DROP CONSTRAINT IF EXISTS matrix_snapshots_batch_stem_id_fkey;
ALTER TABLE matrix_snapshots
    ADD CONSTRAINT matrix_snapshots_batch_stem_id_fkey
    FOREIGN KEY (batch_stem_id) REFERENCES batch_stems(id) ON DELETE CASCADE;

-- 7. Add mutual exclusivity check constraints
ALTER TABLE spans DROP CONSTRAINT IF EXISTS chk_spans_owner;
ALTER TABLE spans
    ADD CONSTRAINT chk_spans_owner
    CHECK ((session_id IS NOT NULL AND batch_stem_id IS NULL) OR (session_id IS NULL AND batch_stem_id IS NOT NULL));

ALTER TABLE relations DROP CONSTRAINT IF EXISTS chk_relations_owner;
ALTER TABLE relations
    ADD CONSTRAINT chk_relations_owner
    CHECK ((session_id IS NOT NULL AND batch_stem_id IS NULL) OR (session_id IS NULL AND batch_stem_id IS NOT NULL));

ALTER TABLE matrix_snapshots DROP CONSTRAINT IF EXISTS chk_matrix_snapshots_owner;
ALTER TABLE matrix_snapshots
    ADD CONSTRAINT chk_matrix_snapshots_owner
    CHECK ((session_id IS NOT NULL AND batch_stem_id IS NULL) OR (session_id IS NULL AND batch_stem_id IS NOT NULL));

COMMIT;
