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
    SpanCreate, SpanUpdate, MatrixOverride
)
from allen.relations import build_matrix, RELATION_NAMES, INVERSES
from allen.validate import transitivity_check


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
           (session_id, label_type, seq_label, span_text, char_start, char_end, tl_start, tl_end)
           VALUES ($1,$2,$3,$4,$5,$6,$7,$8)
           RETURNING *""",
        session_id, body.label_type, seq_label,
        body.span_text, body.char_start, body.char_end,
        body.tl_start, body.tl_end
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
