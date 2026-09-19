# Group Annotation Workflow — Context & Design Brief

> **Purpose of this document**: Give a developer (or an agentic AI working with one)
> enough context to implement a new **group annotation workflow** with
> **inter-annotator agreement** measurement on top of the existing
> Spatio-Temporal-Labeling codebase.

---

## Table of Contents

1. [Project Overview](#1-project-overview)
2. [Current (Old) Workflow](#2-current-old-workflow)
3. [Proposed Group Annotation Workflow](#3-proposed-group-annotation-workflow)
4. [Agreement Metrics — Why Not Just Cohen's Kappa?](#4-agreement-metrics)
5. [Proposed Database Schema Changes](#5-proposed-database-schema-changes)
6. [Proposed API Endpoints](#6-proposed-api-endpoints)
7. [Frontend Changes](#7-frontend-changes)
8. [Recommendations](#8-recommendations)
9. [Open Questions](#9-open-questions)
10. [Reference: Existing Codebase Map](#10-reference-existing-codebase-map)

---

## 1. Project Overview

**Spatio-Temporal-Labeling** is a web-based annotation tool for temporal event
extraction and Allen's Interval Algebra relation labeling.

| Layer | Tech | Location |
|---|---|---|
| Backend | FastAPI (Python, async) | `backend/main.py` (~1836 lines) |
| Database | PostgreSQL on Neon (via asyncpg) | `backend/database.py` |
| Frontend | Next.js (App Router, TypeScript) | `spatiotemporal-labeling/` |
| LLM assist | OpenRouter (Gemini Flash Lite) | `backend/llm.py` |
| Allen logic | Pure Python | `backend/allen/relations.py`, `backend/allen/validate.py` |

### What the tool does

1. A **stem** is a short narrative text (e.g. a paragraph describing a sequence of events).
2. An annotator **marks events** (text spans) in the stem.
3. The annotator **positions events on a 0–100 timeline** (start/end for each event).
4. The system **computes an Allen's Interval Algebra relation matrix** from those
   timeline positions — a 13-relation system (`precedes`, `meets`, `overlaps`,
   `starts`, `during`, `finishes`, `equals`, and their inverses).
5. The annotator can **override** individual matrix cells if they disagree with the
   computed relation.
6. The result is exported as structured JSON for downstream NLP research.

### Allen's 13 Interval Relations (reference)

| Code | Name | Symbol | Inverse |
|---|---|---|---|
| +1 | precedes | `<` | −1 (preceded-by) |
| +2 | meets | `m` | −2 (met-by) |
| +3 | overlaps | `o` | −3 (overlapped-by) |
| +4 | starts | `s` | −4 (started-by) |
| +5 | during | `d` | −5 (contains) |
| +6 | finishes | `f` | −6 (finished-by) |
| +7 | equals | `=` | +7 (self-inverse) |

Defined in `backend/allen/relations.py`.

---

## 2. Current (Old) Workflow

### 2.1 Single-User Batch Workflow

The current system supports one annotator doing everything alone:

```
User logs in
  └─→ Dashboard: sees stems pool
       └─→ Creates a "batch" (selects N stems, gets a 4-hour lock)
            └─→ For each stem in the batch:
                 Step 1: TextLabeler — highlight event spans in text
                 Step 2: Timeline    — drag events on 0–100 slider
                 Step 3: AllenMatrix — view/override the N×N relation matrix
                 └─→ Mark stem as "done"
            └─→ Batch complete → export JSON
```

**Key characteristics:**
- **One person** does all three steps (event marking + timeline + matrix review).
- No inter-annotator agreement — single annotator per stem.
- Batch has a time lock (`expires_at`), max 3 rebooks.
- LLM can assist with event extraction and timeline positioning (optional).

### 2.2 Current Database Schema

```
users ──────────────────────── auth_sessions
  │                                (cookie-based login)
  │
  ├── batches (owner_id → users.id)
  │     └── batch_stems (batch_id → batches.id, stem_id → stems.id)
  │           ├── spans (batch_stem_id → batch_stems.id)
  │           ├── relations (batch_stem_id → batch_stems.id)
  │           └── matrix_snapshots (batch_stem_id → batch_stems.id)
  │
  └── stems (the text pool)
```

**Tables:**

| Table | Purpose | Key Columns |
|---|---|---|
| `users` | Registered users | `id, email, username, password_hash` |
| `stems` | Narrative text pool | `id, text, word_count, source` |
| `batches` | A user's work session (N stems) | `id, name, owner_id, locked_at, expires_at, status` |
| `batch_stems` | Join table: batch ↔ stem | `id, batch_id, stem_id, status, completed_by` |
| `spans` | Event/time labels in text | `id, session_id?, batch_stem_id?, label_type, seq_label, span_text, char_start, char_end, tl_start, tl_end, source` |
| `relations` | Pairwise Allen relations | `id, session_id?, batch_stem_id?, span_i_id, span_j_id, relation_code, is_override` |
| `matrix_snapshots` | Full N×N matrix as JSON | `id, session_id?, batch_stem_id?, matrix_json, span_order` |
| `annotation_sessions` | Legacy (pre-batch) sessions | `id, username, stem_text, status` |

> **Note:** `spans`, `relations`, and `matrix_snapshots` each have a mutual-exclusivity
> CHECK constraint — exactly one of `session_id`, `batch_stem_id` must be non-null.
> This was added in migration `004_fix_schema_and_orphans.sql`. The new group workflow
> will need to extend this constraint to include a third owner column (`group_task_id`).

### 2.3 The Problem with Single-Annotator Workflow

For rigorous NLP research, a single annotator per stem is insufficient:

- **No reliability measurement** — you can't compute inter-annotator agreement (IAA).
- **Annotator bias** — one person's interpretation becomes ground truth.
- **Not publishable** — most NLP venues require IAA scores (κ, α, or similar) for
  annotation datasets.

---

## 3. Proposed Group Annotation Workflow

### 3.1 High-Level Flow

```
Admin creates a Group Annotation Task for a stem
  │
  ├─→ 1 Event Annotator marks events (TextLabeler only)
  │     └─→ Submits events → events are LOCKED (read-only for everyone)
  │
  ├─→ 3 Timeline Annotators (independently, in parallel)
  │     ├─→ Annotator 1: positions events on timeline → submits
  │     ├─→ Annotator 2: positions events on timeline → submits
  │     └─→ Annotator 3: positions events on timeline → submits
  │
  └─→ System computes inter-annotator agreement
        ├─→ κ ≥ threshold → ✅ Accepted into research dataset
        ├─→ κ moderate    → ⚠️ Needs adjudication
        └─→ κ too low     → ❌ Rejected, needs re-annotation
```

### 3.2 Phase-by-Phase Detail

#### Phase 1: Event Marking (1 person)

- The **event annotator** opens the stem and sees only the TextLabeler step.
- They highlight event spans in the text (same UI as current Step 1).
- When satisfied, they click **"Submit Events"**.
- Events become **locked** — no one can add, delete, or modify the event spans after this.
- The task status moves from `event_pending` → `event_done`.

#### Phase 2: Timeline Annotation (3 people, independently)

- Each **timeline annotator** sees the stem text with events highlighted (read-only).
- They see Steps 2 & 3: the Timeline slider and the AllenMatrix.
- Each annotator **independently** positions all events on the 0–100 timeline.
- They **cannot see** each other's work (to prevent bias).
- When done, they click **"Submit Timeline"**.
- The system automatically builds their individual Allen relation matrix from their
  timeline positions (using `build_matrix()` from `backend/allen/relations.py`).
- After submission, the annotator **cannot re-enter** (prevents adjusting after
  seeing agreement scores).

#### Phase 3: Agreement Computation (automatic)

- Triggered when all 3 timeline annotators have submitted.
- The system computes agreement metrics (see Section 4).
- Results are stored on the `group_annotation_tasks` row.

#### Phase 4: Acceptance Decision

- Based on the computed agreement score vs. the threshold.
- An admin can also manually override the decision.

### 3.3 Key Design Principles

1. **Independence**: Timeline annotators must not see each other's work.
2. **Same events**: All 3 annotators position the **same** set of events (defined by
   the event annotator). This is critical — you can only compare timelines if the
   events are identical.
3. **Immutability after submission**: Once submitted, an annotator's work is frozen.
4. **Separation of concerns**: Event identification is a separate skill from timeline
   positioning. Splitting them lets you measure timeline agreement without confounding
   it with event-identification disagreement.

---

## 4. Agreement Metrics

### 4.1 Why Not Just Cohen's Kappa?

The user's original request mentions **Cohen's Kappa**. However, there are important
limitations:

| Limitation | Detail |
|---|---|
| **2 raters only** | Cohen's Kappa is defined for exactly 2 raters. We have 3. |
| **Categorical data only** | Cohen's Kappa requires categorical labels. Timeline positions (0–100) are continuous. |

### 4.2 What to Use Instead

We recommend computing **multiple complementary metrics**:

#### For Timeline Positions (continuous data, 3 raters):

| Metric | Why | How |
|---|---|---|
| **Krippendorff's Alpha (interval)** | Designed for 2+ raters, any data type including continuous. Chance-corrected. | Compare `(tl_start, tl_end)` values across 3 annotators for each event. |
| **ICC (Intraclass Correlation Coefficient)** | Standard for continuous inter-rater reliability. | Two-way random, single measures (ICC(2,1)). |

#### For Allen Relation Matrices (categorical data, 3 raters):

| Metric | Why | How |
|---|---|---|
| **Cohen's Kappa (pairwise average)** | The user specifically requested it. Compute for each of the 3 pairs, then average. | Flatten upper triangle of each N×N matrix → compare as categorical vectors. |
| **Fleiss' Kappa** | Native multi-rater extension of Cohen's Kappa. | All 3 raters' relation codes compared simultaneously. |

#### Recommended Primary Metric

**Krippendorff's Alpha** as the primary acceptance criterion (handles continuous
timeline data natively with 3+ raters), with **Cohen's Kappa (pairwise avg)** on the
Allen relations as a secondary check.

### 4.3 Standard Agreement Thresholds

| Value | Interpretation | Proposed Action |
|---|---|---|
| ≥ 0.80 | Almost perfect agreement | ✅ Accept |
| 0.60 – 0.79 | Substantial agreement | ✅ Accept (flagged) |
| 0.40 – 0.59 | Moderate agreement | ⚠️ Adjudication needed |
| < 0.40 | Fair / Poor agreement | ❌ Reject, re-annotate |

**Proposed default threshold: κ/α ≥ 0.60 (substantial agreement).**

### 4.4 What Exactly Gets Compared

| Level | Data | Compared Across | Metric |
|---|---|---|---|
| **Timeline positions** | For each event Eₖ: the `(tl_start, tl_end)` from each annotator | 3 annotators | Krippendorff's α (interval) |
| **Allen relations** | For each event pair (Eᵢ, Eⱼ): the relation code derived from each annotator's timeline | 3 annotators (pairwise for Cohen's κ) | Cohen's κ (avg), Fleiss' κ |

### 4.5 Algorithm Sketches

#### Krippendorff's Alpha (interval data)

```python
import numpy as np
from itertools import combinations

def krippendorff_alpha_interval(data_matrix):
    """
    data_matrix: np.array of shape (n_annotators, n_items)
    Each cell = a value (e.g., tl_start for one event from one annotator).
    NaN = missing data.
    Returns: alpha (float)
    """
    n_annotators, n_items = data_matrix.shape

    # Observed disagreement (within-item)
    Do = 0
    count_o = 0
    for k in range(n_items):
        values = data_matrix[:, k]
        valid = values[~np.isnan(values)]
        m = len(valid)
        if m < 2:
            continue
        for c, d in combinations(valid, 2):
            Do += (c - d) ** 2
            count_o += 1
    Do /= count_o if count_o else 1

    # Expected disagreement (across all values)
    all_values = data_matrix[~np.isnan(data_matrix)]
    De = 0
    count_e = 0
    for c, d in combinations(all_values, 2):
        De += (c - d) ** 2
        count_e += 1
    De /= count_e if count_e else 1

    return 1 - Do / De if De != 0 else 1.0
```

#### Cohen's Kappa (pairwise average on Allen relations)

```python
from sklearn.metrics import cohen_kappa_score
from itertools import combinations
import numpy as np

def average_cohens_kappa(matrices):
    """
    matrices: list of 3 N×N Allen relation matrices (list of lists)
    Returns: average pairwise Cohen's kappa
    """
    kappas = []
    for m1, m2 in combinations(matrices, 2):
        flat1, flat2 = [], []
        n = len(m1)
        for i in range(n):
            for j in range(i + 1, n):  # upper triangle only
                flat1.append(m1[i][j])
                flat2.append(m2[i][j])
        if len(set(flat1 + flat2)) > 1:
            kappas.append(cohen_kappa_score(flat1, flat2))
        else:
            kappas.append(1.0)  # trivial perfect agreement
    return float(np.mean(kappas))
```

---

## 5. Proposed Database Schema Changes

### 5.1 New Tables

```sql
-- A group annotation task: ties one stem to 1 event annotator + 3 timeline annotators
CREATE TABLE IF NOT EXISTS group_annotation_tasks (
    id                  SERIAL PRIMARY KEY,
    stem_id             INT NOT NULL REFERENCES stems(id) ON DELETE CASCADE,
    status              TEXT NOT NULL DEFAULT 'event_pending',
    -- Statuses: 'event_pending' | 'event_done' | 'timelines_pending'
    --           | 'computing' | 'accepted' | 'rejected' | 'adjudication'
    created_by          INT NOT NULL REFERENCES users(id),
    created_at          TIMESTAMPTZ DEFAULT now(),
    updated_at          TIMESTAMPTZ DEFAULT now(),
    -- Agreement scores (populated after all 3 timelines submitted)
    krippendorff_alpha  FLOAT,
    cohens_kappa_avg    FLOAT,
    fleiss_kappa        FLOAT,
    agreement_details   JSONB,           -- per-event-pair breakdown
    acceptance_threshold FLOAT DEFAULT 0.60,
    UNIQUE(stem_id)                      -- one active group task per stem
);

-- Role assignments within a group task
CREATE TABLE IF NOT EXISTS group_annotation_members (
    id              SERIAL PRIMARY KEY,
    task_id         INT NOT NULL REFERENCES group_annotation_tasks(id) ON DELETE CASCADE,
    user_id         INT NOT NULL REFERENCES users(id),
    role            TEXT NOT NULL,        -- 'event_annotator' | 'timeline_annotator'
    status          TEXT NOT NULL DEFAULT 'pending',  -- 'pending' | 'in_progress' | 'done'
    annotator_index INT,                 -- 1, 2, or 3 (NULL for event annotator)
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
```

### 5.2 Modifications to Existing Tables

```sql
-- Add group_task_id to spans (event annotator creates spans here)
ALTER TABLE spans ADD COLUMN IF NOT EXISTS group_task_id INT
    REFERENCES group_annotation_tasks(id) ON DELETE CASCADE;

-- Update the mutual-exclusivity CHECK to allow 3 owners
ALTER TABLE spans DROP CONSTRAINT IF EXISTS chk_spans_owner;
ALTER TABLE spans ADD CONSTRAINT chk_spans_owner CHECK (
    (CASE WHEN session_id IS NOT NULL THEN 1 ELSE 0 END +
     CASE WHEN batch_stem_id IS NOT NULL THEN 1 ELSE 0 END +
     CASE WHEN group_task_id IS NOT NULL THEN 1 ELSE 0 END) = 1
);
```

### 5.3 How Existing Tables Are Reused

| Table | Role in Group Workflow |
|---|---|
| `stems` | `group_annotation_tasks.stem_id → stems.id` |
| `spans` | Event annotator creates spans with `group_task_id` set. All 3 timeline annotators reference these same span IDs via `timeline_annotations.span_id → spans.id` |
| `users` | Members are users. No new role column needed on `users` — roles are per-task in `group_annotation_members` |
| `batches` / `batch_stems` | **Not used** — group annotation is a parallel workflow |
| `relations` / `matrix_snapshots` | **Not used directly** — each timeline annotator's relations are stored in `timeline_relation_matrices` instead. The shared event spans go in `spans` as before. |

---

## 6. Proposed API Endpoints

| Method | Path | Who Can Call | Description |
|---|---|---|---|
| `POST` | `/group-tasks` | Admin/Lead | Create a group annotation task (stem_id, event_user_id, timeline_user_ids[3]) |
| `GET` | `/group-tasks` | Authenticated | List tasks assigned to the current user |
| `GET` | `/group-tasks/{id}` | Authenticated | Task details + agreement scores |
| `GET` | `/group-tasks/{id}/events` | Any member | Get event spans (read-only for timeline annotators) |
| `POST` | `/group-tasks/{id}/events` | Event Annotator | Create an event span |
| `DELETE` | `/group-tasks/{id}/events/{span_id}` | Event Annotator | Delete an event span |
| `POST` | `/group-tasks/{id}/submit-events` | Event Annotator | Lock events, advance status to `event_done` |
| `GET` | `/group-tasks/{id}/my-timeline` | Timeline Annotator | Get this annotator's saved positions |
| `PUT` | `/group-tasks/{id}/my-timeline` | Timeline Annotator | Save/update timeline positions (bulk upsert) |
| `POST` | `/group-tasks/{id}/submit-timeline` | Timeline Annotator | Finalize: lock positions, build Allen matrix, check if all 3 done → trigger agreement |
| `GET` | `/group-tasks/{id}/agreement` | Admin/Lead | Get computed agreement scores |
| `POST` | `/group-tasks/{id}/accept` | Admin/Lead | Manually accept or reject |
| `GET` | `/group-tasks/dashboard` | Authenticated | Aggregated stats: pending/completed/scores |

---

## 7. Frontend Changes

### 7.1 New Pages

| Route | Component | Purpose |
|---|---|---|
| `app/group-tasks/page.tsx` | Group task list | Shows tasks assigned to the logged-in user |
| `app/group-tasks/create/page.tsx` | Create form | Select stem, assign 1 event + 3 timeline annotators |
| `app/group-tasks/[task_id]/page.tsx` | Task detail | Status tracker, member list, agreement scores |
| `app/group-annotate/[task_id]/page.tsx` | Annotation view | Adapts based on user's role (see below) |

### 7.2 Annotation Interface Behavior

**If user is the Event Annotator:**
- Shows **TextLabeler** only (Step 1 of the current 3-step flow).
- User highlights event spans in the text.
- "Submit Events" button locks the events.
- Steps 2 and 3 are hidden.

**If user is a Timeline Annotator:**
- Shows **Timeline + AllenMatrix** (Steps 2 & 3), but events are **read-only**.
- Event badges are visible in the text but not editable.
- User drags events on the timeline independently.
- "Submit Timeline" button saves positions, builds Allen matrix, and locks the view.
- **Cannot see other annotators' work.**

### 7.3 New Components

| Component | Purpose |
|---|---|
| `components/AgreementDashboard.tsx` | Displays κ/α scores with color coding |
| `components/TimelineComparison.tsx` | Side-by-side overlay of 3 timelines (admin-only, after all submissions) |

---

## 8. Recommendations

### R1: Use Krippendorff's Alpha as the Primary Metric

Cohen's Kappa is limited to 2 raters and categorical data. Since we have 3 raters
and continuous timeline positions, **Krippendorff's Alpha (interval)** is the
statistically correct primary metric. Compute Cohen's Kappa on the Allen relation
matrices as a familiar secondary metric.

### R2: Per-Task Role Assignment (Not Per-User Roles)

Don't add a `role` column to the `users` table. Instead, assign roles per-task in
`group_annotation_members`. This is more flexible — the same user can be an event
annotator for one stem and a timeline annotator for another.

### R3: Store All 3 Annotator Timelines Separately

Don't merge or average the timelines during annotation. Store each annotator's
`(tl_start, tl_end)` independently in `timeline_annotations`. Merging can happen at
export time based on the chosen consensus strategy.

### R4: Keep the Old Batch Workflow Operational

The group annotation workflow should exist alongside the current single-user batch
workflow, not replace it. Use the single-user workflow for initial exploration and
the group workflow for research-grade annotation.

### R5: Immutability After Submission

Once a timeline annotator submits, their data should be frozen. This prevents them
from seeing agreement scores and retroactively adjusting. Implement this by checking
`group_annotation_members.status = 'done'` and rejecting further writes.

### R6: Use scikit-learn for Cohen's Kappa

`sklearn.metrics.cohen_kappa_score` is battle-tested. For Krippendorff's Alpha, use
the `krippendorff` Python package (`pip install krippendorff`) or implement from
scratch (the algorithm is ~30 lines — see Section 4.5).

### R7: Implementation Order

1. **Database migration** (new tables + `spans` modification) — Phase 1
2. **Backend API endpoints** — Phase 1
3. **Agreement computation module** (`backend/agreement.py`) — Phase 1
4. **Frontend: task management** (create, list, detail pages) — Phase 2
5. **Frontend: annotation interface** (role-adaptive view) — Phase 3
6. **Frontend: agreement dashboard** — Phase 4
7. **Export with agreement scores** — Phase 5

---

## 9. Open Questions

These must be resolved before implementation begins:

### Q1: Agreement Metric Preference

> Should we use **Krippendorff's Alpha** as the primary acceptance criterion
> (recommended, handles continuous data natively), or stick strictly with
> **Cohen's Kappa** as originally requested?
>
> Both can be computed and stored. The question is which one gates acceptance.

### Q2: Acceptance Threshold

> Is **κ/α ≥ 0.60** (substantial agreement) the right cutoff, or does the research
> require a different threshold? Some NLP papers use 0.67 or 0.80.

### Q3: Final Consensus Matrix Strategy

> When a stem is accepted, what becomes the "gold standard" Allen matrix?
>
> - **(a) Majority vote**: For each cell (i,j), take the relation that 2-of-3
>   annotators agree on.
> - **(b) Averaged positions**: Average the 3 annotators' `(tl_start, tl_end)` per
>   event, then recompute the matrix from the averaged positions.
> - **(c) Closest-to-consensus**: Pick the single annotator whose matrix has the
>   highest agreement with the other two, and use their matrix.
>
> Recommendation: **(b)** — it produces a single coherent matrix that respects the
> Allen algebra constraints.

### Q4: Task Creation Permissions

> Who can create group annotation tasks?
>
> - **(a) Any registered user** — self-service, simpler.
> - **(b) Admin/lead role only** — requires adding a `role` column to `users`
>   (e.g., `'admin' | 'annotator'`), or a separate `admins` table.
>
> If (b), we need to define how users become admins (first user? manual SQL?
> Settings page?).

### Q5: Re-Annotation Strategy on Rejection

> When κ is below the threshold:
>
> - **(a)** Allow the **same 3** timeline annotators to redo their work.
> - **(b)** Assign **new** annotators (requires a pool of available annotators).
> - **(c)** Flag for **manual adjudication** by an expert who reviews all 3
>   timelines and creates the gold standard.
>
> Recommendation: **(c)** for research rigor.

### Q6: Scope of Group Workflow vs. Old Workflow

> Should the old single-user batch workflow remain fully operational alongside the
> new group workflow, or should it be deprecated / hidden?
>
> Recommendation: Keep both. The single-user workflow is useful for solo exploration
> and training new annotators before they participate in group tasks.

---

## 10. Reference: Existing Codebase Map

### Backend Files

| File | Purpose | Key Functions |
|---|---|---|
| `backend/main.py` | All API routes (~1836 lines) | `create_batch`, `create_batch_span`, `save_batch_matrix`, `override_batch_matrix`, `mark_batch_stem_done`, `export_batch_json` |
| `backend/database.py` | asyncpg connection pool | `get_pool()`, `close_pool()` |
| `backend/models.py` | Pydantic request/response schemas | `BatchSpanCreate`, `BatchSpanOut`, `MatrixOverride`, `SpanCreate`, `SpanOut` |
| `backend/llm.py` | LLM integration (OpenRouter) | `callLLM()`, `_call_openai_compatible()` |
| `backend/allen/relations.py` | Allen relation computation | `compute_relation()`, `build_matrix()`, `INVERSES`, `RELATIONS` |
| `backend/allen/validate.py` | Transitivity checking | `transitivity_check()` |

### Frontend Files

| File | Purpose |
|---|---|
| `spatiotemporal-labeling/app/annotate/[batch_id]/[stem_id]/page.tsx` | 3-step annotator (TextLabeler → Timeline → AllenMatrix) |
| `spatiotemporal-labeling/app/dashboard/page.tsx` | User dashboard |
| `spatiotemporal-labeling/app/stems/page.tsx` | Stems pool browser |
| `spatiotemporal-labeling/components/TextLabeler.tsx` | Event/time span marking |
| `spatiotemporal-labeling/components/Timeline.tsx` | 0–100 timeline slider |
| `spatiotemporal-labeling/components/AllenMatrix.tsx` | N×N relation matrix |
| `spatiotemporal-labeling/lib/api.ts` | API helper (`apiFetch()`) |
| `spatiotemporal-labeling/lib/types.ts` | TypeScript interfaces |

### Database Migrations

| File | What it does |
|---|---|
| `backend/migrations/schema.sql` | Original schema (sessions, spans, relations, matrix_snapshots) |
| `backend/migrations/002_add_source.sql` | Added `source` column to spans |
| `backend/migrations/003_multi_user.sql` | Added users, stems, batches, batch_stems, auth_sessions |
| `backend/migrations/004_fix_schema_and_orphans.sql` | FK fixes, CHECK constraints, negative-ID migration |
| `backend/migrations/005_group_annotation.sql` | **TO BE CREATED** — the group annotation schema |

### Key Constraints to Know

1. **Mutual exclusivity on `spans`**: Each span must belong to exactly one of
   `session_id`, `batch_stem_id`, or (new) `group_task_id`. Enforced by a CHECK
   constraint.

2. **Partial unique indexes on `relations`**: The `ON CONFLICT` clauses must include
   `WHERE session_id IS NOT NULL` (or `batch_stem_id IS NOT NULL`) to match the
   partial unique index. This is a PostgreSQL requirement.

3. **`build_matrix()`** in `allen/relations.py` takes a list of span dicts with
   `tl_start` and `tl_end` keys and returns an N×N list-of-lists with Allen relation
   codes.

4. **INVERSES dict** maps each relation code to its inverse. Used to fill in
   `matrix[j][i]` when `matrix[i][j]` is known.

---

*Last updated: 2026-09-19*
