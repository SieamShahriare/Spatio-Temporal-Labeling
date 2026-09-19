"""
FastAPI backend for Spatiotemporal Annotation & Allen's Algebra Benchmarking System.
"""

import json
import csv
import io
import os
import random
from typing import Optional
from datetime import datetime, timezone, timedelta
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Query, Request, Depends, UploadFile, File
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse, Response

from database import get_pool, close_pool
from models import (
    SessionCreate, SessionStatusUpdate,
    SpanCreate, SpanUpdate, MatrixOverride,
    ExtractEventsRequest, ExtractEventsResponse,
    ExtractTimelineRequest, ExtractTimelineResponse,
    LLMLabelAndTimelineRequest, LLMLabelAndTimelineResponse,
    SignupRequest, LoginRequest, UserOut, AuthMeResponse,
    StemOut, StemsListResponse, StemsImportResponse,
    BatchCreate, BatchOut, BatchDetailOut,
    BatchSpanCreate, BatchSpanOut,
    ConflictResponse,
    GroupTaskCreate, GroupTaskOut, GroupTaskDetailOut, GroupMemberOut,
    GroupEventSpanCreate, GroupEventSpanOut,
    TimelineUpsertRequest, TimelinePositionOut,
    GroupAgreementOut, GroupTaskDecision, UserBriefOut,
    DistributeRequest, DistributeResponse, DistributeSkip,
    ReassignRequest, MyTaskOut,
)
from auth import (
    hash_password, verify_password,
    create_session, get_session, delete_session as delete_auth_session, get_user_by_id,
    set_session_cookies, clear_session_cookies,
    get_current_user, get_current_user_optional, validate_csrf,
)
from allen.relations import build_matrix, RELATION_NAMES, INVERSES
from allen.validate import transitivity_check
from llm import callLLM
from agreement import compute_agreement


SYSTEM_PROMPT = """You extract temporal EVENTS from a narrative.

An event is a concrete occurrence, action, or state-change that happens at a point or
over a span of story time (e.g. "signed up for a half marathon", "started training",
"pulled a muscle", "the race started", "crossed the finish line").
Do NOT return bare time expressions ("first Saturday of March", "6 AM", "mid-February")
as events — instead USE them to decide when events happen.

Order events by STORY TIME, not by the order they appear in the text. Narratives jump
around; honor cues like "five months earlier", "nearly a year ago", "the last day of
January", "mid-February", "the Wednesday before", "On Saturday", "6 AM".

Return the VERBATIM text of each event exactly as it appears in the source, so it can be
located by string match. If that exact string appears more than once, give its 1-based
occurrence index.

Respond with JSON only. No prose, no markdown fences."""

SCHEMA_JSON = json.dumps({
    "events": [
        {
            "text": "verbatim substring, exactly as in the source",
            "occurrence": 1
        }
    ]
}, indent=2)

TIMELINE_SCHEMA_JSON = json.dumps({
    "positions": [
        {
            "text": "verbatim event text, exactly as provided",
            "start": 0,
            "end": 100,
            "reason": "short note"
        }
    ]
}, indent=2)

TIMELINE_SYSTEM_PROMPT = """You assign relative timeline positions to events extracted from a narrative.

Given a stem text and a list of events with their verbatim texts, place each event on a
0-100 timeline where 0 is the earliest moment any event begins and 100 is the latest
moment any event ends. Use cues in the text like "five months earlier", "nearly a year
ago", "the last day of January", "mid-February", "the Wednesday before", "On Saturday",
"6 AM", durations ("trained for five months"), and ordering words ("first", "then", "before",
"after") to decide relative positions and durations.

Punctual events (an instant) -> end == start (or start + 0.5).
Durative events (spanning time) -> width proportional to real-world duration relative
to other events.

Return the updated start and end for EACH event exactly in the order given.
Return JSON only. No prose, no markdown fences."""


TIMELINE_MIN = 0.0
TIMELINE_MAX = 100.0
MIN_WIDTH = 5.0

LOCK_HOURS = 4
MAX_REBOOKS = 3


@asynccontextmanager
async def lifespan(app: FastAPI):
    pool = await get_pool()
    yield
    await close_pool()


app = FastAPI(title="Spatiotemporal Annotator API", version="1.0.0", lifespan=lifespan)

# Comma-separated list, e.g. "http://localhost:3000,https://my-app.vercel.app"
CORS_ORIGINS = [o.strip() for o in os.getenv("CORS_ORIGINS", "http://localhost:3000").split(",") if o.strip()]

app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
async def health():
    return {"ok": True}


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
async def create_annotation_session(body: SessionCreate):
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
                   ON CONFLICT (session_id, span_i_id, span_j_id) WHERE session_id IS NOT NULL
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
           ON CONFLICT (session_id, span_i_id, span_j_id) WHERE session_id IS NOT NULL
           DO UPDATE SET relation_code=$4, is_override=TRUE""",
        session_id, si_id, sj_id, body.relation_code
    )
    await pool.execute(
        """INSERT INTO relations (session_id, span_i_id, span_j_id, relation_code, is_override)
           VALUES ($1,$2,$3,$4,TRUE)
           ON CONFLICT (session_id, span_i_id, span_j_id) WHERE session_id IS NOT NULL
           DO UPDATE SET relation_code=$4, is_override=TRUE""",
        session_id, sj_id, si_id, inv
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
# AUTH
# ---------------------------------------------------------------------------

@app.post("/auth/signup", status_code=201)
async def signup(body: SignupRequest, response: Response):
    pool = await get_pool()
    existing = await pool.fetchrow("SELECT id FROM users WHERE email = $1", body.email)
    if existing:
        raise HTTPException(status_code=409, detail="Email already registered")
    pw_hash = hash_password(body.password)
    row = await pool.fetchrow(
        "INSERT INTO users (email, username, password_hash) VALUES ($1, $2, $3) RETURNING id, email, username, created_at",
        body.email, body.username, pw_hash
    )
    user = dict(row)
    token, csrf_token, _ = await create_session(user["id"])
    set_session_cookies(response, token, csrf_token)
    return {"user": UserOut(**user).model_dump(), "csrf_token": csrf_token}


@app.post("/auth/login")
async def login(body: LoginRequest, response: Response):
    pool = await get_pool()
    row = await pool.fetchrow("SELECT * FROM users WHERE email = $1", body.email)
    if not row or not verify_password(body.password, row["password_hash"]):
        raise HTTPException(status_code=401, detail="Invalid email or password")
    user = dict(row)
    token, csrf_token, _ = await create_session(user["id"])
    set_session_cookies(response, token, csrf_token)
    return {"user": UserOut(id=user["id"], email=user["email"], username=user["username"], created_at=user["created_at"]).model_dump(), "csrf_token": csrf_token}


@app.post("/auth/logout", status_code=204)
async def logout(request: Request, response: Response):
    token = request.cookies.get("session_token")
    if token:
        await delete_auth_session(token)
    clear_session_cookies(response)
    return None


@app.get("/auth/me")
async def auth_me(request: Request):
    user = await get_current_user(request)
    session = getattr(request.state, "session", None)
    return AuthMeResponse(
        user=UserOut(**user),
        csrf_token=session["csrf_token"] if session else ""
    )


# ---------------------------------------------------------------------------
# HELPERS
# ---------------------------------------------------------------------------

def _now() -> datetime:
    return datetime.now(timezone.utc)


def _ensure_aware(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt


def _seconds_until(target: datetime) -> int:
    return max(0, int((_ensure_aware(target) - _now()).total_seconds()))


async def _require_batch_lock(batch_id: int, user: dict) -> dict:
    pool = await get_pool()
    batch = await pool.fetchrow(
        "SELECT * FROM batches WHERE id = $1 AND owner_id = $2",
        batch_id, user["id"]
    )
    if not batch:
        raise HTTPException(status_code=404, detail="Batch not found")
    if _ensure_aware(batch["expires_at"]) <= _now():        raise HTTPException(
            status_code=423,
            detail="Lock expired or not yours - this batch may have returned to the pool"
        )
    return batch


# ---------------------------------------------------------------------------
# STEMS
# ---------------------------------------------------------------------------

@app.get("/stems")
async def list_stems(
    request: Request,
    search: Optional[str] = Query(None),
    status: str = Query("all"),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
):
    pool = await get_pool()
    user = await get_current_user_optional(request)
    like = f"%{search.strip()}%" if search else None
    offset = (page - 1) * page_size

    base_where = ""
    params = [page_size, offset]
    idx = 3

    if like:
        base_where = f"""
            AND (
                s.text ILIKE ${idx}
                OR CAST(s.id AS TEXT) ILIKE ${idx}
                OR EXISTS (
                    SELECT 1 FROM batch_stems bs
                    JOIN batches b ON b.id = bs.batch_id
                    JOIN users u ON u.id = b.owner_id
                    WHERE bs.stem_id = s.id
                      AND (u.username ILIKE ${idx} OR u.email ILIKE ${idx})
                )
                OR EXISTS (
                    SELECT 1 FROM batch_stems bs
                    JOIN users u ON u.id = bs.completed_by
                    WHERE bs.stem_id = s.id
                      AND bs.status = 'done'
                      AND (u.username ILIKE ${idx} OR u.email ILIKE ${idx})
                )
            )
        """
        params.append(like)
        idx += 1

    status_filter = ""
    if status == "available":
        status_filter = "AND act.owner_id IS NULL AND dn.completed_by IS NULL"
    elif status == "booked":
        status_filter = "AND act.owner_id IS NOT NULL"
    elif status == "completed":
        status_filter = "AND dn.completed_by IS NOT NULL"
    elif status == "mine" and user:
        status_filter = f"AND act.owner_id = ${idx}"
        params.append(user["id"])
        idx += 1

    count_sql = f"""
        SELECT COUNT(*) FROM stems s
        LEFT JOIN LATERAL (
            SELECT b.owner_id
            FROM batch_stems bs JOIN batches b ON b.id = bs.batch_id
            WHERE bs.stem_id = s.id
              AND b.expires_at > now()
              AND b.status = 'active'
              AND bs.status <> 'done'
            ORDER BY b.expires_at DESC LIMIT 1
        ) act ON true
        LEFT JOIN LATERAL (
            SELECT bs.completed_by
            FROM batch_stems bs
            WHERE bs.stem_id = s.id AND bs.status = 'done'
            ORDER BY bs.completed_at DESC LIMIT 1
        ) dn ON true
        WHERE 1=1 {base_where} {status_filter}
    """

    count_rows = await pool.fetch(count_sql, *params[2:])
    total = count_rows[0]["count"] if count_rows else 0

    data_sql = f"""
        SELECT s.id, s.text, s.word_count,
               act.owner_id AS booked_by,
               u1.username AS booked_username,
               act.expires_at AS locked_until,
               dn.completed_by,
               u2.username AS completed_username,
               dn.completed_at
        FROM stems s
        LEFT JOIN LATERAL (
            SELECT b.owner_id, b.expires_at
            FROM batch_stems bs JOIN batches b ON b.id = bs.batch_id
            WHERE bs.stem_id = s.id
              AND b.expires_at > now()
              AND b.status = 'active'
              AND bs.status <> 'done'
            ORDER BY b.expires_at DESC LIMIT 1
        ) act ON true
        LEFT JOIN users u1 ON u1.id = act.owner_id
        LEFT JOIN LATERAL (
            SELECT bs.completed_by, bs.completed_at
            FROM batch_stems bs
            WHERE bs.stem_id = s.id AND bs.status = 'done'
            ORDER BY bs.completed_at DESC LIMIT 1
        ) dn ON true
        LEFT JOIN users u2 ON u2.id = dn.completed_by
        WHERE 1=1 {base_where} {status_filter}
        ORDER BY s.id
        LIMIT $1 OFFSET $2
    """

    data_rows = await pool.fetch(data_sql, *params)

    items = []
    for r in data_rows:
        booked_by = None
        locked_until = None
        if r["booked_by"] is not None:
            booked_by = {"id": r["booked_by"], "username": r["booked_username"]}
            locked_until = r["locked_until"]

        completed_by = None
        completed_at = None
        if r["completed_by"] is not None:
            completed_by = {"id": r["completed_by"], "username": r["completed_username"]}
            completed_at = r["completed_at"]

        state = "available"
        if booked_by is not None:
            state = "booked"
        elif completed_by is not None:
            state = "completed"

        items.append(StemOut(
            id=r["id"],
            text=r["text"],
            word_count=r["word_count"],
            state=state,
            booked_by=booked_by,
            locked_until=locked_until,
            completed_by=completed_by,
            completed_at=completed_at,
        ))

    return StemsListResponse(items=items, total=total, page=page, page_size=page_size)


@app.post("/stems/import")
async def import_stems(request: Request, user=Depends(get_current_user)):
    validate_csrf(request)
    pool = await get_pool()

    content_type = request.headers.get("content-type", "")
    texts: list[str] = []

    if "multipart/form-data" in content_type:
        form = await request.form()
        texts_field = form.get("texts")
        if texts_field:
            try:
                raw = json.loads(texts_field)
                if isinstance(raw, list):
                    texts.extend([t.strip() for t in raw if isinstance(t, str) and t.strip()])
            except json.JSONDecodeError:
                pass

        file = form.get("file")
        if file and hasattr(file, "filename") and hasattr(file, "read"):
            raw_bytes = await file.read()
            filename = file.filename or ""
            ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
            content = raw_bytes.decode("utf-8")

            if ext == "txt":
                texts.extend([t.strip() for t in content.split("\n\n") if t.strip()])
            elif ext == "csv":
                reader = csv.DictReader(io.StringIO(content))
                text_columns = ["text", "stem_text", "stem", "passage", "content", "story", "description"]
                for row in reader:
                    txt = ""
                    for key in text_columns:
                        val = row.get(key)
                        if val:
                            txt = val.strip()
                            break
                    if txt:
                        texts.append(txt)
            elif ext == "json":
                try:
                    data = json.loads(content)
                    if isinstance(data, list):
                        for item in data:
                            if isinstance(item, str):
                                t = item.strip()
                                if t:
                                    texts.append(t)
                            elif isinstance(item, dict):
                                t = (item.get("text") or "").strip()
                                if t:
                                    texts.append(t)
                except json.JSONDecodeError:
                    raise HTTPException(status_code=400, detail="Invalid JSON file")
            else:
                raise HTTPException(status_code=400, detail=f"Unsupported file type: .{ext}")
    else:
        try:
            body = await request.json()
            raw = body.get("texts", [])
            if isinstance(raw, list):
                texts = [t.strip() for t in raw if isinstance(t, str) and t.strip()]
            else:
                raise HTTPException(status_code=400, detail="Expected { texts: string[] }")
        except Exception:
            raise HTTPException(status_code=400, detail="Invalid request body")

    if not texts:
        return StemsImportResponse(created=0, skipped=0)

    unique_texts = list(dict.fromkeys(texts))

    existing_rows = await pool.fetch(
        "SELECT text FROM stems WHERE text = ANY($1::text[])",
        unique_texts
    )
    existing_set = {r["text"] for r in existing_rows}

    to_insert = [t for t in unique_texts if t not in existing_set]
    skipped = len(unique_texts) - len(to_insert)
    created = 0

    if to_insert:
        values = [(t, len(t.split()), "upload") for t in to_insert]
        await pool.executemany(
            "INSERT INTO stems (text, word_count, source) VALUES ($1, $2, $3)",
            values
        )
        created = len(values)

    return StemsImportResponse(created=created, skipped=skipped)


# ---------------------------------------------------------------------------
# BATCHES
# ---------------------------------------------------------------------------

@app.post("/batches", status_code=201)
async def create_batch(body: BatchCreate, request: Request, user=Depends(get_current_user)):
    validate_csrf(request)
    pool = await get_pool()
    if not body.stem_ids:
        raise HTTPException(status_code=400, detail="stem_ids must not be empty")

    async with pool.acquire() as conn:
        async with conn.transaction():
            conflicts = await conn.fetch(
                """
                SELECT bs.stem_id
                FROM batch_stems bs
                JOIN batches b ON b.id = bs.batch_id
                WHERE b.expires_at > now()
                  AND b.status = 'active'
                  AND bs.stem_id = ANY($1::int[])
                  AND bs.status <> 'done'
                FOR UPDATE
                """,
                body.stem_ids
            )
            if conflicts:
                conflict_ids = [r["stem_id"] for r in conflicts]
                raise HTTPException(
                    status_code=409,
                    detail=ConflictResponse(
                        message="Some stems were just taken",
                        conflict_stem_ids=conflict_ids
                    ).model_dump()
                )

            now = _now()
            expires = now + timedelta(hours=LOCK_HOURS)
            batch_row = await conn.fetchrow(
                """INSERT INTO batches (name, owner_id, locked_at, expires_at, rebook_count, status)
                   VALUES ($1, $2, $3, $4, 0, 'active')
                   RETURNING id, name, owner_id, created_at, locked_at, expires_at, rebook_count, status""",
                body.name, user["id"], now, expires
            )
            batch = dict(batch_row)
            for stem_id in body.stem_ids:
                await conn.execute(
                    "INSERT INTO batch_stems (batch_id, stem_id, status) VALUES ($1, $2, 'not_started')",
                    batch["id"], stem_id
                )

    return BatchOut(
        id=batch["id"],
        name=batch["name"],
        owner_id=batch["owner_id"],
        owner_username=user["username"],
        created_at=batch["created_at"],
        locked_at=batch["locked_at"],
        expires_at=batch["expires_at"],
        rebook_count=batch["rebook_count"],
        status=batch["status"],
        remaining_seconds=_seconds_until(batch["expires_at"]),
        progress={"done": 0, "total": len(body.stem_ids)},
    )


@app.get("/batches")
async def list_batches(request: Request):
    user = await get_current_user(request)
    pool = await get_pool()
    rows = await pool.fetch(
        "SELECT * FROM batches WHERE owner_id = $1 ORDER BY created_at DESC",
        user["id"]
    )
    result = []
    for r in rows:
        total = await pool.fetchval(
            "SELECT COUNT(*) FROM batch_stems WHERE batch_id = $1", r["id"]
        )
        done = await pool.fetchval(
            "SELECT COUNT(*) FROM batch_stems WHERE batch_id = $1 AND status = 'done'", r["id"]
        )
        result.append(BatchOut(
            id=r["id"],
            name=r["name"],
            owner_id=r["owner_id"],
            owner_username=user["username"],
            created_at=r["created_at"],
            locked_at=r["locked_at"],
            expires_at=r["expires_at"],
            rebook_count=r["rebook_count"],
            status=r["status"],
            remaining_seconds=_seconds_until(r["expires_at"]),
            progress={"done": done, "total": total},
        ))
    return result


@app.get("/batches/{batch_id}")
async def get_batch(batch_id: int, request: Request):
    user = await get_current_user(request)
    pool = await get_pool()
    batch = await pool.fetchrow("SELECT * FROM batches WHERE id = $1", batch_id)
    if not batch:
        raise HTTPException(status_code=404, detail="Batch not found")
    if batch["owner_id"] != user["id"]:
        raise HTTPException(status_code=403, detail="Not your batch")

    bs_rows = await pool.fetch(
        """
        SELECT bs.id, bs.stem_id, bs.status, bs.completed_by, bs.completed_at, bs.updated_at,
               s.text AS stem_text, s.word_count,
               u.username AS completed_username
        FROM batch_stems bs
        JOIN stems s ON s.id = bs.stem_id
        LEFT JOIN users u ON u.id = bs.completed_by
        WHERE bs.batch_id = $1
        ORDER BY bs.id
        """,
        batch_id
    )
    stems = []
    for r in bs_rows:
        stems.append({
            "id": r["id"],
            "stem_id": r["stem_id"],
            "stem_text": r["stem_text"],
            "word_count": r["word_count"],
            "status": r["status"],
            "completed_by": {"id": r["completed_by"], "username": r["completed_username"]} if r["completed_by"] else None,
            "completed_at": r["completed_at"],
            "updated_at": r["updated_at"],
        })

    total = len(stems)
    done = sum(1 for s in stems if s["status"] == "done")

    return BatchDetailOut(
        id=batch["id"],
        name=batch["name"],
        owner_id=batch["owner_id"],
        owner_username=user["username"],
        created_at=batch["created_at"],
        locked_at=batch["locked_at"],
        expires_at=batch["expires_at"],
        rebook_count=batch["rebook_count"],
        status=batch["status"],
        remaining_seconds=_seconds_until(batch["expires_at"]),
        progress={"done": done, "total": total},
        stems=stems,
    )


@app.post("/batches/{batch_id}/rebook")
async def rebook_batch(batch_id: int, request: Request, user=Depends(get_current_user)):
    validate_csrf(request)
    pool = await get_pool()
    batch = await pool.fetchrow(
        "SELECT * FROM batches WHERE id = $1 AND owner_id = $2 FOR UPDATE",
        batch_id, user["id"]
    )
    if not batch:
        raise HTTPException(status_code=404, detail="Batch not found")
    if batch["rebook_count"] >= MAX_REBOOKS:
        raise HTTPException(status_code=409, detail="Re-book limit reached")
    now = _now()
    expires = now + timedelta(hours=LOCK_HOURS)
    await pool.execute(
        "UPDATE batches SET locked_at = $1, expires_at = $2, rebook_count = rebook_count + 1 WHERE id = $3",
        now, expires, batch_id
    )
    return {"ok": True, "remaining_seconds": LOCK_HOURS * 3600}


@app.post("/batches/{batch_id}/release")
async def release_batch(batch_id: int, request: Request, user=Depends(get_current_user)):
    validate_csrf(request)
    pool = await get_pool()
    result = await pool.execute(
        "UPDATE batches SET expires_at = now(), status = 'released' WHERE id = $1 AND owner_id = $2",
        batch_id, user["id"]
    )
    if result == "UPDATE 0":
        raise HTTPException(status_code=404, detail="Batch not found")
    return {"ok": True}


# ---------------------------------------------------------------------------
# BATCH STEM ANNOTATIONS
# ---------------------------------------------------------------------------

def _batch_span_to_out(row: dict, seq_label: str, batch_stem_id: int) -> dict:
    return {
        "id": row["id"],
        "batch_stem_id": row.get("batch_stem_id") or batch_stem_id,
        "session_id": row.get("session_id"),
        "label_type": row["label_type"],
        "seq_label": seq_label,
        "span_text": row["span_text"],
        "char_start": row["char_start"],
        "char_end": row["char_end"],
        "tl_start": row["tl_start"],
        "tl_end": row["tl_end"],
        "source": row["source"],
        "created_at": row["created_at"],
    }


@app.get("/batch-stems/{batch_stem_id}")
async def get_batch_stem(batch_stem_id: int, request: Request):
    user = await get_current_user(request)
    pool = await get_pool()
    bs = await pool.fetchrow(
        """
        SELECT bs.*, s.text AS stem_text, s.word_count
        FROM batch_stems bs
        JOIN stems s ON s.id = bs.stem_id
        JOIN batches b ON b.id = bs.batch_id
        WHERE bs.id = $1 AND b.owner_id = $2
        """,
        batch_stem_id, user["id"]
    )
    if not bs:
        raise HTTPException(status_code=404, detail="Batch stem not found")
    batch = await pool.fetchrow("SELECT * FROM batches WHERE id = $1", bs["batch_id"])
    if _ensure_aware(batch["expires_at"]) <= _now():
        raise HTTPException(status_code=423, detail="Lock expired")
    spans = await pool.fetch(
        "SELECT * FROM spans WHERE batch_stem_id = $1 ORDER BY created_at",
        batch_stem_id
    )
    label_counts = {}
    seq_spans = []
    for s in spans:
        lt = s["label_type"]
        label_counts[lt] = label_counts.get(lt, 0) + 1
        seq = f"{'E' if lt == 'Event' else 'T'}{label_counts[lt]}"
        seq_spans.append(_batch_span_to_out(dict(s), seq, batch_stem_id))
    return {
        "id": bs["id"],
        "batch_id": bs["batch_id"],
        "stem_id": bs["stem_id"],
        "stem_text": bs["stem_text"],
        "word_count": bs["word_count"],
        "status": bs["status"],
        "completed_by": bs["completed_by"],
        "completed_at": bs["completed_at"],
        "updated_at": bs["updated_at"],
        "spans": seq_spans,
        "expires_at": batch["expires_at"],
    }


@app.post("/batch-stems/{batch_stem_id}/spans", status_code=201)
async def create_batch_span(batch_stem_id: int, body: BatchSpanCreate, request: Request, user=Depends(get_current_user)):
    validate_csrf(request)
    pool = await get_pool()
    bs = await pool.fetchrow(
        "SELECT bs.*, b.owner_id, b.expires_at FROM batch_stems bs JOIN batches b ON b.id = bs.batch_id WHERE bs.id = $1",
        batch_stem_id
    )
    if not bs or bs["owner_id"] != user["id"]:
        raise HTTPException(status_code=404, detail="Batch stem not found")
    if _ensure_aware(bs["expires_at"]) <= _now():
        raise HTTPException(status_code=423, detail="Lock expired")
    existing = await pool.fetch(
        "SELECT * FROM spans WHERE batch_stem_id = $1 ORDER BY created_at", batch_stem_id
    )
    prefix = "E" if body.label_type == "Event" else "T"
    count = sum(1 for s in existing if s["label_type"] == body.label_type)
    seq_label = f"{prefix}{count + 1}"
    row = await pool.fetchrow(
        """INSERT INTO spans (batch_stem_id, label_type, seq_label, span_text, char_start, char_end, tl_start, tl_end, source)
           VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9) RETURNING *""",
        batch_stem_id, body.label_type, seq_label,
        body.span_text, body.char_start, body.char_end,
        body.tl_start, body.tl_end, body.source
    )
    if bs["status"] == "not_started":
        await pool.execute(
            "UPDATE batch_stems SET status = 'in_progress' WHERE id = $1", batch_stem_id
        )
    return _batch_span_to_out(dict(row), seq_label, batch_stem_id)


@app.get("/batch-stems/{batch_stem_id}/spans")
async def list_batch_spans(batch_stem_id: int, request: Request):
    user = await get_current_user(request)
    pool = await get_pool()
    bs = await pool.fetchrow(
        "SELECT bs.*, b.owner_id FROM batch_stems bs JOIN batches b ON b.id = bs.batch_id WHERE bs.id = $1",
        batch_stem_id
    )
    if not bs or bs["owner_id"] != user["id"]:
        raise HTTPException(status_code=404, detail="Batch stem not found")
    spans = await pool.fetch(
        "SELECT * FROM spans WHERE batch_stem_id = $1 ORDER BY created_at", batch_stem_id
    )
    label_counts = {}
    result = []
    for s in spans:
        lt = s["label_type"]
        label_counts[lt] = label_counts.get(lt, 0) + 1
        seq = f"{'E' if lt == 'Event' else 'T'}{label_counts[lt]}"
        result.append(_batch_span_to_out(dict(s), seq, batch_stem_id))
    return result


@app.patch("/batch-stems/{batch_stem_id}/spans/{span_id}")
async def update_batch_span(batch_stem_id: int, span_id: int, body: SpanUpdate, request: Request, user=Depends(get_current_user)):
    validate_csrf(request)
    pool = await get_pool()
    bs = await pool.fetchrow(
        "SELECT bs.*, b.owner_id, b.expires_at FROM batch_stems bs JOIN batches b ON b.id = bs.batch_id WHERE bs.id = $1",
        batch_stem_id
    )
    if not bs or bs["owner_id"] != user["id"]:
        raise HTTPException(status_code=404, detail="Batch stem not found")
    if _ensure_aware(bs["expires_at"]) <= _now():
        raise HTTPException(status_code=423, detail="Lock expired")
    span = await pool.fetchrow("SELECT * FROM spans WHERE id = $1 AND batch_stem_id = $2", span_id, batch_stem_id)
    if not span:
        raise HTTPException(status_code=404, detail="Span not found")
    tl_start = body.tl_start if body.tl_start is not None else span["tl_start"]
    tl_end = body.tl_end if body.tl_end is not None else span["tl_end"]
    updated = await pool.fetchrow(
        "UPDATE spans SET tl_start=$1, tl_end=$2 WHERE id=$3 RETURNING *",
        tl_start, tl_end, span_id
    )
    return _batch_span_to_out(dict(updated), span["seq_label"], batch_stem_id)


@app.delete("/batch-stems/{batch_stem_id}/spans/{span_id}", status_code=204)
async def delete_batch_span(batch_stem_id: int, span_id: int, request: Request, user=Depends(get_current_user)):
    validate_csrf(request)
    pool = await get_pool()
    bs = await pool.fetchrow(
        "SELECT bs.*, b.owner_id, b.expires_at FROM batch_stems bs JOIN batches b ON b.id = bs.batch_id WHERE bs.id = $1",
        batch_stem_id
    )
    if not bs or bs["owner_id"] != user["id"]:
        raise HTTPException(status_code=404, detail="Batch stem not found")
    if _ensure_aware(bs["expires_at"]) <= _now():
        raise HTTPException(status_code=423, detail="Lock expired")
    span = await pool.fetchrow("SELECT * FROM spans WHERE id = $1 AND batch_stem_id = $2", span_id, batch_stem_id)
    if not span:
        raise HTTPException(status_code=404, detail="Span not found")
    await pool.execute("DELETE FROM spans WHERE id = $1", span_id)
    return None


@app.post("/batch-stems/{batch_stem_id}/matrix/save")
async def save_batch_matrix(batch_stem_id: int, request: Request, user=Depends(get_current_user)):
    validate_csrf(request)
    pool = await get_pool()
    bs = await pool.fetchrow(
        "SELECT bs.*, b.owner_id, b.expires_at FROM batch_stems bs JOIN batches b ON b.id = bs.batch_id WHERE bs.id = $1",
        batch_stem_id
    )
    if not bs or bs["owner_id"] != user["id"]:
        raise HTTPException(status_code=404, detail="Batch stem not found")
    if _ensure_aware(bs["expires_at"]) <= _now():
        raise HTTPException(status_code=423, detail="Lock expired")
    spans = await pool.fetch(
        "SELECT * FROM spans WHERE batch_stem_id = $1 AND label_type = 'Event' ORDER BY created_at",
        batch_stem_id
    )
    span_list = [dict(s) for s in spans]
    matrix = build_matrix(span_list)
    span_order = [{"id": s["id"], "seq_label": s["seq_label"]} for s in span_list]

    existing = await pool.fetchrow(
        "SELECT id FROM matrix_snapshots WHERE batch_stem_id=$1", batch_stem_id
    )
    if existing:
        await pool.execute(
            "UPDATE matrix_snapshots SET matrix_json=$1, span_order=$2, updated_at=now() WHERE batch_stem_id=$3",
            json.dumps(matrix), json.dumps(span_order), batch_stem_id
        )
    else:
        await pool.execute(
            "INSERT INTO matrix_snapshots (batch_stem_id, matrix_json, span_order) VALUES ($1,$2,$3)",
            batch_stem_id, json.dumps(matrix), json.dumps(span_order)
        )

    for i, si in enumerate(span_list):
        for j, sj in enumerate(span_list):
            code = matrix[i][j]
            await pool.execute(
                """INSERT INTO relations (batch_stem_id, span_i_id, span_j_id, relation_code)
                   VALUES ($1,$2,$3,$4)
                   ON CONFLICT (batch_stem_id, span_i_id, span_j_id) WHERE batch_stem_id IS NOT NULL
                   DO UPDATE SET relation_code=$4""",
                batch_stem_id, si["id"], sj["id"], code
            )

    return {"ok": True, "matrix": matrix, "span_order": span_order}


@app.get("/batch-stems/{batch_stem_id}/matrix")
async def get_batch_matrix(batch_stem_id: int, request: Request):
    user = await get_current_user(request)
    pool = await get_pool()
    bs = await pool.fetchrow(
        "SELECT bs.*, b.owner_id FROM batch_stems bs JOIN batches b ON b.id = bs.batch_id WHERE bs.id = $1",
        batch_stem_id
    )
    if not bs or bs["owner_id"] != user["id"]:
        raise HTTPException(status_code=404, detail="Batch stem not found")
    spans = await pool.fetch(
        "SELECT * FROM spans WHERE batch_stem_id = $1 AND label_type = 'Event' ORDER BY created_at",
        batch_stem_id
    )
    span_list = [dict(s) for s in spans]
    matrix = build_matrix(span_list)
    span_order = [{"id": s["id"], "seq_label": s["seq_label"]} for s in span_list]
    violations = transitivity_check(matrix, [s["seq_label"] for s in span_list])
    return {"matrix": matrix, "span_order": span_order, "violations": violations}


@app.patch("/batch-stems/{batch_stem_id}/matrix/override")
async def override_batch_matrix(batch_stem_id: int, body: MatrixOverride, request: Request, user=Depends(get_current_user)):
    validate_csrf(request)
    pool = await get_pool()
    bs = await pool.fetchrow(
        "SELECT bs.*, b.owner_id, b.expires_at FROM batch_stems bs JOIN batches b ON b.id = bs.batch_id WHERE bs.id = $1",
        batch_stem_id
    )
    if not bs or bs["owner_id"] != user["id"]:
        raise HTTPException(status_code=404, detail="Batch stem not found")
    if _ensure_aware(bs["expires_at"]) <= _now():
        raise HTTPException(status_code=423, detail="Lock expired")
    spans = await pool.fetch(
        "SELECT * FROM spans WHERE batch_stem_id = $1 AND label_type = 'Event' ORDER BY created_at",
        batch_stem_id
    )
    span_list = [dict(s) for s in spans]
    n = len(span_list)
    if body.i < 0 or body.i >= n or body.j < 0 or body.j >= n:
        raise HTTPException(status_code=400, detail="Index out of range")
    if body.i == body.j:
        raise HTTPException(status_code=400, detail="Cannot override diagonal")

    snapshot = await pool.fetchrow(
        "SELECT * FROM matrix_snapshots WHERE batch_stem_id=$1 ORDER BY updated_at DESC LIMIT 1",
        batch_stem_id
    )
    if not snapshot:
        raise HTTPException(status_code=400, detail="Save matrix first before overriding")

    matrix = json.loads(snapshot["matrix_json"])
    matrix[body.i][body.j] = body.relation_code
    inv = INVERSES.get(body.relation_code, -body.relation_code)
    matrix[body.j][body.i] = inv

    await pool.execute(
        "UPDATE matrix_snapshots SET matrix_json=$1, updated_at=now() WHERE batch_stem_id=$2",
        json.dumps(matrix), batch_stem_id
    )

    si_id = span_list[body.i]["id"]
    sj_id = span_list[body.j]["id"]
    await pool.execute(
        """INSERT INTO relations (batch_stem_id, span_i_id, span_j_id, relation_code, is_override)
           VALUES ($1,$2,$3,$4,TRUE)
           ON CONFLICT (batch_stem_id, span_i_id, span_j_id) WHERE batch_stem_id IS NOT NULL
           DO UPDATE SET relation_code=$4, is_override=TRUE""",
        batch_stem_id, si_id, sj_id, body.relation_code
    )
    await pool.execute(
        """INSERT INTO relations (batch_stem_id, span_i_id, span_j_id, relation_code, is_override)
           VALUES ($1,$2,$3,$4,TRUE)
           ON CONFLICT (batch_stem_id, span_i_id, span_j_id) WHERE batch_stem_id IS NOT NULL
           DO UPDATE SET relation_code=$4, is_override=TRUE""",
        batch_stem_id, sj_id, si_id, inv
    )
    return {"ok": True, "matrix": matrix}


@app.post("/batch-stems/{batch_stem_id}/mark-done")
async def mark_batch_stem_done(batch_stem_id: int, request: Request, user=Depends(get_current_user)):
    validate_csrf(request)
    pool = await get_pool()
    bs = await pool.fetchrow(
        "SELECT bs.*, b.owner_id, b.expires_at FROM batch_stems bs JOIN batches b ON b.id = bs.batch_id WHERE bs.id = $1",
        batch_stem_id
    )
    if not bs or bs["owner_id"] != user["id"]:
        raise HTTPException(status_code=404, detail="Batch stem not found")
    if _ensure_aware(bs["expires_at"]) <= _now():        raise HTTPException(status_code=423, detail="Lock expired")
    await pool.execute(
        "UPDATE batch_stems SET status = 'done', completed_by = $1, completed_at = now() WHERE id = $2",
        user["id"], batch_stem_id
    )
    return {"ok": True}


@app.post("/batch-stems/{batch_stem_id}/status")
async def update_batch_stem_status(batch_stem_id: int, body: dict, request: Request, user=Depends(get_current_user)):
    validate_csrf(request)
    pool = await get_pool()
    bs = await pool.fetchrow(
        "SELECT bs.*, b.owner_id, b.expires_at FROM batch_stems bs JOIN batches b ON b.id = bs.batch_id WHERE bs.id = $1",
        batch_stem_id
    )
    if not bs or bs["owner_id"] != user["id"]:
        raise HTTPException(status_code=404, detail="Batch stem not found")
    if _ensure_aware(bs["expires_at"]) <= _now():        raise HTTPException(status_code=423, detail="Lock expired")
    new_status = body.get("status", "in_progress")
    if new_status not in ("not_started", "in_progress", "done"):
        raise HTTPException(status_code=400, detail="Invalid status")
    await pool.execute(
        "UPDATE batch_stems SET status = $1 WHERE id = $2",
        new_status, batch_stem_id
    )
    return {"ok": True}


# ---------------------------------------------------------------------------
# BATCH EXPORT
# ---------------------------------------------------------------------------

@app.get("/batches/{batch_id}/export/csv")
async def export_batch_csv(batch_id: int, request: Request):
    user = await get_current_user(request)
    pool = await get_pool()
    batch = await pool.fetchrow("SELECT * FROM batches WHERE id=$1 AND owner_id=$2", batch_id, user["id"])
    if not batch:
        raise HTTPException(status_code=404, detail="Batch not found")
    bs_list = await pool.fetch("SELECT id FROM batch_stems WHERE batch_id=$1 AND status='done'", batch_id)
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["batch_id", "batch_name", "stem_id", "stem_text", "span_i", "span_j",
                     "relation_code", "relation_name", "is_override"])
    for bs in bs_list:
        spans = await pool.fetch("SELECT * FROM spans WHERE batch_stem_id=$1", bs["id"])
        relations = await pool.fetch(
            """SELECT r.*, si.seq_label as label_i, sj.seq_label as label_j
               FROM relations r
               JOIN spans si ON r.span_i_id = si.id
               JOIN spans sj ON r.span_j_id = sj.id
               WHERE r.batch_stem_id=$1""",
            bs["id"]
        )
        stem_row = await pool.fetchrow("SELECT text FROM stems WHERE id=(SELECT stem_id FROM batch_stems WHERE id=$1)", bs["id"])
        stem_text = stem_row["text"] if stem_row else ""
        for r in relations:
            writer.writerow([
                batch_id, batch["name"], bs["id"], stem_text[:80],
                r["label_i"], r["label_j"], r["relation_code"],
                RELATION_NAMES.get(r["relation_code"], "unknown"),
                r["is_override"]
            ])
    output.seek(0)
    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename=batch_{batch_id}.csv"}
    )


@app.get("/batches/{batch_id}/export/json")
async def export_batch_json(batch_id: int, request: Request):
    user = await get_current_user(request)
    pool = await get_pool()
    batch = await pool.fetchrow("SELECT * FROM batches WHERE id=$1 AND owner_id=$2", batch_id, user["id"])
    if not batch:
        raise HTTPException(status_code=404, detail="Batch not found")
    bs_list = await pool.fetch(
        """SELECT bs.*, s.text AS stem_text
           FROM batch_stems bs
           JOIN stems s ON s.id = bs.stem_id
           WHERE bs.batch_id=$1 AND bs.status='done'
           ORDER BY bs.id""",
        batch_id
    )
    batch_data = {
        "id": batch["id"],
        "name": batch["name"],
        "owner_id": batch["owner_id"],
        "status": batch["status"],
        "stems": []
    }
    for bs in bs_list:
        spans = await pool.fetch("SELECT * FROM spans WHERE batch_stem_id=$1 ORDER BY created_at", bs["id"])
        snapshot = await pool.fetchrow(
            "SELECT * FROM matrix_snapshots WHERE batch_stem_id=$1 ORDER BY updated_at DESC LIMIT 1",
            bs["id"]
        )
        batch_data["stems"].append({
            "batch_stem_id": bs["id"],
            "stem_id": bs["stem_id"],
            "stem_text": bs["stem_text"],
            "spans": [{k: _serialize(v) for k, v in dict(sp).items()} for sp in spans],
            "matrix": json.loads(snapshot["matrix_json"]) if snapshot else [],
            "span_order": json.loads(snapshot["span_order"]) if snapshot else [],
        })
    return batch_data


@app.get("/batch-stems/{batch_stem_id}/export/json")
async def export_batch_stem_json(batch_stem_id: int, request: Request):
    user = await get_current_user(request)
    pool = await get_pool()
    bs = await pool.fetchrow("SELECT * FROM batch_stems WHERE id=$1", batch_stem_id)
    if not bs:
        raise HTTPException(status_code=404, detail="Batch stem not found")
    batch = await pool.fetchrow("SELECT * FROM batches WHERE id=$1 AND owner_id=$2", bs["batch_id"], user["id"])
    if not batch:
        raise HTTPException(status_code=404, detail="Batch not found")
    stem_row = await pool.fetchrow("SELECT text FROM stems WHERE id=$1", bs["stem_id"])
    stem_text = stem_row["text"] if stem_row else ""
    spans = await pool.fetch("SELECT * FROM spans WHERE batch_stem_id=$1 ORDER BY created_at", batch_stem_id)
    snapshot = await pool.fetchrow(
        "SELECT * FROM matrix_snapshots WHERE batch_stem_id=$1 ORDER BY updated_at DESC LIMIT 1",
        batch_stem_id
    )
    return {
        "batch_stem_id": bs["id"],
        "stem_id": bs["stem_id"],
        "stem_text": stem_text,
        "status": bs["status"],
        "spans": [{k: _serialize(v) for k, v in dict(sp).items()} for sp in spans],
        "matrix": json.loads(snapshot["matrix_json"]) if snapshot else [],
        "span_order": json.loads(snapshot["span_order"]) if snapshot else [],
    }


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
async def extract_events(body: ExtractEventsRequest, request: Request, user=Depends(get_current_user)):
    validate_csrf(request)
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
        typed.append({
            "text": evt_text,
            "char_start": chars["char_start"],
            "char_end": chars["char_end"],
        })

    # Step 2: deduplicate by char overlap within this batch
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
                "source": "llm",
            })

    return ExtractEventsResponse(events=accepted, skipped=skipped).model_dump()


@app.post("/api/extract-timeline")
async def extract_timeline(body: ExtractTimelineRequest, request: Request, user=Depends(get_current_user)):
    validate_csrf(request)
    pool = await get_pool()
    session_id = body.session_id

    if session_id >= 0:
        await _get_session_or_404(pool, session_id)
        event_rows = await _get_event_spans(pool, session_id)
        session_row = await pool.fetchrow("SELECT stem_text FROM annotation_sessions WHERE id=$1", session_id)
        stem_text = session_row["stem_text"] if session_row else ""
    else:
        batch_stem_id = -session_id
        bs = await pool.fetchrow(
            "SELECT bs.*, s.text AS stem_text FROM batch_stems bs JOIN stems s ON s.id = bs.stem_id WHERE bs.id=$1",
            batch_stem_id
        )
        if not bs:
            raise HTTPException(status_code=404, detail="Batch stem not found")
        event_rows = await pool.fetch(
            "SELECT * FROM spans WHERE batch_stem_id = $1 AND label_type = 'Event' ORDER BY created_at",
            batch_stem_id
        )
        stem_text = bs["stem_text"]

    if not event_rows:
        return ExtractTimelineResponse(updated=[], skipped=[]).model_dump()

    events_payload = [
        {
            "text": r["span_text"],
            "occurrence": 1,
            "char_start": r["char_start"],
            "char_end": r["char_end"],
        }
        for r in event_rows
    ]
    events_for_prompt = [
        {"text": r["span_text"], "occurrence": 1}
        for r in event_rows
    ]

    user_msg = (
        f"Stem text:\n{stem_text}\n\n"
        f"Events (in order):\n{json.dumps(events_for_prompt, indent=2)}\n\n"
        f"Return JSON matching this schema:\n{TIMELINE_SCHEMA_JSON}"
    )

    try:
        raw = await callLLM(TIMELINE_SYSTEM_PROMPT, user_msg)
    except ValueError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"LLM provider error: {exc}") from exc

    if not isinstance(raw, dict):
        raise HTTPException(status_code=502, detail="LLM returned an unexpected response shape.")

    positions = raw.get("positions", [])
    if not isinstance(positions, list):
        raise HTTPException(status_code=502, detail="LLM returned an unexpected positions list.")

    pos_by_text: dict[str, dict] = {}
    for p in positions:
        if not isinstance(p, dict):
            continue
        txt = p.get("text", "")
        if not txt:
            continue
        pos_by_text[txt] = p

    updated = []
    skipped = []

    for r in event_rows:
        span_id = r["id"]
        pos = pos_by_text.get(r["span_text"])
        if pos is None:
            skipped.append({"text": r["span_text"], "reason": "Not found in LLM response."})
            continue
        start = pos.get("start")
        end = pos.get("end")
        if not isinstance(start, (int, float)) or not isinstance(end, (int, float)):
            skipped.append({"text": r["span_text"], "reason": "Missing start or end value from model."})
            continue
        start = round(max(TIMELINE_MIN, min(TIMELINE_MAX, start)), 1)
        end = round(max(TIMELINE_MIN, min(TIMELINE_MAX, end)), 1)
        if end < start:
            avg = (start + end) / 2
            start = round(avg - MIN_WIDTH / 2, 1)
            end = round(avg + MIN_WIDTH / 2, 1)
        elif end == start:
            end = round(start + MIN_WIDTH, 1)
        await pool.execute(
            "UPDATE spans SET tl_start=$1, tl_end=$2, source='llm' WHERE id=$3",
            start, end, span_id
        )
        updated.append({
            "span_id": span_id,
            "seq_label": r["seq_label"],
            "span_text": r["span_text"],
            "tl_start": start,
            "tl_end": end,
        })

    return ExtractTimelineResponse(updated=updated, skipped=skipped).model_dump()


@app.post("/api/llm-label-and-timeline")
async def llm_label_and_timeline(body: LLMLabelAndTimelineRequest, request: Request, user=Depends(get_current_user)):
    validate_csrf(request)
    pool = await get_pool()
    batch_stem_id = body.batch_stem_id
    text = (body.text or "").strip()
    if not text:
        return LLMLabelAndTimelineResponse(events=[], skipped_events=[], timeline_updated=[], timeline_skipped=[]).model_dump()

    bs = await pool.fetchrow(
        "SELECT bs.*, s.text AS stem_text, b.owner_id, b.expires_at FROM batch_stems bs JOIN stems s ON s.id = bs.stem_id JOIN batches b ON b.id = bs.batch_id WHERE bs.id=$1",
        batch_stem_id
    )
    if not bs or bs["owner_id"] != user["id"]:
        raise HTTPException(status_code=404, detail="Batch stem not found")
    if _ensure_aware(bs["expires_at"]) <= _now():
        raise HTTPException(status_code=423, detail="Lock expired")
    stem_text = bs["stem_text"]

    async with pool.acquire() as conn:
        async with conn.transaction():
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

            typed: list[dict] = []
            skipped_events: list[dict] = []
            for ev in raw_events:
                if not isinstance(ev, dict):
                    continue
                evt_text = ev.get("text", "")
                chars = _find_raw_event_chars(text, ev)
                if chars is None:
                    skipped_events.append({
                        "text": evt_text,
                        "reason": "Could not locate text in source even after whitespace normalization."
                    })
                    continue
                typed.append({
                    "text": evt_text,
                    "char_start": chars["char_start"],
                    "char_end": chars["char_end"],
                })

            accepted_events: list[dict] = []
            for t in typed:
                overlap = any(
                    _overlaps(t["char_start"], t["char_end"], a["char_start"], a["char_end"])
                    for a in accepted_events
                )
                if overlap:
                    skipped_events.append({"text": t["text"], "reason": "Overlaps with another extracted event in this batch."})
                else:
                    accepted_events.append({
                        "label_type": "Event",
                        "span_text": t["text"],
                        "char_start": t["char_start"],
                        "char_end": t["char_end"],
                        "source": "llm",
                    })

            existing = await conn.fetch(
                "SELECT * FROM spans WHERE batch_stem_id = $1 ORDER BY created_at", batch_stem_id
            )
            event_count = sum(1 for s in existing if s["label_type"] == "Event")
            created_spans = []
            for event in accepted_events:
                event_count += 1
                seq_label = f"E{event_count}"
                row = await conn.fetchrow(
                    """INSERT INTO spans (batch_stem_id, label_type, seq_label, span_text, char_start, char_end, tl_start, tl_end, source)
                       VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9) RETURNING *""",
                    batch_stem_id, "Event", seq_label,
                    event["span_text"], event["char_start"], event["char_end"],
                    10.0, 30.0, "llm"
                )
                created_spans.append(dict(row))

            all_event_rows = await conn.fetch(
                "SELECT * FROM spans WHERE batch_stem_id = $1 AND label_type = 'Event' ORDER BY created_at",
                batch_stem_id
            )
            if not all_event_rows:
                return LLMLabelAndTimelineResponse(
                    events=accepted_events,
                    skipped_events=skipped_events,
                    timeline_updated=[],
                    timeline_skipped=[]
                ).model_dump()

            events_payload = [
                {"text": r["span_text"], "occurrence": 1, "char_start": r["char_start"], "char_end": r["char_end"]}
                for r in all_event_rows
            ]
            events_for_prompt = [{"text": r["span_text"], "occurrence": 1} for r in all_event_rows]

            user_msg = (
                f"Stem text:\n{stem_text}\n\n"
                f"Events (in order):\n{json.dumps(events_for_prompt, indent=2)}\n\n"
                f"Return JSON matching this schema:\n{TIMELINE_SCHEMA_JSON}"
            )

            try:
                raw = await callLLM(TIMELINE_SYSTEM_PROMPT, user_msg)
            except ValueError as exc:
                raise HTTPException(status_code=502, detail=str(exc)) from exc
            except Exception as exc:
                raise HTTPException(status_code=502, detail=f"LLM provider error: {exc}") from exc

            if not isinstance(raw, dict):
                raise HTTPException(status_code=502, detail="LLM returned an unexpected response shape.")
            positions = raw.get("positions", [])
            if not isinstance(positions, list):
                raise HTTPException(status_code=502, detail="LLM returned an unexpected positions list.")

            pos_by_text: dict[str, dict] = {}
            for p in positions:
                if not isinstance(p, dict):
                    continue
                txt = p.get("text", "")
                if txt:
                    pos_by_text[txt] = p

            timeline_updated = []
            timeline_skipped = []

            for r in all_event_rows:
                span_id = r["id"]
                pos = pos_by_text.get(r["span_text"])
                if pos is None:
                    timeline_skipped.append({"text": r["span_text"], "reason": "Not found in LLM response."})
                    continue
                start = pos.get("start")
                end = pos.get("end")
                if not isinstance(start, (int, float)) or not isinstance(end, (int, float)):
                    timeline_skipped.append({"text": r["span_text"], "reason": "Missing start or end value from model."})
                    continue
                start = round(max(TIMELINE_MIN, min(TIMELINE_MAX, start)), 1)
                end = round(max(TIMELINE_MIN, min(TIMELINE_MAX, end)), 1)
                if end < start:
                    avg = (start + end) / 2
                    start = round(avg - MIN_WIDTH / 2, 1)
                    end = round(avg + MIN_WIDTH / 2, 1)
                elif end == start:
                    end = round(start + MIN_WIDTH, 1)
                await conn.execute(
                    "UPDATE spans SET tl_start=$1, tl_end=$2, source='llm' WHERE id=$3",
                    start, end, span_id
                )
                timeline_updated.append({
                    "span_id": span_id,
                    "seq_label": r["seq_label"],
                    "span_text": r["span_text"],
                    "tl_start": start,
                    "tl_end": end,
                })

            return LLMLabelAndTimelineResponse(
                events=accepted_events,
                skipped_events=skipped_events,
                timeline_updated=timeline_updated,
                timeline_skipped=timeline_skipped
            ).model_dump()


# ---------------------------------------------------------------------------
# Group annotation workflow (inter-annotator agreement)
# See context/group_workflow_redesign.md for the design rationale. Supersedes
# the older workflow described in context/cohen_kappa.md.
# ---------------------------------------------------------------------------

@app.get("/users")
async def list_users(request: Request, user=Depends(get_current_user)):
    pool = await get_pool()
    rows = await pool.fetch("SELECT id, username, email FROM users ORDER BY username")
    return [UserBriefOut(**dict(r)).model_dump() for r in rows]


async def _get_group_member(pool, task_id: int, user_id: int) -> Optional[dict]:
    row = await pool.fetchrow(
        "SELECT * FROM group_annotation_members WHERE task_id=$1 AND user_id=$2",
        task_id, user_id
    )
    return dict(row) if row else None


async def _get_task_and_member_role(pool, task_id: int, user_id: int) -> Optional[dict]:
    """One round trip in place of a separate task fetch + member fetch.
    {task_status, task_decision, member_id, member_role, member_status} —
    the member_* fields are None if the caller isn't a member of this task."""
    row = await pool.fetchrow(
        """SELECT gt.status AS task_status, gt.decision AS task_decision,
                  gm.id AS member_id, gm.role AS member_role, gm.status AS member_status
           FROM group_annotation_tasks gt
           LEFT JOIN group_annotation_members gm ON gm.task_id = gt.id AND gm.user_id = $2
           WHERE gt.id = $1""",
        task_id, user_id
    )
    return dict(row) if row else None


async def _group_members_out(pool, task_id: int) -> list:
    rows = await pool.fetch(
        """SELECT gm.*, u.username FROM group_annotation_members gm
           JOIN users u ON u.id = gm.user_id
           WHERE gm.task_id = $1 ORDER BY gm.role, gm.annotator_index NULLS FIRST""",
        task_id
    )
    return [GroupMemberOut(**dict(m)).model_dump() for m in rows]


async def _get_access_and_membership(pool, task_id: int, user_id: int) -> Optional[dict]:
    """One round trip in place of a separate access-check query plus a
    separate membership query: {is_creator, is_member}, or None if the task
    doesn't exist at all."""
    row = await pool.fetchrow(
        """SELECT (gt.created_by = $2) AS is_creator, (gm.id IS NOT NULL) AS is_member
           FROM group_annotation_tasks gt
           LEFT JOIN group_annotation_members gm ON gm.task_id = gt.id AND gm.user_id = $2
           WHERE gt.id = $1
           LIMIT 1""",
        task_id, user_id
    )
    return dict(row) if row else None


async def _require_group_access(pool, task_id: int, user_id: int) -> dict:
    """Raises 404 unless the caller is the creator or a member. Returns the
    membership row so callers needing `is_member` too don't issue a second query."""
    access = await _get_access_and_membership(pool, task_id, user_id)
    if not access or not (access["is_creator"] or access["is_member"]):
        raise HTTPException(status_code=404, detail="Group task not found")
    return access


async def _get_group_task_detail(pool, task_id: int, viewer_user_id: Optional[int] = None) -> dict:
    """Builds the full task detail. Per D7, a viewer who is a member of this task
    never sees its agreement scores, outcome or decision — only workflow status.
    Membership is derived from the members list already being fetched here,
    rather than a separate query."""
    task = await pool.fetchrow(
        "SELECT gt.*, s.text AS stem_text FROM group_annotation_tasks gt JOIN stems s ON s.id = gt.stem_id WHERE gt.id = $1",
        task_id
    )
    if not task:
        raise HTTPException(status_code=404, detail="Group task not found")
    members = await _group_members_out(pool, task_id)
    agreement_details = json.loads(task["agreement_details"]) if task["agreement_details"] else None

    hide_scores = viewer_user_id is not None and any(m["user_id"] == viewer_user_id for m in members)

    return GroupTaskDetailOut(
        id=task["id"], stem_id=task["stem_id"], stem_text=task["stem_text"],
        status=task["status"],
        outcome=None if hide_scores else task["outcome"],
        decision=None if hide_scores else task["decision"],
        scores_stale=task["scores_stale"],
        created_by=task["created_by"],
        created_at=task["created_at"], updated_at=task["updated_at"],
        acceptance_threshold=task["acceptance_threshold"],
        members=members,
        krippendorff_alpha=None if hide_scores else task["krippendorff_alpha"],
        cohens_kappa_avg=None if hide_scores else task["cohens_kappa_avg"],
        fleiss_kappa=None if hide_scores else task["fleiss_kappa"],
        agreement_details=None if hide_scores else agreement_details,
        scores_hidden=hide_scores,
    ).model_dump()


async def _member_positions(pool, member_id: int, spans: list) -> dict:
    """{span_id: (tl_start, tl_end)} for a member, falling back to the span's
    placeholder position for any event not yet positioned."""
    rows = await pool.fetch("SELECT * FROM timeline_annotations WHERE member_id=$1", member_id)
    pos_by_span = {r["span_id"]: r for r in rows}
    return {
        s["id"]: (
            (pos_by_span[s["id"]]["tl_start"], pos_by_span[s["id"]]["tl_end"])
            if s["id"] in pos_by_span else (s["tl_start"], s["tl_end"])
        )
        for s in spans
    }


async def _member_matrix(pool, member_id: int, spans: list) -> dict:
    """This member's N x N matrix, derived from their positions with any stored
    cell overrides applied on top (D3)."""
    positions = await _member_positions(pool, member_id, spans)
    span_list = [{"id": s["id"], "tl_start": positions[s["id"]][0], "tl_end": positions[s["id"]][1]} for s in spans]
    matrix = build_matrix(span_list)

    id_index = {s["id"]: idx for idx, s in enumerate(spans)}
    overrides = await pool.fetch(
        "SELECT * FROM timeline_relations WHERE member_id=$1 AND is_override=TRUE", member_id
    )
    for r in overrides:
        i, j = id_index.get(r["span_i_id"]), id_index.get(r["span_j_id"])
        if i is not None and j is not None:
            matrix[i][j] = r["relation_code"]

    span_order = [{"id": s["id"], "seq_label": s["seq_label"]} for s in spans]
    return {"matrix": matrix, "span_order": span_order}


async def _save_member_relations(pool, task_id: int, member_id: int, spans: list, matrix: list) -> None:
    """Upserts the derived relation for every non-overridden cell, in one
    round trip regardless of how many events there are (a Python loop of
    individual awaits here was N*(N-1) round trips per save/submit — the
    dominant cost on every timeline action). Cells the annotator has
    overridden are left untouched, so re-deriving from fresh positions never
    clobbers an override."""
    n = len(spans)
    if n < 2:
        return
    task_ids, member_ids, span_i_ids, span_j_ids, codes = [], [], [], [], []
    for i in range(n):
        for j in range(n):
            if i == j:
                continue
            task_ids.append(task_id)
            member_ids.append(member_id)
            span_i_ids.append(spans[i]["id"])
            span_j_ids.append(spans[j]["id"])
            codes.append(matrix[i][j])

    await pool.execute(
        """INSERT INTO timeline_relations (task_id, member_id, span_i_id, span_j_id, relation_code, is_override)
           SELECT t, m, si, sj, code, FALSE
           FROM unnest($1::int[], $2::int[], $3::int[], $4::int[], $5::int[]) AS u(t, m, si, sj, code)
           ON CONFLICT (member_id, span_i_id, span_j_id)
           DO UPDATE SET relation_code = EXCLUDED.relation_code, updated_at = now()
           WHERE timeline_relations.is_override = FALSE""",
        task_ids, member_ids, span_i_ids, span_j_ids, codes
    )


async def _invalidate_timelines_for_span_change(pool, task_id: int) -> None:
    """Per §5.5: an event span was added or removed. All submitted timeline
    work is superseded — annotators must re-position and re-submit before
    agreement can be computed again. Prior revisions are kept, not deleted."""
    await pool.execute(
        """UPDATE group_annotation_members SET status='in_progress'
           WHERE task_id=$1 AND role='timeline_annotator' AND status='submitted'""",
        task_id
    )
    await pool.execute(
        "UPDATE group_annotation_tasks SET status='timelines_pending', scores_stale=TRUE, updated_at=now() WHERE id=$1",
        task_id
    )


async def _finalize_group_agreement(pool, task_id: int) -> None:
    task = await pool.fetchrow("SELECT * FROM group_annotation_tasks WHERE id=$1", task_id)
    members = await pool.fetch(
        "SELECT * FROM group_annotation_members WHERE task_id=$1 AND role='timeline_annotator'",
        task_id
    )
    positions: dict = {}
    matrices: dict = {}
    based_on_revisions: dict = {}
    for m in members:
        rows = await pool.fetch("SELECT * FROM timeline_annotations WHERE member_id=$1", m["id"])
        positions[m["id"]] = {r["span_id"]: (r["tl_start"], r["tl_end"]) for r in rows}
        mat_row = await pool.fetchrow("SELECT * FROM timeline_relation_matrices WHERE member_id=$1", m["id"])
        if mat_row:
            matrices[m["id"]] = json.loads(mat_row["matrix_json"])
        rev_no = await pool.fetchval(
            "SELECT MAX(revision_no) FROM timeline_submission_revisions WHERE member_id=$1", m["id"]
        )
        if rev_no is not None:
            based_on_revisions[str(m["id"])] = rev_no

    result = compute_agreement(positions, matrices, threshold=task["acceptance_threshold"])

    run_no = await pool.fetchval(
        "SELECT COALESCE(MAX(run_no), 0) + 1 FROM agreement_runs WHERE task_id=$1", task_id
    )

    await pool.execute(
        """UPDATE group_annotation_tasks
           SET krippendorff_alpha=$1, cohens_kappa_avg=$2, fleiss_kappa=$3,
               agreement_details=$4, status='computed', outcome=$5, scores_stale=FALSE,
               updated_at=now()
           WHERE id=$6""",
        result["krippendorff_alpha"], result["cohens_kappa_avg"], result["fleiss_kappa"],
        json.dumps(result["agreement_details"]), result["status"], task_id
    )
    await pool.execute(
        """INSERT INTO agreement_runs (task_id, run_no, krippendorff_alpha, cohens_kappa_avg, fleiss_kappa, outcome, based_on_revisions)
           VALUES ($1,$2,$3,$4,$5,$6,$7)""",
        task_id, run_no, result["krippendorff_alpha"], result["cohens_kappa_avg"], result["fleiss_kappa"],
        result["status"], json.dumps(based_on_revisions)
    )


@app.post("/group-tasks", status_code=201)
async def create_group_task(body: GroupTaskCreate, request: Request, user=Depends(get_current_user)):
    """Single-task creation. Kept for now alongside /group-tasks/distribute;
    see context/group_workflow_redesign.md §10.3."""
    validate_csrf(request)
    pool = await get_pool()
    stem = await pool.fetchrow("SELECT * FROM stems WHERE id=$1", body.stem_id)
    if not stem:
        raise HTTPException(status_code=404, detail="Stem not found")

    all_user_ids = [body.event_user_id] + body.timeline_user_ids
    if len(set(all_user_ids)) != len(all_user_ids):
        raise HTTPException(status_code=400, detail="Event annotator and timeline annotators must be distinct users")
    found = await pool.fetch("SELECT id FROM users WHERE id = ANY($1::int[])", all_user_ids)
    missing = set(all_user_ids) - {r["id"] for r in found}
    if missing:
        raise HTTPException(status_code=400, detail=f"Unknown user id(s): {sorted(missing)}")

    existing = await pool.fetchrow("SELECT id FROM group_annotation_tasks WHERE stem_id=$1", body.stem_id)
    if existing:
        raise HTTPException(status_code=409, detail="A group annotation task already exists for this stem")

    async with pool.acquire() as conn:
        async with conn.transaction():
            task = await conn.fetchrow(
                "INSERT INTO group_annotation_tasks (stem_id, created_by) VALUES ($1,$2) RETURNING *",
                body.stem_id, user["id"]
            )
            await conn.execute(
                "INSERT INTO group_annotation_members (task_id, user_id, role, assigned_by) VALUES ($1,$2,'event_annotator',$3)",
                task["id"], body.event_user_id, user["id"]
            )
            for idx, uid in enumerate(body.timeline_user_ids, start=1):
                await conn.execute(
                    """INSERT INTO group_annotation_members (task_id, user_id, role, annotator_index, assigned_by)
                       VALUES ($1,$2,'timeline_annotator',$3,$4)""",
                    task["id"], uid, idx, user["id"]
                )
    return await _get_group_task_detail(pool, task["id"], viewer_user_id=user["id"])


@app.post("/group-tasks/distribute", status_code=201)
async def distribute_group_tasks(body: DistributeRequest, request: Request, user=Depends(get_current_user)):
    """Bulk allocation per §3.2: a randomly-ordered ring of the annotator pool,
    re-shuffled every full cycle, stepped by 1 role per stem so the
    event-annotator role and every pairing rotate through the whole pool."""
    validate_csrf(request)
    pool = await get_pool()

    if body.pool_user_ids:
        pool_ids = list(dict.fromkeys(body.pool_user_ids))
        found = await pool.fetch("SELECT id FROM users WHERE id = ANY($1::int[])", pool_ids)
        missing = set(pool_ids) - {r["id"] for r in found}
        if missing:
            raise HTTPException(status_code=400, detail=f"Unknown user id(s): {sorted(missing)}")
    else:
        pool_ids = [r["id"] for r in await pool.fetch("SELECT id FROM users ORDER BY id")]

    n = len(pool_ids)
    if n < 4:
        raise HTTPException(status_code=400, detail="At least 4 annotators are required to distribute group tasks")

    stem_rows = await pool.fetch("SELECT id FROM stems WHERE id = ANY($1::int[])", body.stem_ids)
    found_stem_ids = {r["id"] for r in stem_rows}
    taken_rows = await pool.fetch(
        "SELECT stem_id FROM group_annotation_tasks WHERE stem_id = ANY($1::int[])", body.stem_ids
    )
    already_taken = {r["stem_id"] for r in taken_rows}

    skipped: list = []
    to_create: list = []
    seen_stem_ids: set = set()
    for sid in body.stem_ids:
        if sid not in found_stem_ids:
            skipped.append({"stem_id": sid, "reason": "Stem not found"})
        elif sid in already_taken or sid in seen_stem_ids:
            skipped.append({"stem_id": sid, "reason": "A group task already exists for this stem"})
        else:
            to_create.append(sid)
            seen_stem_ids.add(sid)

    load_rows = await pool.fetch(
        """SELECT user_id, COUNT(*) AS n FROM group_annotation_members
           WHERE user_id = ANY($1::int[]) GROUP BY user_id""",
        pool_ids
    )
    load = {r["user_id"]: r["n"] for r in load_rows}

    ring = pool_ids[:]
    random.shuffle(ring)
    if ring:
        least_idx = min(range(n), key=lambda idx: load.get(ring[idx], 0))
        ring = ring[least_idx:] + ring[:least_idx]

    # Compute every role assignment in Python first — no DB round trips here —
    # so the actual writes below can be two batched statements instead of
    # ~5 round trips per stem.
    assignments: list = []
    for i, stem_id in enumerate(to_create):
        if i > 0 and i % n == 0:
            random.shuffle(ring)
        event_uid = ring[i % n]
        timeline_uids = [ring[(i + k) % n] for k in (1, 2, 3)]
        assignments.append((stem_id, event_uid, timeline_uids))

    created_task_ids: list = []
    async with pool.acquire() as conn:
        async with conn.transaction():
            run_row = await conn.fetchrow(
                "INSERT INTO distribution_runs (created_by, stem_count, pool_user_ids) VALUES ($1,$2,$3) RETURNING id",
                user["id"], len(to_create), json.dumps(pool_ids)
            )
            run_id = run_row["id"]

            if assignments:
                # One round trip for every task row, via unnest over the stem list.
                stem_ids_ordered = [a[0] for a in assignments]
                task_rows = await conn.fetch(
                    """INSERT INTO group_annotation_tasks (stem_id, created_by, distribution_run_id)
                       SELECT unnest($1::int[]), $2, $3
                       RETURNING id, stem_id""",
                    stem_ids_ordered, user["id"], run_id
                )
                task_id_by_stem = {r["stem_id"]: r["id"] for r in task_rows}
                created_task_ids = [task_id_by_stem[sid] for sid in stem_ids_ordered]

                # One more round trip for every member row across every task,
                # via unnest over five parallel columns.
                m_task_ids, m_user_ids, m_roles, m_indices, m_assigned_by = [], [], [], [], []
                for stem_id, event_uid, timeline_uids in assignments:
                    tid = task_id_by_stem[stem_id]
                    m_task_ids.append(tid); m_user_ids.append(event_uid)
                    m_roles.append('event_annotator'); m_indices.append(None); m_assigned_by.append(user["id"])
                    for idx, uid in enumerate(timeline_uids, start=1):
                        m_task_ids.append(tid); m_user_ids.append(uid)
                        m_roles.append('timeline_annotator'); m_indices.append(idx); m_assigned_by.append(user["id"])

                await conn.execute(
                    """INSERT INTO group_annotation_members (task_id, user_id, role, annotator_index, assigned_by)
                       SELECT * FROM unnest($1::int[], $2::int[], $3::text[], $4::int[], $5::int[])""",
                    m_task_ids, m_user_ids, m_roles, m_indices, m_assigned_by
                )

    return DistributeResponse(
        distribution_run_id=run_id,
        created_task_ids=created_task_ids,
        skipped=[DistributeSkip(**s) for s in skipped],
        pool_size=n,
    ).model_dump()


@app.get("/my-tasks")
async def list_my_tasks(request: Request, user=Depends(get_current_user)):
    pool = await get_pool()
    rows = await pool.fetch(
        """SELECT gm.id AS member_id, gm.task_id, gm.role, gm.annotator_index, gm.status AS member_status,
                  gt.status AS task_status, gt.stem_id, s.text AS stem_text
           FROM group_annotation_members gm
           JOIN group_annotation_tasks gt ON gt.id = gm.task_id
           JOIN stems s ON s.id = gt.stem_id
           WHERE gm.user_id = $1
           ORDER BY gt.created_at DESC""",
        user["id"]
    )
    result = []
    for r in rows:
        blocked = r["role"] == "timeline_annotator" and r["task_status"] == "event_pending"
        result.append(MyTaskOut(
            task_id=r["task_id"], member_id=r["member_id"], stem_id=r["stem_id"], stem_text=r["stem_text"],
            role=r["role"], annotator_index=r["annotator_index"],
            member_status=r["member_status"], task_status=r["task_status"],
            blocked=blocked,
            blocked_reason="Waiting for the event annotator to submit events" if blocked else None,
        ).model_dump())
    return result


@app.post("/group-tasks/{task_id}/members/{member_id}/reassign")
async def reassign_member(task_id: int, member_id: int, body: ReassignRequest, request: Request, user=Depends(get_current_user)):
    """Hand-off / recovery per §3.3. Callable by anyone — the assignee handing
    off their own work, or another annotator recovering an abandoned one."""
    validate_csrf(request)
    pool = await get_pool()
    task = await pool.fetchrow("SELECT * FROM group_annotation_tasks WHERE id=$1", task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Group task not found")
    member = await pool.fetchrow(
        "SELECT * FROM group_annotation_members WHERE id=$1 AND task_id=$2", member_id, task_id
    )
    if not member:
        raise HTTPException(status_code=404, detail="Assignment not found")
    if member["status"] == "submitted":
        raise HTTPException(status_code=409, detail="Cannot reassign a submitted assignment")

    new_user = await pool.fetchrow("SELECT id FROM users WHERE id=$1", body.user_id)
    if not new_user:
        raise HTTPException(status_code=400, detail="Unknown user id")
    conflict = await pool.fetchrow(
        "SELECT id FROM group_annotation_members WHERE task_id=$1 AND user_id=$2 AND id != $3",
        task_id, body.user_id, member_id
    )
    if conflict:
        raise HTTPException(status_code=400, detail="That user already holds a role on this stem")

    await pool.execute(
        """UPDATE group_annotation_members
           SET reassigned_from = user_id, reassigned_at = now(), user_id = $1,
               status = 'pending', started_at = NULL
           WHERE id = $2""",
        body.user_id, member_id
    )
    return await _get_group_task_detail(pool, task_id, viewer_user_id=user["id"])


@app.get("/group-tasks")
async def list_group_tasks(request: Request, user=Depends(get_current_user)):
    """Two round trips regardless of how many tasks are returned: one for the
    tasks, one for every member of every one of those tasks at once. Member
    rows are grouped in Python instead of being fetched per task."""
    pool = await get_pool()
    rows = await pool.fetch(
        """SELECT DISTINCT gt.*, s.text AS stem_text FROM group_annotation_tasks gt
           JOIN stems s ON s.id = gt.stem_id
           LEFT JOIN group_annotation_members gm ON gm.task_id = gt.id
           WHERE gt.created_by = $1 OR gm.user_id = $1
           ORDER BY gt.created_at DESC""",
        user["id"]
    )
    task_ids = [row["id"] for row in rows]
    member_rows = await pool.fetch(
        """SELECT gm.*, u.username FROM group_annotation_members gm
           JOIN users u ON u.id = gm.user_id
           WHERE gm.task_id = ANY($1::int[])
           ORDER BY gm.task_id, gm.role, gm.annotator_index NULLS FIRST""",
        task_ids
    ) if task_ids else []

    members_by_task: dict = {}
    for m in member_rows:
        members_by_task.setdefault(m["task_id"], []).append(GroupMemberOut(**dict(m)).model_dump())

    results = []
    for row in rows:
        members = members_by_task.get(row["id"], [])
        hide_scores = any(m["user_id"] == user["id"] for m in members)
        results.append(GroupTaskOut(
            id=row["id"], stem_id=row["stem_id"], stem_text=row["stem_text"],
            status=row["status"],
            outcome=None if hide_scores else row["outcome"],
            decision=None if hide_scores else row["decision"],
            scores_stale=row["scores_stale"],
            created_by=row["created_by"],
            created_at=row["created_at"], updated_at=row["updated_at"],
            acceptance_threshold=row["acceptance_threshold"], members=members
        ).model_dump())
    return results


@app.get("/group-tasks/dashboard")
async def group_tasks_dashboard(request: Request, user=Depends(get_current_user)):
    pool = await get_pool()
    # Buckets by outcome where one has been computed, else by workflow status —
    # keeps the existing dashboard UI meaningful without a frontend change here.
    status_rows = await pool.fetch(
        """SELECT COALESCE(gt.outcome, gt.status) AS status, COUNT(DISTINCT gt.id) AS n
           FROM group_annotation_tasks gt
           LEFT JOIN group_annotation_members gm ON gm.task_id = gt.id
           WHERE gt.created_by = $1 OR gm.user_id = $1
           GROUP BY COALESCE(gt.outcome, gt.status)""",
        user["id"]
    )
    by_status = {r["status"]: r["n"] for r in status_rows}
    # Aggregate stats intentionally include the viewer's own tasks (§6 "accepted leak") —
    # only per-task views hide individual scores.
    scored = await pool.fetch(
        """SELECT DISTINCT gt.id, gt.krippendorff_alpha FROM group_annotation_tasks gt
           LEFT JOIN group_annotation_members gm ON gm.task_id = gt.id
           WHERE (gt.created_by = $1 OR gm.user_id = $1) AND gt.krippendorff_alpha IS NOT NULL""",
        user["id"]
    )
    alphas = [s["krippendorff_alpha"] for s in scored]
    avg_alpha = sum(alphas) / len(alphas) if alphas else None
    return {"by_status": by_status, "completed_with_scores": len(alphas), "avg_krippendorff_alpha": avg_alpha}


@app.get("/group-tasks/{task_id}")
async def get_group_task(task_id: int, request: Request, user=Depends(get_current_user)):
    pool = await get_pool()
    await _require_group_access(pool, task_id, user["id"])
    return await _get_group_task_detail(pool, task_id, viewer_user_id=user["id"])


@app.get("/group-tasks/{task_id}/events")
async def list_group_events(task_id: int, request: Request, user=Depends(get_current_user)):
    pool = await get_pool()
    await _require_group_access(pool, task_id, user["id"])
    spans = await pool.fetch("SELECT * FROM spans WHERE group_task_id = $1 ORDER BY created_at", task_id)
    return [
        GroupEventSpanOut(
            id=s["id"], group_task_id=task_id, label_type=s["label_type"],
            seq_label=s["seq_label"], span_text=s["span_text"],
            char_start=s["char_start"], char_end=s["char_end"], created_at=s["created_at"]
        ).model_dump()
        for s in spans
    ]


@app.post("/group-tasks/{task_id}/events", status_code=201)
async def create_group_event(task_id: int, body: GroupEventSpanCreate, request: Request, user=Depends(get_current_user)):
    """Per D1/§5.5: the event annotator can add events at any time before the
    task's decision is finalized. Adding a span after timeline work exists
    invalidates all three timeline submissions (new event, no positions yet)."""
    validate_csrf(request)
    pool = await get_pool()
    task_and_member = await pool.fetchrow(
        """SELECT gt.status AS task_status, gt.decision,
                  gm.id AS member_id, gm.role AS member_role, gm.status AS member_status
           FROM group_annotation_tasks gt
           LEFT JOIN group_annotation_members gm ON gm.task_id = gt.id AND gm.user_id = $2
           WHERE gt.id = $1""",
        task_id, user["id"]
    )
    if not task_and_member:
        raise HTTPException(status_code=404, detail="Group task not found")
    if task_and_member["member_role"] != "event_annotator":
        raise HTTPException(status_code=403, detail="Only the event annotator can add events")
    if task_and_member["decision"] is not None:
        raise HTTPException(status_code=409, detail="Task decision is finalized; ask a non-participant to reopen it")
    member = {"id": task_and_member["member_id"], "status": task_and_member["member_status"]}

    # Count-then-insert combined into one round trip.
    row = await pool.fetchrow(
        """INSERT INTO spans (group_task_id, label_type, seq_label, span_text, char_start, char_end, tl_start, tl_end, source)
           SELECT $1, 'Event', 'E' || (COALESCE((SELECT COUNT(*) FROM spans WHERE group_task_id = $1), 0) + 1)::text,
                  $2, $3, $4, 10.0, 30.0, 'manual'
           RETURNING *""",
        task_id, body.span_text, body.char_start, body.char_end
    )

    if member["status"] in ("pending", "submitted"):
        await pool.execute(
            "UPDATE group_annotation_members SET status='in_progress', started_at=COALESCE(started_at, now()) WHERE id=$1",
            member["id"]
        )
    if task_and_member["task_status"] != "event_pending":
        await _invalidate_timelines_for_span_change(pool, task_id)

    return GroupEventSpanOut(
        id=row["id"], group_task_id=task_id, label_type=row["label_type"],
        seq_label=row["seq_label"], span_text=row["span_text"],
        char_start=row["char_start"], char_end=row["char_end"], created_at=row["created_at"]
    ).model_dump()


@app.delete("/group-tasks/{task_id}/events/{span_id}", status_code=204)
async def delete_group_event(task_id: int, span_id: int, request: Request, user=Depends(get_current_user)):
    validate_csrf(request)
    pool = await get_pool()
    task = await pool.fetchrow("SELECT * FROM group_annotation_tasks WHERE id=$1", task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Group task not found")
    member = await _get_group_member(pool, task_id, user["id"])
    if not member or member["role"] != "event_annotator":
        raise HTTPException(status_code=403, detail="Only the event annotator can delete events")
    if task["decision"] is not None:
        raise HTTPException(status_code=409, detail="Task decision is finalized; ask a non-participant to reopen it")
    span = await pool.fetchrow("SELECT * FROM spans WHERE id=$1 AND group_task_id=$2", span_id, task_id)
    if not span:
        raise HTTPException(status_code=404, detail="Span not found")

    await pool.execute("DELETE FROM spans WHERE id = $1", span_id)
    if member["status"] in ("pending", "submitted"):
        await pool.execute(
            "UPDATE group_annotation_members SET status='in_progress', started_at=COALESCE(started_at, now()) WHERE id=$1",
            member["id"]
        )
    if task["status"] != "event_pending":
        await _invalidate_timelines_for_span_change(pool, task_id)
    return None


@app.post("/group-tasks/{task_id}/submit-events")
async def submit_group_events(task_id: int, request: Request, user=Depends(get_current_user)):
    """One-way system transition event_pending -> timelines_pending. The event
    annotator can keep editing spans afterward (handled by the endpoints
    above); this endpoint only ever fires the initial unlock."""
    validate_csrf(request)
    pool = await get_pool()
    task = await pool.fetchrow("SELECT * FROM group_annotation_tasks WHERE id=$1", task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Group task not found")
    member = await _get_group_member(pool, task_id, user["id"])
    if not member or member["role"] != "event_annotator":
        raise HTTPException(status_code=403, detail="Only the event annotator can submit events")
    if task["status"] != "event_pending":
        raise HTTPException(status_code=409, detail="Events already submitted")
    count = await pool.fetchval("SELECT COUNT(*) FROM spans WHERE group_task_id = $1", task_id)
    if count < 2:
        raise HTTPException(status_code=400, detail="At least 2 events are required before submitting")

    async with pool.acquire() as conn:
        async with conn.transaction():
            await conn.execute(
                "UPDATE group_annotation_members SET status='submitted', completed_at=now() WHERE id=$1",
                member["id"]
            )
            await conn.execute(
                "UPDATE group_annotation_tasks SET status='timelines_pending', updated_at=now() WHERE id=$1",
                task_id
            )
    return await _get_group_task_detail(pool, task_id, viewer_user_id=user["id"])


@app.get("/group-tasks/{task_id}/my-timeline")
async def get_my_timeline(task_id: int, request: Request, user=Depends(get_current_user)):
    pool = await get_pool()
    member = await _get_group_member(pool, task_id, user["id"])
    if not member or member["role"] != "timeline_annotator":
        raise HTTPException(status_code=403, detail="Not a timeline annotator on this task")
    spans = await pool.fetch("SELECT * FROM spans WHERE group_task_id = $1 ORDER BY created_at", task_id)
    positions = await pool.fetch("SELECT * FROM timeline_annotations WHERE member_id = $1", member["id"])
    pos_by_span = {p["span_id"]: p for p in positions}
    result = [
        TimelinePositionOut(
            span_id=s["id"], seq_label=s["seq_label"], span_text=s["span_text"],
            tl_start=pos_by_span[s["id"]]["tl_start"] if s["id"] in pos_by_span else s["tl_start"],
            tl_end=pos_by_span[s["id"]]["tl_end"] if s["id"] in pos_by_span else s["tl_end"],
        ).model_dump()
        for s in spans
    ]
    return {"member_status": member["status"], "positions": result}


@app.put("/group-tasks/{task_id}/my-timeline")
async def upsert_my_timeline(task_id: int, body: TimelineUpsertRequest, request: Request, user=Depends(get_current_user)):
    """Per D1: always editable. Re-entering after submission flips the member
    back to in_progress and marks the task's scores stale rather than
    rejecting the write."""
    validate_csrf(request)
    pool = await get_pool()
    info = await _get_task_and_member_role(pool, task_id, user["id"])
    if not info:
        raise HTTPException(status_code=404, detail="Group task not found")
    if info["member_role"] != "timeline_annotator":
        raise HTTPException(status_code=403, detail="Not a timeline annotator on this task")
    if info["task_status"] not in ("timelines_pending", "computed"):
        raise HTTPException(status_code=409, detail="Timeline annotation is not open for this task")
    if info["task_decision"] is not None:
        raise HTTPException(status_code=409, detail="Task decision is finalized; ask a non-participant to reopen it")
    member = {"id": info["member_id"], "status": info["member_status"]}

    valid_span_ids = {r["id"] for r in await pool.fetch("SELECT id FROM spans WHERE group_task_id = $1", task_id)}
    for pos in body.positions:
        if pos.span_id not in valid_span_ids:
            raise HTTPException(status_code=400, detail=f"Span {pos.span_id} does not belong to this task")

    was_submitted = member["status"] == "submitted"
    async with pool.acquire() as conn:
        async with conn.transaction():
            if body.positions:
                # One round trip for every position in the batch, instead of
                # one insert per position — the frontend sends all of them
                # at once right before submitting.
                task_ids = [task_id] * len(body.positions)
                member_ids = [member["id"]] * len(body.positions)
                span_ids = [p.span_id for p in body.positions]
                tl_starts = [p.tl_start for p in body.positions]
                tl_ends = [p.tl_end for p in body.positions]
                sources = [p.source for p in body.positions]
                await conn.execute(
                    """INSERT INTO timeline_annotations (task_id, member_id, span_id, tl_start, tl_end, source)
                       SELECT * FROM unnest($1::int[], $2::int[], $3::int[], $4::float[], $5::float[], $6::text[])
                       ON CONFLICT (member_id, span_id)
                       DO UPDATE SET tl_start = EXCLUDED.tl_start, tl_end = EXCLUDED.tl_end,
                                     source = EXCLUDED.source, updated_at = now()""",
                    task_ids, member_ids, span_ids, tl_starts, tl_ends, sources
                )
            if member["status"] in ("pending", "submitted") and body.positions:
                await conn.execute(
                    "UPDATE group_annotation_members SET status='in_progress', started_at=COALESCE(started_at, now()) WHERE id=$1",
                    member["id"]
                )
            if was_submitted:
                await conn.execute(
                    "UPDATE group_annotation_tasks SET status='timelines_pending', scores_stale=TRUE, updated_at=now() WHERE id=$1",
                    task_id
                )
    return {"ok": True}


@app.post("/group-tasks/{task_id}/my-timeline/llm-extract")
async def llm_extract_my_timeline(task_id: int, request: Request, user=Depends(get_current_user)):
    """LLM timeline assist, scoped to this member only (§8). Writes into
    timeline_annotations, never the shared spans table, so it can't leak one
    annotator's LLM-derived positions into another's independent work."""
    validate_csrf(request)
    pool = await get_pool()
    task = await pool.fetchrow(
        "SELECT gt.*, s.text AS stem_text FROM group_annotation_tasks gt JOIN stems s ON s.id = gt.stem_id WHERE gt.id=$1",
        task_id
    )
    if not task:
        raise HTTPException(status_code=404, detail="Group task not found")
    member = await _get_group_member(pool, task_id, user["id"])
    if not member or member["role"] != "timeline_annotator":
        raise HTTPException(status_code=403, detail="Not a timeline annotator on this task")
    if task["decision"] is not None:
        raise HTTPException(status_code=409, detail="Task decision is finalized; ask a non-participant to reopen it")

    event_rows = await pool.fetch("SELECT * FROM spans WHERE group_task_id = $1 ORDER BY created_at", task_id)
    if not event_rows:
        return ExtractTimelineResponse(updated=[], skipped=[]).model_dump()

    events_for_prompt = [{"text": r["span_text"], "occurrence": 1} for r in event_rows]
    user_msg = (
        f"Stem text:\n{task['stem_text']}\n\n"
        f"Events (in order):\n{json.dumps(events_for_prompt, indent=2)}\n\n"
        f"Return JSON matching this schema:\n{TIMELINE_SCHEMA_JSON}"
    )
    try:
        raw = await callLLM(TIMELINE_SYSTEM_PROMPT, user_msg)
    except ValueError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"LLM provider error: {exc}") from exc

    if not isinstance(raw, dict):
        raise HTTPException(status_code=502, detail="LLM returned an unexpected response shape.")
    positions = raw.get("positions", [])
    if not isinstance(positions, list):
        raise HTTPException(status_code=502, detail="LLM returned an unexpected positions list.")
    pos_by_text = {p.get("text"): p for p in positions if isinstance(p, dict) and p.get("text")}

    updated, skipped = [], []
    was_submitted = member["status"] == "submitted"
    async with pool.acquire() as conn:
        async with conn.transaction():
            for r in event_rows:
                pos = pos_by_text.get(r["span_text"])
                if pos is None:
                    skipped.append({"text": r["span_text"], "reason": "Not found in LLM response."})
                    continue
                start, end = pos.get("start"), pos.get("end")
                if not isinstance(start, (int, float)) or not isinstance(end, (int, float)):
                    skipped.append({"text": r["span_text"], "reason": "Missing start or end value from model."})
                    continue
                start = round(max(TIMELINE_MIN, min(TIMELINE_MAX, start)), 1)
                end = round(max(TIMELINE_MIN, min(TIMELINE_MAX, end)), 1)
                if end < start:
                    avg = (start + end) / 2
                    start = round(avg - MIN_WIDTH / 2, 1)
                    end = round(avg + MIN_WIDTH / 2, 1)
                elif end == start:
                    end = round(start + MIN_WIDTH, 1)
                await conn.execute(
                    """INSERT INTO timeline_annotations (task_id, member_id, span_id, tl_start, tl_end, source)
                       VALUES ($1,$2,$3,$4,$5,'llm')
                       ON CONFLICT (member_id, span_id) DO UPDATE SET tl_start=$4, tl_end=$5, source='llm', updated_at=now()""",
                    task_id, member["id"], r["id"], start, end
                )
                updated.append({
                    "span_id": r["id"], "seq_label": r["seq_label"],
                    "span_text": r["span_text"], "tl_start": start, "tl_end": end,
                })
            if member["status"] in ("pending", "submitted"):
                await conn.execute(
                    "UPDATE group_annotation_members SET status='in_progress', started_at=COALESCE(started_at, now()) WHERE id=$1",
                    member["id"]
                )
            if was_submitted:
                await conn.execute(
                    "UPDATE group_annotation_tasks SET status='timelines_pending', scores_stale=TRUE, updated_at=now() WHERE id=$1",
                    task_id
                )

    return ExtractTimelineResponse(updated=updated, skipped=skipped).model_dump()


@app.get("/group-tasks/{task_id}/my-matrix")
async def get_my_matrix(task_id: int, request: Request, user=Depends(get_current_user)):
    pool = await get_pool()
    member = await _get_group_member(pool, task_id, user["id"])
    if not member or member["role"] != "timeline_annotator":
        raise HTTPException(status_code=403, detail="Not a timeline annotator on this task")
    spans = await pool.fetch("SELECT * FROM spans WHERE group_task_id = $1 ORDER BY created_at", task_id)
    result = await _member_matrix(pool, member["id"], spans)
    violations = transitivity_check(result["matrix"], [s["seq_label"] for s in spans])
    return {**result, "violations": violations}


@app.post("/group-tasks/{task_id}/my-matrix/save")
async def save_my_matrix(task_id: int, request: Request, user=Depends(get_current_user)):
    """Re-derives this member's matrix from their current positions. Cells
    they have overridden are preserved (§5.4)."""
    validate_csrf(request)
    pool = await get_pool()
    task = await pool.fetchrow("SELECT * FROM group_annotation_tasks WHERE id=$1", task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Group task not found")
    member = await _get_group_member(pool, task_id, user["id"])
    if not member or member["role"] != "timeline_annotator":
        raise HTTPException(status_code=403, detail="Not a timeline annotator on this task")
    if task["decision"] is not None:
        raise HTTPException(status_code=409, detail="Task decision is finalized; ask a non-participant to reopen it")

    spans = await pool.fetch("SELECT * FROM spans WHERE group_task_id = $1 ORDER BY created_at", task_id)
    positions = await _member_positions(pool, member["id"], spans)
    span_list = [{"id": s["id"], "tl_start": positions[s["id"]][0], "tl_end": positions[s["id"]][1]} for s in spans]
    derived = build_matrix(span_list)
    await _save_member_relations(pool, task_id, member["id"], spans, derived)
    result = await _member_matrix(pool, member["id"], spans)
    return result


@app.patch("/group-tasks/{task_id}/my-matrix/override")
async def override_my_matrix(task_id: int, body: MatrixOverride, request: Request, user=Depends(get_current_user)):
    """Per D3: timeline annotators can override individual Allen matrix cells,
    same as the batch flow's Step 3. Overriding after submission counts as an
    edit and re-opens the task for recompute (D1)."""
    validate_csrf(request)
    pool = await get_pool()
    task = await pool.fetchrow("SELECT * FROM group_annotation_tasks WHERE id=$1", task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Group task not found")
    member = await _get_group_member(pool, task_id, user["id"])
    if not member or member["role"] != "timeline_annotator":
        raise HTTPException(status_code=403, detail="Not a timeline annotator on this task")
    if task["decision"] is not None:
        raise HTTPException(status_code=409, detail="Task decision is finalized; ask a non-participant to reopen it")

    spans = await pool.fetch("SELECT * FROM spans WHERE group_task_id = $1 ORDER BY created_at", task_id)
    n = len(spans)
    if body.i < 0 or body.i >= n or body.j < 0 or body.j >= n:
        raise HTTPException(status_code=400, detail="Index out of range")
    if body.i == body.j:
        raise HTTPException(status_code=400, detail="Cannot override diagonal")

    si, sj = spans[body.i]["id"], spans[body.j]["id"]
    inv = INVERSES.get(body.relation_code, -body.relation_code)

    async with pool.acquire() as conn:
        async with conn.transaction():
            for a, b, code in ((si, sj, body.relation_code), (sj, si, inv)):
                await conn.execute(
                    """INSERT INTO timeline_relations (task_id, member_id, span_i_id, span_j_id, relation_code, is_override)
                       VALUES ($1,$2,$3,$4,$5,TRUE)
                       ON CONFLICT (member_id, span_i_id, span_j_id) DO UPDATE SET relation_code=$5, is_override=TRUE, updated_at=now()""",
                    task_id, member["id"], a, b, code
                )
            if member["status"] == "submitted":
                await conn.execute("UPDATE group_annotation_members SET status='in_progress' WHERE id=$1", member["id"])
                await conn.execute(
                    "UPDATE group_annotation_tasks SET status='timelines_pending', scores_stale=TRUE, updated_at=now() WHERE id=$1",
                    task_id
                )

    return await _member_matrix(pool, member["id"], spans)


@app.post("/group-tasks/{task_id}/submit-timeline")
async def submit_timeline(task_id: int, request: Request, user=Depends(get_current_user)):
    validate_csrf(request)
    pool = await get_pool()
    info = await _get_task_and_member_role(pool, task_id, user["id"])
    if not info:
        raise HTTPException(status_code=404, detail="Group task not found")
    if info["member_role"] != "timeline_annotator":
        raise HTTPException(status_code=403, detail="Not a timeline annotator on this task")
    if info["task_status"] not in ("timelines_pending", "computed"):
        raise HTTPException(status_code=409, detail="Timeline annotation is not open for this task")
    if info["task_decision"] is not None:
        raise HTTPException(status_code=409, detail="Task decision is finalized; ask a non-participant to reopen it")
    member_id = info["member_id"]

    # Spans + this member's positions in one round trip (was two), so the
    # matrix can be built without a second fetch later.
    rows = await pool.fetch(
        """SELECT s.id, s.seq_label, ta.tl_start, ta.tl_end, ta.source
           FROM spans s
           LEFT JOIN timeline_annotations ta ON ta.span_id = s.id AND ta.member_id = $2
           WHERE s.group_task_id = $1
           ORDER BY s.created_at""",
        task_id, member_id
    )
    missing = [r["seq_label"] for r in rows if r["tl_start"] is None]
    if missing:
        raise HTTPException(status_code=400, detail=f"Missing timeline positions for: {', '.join(missing)}")

    span_list = [{"id": r["id"], "tl_start": r["tl_start"], "tl_end": r["tl_end"]} for r in rows]
    derived_matrix = build_matrix(span_list)
    await _save_member_relations(pool, task_id, member_id, rows, derived_matrix)

    # Apply any prior overrides to the just-derived matrix in Python — one
    # query for the overrides, instead of re-fetching positions we already
    # have (that's what _member_matrix would otherwise do here).
    matrix = [row[:] for row in derived_matrix]
    id_index = {r["id"]: idx for idx, r in enumerate(rows)}
    overrides = await pool.fetch(
        "SELECT * FROM timeline_relations WHERE member_id=$1 AND is_override=TRUE", member_id
    )
    for o in overrides:
        i, j = id_index.get(o["span_i_id"]), id_index.get(o["span_j_id"])
        if i is not None and j is not None:
            matrix[i][j] = o["relation_code"]
    span_order = [{"id": r["id"], "seq_label": r["seq_label"]} for r in rows]

    had_llm_assist = any(r["source"] == "llm" for r in rows)
    positions_json = [{"span_id": r["id"], "tl_start": r["tl_start"], "tl_end": r["tl_end"]} for r in rows]

    async with pool.acquire() as conn:
        async with conn.transaction():
            await conn.execute(
                """INSERT INTO timeline_relation_matrices (task_id, member_id, matrix_json, span_order)
                   VALUES ($1,$2,$3,$4)
                   ON CONFLICT (task_id, member_id) DO UPDATE SET matrix_json=$3, span_order=$4""",
                task_id, member_id, json.dumps(matrix), json.dumps(span_order)
            )
            # next revision_no folded into the insert itself — one round trip
            # instead of a separate SELECT MAX(...) beforehand.
            await conn.execute(
                """INSERT INTO timeline_submission_revisions
                       (task_id, member_id, revision_no, positions_json, matrix_json, span_order, had_llm_assist)
                   SELECT $1, $2,
                          COALESCE((SELECT MAX(revision_no) FROM timeline_submission_revisions WHERE member_id = $2), 0) + 1,
                          $3, $4, $5, $6""",
                task_id, member_id, json.dumps(positions_json),
                json.dumps(matrix), json.dumps(span_order), had_llm_assist
            )
            await conn.execute(
                "UPDATE group_annotation_members SET status='submitted', completed_at=now() WHERE id=$1",
                member_id
            )

    remaining = await pool.fetch(
        "SELECT status FROM group_annotation_members WHERE task_id=$1 AND role='timeline_annotator'",
        task_id
    )
    if all(m["status"] == "submitted" for m in remaining):
        await _finalize_group_agreement(pool, task_id)
    elif info["task_status"] == "computed":
        # A revision after a prior full completion — back to pending until all 3 resubmit.
        await pool.execute(
            "UPDATE group_annotation_tasks SET status='timelines_pending', scores_stale=TRUE, updated_at=now() WHERE id=$1",
            task_id
        )

    return await _get_group_task_detail(pool, task_id, viewer_user_id=user["id"])


@app.get("/group-tasks/{task_id}/agreement")
async def get_group_agreement(task_id: int, request: Request, user=Depends(get_current_user)):
    """Per D7: members of the task cannot see its agreement scores at all."""
    pool = await get_pool()
    access = await _require_group_access(pool, task_id, user["id"])
    if access["is_member"]:
        raise HTTPException(status_code=403, detail="Participants cannot view their own task's agreement scores")
    task = await pool.fetchrow("SELECT * FROM group_annotation_tasks WHERE id=$1", task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Group task not found")
    details = json.loads(task["agreement_details"]) if task["agreement_details"] else None
    return GroupAgreementOut(
        task_id=task_id, status=task["status"],
        krippendorff_alpha=task["krippendorff_alpha"],
        cohens_kappa_avg=task["cohens_kappa_avg"],
        fleiss_kappa=task["fleiss_kappa"],
        acceptance_threshold=task["acceptance_threshold"],
        agreement_details=details,
        scores_stale=task["scores_stale"],
    ).model_dump()


@app.get("/group-tasks/{task_id}/revisions")
async def get_group_revisions(task_id: int, request: Request, user=Depends(get_current_user)):
    """Submission history, non-participants only (§10.1)."""
    pool = await get_pool()
    access = await _require_group_access(pool, task_id, user["id"])
    if access["is_member"]:
        raise HTTPException(status_code=403, detail="Participants cannot view their own task's revision history")
    rows = await pool.fetch(
        """SELECT r.*, gm.user_id, gm.annotator_index, u.username
           FROM timeline_submission_revisions r
           JOIN group_annotation_members gm ON gm.id = r.member_id
           JOIN users u ON u.id = gm.user_id
           WHERE r.task_id = $1 ORDER BY r.submitted_at""",
        task_id
    )
    return [
        {
            "member_id": r["member_id"], "user_id": r["user_id"], "username": r["username"],
            "annotator_index": r["annotator_index"], "revision_no": r["revision_no"],
            "had_llm_assist": r["had_llm_assist"], "submitted_at": r["submitted_at"].isoformat(),
        }
        for r in rows
    ]


@app.get("/group-tasks/{task_id}/agreement-runs")
async def get_group_agreement_runs(task_id: int, request: Request, user=Depends(get_current_user)):
    """Agreement over time, non-participants only (§10.1)."""
    pool = await get_pool()
    access = await _require_group_access(pool, task_id, user["id"])
    if access["is_member"]:
        raise HTTPException(status_code=403, detail="Participants cannot view their own task's agreement history")
    rows = await pool.fetch(
        "SELECT * FROM agreement_runs WHERE task_id = $1 ORDER BY run_no", task_id
    )
    return [
        {
            "run_no": r["run_no"], "krippendorff_alpha": r["krippendorff_alpha"],
            "cohens_kappa_avg": r["cohens_kappa_avg"], "fleiss_kappa": r["fleiss_kappa"],
            "outcome": r["outcome"], "based_on_revisions": json.loads(r["based_on_revisions"]),
            "computed_at": r["computed_at"].isoformat(),
        }
        for r in rows
    ]


@app.post("/group-tasks/{task_id}/accept")
async def decide_group_task(task_id: int, body: GroupTaskDecision, request: Request, user=Depends(get_current_user)):
    """Per D6/§6: any non-participant may set or clear the decision — no
    admin role, no creator privilege. Passing decision=null reopens the task."""
    validate_csrf(request)
    pool = await get_pool()
    access = await _get_access_and_membership(pool, task_id, user["id"])
    if not access:
        raise HTTPException(status_code=404, detail="Group task not found")
    if access["is_member"]:
        raise HTTPException(status_code=403, detail="Participants cannot finalize a decision on their own task")

    if body.decision is None:
        await pool.execute(
            "UPDATE group_annotation_tasks SET decision=NULL, decided_by=NULL, decided_at=NULL, updated_at=now() WHERE id=$1",
            task_id
        )
    else:
        valid_decisions = {"accepted", "accepted_flagged", "adjudication", "rejected"}
        if body.decision not in valid_decisions:
            raise HTTPException(status_code=400, detail=f"Decision must be one of {sorted(valid_decisions)}")
        await pool.execute(
            "UPDATE group_annotation_tasks SET decision=$1, decided_by=$2, decided_at=now(), updated_at=now() WHERE id=$3",
            body.decision, user["id"], task_id
        )
    return await _get_group_task_detail(pool, task_id, viewer_user_id=user["id"])
