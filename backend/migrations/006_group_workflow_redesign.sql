-- ============================================================================
-- 006_group_workflow_redesign — Split status/outcome/decision, add
-- reassignment, per-member matrix overrides, append-only revision/agreement
-- history, and distribution provenance.
-- See context/group_workflow_redesign.md for the design rationale.
-- ============================================================================

BEGIN;

-- ---------------------------------------------------------------------------
-- 1. Task: split status / outcome / decision (§9.1)
-- ---------------------------------------------------------------------------

ALTER TABLE group_annotation_tasks ADD COLUMN IF NOT EXISTS outcome      TEXT;
ALTER TABLE group_annotation_tasks ADD COLUMN IF NOT EXISTS decision     TEXT;
ALTER TABLE group_annotation_tasks ADD COLUMN IF NOT EXISTS decided_by   INT REFERENCES users(id);
ALTER TABLE group_annotation_tasks ADD COLUMN IF NOT EXISTS decided_at   TIMESTAMPTZ;
ALTER TABLE group_annotation_tasks ADD COLUMN IF NOT EXISTS scores_stale BOOLEAN NOT NULL DEFAULT FALSE;

-- Remap rows written by migration 005, where verdicts were stored in `status`.
UPDATE group_annotation_tasks
   SET outcome = status, status = 'computed'
 WHERE status IN ('accepted', 'accepted_flagged', 'adjudication', 'rejected');

-- ---------------------------------------------------------------------------
-- 2. Members: rename 'done' -> 'submitted', reassignment provenance (§9.2)
-- ---------------------------------------------------------------------------

UPDATE group_annotation_members SET status = 'submitted' WHERE status = 'done';

ALTER TABLE group_annotation_members ADD COLUMN IF NOT EXISTS assigned_by     INT REFERENCES users(id);
ALTER TABLE group_annotation_members ADD COLUMN IF NOT EXISTS reassigned_from INT REFERENCES users(id);
ALTER TABLE group_annotation_members ADD COLUMN IF NOT EXISTS reassigned_at   TIMESTAMPTZ;

-- ---------------------------------------------------------------------------
-- 3. Per-member relations (override support) (§9.3)
-- ---------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS timeline_relations (
    id            SERIAL PRIMARY KEY,
    task_id       INT NOT NULL REFERENCES group_annotation_tasks(id)   ON DELETE CASCADE,
    member_id     INT NOT NULL REFERENCES group_annotation_members(id) ON DELETE CASCADE,
    span_i_id     INT NOT NULL REFERENCES spans(id) ON DELETE CASCADE,
    span_j_id     INT NOT NULL REFERENCES spans(id) ON DELETE CASCADE,
    relation_code INT NOT NULL,
    is_override   BOOLEAN NOT NULL DEFAULT FALSE,
    created_at    TIMESTAMPTZ DEFAULT now(),
    updated_at    TIMESTAMPTZ DEFAULT now(),
    UNIQUE(member_id, span_i_id, span_j_id)
);

CREATE INDEX IF NOT EXISTS idx_timeline_relations_task ON timeline_relations(task_id);
CREATE INDEX IF NOT EXISTS idx_timeline_relations_member ON timeline_relations(member_id);

-- ---------------------------------------------------------------------------
-- 4. Timeline position provenance (§9.4)
-- ---------------------------------------------------------------------------

ALTER TABLE timeline_annotations ADD COLUMN IF NOT EXISTS source TEXT NOT NULL DEFAULT 'manual';

-- ---------------------------------------------------------------------------
-- 5. Append-only history: revisions + agreement runs (§9.5)
-- ---------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS timeline_submission_revisions (
    id             SERIAL PRIMARY KEY,
    task_id        INT NOT NULL REFERENCES group_annotation_tasks(id)   ON DELETE CASCADE,
    member_id      INT NOT NULL REFERENCES group_annotation_members(id) ON DELETE CASCADE,
    revision_no    INT NOT NULL,
    positions_json JSONB NOT NULL,
    matrix_json    JSONB NOT NULL,
    span_order     JSONB NOT NULL,
    had_llm_assist BOOLEAN NOT NULL DEFAULT FALSE,
    submitted_at   TIMESTAMPTZ DEFAULT now(),
    UNIQUE(member_id, revision_no)
);

CREATE INDEX IF NOT EXISTS idx_revisions_task ON timeline_submission_revisions(task_id);

CREATE TABLE IF NOT EXISTS agreement_runs (
    id                  SERIAL PRIMARY KEY,
    task_id             INT NOT NULL REFERENCES group_annotation_tasks(id) ON DELETE CASCADE,
    run_no              INT NOT NULL,
    krippendorff_alpha  FLOAT,
    cohens_kappa_avg    FLOAT,
    fleiss_kappa        FLOAT,
    outcome             TEXT,
    based_on_revisions  JSONB NOT NULL,   -- {"<member_id>": <revision_no>}
    computed_at         TIMESTAMPTZ DEFAULT now(),
    UNIQUE(task_id, run_no)
);

CREATE INDEX IF NOT EXISTS idx_agreement_runs_task ON agreement_runs(task_id);

-- ---------------------------------------------------------------------------
-- 6. Distribution provenance (§9.6)
-- ---------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS distribution_runs (
    id            SERIAL PRIMARY KEY,
    created_by    INT NOT NULL REFERENCES users(id),
    created_at    TIMESTAMPTZ DEFAULT now(),
    stem_count    INT NOT NULL,
    pool_user_ids JSONB NOT NULL
);

ALTER TABLE group_annotation_tasks
    ADD COLUMN IF NOT EXISTS distribution_run_id INT REFERENCES distribution_runs(id);

COMMIT;
