-- ============================================================================
-- 005_group_annotation — Group annotation workflow with inter-annotator
-- agreement (Krippendorff's alpha primary, Cohen's/Fleiss' kappa secondary).
-- See context/cohen_kappa.md for the design rationale.
-- ============================================================================

BEGIN;

-- A group annotation task: ties one stem to 1 event annotator + N timeline annotators
CREATE TABLE IF NOT EXISTS group_annotation_tasks (
    id                    SERIAL PRIMARY KEY,
    stem_id               INT NOT NULL REFERENCES stems(id) ON DELETE CASCADE,
    status                TEXT NOT NULL DEFAULT 'event_pending',
    -- 'event_pending' | 'event_done' | 'timelines_pending' | 'computing'
    -- | 'accepted' | 'accepted_flagged' | 'adjudication' | 'rejected'
    created_by            INT NOT NULL REFERENCES users(id),
    created_at            TIMESTAMPTZ DEFAULT now(),
    updated_at            TIMESTAMPTZ DEFAULT now(),
    krippendorff_alpha    FLOAT,
    cohens_kappa_avg      FLOAT,
    fleiss_kappa          FLOAT,
    agreement_details     JSONB,
    acceptance_threshold  FLOAT NOT NULL DEFAULT 0.60,
    UNIQUE(stem_id)
);

-- Role assignments within a group task
CREATE TABLE IF NOT EXISTS group_annotation_members (
    id              SERIAL PRIMARY KEY,
    task_id         INT NOT NULL REFERENCES group_annotation_tasks(id) ON DELETE CASCADE,
    user_id         INT NOT NULL REFERENCES users(id),
    role            TEXT NOT NULL,        -- 'event_annotator' | 'timeline_annotator'
    status          TEXT NOT NULL DEFAULT 'pending',  -- 'pending' | 'in_progress' | 'done'
    annotator_index INT,                 -- 1..N for timeline annotators, NULL for event annotator
    started_at      TIMESTAMPTZ,
    completed_at    TIMESTAMPTZ,
    UNIQUE(task_id, user_id),
    UNIQUE(task_id, role, annotator_index)
);

-- Each timeline annotator's independent event positions
CREATE TABLE IF NOT EXISTS timeline_annotations (
    id          SERIAL PRIMARY KEY,
    task_id     INT NOT NULL REFERENCES group_annotation_tasks(id) ON DELETE CASCADE,
    member_id   INT NOT NULL REFERENCES group_annotation_members(id) ON DELETE CASCADE,
    span_id     INT NOT NULL REFERENCES spans(id) ON DELETE CASCADE,
    tl_start    FLOAT NOT NULL,
    tl_end      FLOAT NOT NULL,
    created_at  TIMESTAMPTZ DEFAULT now(),
    updated_at  TIMESTAMPTZ DEFAULT now(),
    UNIQUE(member_id, span_id)
);

-- Each timeline annotator's derived Allen matrix
CREATE TABLE IF NOT EXISTS timeline_relation_matrices (
    id          SERIAL PRIMARY KEY,
    task_id     INT NOT NULL REFERENCES group_annotation_tasks(id) ON DELETE CASCADE,
    member_id   INT NOT NULL REFERENCES group_annotation_members(id) ON DELETE CASCADE,
    matrix_json JSONB NOT NULL,
    span_order  JSONB NOT NULL,
    created_at  TIMESTAMPTZ DEFAULT now(),
    UNIQUE(task_id, member_id)
);

CREATE INDEX IF NOT EXISTS idx_group_members_task ON group_annotation_members(task_id);
CREATE INDEX IF NOT EXISTS idx_group_members_user ON group_annotation_members(user_id);
CREATE INDEX IF NOT EXISTS idx_timeline_annotations_task ON timeline_annotations(task_id);
CREATE INDEX IF NOT EXISTS idx_timeline_annotations_member ON timeline_annotations(member_id);

-- Extend spans with group_task_id (event annotator creates spans here)
ALTER TABLE spans ADD COLUMN IF NOT EXISTS group_task_id INT
    REFERENCES group_annotation_tasks(id) ON DELETE CASCADE;

-- Widen the mutual-exclusivity CHECK to allow a third owner column
ALTER TABLE spans DROP CONSTRAINT IF EXISTS chk_spans_owner;
ALTER TABLE spans ADD CONSTRAINT chk_spans_owner CHECK (
    (CASE WHEN session_id IS NOT NULL THEN 1 ELSE 0 END +
     CASE WHEN batch_stem_id IS NOT NULL THEN 1 ELSE 0 END +
     CASE WHEN group_task_id IS NOT NULL THEN 1 ELSE 0 END) = 1
);

COMMIT;
