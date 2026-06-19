-- ANNOTATION SESSIONS (one per annotator stem paste)
CREATE TABLE IF NOT EXISTS annotation_sessions (
    id           SERIAL PRIMARY KEY,
    username     TEXT NOT NULL,
    stem_text    TEXT NOT NULL,
    status       TEXT NOT NULL DEFAULT 'in_progress',
    completed_at TIMESTAMPTZ,
    created_at   TIMESTAMPTZ DEFAULT now()
);

-- SPANS (event and time labels within the session)
CREATE TABLE IF NOT EXISTS spans (
    id          SERIAL PRIMARY KEY,
    session_id  INT NOT NULL REFERENCES annotation_sessions(id) ON DELETE CASCADE,
    label_type  TEXT NOT NULL,
    seq_label   TEXT NOT NULL,
    span_text   TEXT NOT NULL,
    char_start  INT NOT NULL,
    char_end    INT NOT NULL,
    tl_start    FLOAT NOT NULL,
    tl_end      FLOAT NOT NULL,
    created_at  TIMESTAMPTZ DEFAULT now()
);

-- RELATIONS (flat list of pairwise Allen relations)
CREATE TABLE IF NOT EXISTS relations (
    id           SERIAL PRIMARY KEY,
    session_id   INT NOT NULL REFERENCES annotation_sessions(id) ON DELETE CASCADE,
    span_i_id    INT NOT NULL REFERENCES spans(id) ON DELETE CASCADE,
    span_j_id    INT NOT NULL REFERENCES spans(id) ON DELETE CASCADE,
    relation_code INT NOT NULL,
    is_override  BOOLEAN DEFAULT FALSE,
    created_at   TIMESTAMPTZ DEFAULT now(),
    UNIQUE(session_id, span_i_id, span_j_id)
);

-- MATRIX SNAPSHOTS (full matrix as JSONB for fast retrieval and export)
CREATE TABLE IF NOT EXISTS matrix_snapshots (
    id           SERIAL PRIMARY KEY,
    session_id   INT NOT NULL REFERENCES annotation_sessions(id) ON DELETE CASCADE,
    matrix_json  JSONB NOT NULL,
    span_order   JSONB NOT NULL,
    created_at   TIMESTAMPTZ DEFAULT now(),
    updated_at   TIMESTAMPTZ DEFAULT now()
);
