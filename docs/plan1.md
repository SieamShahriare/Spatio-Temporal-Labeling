# Spatiotemporal Annotation & Allen's Algebra Benchmarking System

## Implementation Plan

---

## Table of Contents

1. [Project Overview](#1-project-overview)
2. [System Architecture](#2-system-architecture)
3. [Allen's Algebra Numeric Encoding](#3-allens-algebra-numeric-encoding)
4. [Database Design](#4-database-design)
5. [Backend Design](#5-backend-design)
6. [Frontend Design](#6-frontend-design)
7. [Phase-by-Phase Implementation](#7-phase-by-phase-implementation)
8. [Tech Stack Summary](#8-tech-stack-summary)
9. [File & Folder Structure](#9-file--folder-structure)
10. [Open Questions & Decisions](#10-open-questions--decisions)

---

## 1. Project Overview

### Purpose

A web application for annotating short text passages (stems) with **Event** and **Time** span labels, visualizing those spans on a Premiere Pro-style timeline, computing pairwise Allen's Interval Algebra relations between spans, representing relations as a signed integer matrix, and persisting everything to a NeonDB (Postgres) database for export.

### User Flow (End-to-End)

```
[User opens local app at http://localhost:3000]
        |
        v
[Landing Page]
  - Enter Username (to track who labeled the data)
  - Paste Stem Text (the passage to annotate)
  - Click "Start Labeling" -> creates Session in NeonDB
        |
        v
[Step 1: Text Labeling]
  - Select text spans in the stem text
  - Assign each span as "Event" or "Time"
  - Each span auto-assigned a sequential label: E1, E2... / T1, T2...
        |
        v
[Step 2: Timeline & Manual Inputs]
  - Every event/time span gets its own separate horizontal row (lane) in the editor
  - X-axis = narrative order (abstract 0-100 scale, not character offset)
  - Drag blocks left/right or type precise start/end values in manual inputs to set positions
  - Block colors: blue = Event, orange = Time
        |
        v
[Step 3: Matrix Review & Overrides]
  - Matrix is auto-computed from timeline positions and is read-only during timeline editing
  - Annotator clicks "Review Matrix" to unlock the cells and manually override relations if needed
  - Diagonal entries are always locked to 0
        |
        v
[Save / Mark Done]
  - Stem spans + timeline positions + matrix saved to NeonDB
  - Redirects back to Landing Page to label another stem
```

---

## 2. System Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                        FRONTEND                              │
│                    Next.js (React)                           │
│                                                              │
│  ┌───────────────────────┐       ┌────────────────────────┐  │
│  │     Landing Page      │       │    Annotation View     │  │
│  │ (username + text paste│ ────> │  (text labeler +       │  │
│  │  + data export link)  │       │   timeline + matrix)   │  │
│  └───────────────────────┘       └────────────────────────┘  │
└──────────────────────────┬──────────────────────────────────┘
                           │  REST API (JSON)
                           │
 ┌─────────────────────────▼──────────────────────────────────┐
 │                        BACKEND                               │
 │                    FastAPI (Python)                          │
 │                                                              │
 │  /sessions      /spans        /matrix      /export           │
 │                                                              │
 │  Allen's Algebra Engine (Python module)                      │
 │  - Relation computation from timeline positions              │
 │  - Inverse lookup                                            │
 │  - Transitivity violation detection                          │
 └─────────────────────────┬──────────────────────────────────┘
                           │  asyncpg / psycopg2
                           │
 ┌─────────────────────────▼──────────────────────────────────┐
 │                        DATABASE                              │
 │                    NeonDB (Postgres)                         │
 │                                                              │
 │  annotation_sessions | spans | relations | matrix_snapshots  │
 └──────────────────────────────────────────────────────────────┘
```

---

## 3. Allen's Algebra Numeric Encoding

### Canonical Encoding Table

The 13 Allen relations are encoded as signed integers. The ordering follows the standard table from the Wikipedia article on Allen's Interval Algebra.

| Code | Relation Name   | Symbol | Inverse Code | Inverse Name         |
|------|-----------------|--------|--------------|------------------    |
| +1   | precedes        | <      | -1           | preceded-by (>)      |
| +2   | meets           | m      | -2           | met-by (mi)          |
| +3   | overlaps        | o      | -3           | overlapped-by (oi)   |
| +4   | starts          | s      | -4           | started-by (si)      |
| +5   | during          | d      | -5           | contains (di)        |
| +6   | finishes        | f      | -6           | finished-by (fi)     |
| +7   | equals          | =      | +7           | equals (symmetric)   |

### Matrix Rules

- **Diagonal** (span i vs itself): `0`
- **Upper triangle** (i < j): positive integer from the table above
- **Lower triangle** (i > j): negative of the upper triangle value, EXCEPT for `equals` (+7) which stays +7
- If `matrix[i][j] = +3`, then `matrix[j][i] = -3`
- If `matrix[i][j] = +7`, then `matrix[j][i] = +7`

### Python Encoding Module

```python
# allen.py

RELATIONS = {
    'precedes':       +1,
    'meets':          +2,
    'overlaps':       +3,
    'starts':         +4,
    'during':         +5,
    'finishes':       +6,
    'equals':         +7,
    'preceded-by':    -1,
    'met-by':         -2,
    'overlapped-by':  -3,
    'started-by':     -4,
    'contains':       -5,
    'finished-by':    -6,
}

INVERSES = {
    +1: -1,  -1: +1,
    +2: -2,  -2: +2,
    +3: -3,  -3: +3,
    +4: -4,  -4: +4,
    +5: -5,  -5: +5,
    +6: -6,  -6: +6,
    +7: +7,  # equals is its own inverse
}

def compute_relation(a_start, a_end, b_start, b_end, tol=0.01) -> int:
    """
    Returns the Allen relation code for interval A vs interval B.
    tol is a tolerance factor for floating point comparisons.
    """
    def eq(x, y): return abs(x - y) <= tol

    if eq(a_start, b_start) and eq(a_end, b_end): return +7  # equals
    if eq(a_end, b_start):                          return +2  # meets
    if eq(b_end, a_start):                          return -2  # met-by
    if a_end < b_start - tol:                       return +1  # precedes
    if b_end < a_start - tol:                       return -1  # preceded-by
    if eq(a_start, b_start) and a_end < b_end:      return +4  # starts
    if eq(a_start, b_start) and a_end > b_end:      return -4  # started-by
    if eq(a_end, b_end) and a_start > b_start:      return +6  # finishes
    if eq(a_end, b_end) and a_start < b_start:      return -6  # finished-by
    if a_start > b_start and a_end < b_end:         return +5  # during
    if a_start < b_start and a_end > b_end:         return -5  # contains
    if a_start < b_start and a_end > b_start:       return +3  # overlaps
    if b_start < a_start and b_end > a_start:       return -3  # overlapped-by
    return +3  # fallback

def build_matrix(spans: list) -> list[list[int]]:
    """
    Given a list of spans [{tl_start, tl_end}], returns the N x N relation matrix.
    """
    n = len(spans)
    matrix = [[0] * n for _ in range(n)]
    for i in range(n):
        for j in range(n):
            if i == j:
                matrix[i][j] = 0
            elif i < j:
                code = compute_relation(
                    spans[i]['tl_start'], spans[i]['tl_end'],
                    spans[j]['tl_start'], spans[j]['tl_end']
                )
                matrix[i][j] = code
                matrix[j][i] = INVERSES[code]
    return matrix
```

---

## 4. Database Design

### NeonDB (Postgres) Schema

```sql
-- ANNOTATION SESSIONS (one per annotator stem paste)
CREATE TABLE annotation_sessions (
    id           SERIAL PRIMARY KEY,
    username     TEXT NOT NULL,                  -- annotator username
    stem_text    TEXT NOT NULL,                  -- the copy-pasted passage text
    status       TEXT NOT NULL DEFAULT 'in_progress', -- 'in_progress' | 'done'
    completed_at TIMESTAMPTZ,
    created_at   TIMESTAMPTZ DEFAULT now()
);

-- SPANS (event and time labels within the session)
CREATE TABLE spans (
    id          SERIAL PRIMARY KEY,
    session_id  INT NOT NULL REFERENCES annotation_sessions(id) ON DELETE CASCADE,
    label_type  TEXT NOT NULL,           -- 'Event' | 'Time'
    seq_label   TEXT NOT NULL,           -- 'E1', 'E2', 'T1', 'T2' etc
    span_text   TEXT NOT NULL,           -- the selected text
    char_start  INT NOT NULL,            -- original character offset (immutable)
    char_end    INT NOT NULL,            -- original character offset (immutable)
    tl_start    FLOAT NOT NULL,          -- timeline position (set by drag, mutable)
    tl_end      FLOAT NOT NULL,          -- timeline position (set by drag, mutable)
    created_at  TIMESTAMPTZ DEFAULT now()
);

-- RELATIONS (flat list of all pairwise Allen relations, derived from matrix)
CREATE TABLE relations (
    id           SERIAL PRIMARY KEY,
    session_id   INT NOT NULL REFERENCES annotation_sessions(id) ON DELETE CASCADE,
    span_i_id    INT NOT NULL REFERENCES spans(id) ON DELETE CASCADE,
    span_j_id    INT NOT NULL REFERENCES spans(id) ON DELETE CASCADE,
    relation_code INT NOT NULL,          -- +1 to +7, -1 to -6, or 0 for diagonal
    is_override  BOOLEAN DEFAULT FALSE,  -- true if annotator manually changed the cell
    created_at   TIMESTAMPTZ DEFAULT now(),
    UNIQUE(session_id, span_i_id, span_j_id)
);

-- MATRIX SNAPSHOTS (full matrix as JSONB for fast retrieval and export)
CREATE TABLE matrix_snapshots (
    id           SERIAL PRIMARY KEY,
    session_id   INT NOT NULL REFERENCES annotation_sessions(id) ON DELETE CASCADE,
    matrix_json  JSONB NOT NULL,         -- full N x N matrix
    span_order   JSONB NOT NULL,         -- ordered list of span IDs and seq_labels
    created_at   TIMESTAMPTZ DEFAULT now(),
    updated_at   TIMESTAMPTZ DEFAULT now()
);
```

---

## 5. Backend Design

### Framework: FastAPI (Python)

### API Endpoints

#### Annotation Session

```
POST /sessions                  Create a session { username, stem_text } -> returns { session_id }
GET  /sessions                  List all sessions, optionally filter by query param ?username=xxx
GET  /sessions/:id              Get full session (stem_text + spans + matrix snapshot)
PATCH /sessions/:id/status      Mark session done
DELETE /sessions/:id            Delete a session (cascades database spans and relations)
```

#### Spans

```
POST /sessions/:id/spans        Create a new span { label_type, span_text, char_start, char_end, tl_start, tl_end }
PATCH /spans/:id                Update tl_start, tl_end (after drag/manual input)
DELETE /spans/:id               Remove a span
```

#### Matrix

```
GET  /sessions/:id/matrix       Compute matrix from current span positions
POST /sessions/:id/matrix/save  Save matrix snapshot (upsert)
PATCH /sessions/:id/matrix/override   Override specific cell { i, j, relation_code }
```

#### Export

```
GET  /export/csv                Export all completed sessions as CSV (flat relational layout)
GET  /export/json               Export all completed sessions as JSON (full structured output)
```

### Allen's Algebra Module Structure

```
backend/
  allen/
    __init__.py
    relations.py      # compute_relation(), build_matrix(), INVERSES table
    validate.py       # transitivity_check() — flags violations
```

---

## 6. Frontend Design

### Framework: Next.js (App Router) + React

### Pages

```
/                       Landing page (Enter username, Paste stem text, List of past annotations, Link to exports)
/annotate/:session_id   Main annotation view
```

### Annotate Page Layout

```
│  STEP 3: RELATION MATRIX                                     │
│  ┌────────────────────────────────────────────────────────┐  │
│  │  [Unlock Matrix for Review] (Click to edit cells)      │  │
│  │                                                        │  │
│  │      │  E1  │  T1  │  E2  │                            │  │
│  │  E1  │  0   │  +1  │  +3  │                            │  │
│  │  T1  │  -1  │  0   │  +2  │                            │  │
│  │  E2  │  -3  │  -2  │  0   │                            │  │
│  │                                                        │  │
│  │  Diagonal locked to 0. Cell override via dropdown      │  │
│  └────────────────────────────────────────────────────────┘  │
```

---

## 7. Phase-by-Phase Implementation

### Phase 1: Landing Page & Session Init (Days 1–2)
- Set up Next.js app and FastAPI app locally.
- Connect FastAPI to shared NeonDB Postgres.
- Build landing page: form to enter Username, text area to paste stem text, list of recent sessions, and download links for data export.
- Implement `POST /sessions` API to insert paste into `annotation_sessions` and redirect to `/annotate/:session_id`.
- Implement `GET /export/csv` and `GET /export/json` endpoints.

### Phase 2: Allen's Algebra Engine (Day 3)
- Implement `allen/relations.py` with `compute_relation()` and `build_matrix()`.
- Write unit tests for all 13 relations with known interval inputs.
- Implement `allen/validate.py` with transitivity composition table and `transitivity_check()`.

### Phase 3: Text Labeling with Overlaps (Days 4–5)
- Build `TextLabeler` component rendering pasted stem text.
- Implement disjoint segment tokenization algorithm to support overlapping selection highlights.
- Implement sequential label assigning (`E1`, `E2`, `T1`, `T2`) dynamically sorted in reading order.
- Wire to `POST /sessions/:id/spans` and `DELETE /spans/:id`.

### Phase 4: Multi-Row Timeline UI (Days 6–7)
- Build `Timeline` component where each span gets its own vertical row.
- Initialize new spans with constant timeline width (e.g., `10.0` to `30.0`).
- Implement drag-to-move and drag-to-resize boundary handles.
- Implement manual coordinate input fields next to the timeline updating span coordinates on-change.
- Wire up `PATCH /spans/:id` to save span boundaries (debounced).

### Phase 5: Locked Matrix & Review Mode (Day 8)
- Build `AllenMatrix` showing N x N table of relation codes.
- Keep cells locked (read-only) while timeline is edited.
- Implement "Unlock for Review" button to open dropdowns on non-diagonal cells for overrides.
- Implement composition validation warning banner showing transitivity violations.
- Wire overrides to `PATCH /sessions/:id/matrix/override`.

### Phase 6: Save & Final Polish (Day 9)
- Implement "Mark Done & Exit" which sets session status to `done` and redirects to landing page.
- Test end-to-end local workflow with multiple users saving to the shared database.

---

## 8. Tech Stack Summary

| Layer        | Technology           | Reason                                                       |
|--------------|----------------------|--------------------------------------------------------------|
| Frontend     | Next.js 16 (App Router) | Latest React 19 standards, clean routing                     |
| UI Library   | Tailwind CSS v4      | Styling utility classes                                      |
| Canvas       | SVG / DOM Rows       | Render multi-lane timeline rows smoothly                     |
| Backend      | FastAPI (Python)     | Allen's algebra logic cleaner in Python                      |
| DB Driver    | asyncpg              | Async Postgres driver, best for FastAPI                      |
| Database     | NeonDB (Postgres)    | Serverless Postgres; shared instance for research            |

---

## 9. File & Folder Structure

```
spatiotemporal-annotator/
│
├── frontend/                          # Next.js app
│   ├── app/
│   │   ├── page.tsx                   # Landing page (username input + stem text area + export links)
│   │   └── annotate/
│   │       └── [session_id]/
│   │           └── page.tsx           # Main annotation view
│   ├── components/
│   │   ├── TextLabeler.tsx            # Span selection and highlighting
│   │   ├── Timeline.tsx               # Drag timeline with manual input panel
│   │   ├── AllenMatrix.tsx            # Matrix table with review lock/override dropdowns
│   │   ├── TransitivityWarning.tsx    # Warning banner
│   │   └── SpanList.tsx               # List of all spans
│   ├── lib/
│   │   ├── api.ts                     # API fetch calls
│   │   ├── allen.ts                   # Client-side relation helper constants
│   └── types/
│       └── index.ts                   # TypeScript types
│
├── backend/                           # FastAPI app
│   ├── main.py                        # FastAPI entry point & API endpoints
│   ├── database.py                    # NeonDB connection pool
│   ├── models.py                      # Pydantic schemas
│   ├── allen/
│   │   ├── __init__.py
│   │   ├── relations.py               # Relation calculation + build_matrix()
│   │   └── validate.py                # Transitivity composition validator
│   └── migrations/
│       └── schema.sql                 # Initial Postgres database schema
│
└── README.md
```

---

## 10. Repository and Collaboration Setup

The project is structured as a private GitHub repository hosting a Next.js frontend and a FastAPI backend (monorepo).

### How Collaborative Local Development Works

1. **Central Database**: A single shared NeonDB (Postgres) database is created. All annotators' local server builds connect to this database using the same `DATABASE_URL` in their `.env` files.
2. **Local Environment Config**:
   - **Backend**: Create a `.env` file with `DATABASE_URL` pointing to the shared Neon Postgres instance.
   - **Frontend**: Create a `.env.local` file with `NEXT_PUBLIC_API_URL=http://localhost:8000` (pointing to the local FastAPI server).
3. **Getting Started Workflow**:
   - Each annotator clones the private repo.
   - They create their `.env` and `.env.local` files using the shared credentials.
   - They run their own local servers (`uvicorn main:app --reload` on port 8000, and `npm run dev` or `pnpm dev` on port 3000).
   - Annotators identify themselves by typing their unique `username` on the landing page (which creates/resumes their sessions in the shared database).
   - This ensures all annotated data compiles into the single central DB, without requiring a public frontend/backend server deployment.

---

*Document version: 1.1 — Updated implementation plan with multi-row timeline and review overrides*
*Prepared for: Spatiotemporal Benchmarking Research Project*
