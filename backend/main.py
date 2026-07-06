"""
FastAPI backend for Spatiotemporal Annotation & Allen's Algebra Benchmarking System.
"""

import json
import csv
import io
from typing import Optional
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse

from database import get_pool, close_pool
from models import (
    SessionCreate, SessionStatusUpdate,
    SpanCreate, SpanUpdate, MatrixOverride,
    ExtractEventsRequest, ExtractEventsResponse
)
from allen.relations import build_matrix, RELATION_NAMES, INVERSES
from allen.validate import transitivity_check
from llm import callLLM


SYSTEM_PROMPT = """You extract temporal EVENTS from a narrative and lay them out on one relative timeline.

An event is a concrete occurrence, action, or state-change that happens at a point or
over a span of story time (e.g. "signed up for a half marathon", "started training",
"pulled a muscle", "the race started", "crossed the finish line").
Do NOT return bare time expressions ("first Saturday of March", "6 AM", "mid-February")
as events — instead USE them to decide when events happen.

Order events by STORY TIME, not by the order they appear in the text. Narratives jump
around; honor cues like "five months earlier", "nearly a year ago", "the last day of
January", "mid-February", "the Wednesday before", "On Saturday", "6 AM". Place and space
events by when they actually occur in the story world.

Use a 0-100 timeline. 0 = the earliest moment any event begins, 100 = the latest moment
any event ends. For each event give start and end:
- Punctual (an instant, e.g. "crossed the finish line") -> end == start (or +0.5).
- Durative (e.g. "trained for five months", "rested for two weeks") -> width proportional
  to its real-world duration relative to the other events.
Relative ordering and relative durations are what matter, not exact numbers.

Return the VERBATIM text of each event exactly as it appears in the source, so it can be
located by string match. If that exact string appears more than once, give its 1-based
occurrence index.

Respond with JSON only. No prose, no markdown fences."""

SCHEMA_JSON = json.dumps({
    "events": [
        {
            "text": "verbatim substring, exactly as in the source",
            "occurrence": 1,
            "start": 0,
            "end": 100,
            "kind": "punctual | durative",
            "reason": "short note: which time cue placed it (for debugging)"
        }
    ]
}, indent=2)

TIMELINE_MIN = 0.0
TIMELINE_MAX = 100.0
MIN_WIDTH = 5.0


@asynccontextmanager
async def lifespan(app: FastAPI):
    await get_pool()
    yield
    await close_pool()


app = FastAPI(title="Spatiotemporal Annotator API", version="1.0.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------

async def _get_session_or_404(pool, session_id: int):
    row = await pool.fetchrow("SELECT * FROM annotation_sessions WHERE id = $1", session_id)
    if not row:
        raise HTTPException(status_code=404, detail="Session not found")
    return row


async def _get_spans(pool, session_id: int):
    return await pool.fetch(
        "SELECT * FROM spans WHERE session_id = $1 ORDER BY created_at", session_id
    )


async def _get_event_spans(pool, session_id: int):
    return await pool.fetch(
        "SELECT * FROM spans WHERE session_id = $1 AND label_type = 'Event' ORDER BY created_at", session_id
    )


def _next_seq_label(existing_spans, label_type: str) -> str:
    prefix = "E" if label_type == "Event" else "T"
    count = sum(1 for s in existing_spans if s["label_type"] == label_type)
    return f"{prefix}{count + 1}"


# ---------------------------------------------------------------------------
# Sessions
# ---------------------------------------------------------------------------

@app.post("/sessions", status_code=201)
async def create_session(body: SessionCreate):
    pool = await get_pool()
    row = await pool.fetchrow(
        "INSERT INTO annotation_sessions (username, stem_text) VALUES ($1, $2) RETURNING id",
        body.username, body.stem_text
    )
    return {"session_id": row["id"]}


@app.get("/sessions")
async def list_sessions(username: Optional[str] = Query(None)):
    pool = await get_pool()
    if username:
        rows = await pool.fetch(
            "SELECT * FROM annotation_sessions WHERE username = $1 ORDER BY created_at DESC",
            username
        )
    else:
        rows = await pool.fetch(
            "SELECT * FROM annotation_sessions ORDER BY created_at DESC"
        )
    return [dict(r) for r in rows]


@app.get("/sessions/{session_id}")
async def get_session(session_id: int):
    pool = await get_pool()
    session = await _get_session_or_404(pool, session_id)
    spans = await _get_spans(pool, session_id)
    snapshot = await pool.fetchrow(
        "SELECT * FROM matrix_snapshots WHERE session_id = $1 ORDER BY updated_at DESC LIMIT 1",
        session_id
    )
    return {
        **dict(session),
        "spans": [dict(s) for s in spans],
        "matrix_snapshot": dict(snapshot) if snapshot else None
    }


@app.patch("/sessions/{session_id}/status")
async def update_session_status(session_id: int, body: SessionStatusUpdate):
    pool = await get_pool()
    await _get_session_or_404(pool, session_id)
    if body.status == "done":
        await pool.execute(
            "UPDATE annotation_sessions SET status=$1, completed_at=now() WHERE id=$2",
            body.status, session_id
        )
    else:
        await pool.execute(
            "UPDATE annotation_sessions SET status=$1 WHERE id=$2",
            body.status, session_id
        )
    return {"ok": True}


@app.delete("/sessions/{session_id}", status_code=204)
async def delete_session(session_id: int):
    pool = await get_pool()
    await _get_session_or_404(pool, session_id)
    await pool.execute("DELETE FROM annotation_sessions WHERE id=$1", session_id)


# ---------------------------------------------------------------------------
# Spans
# ---------------------------------------------------------------------------

@app.post("/sessions/{session_id}/spans", status_code=201)
async def create_span(session_id: int, body: SpanCreate):
    pool = await get_pool()
    await _get_session_or_404(pool, session_id)
    existing = await _get_spans(pool, session_id)
    seq_label = _next_seq_label(existing, body.label_type)

    row = await pool.fetchrow(
        """INSERT INTO spans
           (session_id, label_type, seq_label, span_text, char_start, char_end, tl_start, tl_end, source)
           VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9)
           RETURNING *""",
        session_id, body.label_type, seq_label,
        body.span_text, body.char_start, body.char_end,
        body.tl_start, body.tl_end,
        body.source
    )
    return dict(row)


@app.patch("/spans/{span_id}")
async def update_span(span_id: int, body: SpanUpdate):
    pool = await get_pool()
    row = await pool.fetchrow("SELECT * FROM spans WHERE id=$1", span_id)
    if not row:
        raise HTTPException(status_code=404, detail="Span not found")
    tl_start = body.tl_start if body.tl_start is not None else row["tl_start"]
    tl_end = body.tl_end if body.tl_end is not None else row["tl_end"]
    updated = await pool.fetchrow(
        "UPDATE spans SET tl_start=$1, tl_end=$2 WHERE id=$3 RETURNING *",
        tl_start, tl_end, span_id
    )
    return dict(updated)


@app.delete("/spans/{span_id}", status_code=204)
async def delete_span(span_id: int):
    pool = await get_pool()
    row = await pool.fetchrow("SELECT * FROM spans WHERE id=$1", span_id)
    if not row:
        raise HTTPException(status_code=404, detail="Span not found")
    await pool.execute("DELETE FROM spans WHERE id=$1", span_id)


# ---------------------------------------------------------------------------
# Matrix
# ---------------------------------------------------------------------------

@app.get("/sessions/{session_id}/matrix")
async def get_matrix(session_id: int):
    pool = await get_pool()
    await _get_session_or_404(pool, session_id)
    spans = await _get_event_spans(pool, session_id)
    span_list = [dict(s) for s in spans]
    matrix = build_matrix(span_list)
    span_order = [{"id": s["id"], "seq_label": s["seq_label"]} for s in span_list]
    violations = transitivity_check(matrix, [s["seq_label"] for s in span_list])
    return {"matrix": matrix, "span_order": span_order, "violations": violations}


@app.post("/sessions/{session_id}/matrix/save")
async def save_matrix(session_id: int):
    pool = await get_pool()
    await _get_session_or_404(pool, session_id)
    spans = await _get_event_spans(pool, session_id)
    span_list = [dict(s) for s in spans]
    matrix = build_matrix(span_list)
    span_order = [{"id": s["id"], "seq_label": s["seq_label"]} for s in span_list]

    existing = await pool.fetchrow(
        "SELECT id FROM matrix_snapshots WHERE session_id=$1", session_id
    )
    if existing:
        await pool.execute(
            "UPDATE matrix_snapshots SET matrix_json=$1, span_order=$2, updated_at=now() WHERE session_id=$3",
            json.dumps(matrix), json.dumps(span_order), session_id
        )
    else:
        await pool.execute(
            "INSERT INTO matrix_snapshots (session_id, matrix_json, span_order) VALUES ($1,$2,$3)",
            session_id, json.dumps(matrix), json.dumps(span_order)
        )

    for i, si in enumerate(span_list):
        for j, sj in enumerate(span_list):
            code = matrix[i][j]
            await pool.execute(
                """INSERT INTO relations (session_id, span_i_id, span_j_id, relation_code)
                   VALUES ($1,$2,$3,$4)
                   ON CONFLICT (session_id, span_i_id, span_j_id)
                   DO UPDATE SET relation_code=$4""",
                session_id, si["id"], sj["id"], code
            )

    return {"ok": True, "matrix": matrix, "span_order": span_order}


@app.patch("/sessions/{session_id}/matrix/override")
async def override_matrix_cell(session_id: int, body: MatrixOverride):
    pool = await get_pool()
    await _get_session_or_404(pool, session_id)
    spans = await _get_event_spans(pool, session_id)
    span_list = [dict(s) for s in spans]
    n = len(span_list)

    if body.i < 0 or body.i >= n or body.j < 0 or body.j >= n:
        raise HTTPException(status_code=400, detail="Index out of range")
    if body.i == body.j:
        raise HTTPException(status_code=400, detail="Cannot override diagonal")

    snapshot = await pool.fetchrow(
        "SELECT * FROM matrix_snapshots WHERE session_id=$1 ORDER BY updated_at DESC LIMIT 1",
        session_id
    )
    if not snapshot:
        raise HTTPException(status_code=400, detail="Save matrix first before overriding")

    matrix = json.loads(snapshot["matrix_json"])
    matrix[body.i][body.j] = body.relation_code
    inv = INVERSES.get(body.relation_code, -body.relation_code)
    matrix[body.j][body.i] = inv

    await pool.execute(
        "UPDATE matrix_snapshots SET matrix_json=$1, updated_at=now() WHERE session_id=$2",
        json.dumps(matrix), session_id
    )

    si_id = span_list[body.i]["id"]
    sj_id = span_list[body.j]["id"]
    await pool.execute(
        """INSERT INTO relations (session_id, span_i_id, span_j_id, relation_code, is_override)
           VALUES ($1,$2,$3,$4,TRUE)
           ON CONFLICT (session_id, span_i_id, span_j_id)
           DO UPDATE SET relation_code=$4, is_override=TRUE""",
        session_id, si_id, sj_id, body.relation_code
    )

    return {"ok": True, "matrix": matrix}


# ---------------------------------------------------------------------------
# Export
# ---------------------------------------------------------------------------

@app.get("/export/csv")
async def export_csv():
    pool = await get_pool()
    sessions = await pool.fetch(
        "SELECT * FROM annotation_sessions WHERE status='done' ORDER BY created_at"
    )
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["session_id", "username", "stem_text", "span_i", "span_j",
                     "relation_code", "relation_name", "is_override"])
    for s in sessions:
        relations = await pool.fetch(
            """SELECT r.*, si.seq_label as label_i, sj.seq_label as label_j
               FROM relations r
               JOIN spans si ON r.span_i_id = si.id
               JOIN spans sj ON r.span_j_id = sj.id
               WHERE r.session_id=$1""",
            s["id"]
        )
        for r in relations:
            writer.writerow([
                s["id"], s["username"], s["stem_text"],
                r["label_i"], r["label_j"], r["relation_code"],
                RELATION_NAMES.get(r["relation_code"], "unknown"),
                r["is_override"]
            ])
    output.seek(0)
    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=annotations.csv"}
    )


@app.get("/export/json")
async def export_json():
    pool = await get_pool()
    sessions = await pool.fetch(
        "SELECT * FROM annotation_sessions WHERE status='done' ORDER BY created_at"
    )
    result = []
    for s in sessions:
        spans = await _get_spans(pool, s["id"])
        snapshot = await pool.fetchrow(
            "SELECT * FROM matrix_snapshots WHERE session_id=$1 ORDER BY updated_at DESC LIMIT 1",
            s["id"]
        )
        result.append({
            **{k: _serialize(v) for k, v in dict(s).items()},
            "spans": [{k: _serialize(v) for k, v in dict(sp).items()} for sp in spans],
            "matrix": json.loads(snapshot["matrix_json"]) if snapshot else [],
            "span_order": json.loads(snapshot["span_order"]) if snapshot else [],
        })
    return result


def _serialize(value):
    if hasattr(value, 'isoformat'):
        return value.isoformat()
    return value

@app.get("/sessions/{session_id}/export")
async def export_session(session_id: int):
    pool = await get_pool()
    session = await _get_session_or_404(pool, session_id)
    spans = await _get_spans(pool, session_id)
    snapshot = await pool.fetchrow(
        "SELECT * FROM matrix_snapshots WHERE session_id=$1 ORDER BY updated_at DESC LIMIT 1",
        session_id
    )
    payload = {
        **{k: _serialize(v) for k, v in dict(session).items()},
        "spans": [{k: _serialize(v) for k, v in dict(sp).items()} for sp in spans],
        "matrix": json.loads(snapshot["matrix_json"]) if snapshot else [],
        "span_order": json.loads(snapshot["span_order"]) if snapshot else [],
    }
    return StreamingResponse(
        iter([json.dumps(payload)]),
        media_type="application/json",
        headers={"Content-Disposition": f"attachment; filename=session_{session_id}.json"}
    )


# ---------------------------------------------------------------------------
# LLM extraction helpers
# ---------------------------------------------------------------------------

def _find_nth_occurrence(text: str, needle: str, n: int) -> int:
    """Return 0-based char_start of the n-th (1-based) case-sensitive match, or -1."""
    start = 0
    for _ in range(n):
        idx = text.find(needle, start)
        if idx == -1:
            return -1
        start = idx + 1
    return start - 1


def _normalize_positions(events: list[dict]) -> list[dict]:
    if not events:
        return events
    starts = [e["start"] for e in events]
    ends = [e["end"] for e in events]
    raw_min = min(starts)
    raw_max = max(ends)
    span = raw_max - raw_min
    if span == 0:
        for e in events:
            e["start"] = TIMELINE_MIN
            e["end"] = TIMELINE_MAX
    else:
        for e in events:
            e["start"] = round((e["start"] - raw_min) / span * (TIMELINE_MAX - TIMELINE_MIN) + TIMELINE_MIN, 1)
            e["end"] = round((e["end"] - raw_min) / span * (TIMELINE_MAX - TIMELINE_MIN) + TIMELINE_MIN, 1)
    return events


def _ensure_end_ge_start(events: list[dict]) -> list[dict]:
    for e in events:
        if e["end"] < e["start"]:
            avg = (e["start"] + e["end"]) / 2
            e["start"] = round(avg - MIN_WIDTH / 2, 1)
            e["end"] = round(avg + MIN_WIDTH / 2, 1)
        elif e["end"] == e["start"]:
            e["end"] = round(e["start"] + MIN_WIDTH, 1)
        e["start"] = max(TIMELINE_MIN, e["start"])
        e["end"] = min(TIMELINE_MAX, e["end"])
    return events


def _find_raw_event_chars(text: str, event: dict) -> Optional[dict]:
    occ = event.get("occurrence", 1)
    event_text = event.get("text", "")
    if not event_text:
        return None
    idx = _find_nth_occurrence(text, event_text, occ)
    if idx != -1:
        return {"char_start": idx, "char_end": idx + len(event_text)}
    collapsed = " ".join(text.split())
    idx = _find_nth_occurrence(collapsed, event_text, occ)
    if idx != -1:
        return {"char_start": idx, "char_end": idx + len(event_text)}
    return None


def _overlaps(a_start, a_end, b_start, b_end) -> bool:
    return not (a_end <= b_start or b_end <= a_start)


# ---------------------------------------------------------------------------
# LLM extraction route
# ---------------------------------------------------------------------------

@app.post("/api/extract-events")
async def extract_events(body: ExtractEventsRequest):
    text = (body.text or "").strip()
    if not text:
        return ExtractEventsResponse(events=[], skipped=[]).model_dump()

    user_msg = f"{text}\n\nReturn JSON matching this schema:\n{SCHEMA_JSON}"
    try:
        raw = await callLLM(SYSTEM_PROMPT, user_msg)
    except ValueError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"LLM provider error: {exc}") from exc

    if not isinstance(raw, dict):
        raise HTTPException(status_code=502, detail="LLM returned an unexpected response shape.")

    raw_events = raw.get("events", [])
    if not isinstance(raw_events, list):
        raise HTTPException(status_code=502, detail="LLM returned an unexpected events list.")

    # Step 1: resolve char offsets and collect typed entries
    typed: list[dict] = []
    skipped: list[dict] = []

    for ev in raw_events:
        if not isinstance(ev, dict):
            continue
        evt_text = ev.get("text", "")
        chars = _find_raw_event_chars(text, ev)
        if chars is None:
            skipped.append({
                "text": evt_text,
                "reason": "Could not locate text in source even after whitespace normalization."
            })
            continue
        if not isinstance(ev.get("start"), (int, float)) or not isinstance(ev.get("end"), (int, float)):
            skipped.append({
                "text": evt_text,
                "reason": "Missing start or end value from model."
            })
            continue
        typed.append({
            "text": evt_text,
            "char_start": chars["char_start"],
            "char_end": chars["char_end"],
            "start": ev["start"],
            "end": ev["end"],
        })

    # Step 2: normalize positions over the resolved set (order-preserving affine)
    _normalize_positions(typed)

    # Step 3: normalize punctual events to ensure end >= start
    _ensure_end_ge_start(typed)

    # Step 4: deduplicate by char overlap within this batch
    accepted: list[dict] = []
    for t in typed:
        overlap = any(
            _overlaps(t["char_start"], t["char_end"], a["char_start"], a["char_end"])
            for a in accepted
        )
        if overlap:
            skipped.append({"text": t["text"], "reason": "Overlaps with another extracted event in this batch."})
        else:
            accepted.append({
                "label_type": "Event",
                "span_text": t["text"],
                "char_start": t["char_start"],
                "char_end": t["char_end"],
                "tl_start": t["start"],
                "tl_end": t["end"],
                "source": "llm",
            })

    return ExtractEventsResponse(events=accepted, skipped=skipped).model_dump()
