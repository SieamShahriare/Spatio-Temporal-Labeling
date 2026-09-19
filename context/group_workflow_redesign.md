# Group Annotation Workflow — Redesign Spec

> **Status**: Agreed method, not yet implemented.
> **Supersedes** the workflow/UI sections of [`cohen_kappa.md`](./cohen_kappa.md).
> The agreement *metrics* defined in that document are unchanged; what changes is how
> work is assigned, how it is edited, and how the annotation UI is built.

---

## Table of Contents

1. [Why This Redesign](#1-why-this-redesign)
2. [Decisions Locked In](#2-decisions-locked-in)
3. [Assignment & Distribution](#3-assignment--distribution)
4. [Task Lifecycle](#4-task-lifecycle)
5. [Editing, Revisions, and Recompute](#5-editing-revisions-and-recompute)
6. [Permission Model](#6-permission-model)
7. [UI Architecture](#7-ui-architecture)
8. [LLM Assist & Provenance](#8-llm-assist--provenance)
9. [Schema Changes](#9-schema-changes)
10. [API Changes](#10-api-changes)
11. [Implementation Order](#11-implementation-order)
12. [Risks & Mitigations](#12-risks--mitigations)
13. [Edge Cases](#13-edge-cases)

---

## 1. Why This Redesign

The first implementation of the group workflow (migration `005`, endpoints in `main.py`,
pages under `app/group-tasks/` and `app/group-annotate/`) is functionally complete but
has three problems:

| Problem | Consequence |
|---|---|
| **Divergent annotation UI** | Group annotators get a bespoke, simplified interface. The batch annotator and the group annotator drift apart with every change, and the group flow is missing the LLM assist entirely. |
| **Manual, one-at-a-time task creation** | Creating a task per stem, hand-picking 4 users each time, does not scale past a handful of stems. |
| **No self-service recovery** | If an assigned annotator cannot do the work, there is no way to hand it off, and no way to revise work once submitted. |

The redesign addresses all three. The agreement computation itself
(`backend/agreement.py`) is sound and stays as-is, with one change: it reads
**overridden** relation matrices instead of purely derived ones (§5).

---

## 2. Decisions Locked In

| # | Decision | Rationale |
|---|---|---|
| D1 | **Annotators can always edit their own work**, including after submission. Agreement recomputes on change. | Practical for a small research team; avoids dead-ended tasks. Independence is protected by D7 instead of by locking. |
| D2 | **4 distinct people per stem** — 1 event annotator + 3 timeline annotators. No person holds two roles on the same stem. | The person who chose the event spans has privileged framing; letting them also rate would inflate agreement. |
| D3 | **Timeline annotators get the full Step 3**, including Allen matrix cell override. Agreement compares overridden matrices. | True UI parity with the batch flow, and it measures what annotators actually assert rather than what slider math derived. |
| D4 | **Distribution is an explicit bulk operation** — select stems, hit Distribute, roles assigned round-robin. | Predictable, auditable, and reviewable after the fact. |
| D5 | **Event marking stays a separate, blocking phase.** | All three timeline annotators must position *the same* spans, or the timeline agreement is not computable. |
| D6 | **No admin role.** Distribution is open to any registered user. | Small trusted team; avoids a whole permissions subsystem. Permissions become membership relationships (§6). |
| D7 | **Participants cannot see agreement scores or each other's work for tasks they are a member of.** | The safeguard that makes D1 safe. Unlimited editing is fine as long as nobody can see the score they would be editing toward. |

---

## 3. Assignment & Distribution

### 3.1 Concepts

An **assignment** (one row in `group_annotation_members`) is the unit of work a person
sees in their queue. Each stem's group task has exactly 4 of them.

A **distribution run** groups the tasks created by a single Distribute action, purely
for provenance — so you can later answer "who distributed these 200 stems, to whom, and
when."

### 3.2 Algorithm

Input: `stem_ids[]`, and an optional `pool_user_ids[]` (default: all registered users).

```
1. Reject if pool size n < 4.                        (see §13 on the n < 5 case)
2. Drop stems that already have a group task.        (UNIQUE(stem_id) already enforces this)
3. Build the ring P: shuffle the pool randomly, then rotate it so the
   least-loaded person sits first.
4. For stem i (0-indexed) in the selected set:
       if i > 0 and i % n == 0:  re-shuffle P        (fresh pairings each full cycle)
       event_annotator     = P[(i    ) % n]
       timeline_annotator1 = P[(i + 1) % n]
       timeline_annotator2 = P[(i + 2) % n]
       timeline_annotator3 = P[(i + 3) % n]
5. Create the task (status = 'event_pending') and its 4 assignments in one transaction.
```

**Why step by 1 and not by 4.** Stepping the rotation offset by 4 looks natural — four
roles, four people — but if the pool size is divisible by 4 the offset only ever lands on
a fraction of the ring, and the event-annotator role gets permanently trapped on the same
two people. Stepping by 1 cycles the event-annotator role through everyone evenly: each
person is the event annotator once every *n* stems and a timeline annotator three times
out of every *n*.

**Why the ring is shuffled.** Rotation alone gives even *load* but systematically biased
*pairings*. With a fixed order and a pool of 8:

```
stem 0: A(event)  B C D(timeline)
stem 1: B(event)  C D E
stem 2: C(event)  D E F
...
stem 7: H(event)  A B C
```

Only 8 distinct trios ever form, out of the 56 possible, and A is never on a task with
D, E or F. If A and E systematically interpret events differently, **no task in the corpus
would ever measure it** — the agreement scores would be blind to the largest disagreement
in the pool.

Re-shuffling the ring every *n* stems fixes this at no cost to load balance: each full
cycle of *n* stems still hands every person exactly 1 event and 3 timeline assignments,
but the trios differ each cycle, so most rater pairs co-occur somewhere across a campaign.
It is also the stronger methods claim — *"annotator trios were randomized across stems"*
rather than *"annotators were assigned in fixed rotation."*

Allocation is therefore **randomly ordered but deterministically allocated**: randomness
decides who is grouped with whom, never how much work anyone receives.

**Load balance.** With *S* stems and *n* people, each person receives `4S/n` assignments,
±1. Seeding the rotation at the least-loaded person keeps successive distribution runs
balanced against each other, not just within a run.

### 3.3 Handoff / Reassignment

Any **un-submitted** assignment can be reassigned to another user.

- The assignee can hand off their own assignment ("I can't do this one")
- Anyone can reassign an assignment for recovery, if a person goes dark
- The new user must not already hold a role on that stem — otherwise one person could
  end up as two of the three timeline raters, which silently corrupts the agreement math
- `reassigned_from` / `reassigned_at` are recorded so churn is auditable

Submitted assignments cannot be reassigned; the work already exists and belongs to whoever
produced it.

---

## 4. Task Lifecycle

The current schema conflates workflow stage and verdict in a single `status` column. That
breaks down once work can be revised — a task can be simultaneously "accepted" and
"someone is editing it." Split into three fields:

| Field | Values | Set by |
|---|---|---|
| `status` | `event_pending` → `timelines_pending` → `computed` | System |
| `outcome` | `accepted` / `accepted_flagged` / `adjudication` / `rejected` / null | System, from α |
| `decision` | `accepted` / `rejected` / `adjudication` / null | A human (non-participant) |

```
        distribute
             │
             ▼
     ┌───────────────┐   event annotator submits   ┌────────────────────┐
     │ event_pending │ ──────────────────────────▶ │ timelines_pending  │
     └───────────────┘                             └────────────────────┘
                                                        │        ▲
                                    all 3 submitted ────┘        │ any member re-opens
                                                        ▼        │ (scores_stale = true)
                                                   ┌──────────┐  │
                                                   │ computed │ ─┘
                                                   └──────────┘
                                                        │ non-participant finalizes
                                                        ▼
                                                   decision set → editing frozen
```

**Blocked assignments.** A timeline assignment on a task still in `event_pending` is
*blocked* — derived, not stored. The queue shows it as "waiting on events" rather than
hiding it, so people can see what is coming.

**Freeze.** Once `decision` is non-null, members cannot edit. Any non-participant can
clear the decision to reopen the task.

---

## 5. Editing, Revisions, and Recompute

### 5.1 Member states

`pending` → `in_progress` → `submitted`, and re-entering a submitted assignment returns it
to `in_progress`. (This renames the current `done` state to `submitted`, which is honest
about the fact that it is not terminal.)

### 5.2 Recompute cycle

1. A member re-opens their work → task returns to `timelines_pending`, and
   `scores_stale = true`. **Existing scores are kept and shown greyed, not deleted** —
   deleting them would make the task look unfinished when it is merely being revised.
2. On re-submit, if all three timeline assignments are `submitted` again, agreement
   recomputes and `scores_stale` clears.

### 5.3 Append-only history

Two tables that are never updated or deleted, only inserted into:

- **`timeline_submission_revisions`** — one row per submit, holding that annotator's
  positions, their matrix, and whether LLM assist was used
- **`agreement_runs`** — one row per recompute, holding the scores and a
  `based_on_revisions` map of `{member_id: revision_no}`

This is what makes unlimited editing publishable. Instead of a bare final number with no
provenance, you can report:

> α = 0.52 at first submission, 0.71 final after revision (3 of 9 annotators revised).

That is a legitimate and disclosable methodology. A final-only number from an editable
system is not.

### 5.4 Matrices now include overrides

Per D3, each timeline annotator's matrix is saved from their positions and then
*mutated* by any cell overrides they make — exactly as the batch flow does with
`matrix_snapshots` + `relations`. Agreement reads the stored per-member matrix, so
overrides flow into Cohen's κ and Fleiss' κ automatically. Krippendorff's α is unaffected;
it reads raw timeline positions.

Overrides are stored in a dedicated `timeline_relations` table rather than by widening the
mutual-exclusivity CHECK on `relations` a third time (`session_id` / `batch_stem_id` /
`group_task_id` / `member_id` would make that constraint unmanageable).

### 5.5 When the event set changes

The event annotator can re-open and edit their work like anyone else (D1), but their edits
are not symmetric with timeline edits, because the event spans are the *shared substrate*
all three timeline annotators rate against.

| Edit | Effect |
|---|---|
| Span boundaries adjusted (`char_start` / `char_end`), span set unchanged | Nothing invalidated. Timelines and matrices still reference the same span IDs; agreement is untouched. |
| Span **added** or **deleted** | All three timeline submissions are superseded. Each timeline assignment returns to `in_progress`, the task returns to `timelines_pending`, and `scores_stale` is set. |

A span-set change is not a recompute — there is nothing to recompute *from*. The other
three annotators hold no position for a newly added event, and their stored matrices are
now the wrong dimension (an N×N matrix where the task needs (N+1)×(N+1)). Agreement cannot
produce a number again until all three re-position and re-submit.

Consequences for the implementation:

- Prior revisions are **retained**, not deleted — `timeline_submission_revisions` is
  append-only, so the superseded work stays in the record and remains reportable
- Each affected annotator's next submit creates a *new* revision, so the history shows
  plainly that the span set changed underneath them
- The UI must warn the event annotator loudly before an add/delete once any timeline work
  exists: *"This will send 3 submitted timelines back for re-annotation."*

---

## 6. Permission Model

With no admin role (D6), every permission is a **membership relationship**: the question is
never "what role does this user have" but "is this user a participant in *this* task."

| Action | Who |
|---|---|
| Distribute stems | Any registered user |
| Annotate an assignment | The assignee |
| Reassign an un-submitted assignment | The assignee, or anyone (recovery) |
| See a task's agreement scores | Anyone **not** a member of that task |
| See another annotator's timeline / matrix | Anyone **not** a member of that task |
| Set or clear `decision` | Anyone **not** a member of that task |

`created_by` on a task survives as provenance — who ran the distribution — but is no
longer a permission.

**Why this preserves independence.** With a pool of *n* people, each person is a member of
roughly `4/n` of all tasks. Everyone therefore retains near-complete visibility into the
dataset's agreement; they simply cannot see scores for the handful of tasks they personally
worked on. No elevated rights required.

**Accepted leak — aggregate stats.** Dashboard-level figures (e.g. average α across all
tasks) will include tasks the viewer participated in. Per-task views exclude their own
tasks; aggregates do not. With any realistic number of tasks a single task's pull on an
average is not actionable signal, and stripping it would make the headline number wrong for
every viewer.

---

## 7. UI Architecture

### 7.1 The core change

Extract the existing 3-step annotator from
`app/annotate/[batch_id]/[stem_id]/page.tsx` into **one shared component** driven by a data
adapter. Both flows then render the same component; neither can drift from the other.

```ts
interface AnnotationSource {
  stemText: string;
  spans: Span[];

  canEditEvents: boolean;
  canEditTimeline: boolean;

  createSpan(labelType, text, charStart, charEnd): Promise<void>;
  deleteSpan(spanId): Promise<void>;
  updateSpanPosition(spanId, tlStart, tlEnd): Promise<void>;

  getMatrix(): Promise<MatrixData>;
  saveMatrix(): Promise<void>;
  overrideMatrix(i, j, code): Promise<void>;

  llm: {
    extractEvents?(text): Promise<void>;
    extractTimeline?(): Promise<void>;
    labelAndTimeline?(text): Promise<void>;
  } | null;

  onSubmit(): Promise<void>;
  submitLabel: string;
}
```

Two adapters:

| Adapter | Backing |
|---|---|
| `batchStemSource(batchStemId)` | `batch_stems`, `spans`, `matrix_snapshots`, `relations` |
| `groupTaskSource(taskId, role)` | `group_annotation_tasks`, `spans`, `timeline_annotations`, `timeline_relations` |

Routes are unchanged — `/annotate/[batch_id]/[stem_id]` and `/group-annotate/[task_id]`
both become thin wrappers that build a source and render `<Annotator source={…} />`.

### 7.2 Role gating

Role controls only which steps are *live*. The chrome, components, keyboard behaviour,
autosave and LLM buttons are identical in both flows.

| Role | Step 1 — Events | Step 2 — Timeline | Step 3 — Matrix |
|---|---|---|---|
| Event annotator | Interactive | Hidden | Hidden |
| Timeline annotator | Read-only (locked spans) | Interactive | Interactive, with override |

### 7.3 Pages

| Page | Change |
|---|---|
| `app/dashboard/page.tsx` | Gains a **"My Assigned Tasks"** section above the existing batch content: role chip, stem preview, state (*Ready* / *Waiting on events* / *Submitted* / *Revise*), action button, reassign affordance. Ready tasks sort first; blocked ones greyed with the reason. |
| `app/group-tasks/distribute/page.tsx` | **New.** Select stems + confirm the annotator pool + preview the resulting allocation, then Distribute. Replaces the one-task-at-a-time create form. |
| `app/group-tasks/page.tsx` | Stays as the campaign overview. Score columns hidden for tasks the viewer is a member of. |
| `app/group-tasks/[task_id]/page.tsx` | Agreement panel gated by membership; gains revision history and agreement-run history. |
| `app/group-annotate/[task_id]/page.tsx` | Reduced to a thin wrapper over the shared annotator. |
| `components/AgreementDashboard.tsx` | Gains stale-score styling and an agreement-over-time view. |
| `components/Annotator.tsx` | **New.** The extracted shared 3-step annotator. |
| `lib/annotationSources.ts` | **New.** The two adapters. |

---

## 8. LLM Assist & Provenance

The LLM buttons come along with the shared component, so they become available in the group
flow for both roles.

**The risk.** If all three timeline annotators use LLM assist, they receive near-identical
positions, and κ ≈ 1.0 / α ≈ 1.0. The score then measures the LLM's determinism, not human
agreement. This does not need to be prevented, but it must be *visible*.

**The mitigation — provenance, not prohibition.**

- `spans.source` already records `manual` | `llm`
- Add `timeline_annotations.source` with the same values
- `timeline_submission_revisions.had_llm_assist` records it per submission

That makes three things possible later, at no cost now: report the LLM-assisted share of
the corpus, exclude LLM-assisted submissions from headline agreement, or treat the LLM as a
fourth virtual annotator and report human–LLM agreement as its own result.

---

## 9. Schema Changes

Migration `006_group_workflow_redesign.sql`. Additive except for the status remap in §9.1.

### 9.1 Task: split status / outcome / decision

```sql
ALTER TABLE group_annotation_tasks ADD COLUMN IF NOT EXISTS outcome      TEXT;
ALTER TABLE group_annotation_tasks ADD COLUMN IF NOT EXISTS decision     TEXT;
ALTER TABLE group_annotation_tasks ADD COLUMN IF NOT EXISTS decided_by   INT REFERENCES users(id);
ALTER TABLE group_annotation_tasks ADD COLUMN IF NOT EXISTS decided_at   TIMESTAMPTZ;
ALTER TABLE group_annotation_tasks ADD COLUMN IF NOT EXISTS scores_stale BOOLEAN NOT NULL DEFAULT FALSE;

-- Remap rows written by migration 005, where verdicts were stored in `status`
UPDATE group_annotation_tasks
   SET outcome = status, status = 'computed'
 WHERE status IN ('accepted', 'accepted_flagged', 'adjudication', 'rejected');
```

### 9.2 Members: reassignment provenance

```sql
ALTER TABLE group_annotation_members ADD COLUMN IF NOT EXISTS assigned_by     INT REFERENCES users(id);
ALTER TABLE group_annotation_members ADD COLUMN IF NOT EXISTS reassigned_from INT REFERENCES users(id);
ALTER TABLE group_annotation_members ADD COLUMN IF NOT EXISTS reassigned_at   TIMESTAMPTZ;

UPDATE group_annotation_members SET status = 'submitted' WHERE status = 'done';
```

### 9.3 Per-member relations (override support)

```sql
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
```

### 9.4 Timeline position provenance

```sql
ALTER TABLE timeline_annotations ADD COLUMN IF NOT EXISTS source TEXT NOT NULL DEFAULT 'manual';
```

### 9.5 Append-only history

```sql
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
```

### 9.6 Distribution provenance

```sql
CREATE TABLE IF NOT EXISTS distribution_runs (
    id            SERIAL PRIMARY KEY,
    created_by    INT NOT NULL REFERENCES users(id),
    created_at    TIMESTAMPTZ DEFAULT now(),
    stem_count    INT NOT NULL,
    pool_user_ids JSONB NOT NULL
);

ALTER TABLE group_annotation_tasks
    ADD COLUMN IF NOT EXISTS distribution_run_id INT REFERENCES distribution_runs(id);
```

---

## 10. API Changes

### 10.1 New

| Method | Path | Notes |
|---|---|---|
| `POST` | `/group-tasks/distribute` | `{stem_ids[], pool_user_ids?[]}` → creates tasks + assignments in one transaction |
| `GET` | `/my-tasks` | Current user's assignments, with derived `blocked` state; powers the dashboard section |
| `POST` | `/group-tasks/{id}/members/{member_id}/reassign` | `{user_id}`; rejects if target already holds a role on the stem |
| `GET` | `/group-tasks/{id}/my-matrix` | The member's own matrix + violations |
| `POST` | `/group-tasks/{id}/my-matrix/save` | Build from the member's positions |
| `PATCH` | `/group-tasks/{id}/my-matrix/override` | `{i, j, relation_code}`; writes `timeline_relations` with `is_override` |
| `GET` | `/group-tasks/{id}/revisions` | Submission history; non-participants only |
| `GET` | `/group-tasks/{id}/agreement-runs` | Agreement over time; non-participants only |

### 10.2 Changed

| Endpoint | Change |
|---|---|
| `PUT /group-tasks/{id}/my-timeline` | No longer rejects when the member has submitted; flips them back to `in_progress` and marks the task `scores_stale` |
| `POST /group-tasks/{id}/submit-timeline` | Uses the member's stored (possibly overridden) matrix; appends a revision row; recomputes when all three are submitted |
| `POST /group-tasks/{id}/accept` → `POST /group-tasks/{id}/decision` | Gate changes from "task creator" to "any non-participant"; records `decided_by` / `decided_at`; accepts null to reopen |
| `GET /group-tasks/{id}/agreement` | Returns `403` for members of that task (D7) |
| `GET /group-tasks/{id}` | Omits score fields for members of that task |
| `POST /api/llm-label-and-timeline` | Accepts a group-task target as well as a batch-stem target; stamps `source='llm'` on positions |

### 10.3 Retired

`POST /group-tasks` (single-task creation) is superseded by `/group-tasks/distribute`.
Worth keeping until the distribute page ships, then removing.

---

## 11. Implementation Order

Each phase leaves the app working.

| Phase | Scope | Why this order |
|---|---|---|
| **1** | Migration `006`; status/outcome/decision split; member status rename | Everything else reads these fields |
| **2** | `/group-tasks/distribute` + `/my-tasks` + reassignment endpoints | Unblocks real multi-stem use immediately, even on the current UI |
| **3** | Dashboard "My Assigned Tasks" + distribute page | The workflow becomes usable end to end |
| **4** | Extract `components/Annotator.tsx` + adapters; migrate the batch route onto it | Do this *before* wiring the group route, so the shared component is proven against the flow that already works |
| **5** | Point the group route at the shared annotator; per-member matrix save/override | Delivers UI parity, LLM assist, and D3 |
| **6** | Revisions, agreement runs, stale-score UI, membership gating of scores | Completes D1 + D7 |
| **7** | Export: agreement scores, revision counts, LLM-assisted share | Research output |

Phase 4 is the risky one — it touches a flow that currently works. It should be done as a
pure refactor with no behaviour change, verified against the batch flow before the group
adapter is written.

---

## 12. Risks & Mitigations

| Risk | Mitigation |
|---|---|
| Editable-forever work lets annotators converge toward a target score | Participants cannot see their own tasks' scores or each other's work (D7). Revision history makes any convergence visible after the fact. |
| LLM assist manufactures artificial agreement | Provenance on spans and positions (§8); report or exclude LLM-assisted submissions. |
| Refactoring the batch annotator breaks a working flow | Phase 4 is a behaviour-preserving refactor, verified on the batch flow before the group adapter exists. |
| Blocked timeline tasks leave people idle early in a campaign | Distribute in waves, or run an events-only first pass over the corpus. The queue shows blocked tasks with reasons so the state is legible. |
| A person abandons assignments mid-campaign | Anyone can reassign an un-submitted assignment. |
| Pool too small to satisfy 4 distinct people | Distribution rejects pools smaller than 4 with a clear error. See §13. |
| Late event-span edits repeatedly discard finished timeline work | Boundary-only edits never invalidate (§5.5); add/delete warns with the exact number of submissions it will reset. Revision history shows whether churn is coming from one annotator. |

---

## 13. Edge Cases

**Pools of exactly 4.** With 4 people and 4 roles per stem, everyone is a member of every
task, so no non-participant exists to view scores or set `decision` (§6). This is
arithmetic, not a distribution-policy choice — no shuffling scheme avoids it.

It is **not a blocker**, because `decision` is only an optional human override on top of
the automatic `outcome`. A 4-person pool simply runs on automatic outcomes: tasks are
still scored, bucketed and exportable; there is just no manual accept/reject until the
pool reaches 5. Distribution therefore enforces a hard floor of 4 and surfaces an
informational note below 5:

> *4 annotators: tasks will be scored automatically. Manual accept/reject becomes
> available with 5 or more annotators.*

Agreement scores for such tasks remain hidden from their members per D7 — which, in a
4-person pool, means hidden from everyone until the pool grows. The scores are still
recorded and exportable.

**Concurrent distribution.** Two people distributing overlapping stem sets at the same
time is resolved by the existing `UNIQUE(stem_id)` constraint on `group_annotation_tasks`;
the second run skips the collided stems and reports them.

**Un-distributing.** A task with no submitted work can be deleted, returning its stem to
the pool. Once any assignment has been submitted, deletion is refused — release it through
`decision = rejected` instead, so the work stays in the record.

---

*Last updated: 2026-09-19*
