"""
FastAPI backend for Spatiotemporal Annotation & Allen's Algebra Benchmarking System.
"""

import json
import csv
import io
import os
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
    SignupRequest, LoginRequest, UserOut, UserRoleUpdate, AuthMeResponse,
    StemOut, StemsListResponse, StemStatsResponse, UserStemStatItem, UserStemStatsResponse, StemsImportResponse,
    CompletedStemItem, CompletedStemsResponse,
    BatchCreate, BatchOut, BatchDetailOut,
    BatchSpanCreate, BatchSpanOut,
    ConflictResponse,
    ReviewDecisionRequest, StemReviewOut, PendingReviewItemOut,
    BatchStemUpdateText,
)
from auth import (
    hash_password, verify_password,
    create_session, get_session, delete_session as delete_auth_session, get_user_by_id,
    set_session_cookies, clear_session_cookies,
    get_current_user, get_current_user_optional, validate_csrf,
    require_reviewer, require_admin, invalidate_session_cache,
)
from allen.relations import build_matrix, RELATION_NAMES, INVERSES
from allen.validate import transitivity_check
from llm import callLLM


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


async def _resequence_spans(pool, batch_stem_id: Optional[int] = None, session_id: Optional[int] = None):
    """
    Ensures spans are numbered sequentially (E1, E2... for Event, T1, T2... for Time)
    without gaps or duplicates, ordered by created_at, id.
    """
    for label_type, prefix in [("Event", "E"), ("Time", "T")]:
        if batch_stem_id is not None:
            spans = await pool.fetch(
                "SELECT id, seq_label FROM spans WHERE batch_stem_id = $1 AND label_type = $2 ORDER BY created_at, id",
                batch_stem_id, label_type
            )
        elif session_id is not None:
            spans = await pool.fetch(
                "SELECT id, seq_label FROM spans WHERE session_id = $1 AND label_type = $2 ORDER BY created_at, id",
                session_id, label_type
            )
        else:
            return
        for idx, s in enumerate(spans, start=1):
            expected = f"{prefix}{idx}"
            if s["seq_label"] != expected:
                await pool.execute("UPDATE spans SET seq_label = $1 WHERE id = $2", expected, s["id"])


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
    if row.get("batch_stem_id"):
        await _resequence_spans(pool, batch_stem_id=row["batch_stem_id"])
        await pool.execute("DELETE FROM matrix_snapshots WHERE batch_stem_id = $1", row["batch_stem_id"])
    elif row.get("session_id"):
        await _resequence_spans(pool, session_id=row["session_id"])
        await pool.execute("DELETE FROM matrix_snapshots WHERE session_id = $1", row["session_id"])
    return None


# ---------------------------------------------------------------------------
# Matrix
# ---------------------------------------------------------------------------

@app.get("/sessions/{session_id}/matrix")
async def get_matrix(session_id: int):
    pool = await get_pool()
    await _get_session_or_404(pool, session_id)
    spans = await _get_event_spans(pool, session_id)
    span_list = [dict(s) for s in spans]
    snapshot = await pool.fetchrow(
        "SELECT * FROM matrix_snapshots WHERE session_id=$1 ORDER BY updated_at DESC LIMIT 1",
        session_id
    )
    if snapshot and snapshot["matrix_json"]:
        try:
            saved_matrix = json.loads(snapshot["matrix_json"])
            if len(saved_matrix) == len(span_list):
                matrix = saved_matrix
            else:
                matrix = build_matrix(span_list)
        except Exception:
            matrix = build_matrix(span_list)
    else:
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

    records = [
        (session_id, si["id"], sj["id"], matrix[i][j])
        for i, si in enumerate(span_list)
        for j, sj in enumerate(span_list)
    ]
    if records:
        await pool.executemany(
            """INSERT INTO relations (session_id, span_i_id, span_j_id, relation_code)
               VALUES ($1, $2, $3, $4)
               ON CONFLICT (session_id, span_i_id, span_j_id) WHERE session_id IS NOT NULL
               DO UPDATE SET relation_code = EXCLUDED.relation_code""",
            records
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
    role = body.role if body.role in ("annotator", "reviewer", "admin") else "annotator"
    row = await pool.fetchrow(
        "INSERT INTO users (email, username, password_hash, role) VALUES ($1, $2, $3, $4) RETURNING id, email, username, role, created_at",
        body.email, body.username, pw_hash, role
    )
    user = dict(row)
    token, csrf_token, _ = await create_session(user["id"])
    set_session_cookies(response, token, csrf_token)
    return {"user": UserOut(**user).model_dump(), "csrf_token": csrf_token}


@app.post("/auth/login")
async def login(body: LoginRequest, response: Response):
    pool = await get_pool()
    row = await pool.fetchrow(
        "SELECT id, email, username, password_hash, COALESCE(role, 'annotator') as role, created_at FROM users WHERE email = $1",
        body.email
    )
    if not row or not verify_password(body.password, row["password_hash"]):
        raise HTTPException(status_code=401, detail="Invalid email or password")
    user = dict(row)
    token, csrf_token, _ = await create_session(user["id"])
    set_session_cookies(response, token, csrf_token)
    return {
        "user": UserOut(
            id=user["id"],
            email=user["email"],
            username=user["username"],
            role=user["role"],
            created_at=user["created_at"],
        ).model_dump(),
        "csrf_token": csrf_token,
    }


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


@app.patch("/admin/users/{user_id}/role")
async def update_user_role(user_id: int, body: UserRoleUpdate, request: Request, admin=Depends(require_admin)):
    validate_csrf(request)
    if body.role not in ("annotator", "reviewer", "admin"):
        raise HTTPException(status_code=400, detail="Invalid role")
    pool = await get_pool()
    updated = await pool.fetchrow(
        "UPDATE users SET role = $1 WHERE id = $2 RETURNING id, email, username, role, created_at",
        body.role, user_id
    )
    if not updated:
        raise HTTPException(status_code=404, detail="User not found")
    invalidate_session_cache(user_id=user_id)
    return {"ok": True, "user": UserOut(**dict(updated)).model_dump()}


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

@app.get("/stems/stats", response_model=StemStatsResponse)
async def get_stem_stats(request: Request):
    pool = await get_pool()
    total = await pool.fetchval("SELECT COUNT(*) FROM stems")
    completed = await pool.fetchval(
        "SELECT COUNT(DISTINCT stem_id) FROM batch_stems WHERE status = 'done'"
    )
    under_review = await pool.fetchval(
        """SELECT COUNT(DISTINCT stem_id) FROM batch_stems 
           WHERE status = 'pending-review' 
             AND stem_id NOT IN (SELECT stem_id FROM batch_stems WHERE status = 'done')"""
    )
    total_val = total or 0
    completed_val = completed or 0
    under_review_val = under_review or 0
    remaining_val = max(0, total_val - completed_val - under_review_val)
    return {
        "total_stems": total_val,
        "completed_stems": completed_val,
        "under_review_stems": under_review_val,
        "remaining_stems": remaining_val,
    }


@app.get("/stems/user-stats", response_model=UserStemStatsResponse)
async def get_user_stem_stats(request: Request, user=Depends(get_current_user)):
    pool = await get_pool()
    query = """
    SELECT 
        u.id AS user_id,
        u.username,
        u.email,
        u.role,
        COALESCE(done_stats.cnt, 0)::int AS done,
        COALESCE(review_stats.cnt, 0)::int AS under_review,
        COALESCE(lock_stats.cnt, 0)::int AS in_lock
    FROM users u
    LEFT JOIN (
        SELECT COALESCE(bs.completed_by, b.owner_id) AS uid, COUNT(DISTINCT bs.stem_id) AS cnt
        FROM batch_stems bs
        JOIN batches b ON b.id = bs.batch_id
        WHERE bs.status = 'done'
        GROUP BY COALESCE(bs.completed_by, b.owner_id)
    ) done_stats ON done_stats.uid = u.id
    LEFT JOIN (
        SELECT b.owner_id AS uid, COUNT(DISTINCT bs.stem_id) AS cnt
        FROM batch_stems bs
        JOIN batches b ON b.id = bs.batch_id
        WHERE bs.status = 'pending-review'
        GROUP BY b.owner_id
    ) review_stats ON review_stats.uid = u.id
    LEFT JOIN (
        SELECT b.owner_id AS uid, COUNT(DISTINCT bs.stem_id) AS cnt
        FROM batch_stems bs
        JOIN batches b ON b.id = bs.batch_id
        WHERE b.status = 'active' 
          AND b.expires_at > now()
          AND bs.status NOT IN ('done', 'pending-review', 'released', 'blacklisted')
        GROUP BY b.owner_id
    ) lock_stats ON lock_stats.uid = u.id
    ORDER BY (COALESCE(done_stats.cnt, 0) + COALESCE(review_stats.cnt, 0) + COALESCE(lock_stats.cnt, 0)) DESC, u.username ASC
    """
    rows = await pool.fetch(query)
    users_list = []
    my_item = None
    for r in rows:
        done_cnt = r["done"]
        under_review_cnt = r["under_review"]
        in_lock_cnt = r["in_lock"]
        item = UserStemStatItem(
            user_id=r["user_id"],
            username=r["username"],
            email=r["email"],
            role=r["role"],
            done=done_cnt,
            under_review=under_review_cnt,
            in_lock=in_lock_cnt,
            total=done_cnt + under_review_cnt + in_lock_cnt,
        )
        users_list.append(item)
        if r["user_id"] == user["id"]:
            my_item = item

    if not my_item:
        my_item = UserStemStatItem(
            user_id=user["id"],
            username=user.get("username", ""),
            email=user.get("email", ""),
            role=user.get("role", "annotator"),
            done=0,
            under_review=0,
            in_lock=0,
            total=0,
        )

    return UserStemStatsResponse(my_stats=my_item, users=users_list)


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

    where_clauses = ["1=1"]
    filter_params = []

    if like:
        filter_params.append(like)
        idx = len(filter_params)
        where_clauses.append(f"""(
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
        )""")

    if status == "available":
        where_clauses.append("s.is_blacklisted = FALSE AND act.owner_id IS NULL AND dn.completed_by IS NULL AND pnd.batch_stem_id IS NULL")
    elif status == "booked":
        where_clauses.append("s.is_blacklisted = FALSE AND act.owner_id IS NOT NULL AND act.status <> 're-evaluate'")
    elif status == "pending-review":
        where_clauses.append("pnd.batch_stem_id IS NOT NULL")
    elif status == "re-evaluate":
        where_clauses.append("((act.owner_id IS NOT NULL AND act.status = 're-evaluate') OR (act.owner_id IS NULL AND rev.decision = 're-evaluate' AND dn.completed_by IS NULL))")
    elif status == "completed":
        where_clauses.append("dn.completed_by IS NOT NULL")
    elif status == "blacklisted":
        where_clauses.append("s.is_blacklisted = TRUE")
    elif status == "mine" and user:
        filter_params.append(user["id"])
        idx = len(filter_params)
        where_clauses.append(f"(act.owner_id = ${idx} OR pnd.owner_id = ${idx})")

    where_sql = " AND ".join(f"({w})" for w in where_clauses)

    count_sql = f"""
        SELECT COUNT(*) FROM stems s
        LEFT JOIN LATERAL (
            SELECT b.owner_id, bs.status
            FROM batch_stems bs JOIN batches b ON b.id = bs.batch_id
            WHERE bs.stem_id = s.id
              AND b.expires_at > now()
              AND b.status = 'active'
              AND bs.status NOT IN ('done', 'pending-review', 'blacklisted', 'released')
            ORDER BY b.expires_at DESC LIMIT 1
        ) act ON true
        LEFT JOIN LATERAL (
            SELECT bs.completed_by
            FROM batch_stems bs
            WHERE bs.stem_id = s.id AND bs.status = 'done'
            ORDER BY bs.completed_at DESC LIMIT 1
        ) dn ON true
        LEFT JOIN LATERAL (
            SELECT bs.id AS batch_stem_id, b.owner_id
            FROM batch_stems bs JOIN batches b ON b.id = bs.batch_id
            WHERE bs.stem_id = s.id AND bs.status = 'pending-review'
            ORDER BY bs.updated_at DESC LIMIT 1
        ) pnd ON true
        LEFT JOIN LATERAL (
            SELECT sr.decision
            FROM stem_reviews sr
            WHERE sr.stem_id = s.id
            ORDER BY sr.created_at DESC LIMIT 1
        ) rev ON true
        WHERE {where_sql}
    """

    count_rows = await pool.fetch(count_sql, *filter_params)
    total = count_rows[0]["count"] if count_rows else 0

    limit_idx = len(filter_params) + 1
    offset_idx = len(filter_params) + 2

    data_sql = f"""
        SELECT s.id, s.text, s.word_count, s.is_blacklisted, s.blacklist_reason,
               s.blacklisted_by, u_bl.username AS blacklisted_username, s.blacklisted_at,
               act.owner_id AS booked_by,
               u1.username AS booked_username,
               act.expires_at AS locked_until,
               act.status AS booked_status,
               dn.completed_batch_stem_id,
               dn.completed_batch_id,
               dn.completed_by,
               u2.username AS completed_username,
               dn.completed_at,
               pnd.batch_stem_id AS pending_batch_stem_id,
               pnd.owner_id AS pending_owner_id,
               u3.username AS pending_username,
               rev.decision AS latest_review_decision,
               rev.comment AS latest_review_comment,
               rev.reviewer_username AS latest_reviewer_username,
               rev.created_at AS latest_review_at
        FROM stems s
        LEFT JOIN users u_bl ON u_bl.id = s.blacklisted_by
        LEFT JOIN LATERAL (
            SELECT b.owner_id, b.expires_at, bs.status
            FROM batch_stems bs JOIN batches b ON b.id = bs.batch_id
            WHERE bs.stem_id = s.id
              AND b.expires_at > now()
              AND b.status = 'active'
              AND bs.status NOT IN ('done', 'pending-review', 'blacklisted', 'released')
            ORDER BY b.expires_at DESC LIMIT 1
        ) act ON true
        LEFT JOIN LATERAL (
            SELECT bs.id AS completed_batch_stem_id, bs.batch_id AS completed_batch_id, bs.completed_by, bs.completed_at
            FROM batch_stems bs
            WHERE bs.stem_id = s.id AND bs.status = 'done'
            ORDER BY bs.completed_at DESC LIMIT 1
        ) dn ON true
        LEFT JOIN LATERAL (
            SELECT bs.id AS batch_stem_id, b.owner_id
            FROM batch_stems bs JOIN batches b ON b.id = bs.batch_id
            WHERE bs.stem_id = s.id AND bs.status = 'pending-review'
            ORDER BY bs.updated_at DESC LIMIT 1
        ) pnd ON true
        LEFT JOIN LATERAL (
            SELECT sr.decision, sr.comment, sr.created_at, ur.username AS reviewer_username
            FROM stem_reviews sr
            JOIN users ur ON ur.id = sr.reviewer_id
            WHERE sr.stem_id = s.id
            ORDER BY sr.created_at DESC LIMIT 1
        ) rev ON true
        LEFT JOIN users u1 ON u1.id = act.owner_id
        LEFT JOIN users u2 ON u2.id = dn.completed_by
        LEFT JOIN users u3 ON u3.id = pnd.owner_id
        WHERE {where_sql}
        ORDER BY s.id
        LIMIT ${limit_idx} OFFSET ${offset_idx}
    """

    data_rows = await pool.fetch(data_sql, *filter_params, page_size, offset)

    items = []
    for r in data_rows:
        booked_by = None
        locked_until = None
        if r["booked_by"] is not None:
            booked_by = {"id": r["booked_by"], "username": r["booked_username"]}
            locked_until = r["locked_until"]
        elif r["pending_owner_id"] is not None:
            booked_by = {"id": r["pending_owner_id"], "username": r["pending_username"]}

        completed_by = None
        completed_at = None
        if r["completed_by"] is not None:
            completed_by = {"id": r["completed_by"], "username": r["completed_username"]}
            completed_at = r["completed_at"]

        blacklisted_by = None
        if r["blacklisted_by"] is not None:
            blacklisted_by = {"id": r["blacklisted_by"], "username": r["blacklisted_username"]}

        latest_review = None
        if r["latest_review_decision"] is not None:
            latest_review = {
                "decision": r["latest_review_decision"],
                "comment": r["latest_review_comment"],
                "reviewer_username": r["latest_reviewer_username"],
                "created_at": r["latest_review_at"],
            }

        state = "available"
        if r["is_blacklisted"]:
            state = "blacklisted"
        elif r["pending_batch_stem_id"] is not None:
            state = "pending-review"
        elif completed_by is not None:
            state = "completed"
        elif booked_by is not None:
            state = "re-evaluate" if r["booked_status"] == "re-evaluate" else "booked"
        elif r["latest_review_decision"] == "re-evaluate":
            state = "re-evaluate"

        items.append(StemOut(
            id=r["id"],
            text=r["text"],
            word_count=r["word_count"],
            state=state,
            booked_by=booked_by,
            locked_until=locked_until,
            completed_by=completed_by,
            completed_at=completed_at,
            completed_batch_stem_id=r["completed_batch_stem_id"] if completed_by else None,
            completed_batch_id=r["completed_batch_id"] if completed_by else None,
            is_blacklisted=bool(r["is_blacklisted"]),
            blacklist_reason=r["blacklist_reason"],
            blacklisted_by=blacklisted_by,
            blacklisted_at=r["blacklisted_at"],
            latest_review=latest_review,
        ))

    return StemsListResponse(items=items, total=total, page=page, page_size=page_size)


@app.get("/completed-stems", response_model=CompletedStemsResponse)
async def list_completed_stems(
    request: Request,
    search: Optional[str] = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    user=Depends(get_current_user),
):
    pool = await get_pool()
    offset = (page - 1) * page_size
    params = []
    where_clauses = ["bs.status = 'done'"]

    if search and search.strip():
        s = f"%{search.strip()}%"
        params.append(s)
        idx = len(params)
        where_clauses.append(f"(s.text ILIKE ${idx} OR u_ann.username ILIKE ${idx} OR u_rev.username ILIKE ${idx} OR b.name ILIKE ${idx})")

    where_sql = " AND ".join(where_clauses)

    count_sql = f"""
        SELECT COUNT(*) FROM batch_stems bs
        JOIN stems s ON s.id = bs.stem_id
        JOIN batches b ON b.id = bs.batch_id
        LEFT JOIN users u_ann ON u_ann.id = bs.completed_by
        LEFT JOIN users u_rev ON u_rev.id = bs.reviewer_id
        WHERE {where_sql}
    """
    total = await pool.fetchval(count_sql, *params)

    limit_idx = len(params) + 1
    offset_idx = len(params) + 2

    data_sql = f"""
        SELECT 
            bs.id AS batch_stem_id,
            bs.batch_id,
            b.name AS batch_name,
            bs.stem_id,
            s.text AS stem_text,
            s.word_count,
            bs.status,
            bs.completed_at,
            u_ann.id AS completed_by_id,
            u_ann.username AS completed_by_username,
            u_rev.id AS reviewer_id,
            u_rev.username AS reviewer_username,
            bs.reviewed_at,
            (SELECT COUNT(*) FROM spans WHERE batch_stem_id = bs.id AND label_type = 'Event') AS event_count,
            (SELECT COUNT(*) FROM spans WHERE batch_stem_id = bs.id AND label_type = 'Time') AS time_count,
            (SELECT json_build_object('decision', sr.decision, 'comment', sr.comment, 'reviewer_username', ur2.username, 'created_at', sr.created_at)
             FROM stem_reviews sr
             JOIN users ur2 ON ur2.id = sr.reviewer_id
             WHERE sr.batch_stem_id = bs.id
             ORDER BY sr.created_at DESC LIMIT 1) AS latest_review
        FROM batch_stems bs
        JOIN stems s ON s.id = bs.stem_id
        JOIN batches b ON b.id = bs.batch_id
        LEFT JOIN users u_ann ON u_ann.id = bs.completed_by
        LEFT JOIN users u_rev ON u_rev.id = bs.reviewer_id
        WHERE {where_sql}
        ORDER BY bs.completed_at DESC NULLS LAST, bs.id DESC
        LIMIT ${limit_idx} OFFSET ${offset_idx}
    """
    rows = await pool.fetch(data_sql, *params, page_size, offset)

    items = []
    for r in rows:
        completed_by = None
        if r["completed_by_id"] is not None:
            completed_by = {"id": r["completed_by_id"], "username": r["completed_by_username"]}
        reviewer = None
        if r["reviewer_id"] is not None:
            reviewer = {"id": r["reviewer_id"], "username": r["reviewer_username"]}

        latest_rev = r["latest_review"]
        if isinstance(latest_rev, str):
            try:
                latest_rev = json.loads(latest_rev)
            except Exception:
                pass

        items.append(CompletedStemItem(
            batch_stem_id=r["batch_stem_id"],
            batch_id=r["batch_id"],
            batch_name=r["batch_name"],
            stem_id=r["stem_id"],
            stem_text=r["stem_text"],
            word_count=r["word_count"],
            status=r["status"],
            completed_by=completed_by,
            completed_at=r["completed_at"],
            reviewer=reviewer,
            reviewed_at=r["reviewed_at"],
            event_count=r["event_count"] or 0,
            time_count=r["time_count"] or 0,
            latest_review=latest_rev,
        ))

    return CompletedStemsResponse(items=items, total=total or 0, page=page, page_size=page_size)


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
            blacklisted = await conn.fetch(
                "SELECT id FROM stems WHERE id = ANY($1::int[]) AND is_blacklisted = TRUE",
                body.stem_ids
            )
            if blacklisted:
                bl_ids = [r["id"] for r in blacklisted]
                raise HTTPException(
                    status_code=409,
                    detail=ConflictResponse(
                        message="Some stems are marked as unannotable / blacklisted",
                        conflict_stem_ids=bl_ids
                    ).model_dump()
                )

            conflicts = await conn.fetch(
                """
                SELECT bs.stem_id
                FROM batch_stems bs
                JOIN batches b ON b.id = bs.batch_id
                WHERE (
                    bs.status = 'pending-review'
                    OR (b.expires_at > now() AND b.status = 'active' AND bs.status NOT IN ('done', 'blacklisted', 'released'))
                )
                AND bs.stem_id = ANY($1::int[])
                FOR UPDATE
                """,
                body.stem_ids
            )
            if conflicts:
                conflict_ids = [r["stem_id"] for r in conflicts]
                raise HTTPException(
                    status_code=409,
                    detail=ConflictResponse(
                        message="Some stems were just taken or are pending review",
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
            await conn.execute(
                "INSERT INTO batch_stems (batch_id, stem_id, status) SELECT $1, unnest($2::int[]), 'not_started'",
                batch["id"], body.stem_ids
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
        progress={"done": 0, "total": len(body.stem_ids), "pending_review": 0, "re_evaluate": 0},
    )


@app.get("/batches")
async def list_batches(request: Request):
    user = await get_current_user(request)
    pool = await get_pool()
    rows = await pool.fetch(
        """
        SELECT b.*,
               COALESCE(p.total, 0) AS total,
               COALESCE(p.done, 0) AS done,
               COALESCE(p.pending_review, 0) AS pending_review,
               COALESCE(p.re_evaluate, 0) AS re_evaluate
        FROM batches b
        LEFT JOIN (
            SELECT batch_id,
                   COUNT(*) AS total,
                   COUNT(*) FILTER (WHERE status = 'done') AS done,
                   COUNT(*) FILTER (WHERE status = 'pending-review') AS pending_review,
                   COUNT(*) FILTER (WHERE status = 're-evaluate') AS re_evaluate
            FROM batch_stems
            GROUP BY batch_id
        ) p ON p.batch_id = b.id
        WHERE b.owner_id = $1
        ORDER BY b.created_at DESC
        """,
        user["id"]
    )
    result = []
    for r in rows:
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
            progress={
                "done": r["done"],
                "total": r["total"],
                "pending_review": r["pending_review"],
                "re_evaluate": r["re_evaluate"]
            },
        ))
    return result


@app.get("/batches/{batch_id}")
async def get_batch(batch_id: int, request: Request):
    user = await get_current_user(request)
    pool = await get_pool()
    batch = await pool.fetchrow(
        """
        SELECT b.*, u.username AS owner_username
        FROM batches b
        JOIN users u ON u.id = b.owner_id
        WHERE b.id = $1
        """,
        batch_id
    )
    if not batch:
        raise HTTPException(status_code=404, detail="Batch not found")
    if batch["owner_id"] != user["id"] and user.get("role") not in ("reviewer", "admin"):
        raise HTTPException(status_code=403, detail="Not your batch")

    bs_rows = await pool.fetch(
        """
        SELECT bs.id, bs.stem_id, bs.status, bs.completed_by, bs.completed_at, bs.updated_at,
               bs.reviewer_id, bs.reviewed_at,
               s.text AS stem_text, s.word_count, s.is_blacklisted, s.blacklist_reason,
               u.username AS completed_username,
               ur.username AS reviewer_username,
               (SELECT json_build_object('decision', sr.decision, 'comment', sr.comment, 'reviewer_username', ur2.username, 'created_at', sr.created_at)
                FROM stem_reviews sr
                JOIN users ur2 ON ur2.id = sr.reviewer_id
                WHERE sr.batch_stem_id = bs.id
                ORDER BY sr.created_at DESC LIMIT 1) AS latest_review
        FROM batch_stems bs
        JOIN stems s ON s.id = bs.stem_id
        LEFT JOIN users u ON u.id = bs.completed_by
        LEFT JOIN users ur ON ur.id = bs.reviewer_id
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
            "reviewer": {"id": r["reviewer_id"], "username": r["reviewer_username"]} if r["reviewer_id"] else None,
            "reviewed_at": r["reviewed_at"],
            "latest_review": r["latest_review"] if isinstance(r["latest_review"], dict) else (json.loads(r["latest_review"]) if r["latest_review"] else None),
            "updated_at": r["updated_at"],
        })

    total = len(stems)
    done = sum(1 for s in stems if s["status"] == "done")
    pending_review = sum(1 for s in stems if s["status"] == "pending-review")
    re_evaluate = sum(1 for s in stems if s["status"] == "re-evaluate")

    return BatchDetailOut(
        id=batch["id"],
        name=batch["name"],
        owner_id=batch["owner_id"],
        owner_username=batch["owner_username"],
        created_at=batch["created_at"],
        locked_at=batch["locked_at"],
        expires_at=batch["expires_at"],
        rebook_count=batch["rebook_count"],
        status=batch["status"],
        remaining_seconds=_seconds_until(batch["expires_at"]),
        progress={"done": done, "total": total, "pending_review": pending_review, "re_evaluate": re_evaluate},
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
    is_reviewer_or_admin = user.get("role") in ("reviewer", "admin")
    bs = await pool.fetchrow(
        """
        SELECT bs.*, s.text AS stem_text, s.word_count, s.is_blacklisted, s.blacklist_reason,
               b.owner_id, b.name as batch_name, b.expires_at,
               u.username as owner_username,
               ur.username as reviewer_username,
               (SELECT json_build_object('decision', sr.decision, 'comment', sr.comment, 'reviewer_username', ur2.username, 'created_at', sr.created_at)
                FROM stem_reviews sr
                JOIN users ur2 ON ur2.id = sr.reviewer_id
                WHERE sr.batch_stem_id = bs.id
                ORDER BY sr.created_at DESC LIMIT 1) AS latest_review
        FROM batch_stems bs
        JOIN stems s ON s.id = bs.stem_id
        JOIN batches b ON b.id = bs.batch_id
        JOIN users u ON u.id = b.owner_id
        LEFT JOIN users ur ON ur.id = bs.reviewer_id
        WHERE bs.id = $1
        """,
        batch_stem_id
    )
    if not bs:
        raise HTTPException(status_code=404, detail="Batch stem not found")
    if bs["owner_id"] != user["id"] and not is_reviewer_or_admin and bs["status"] != "done":
        raise HTTPException(status_code=403, detail="Not your batch stem")
    if not is_reviewer_or_admin and bs["status"] not in ("pending-review", "done", "blacklisted"):
        if _ensure_aware(bs["expires_at"]) <= _now():
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

    latest_rev = bs["latest_review"]
    if isinstance(latest_rev, str):
        try:
            latest_rev = json.loads(latest_rev)
        except Exception:
            pass

    return {
        "id": bs["id"],
        "batch_id": bs["batch_id"],
        "batch_name": bs["batch_name"],
        "stem_id": bs["stem_id"],
        "stem_text": bs["stem_text"],
        "word_count": bs["word_count"],
        "status": bs["status"],
        "owner_id": bs["owner_id"],
        "owner_username": bs["owner_username"],
        "completed_by": bs["completed_by"],
        "completed_at": bs["completed_at"],
        "reviewer": {"id": bs["reviewer_id"], "username": bs["reviewer_username"]} if bs["reviewer_id"] else None,
        "reviewed_at": bs["reviewed_at"],
        "latest_review": latest_rev,
        "is_blacklisted": bool(bs["is_blacklisted"]),
        "blacklist_reason": bs["blacklist_reason"],
        "updated_at": bs["updated_at"],
        "spans": seq_spans,
        "expires_at": bs["expires_at"],
    }


async def _get_batch_stem_for_edit(pool, batch_stem_id: int, user: dict, action_name: str = "edit"):
    is_reviewer_or_admin = user.get("role") in ("reviewer", "admin")
    bs = await pool.fetchrow(
        "SELECT bs.*, b.owner_id, b.expires_at FROM batch_stems bs JOIN batches b ON b.id = bs.batch_id WHERE bs.id = $1",
        batch_stem_id
    )
    if not bs:
        raise HTTPException(status_code=404, detail="Batch stem not found")
    if bs["owner_id"] == user["id"]:
        if bs["status"] in ("pending-review", "done", "blacklisted"):
            raise HTTPException(status_code=400, detail=f"Cannot {action_name} while stem status is '{bs['status']}'")
        if bs["status"] != "re-evaluate" and _ensure_aware(bs["expires_at"]) <= _now():
            raise HTTPException(status_code=423, detail="Lock expired")
    else:
        if not is_reviewer_or_admin:
            raise HTTPException(status_code=404, detail="Batch stem not found")
        if bs["status"] == "blacklisted":
            raise HTTPException(status_code=400, detail=f"Cannot {action_name} a blacklisted stem")
    return bs, is_reviewer_or_admin


@app.post("/batch-stems/{batch_stem_id}/spans", status_code=201)
async def create_batch_span(batch_stem_id: int, body: BatchSpanCreate, request: Request, user=Depends(get_current_user)):
    validate_csrf(request)
    pool = await get_pool()
    bs, is_reviewer_or_admin = await _get_batch_stem_for_edit(pool, batch_stem_id, user, "add spans")
    await _resequence_spans(pool, batch_stem_id=batch_stem_id)
    existing = await pool.fetch(
        "SELECT * FROM spans WHERE batch_stem_id = $1 AND label_type = $2 ORDER BY created_at, id",
        batch_stem_id, body.label_type
    )
    prefix = "E" if body.label_type == "Event" else "T"
    seq_label = f"{prefix}{len(existing) + 1}"
    row = await pool.fetchrow(
        """INSERT INTO spans (batch_stem_id, label_type, seq_label, span_text, char_start, char_end, tl_start, tl_end, source)
           VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9) RETURNING *""",
        batch_stem_id, body.label_type, seq_label,
        body.span_text, body.char_start, body.char_end,
        body.tl_start, body.tl_end, body.source
    )
    if bs["owner_id"] == user["id"] and bs["status"] in ("not_started", "re-evaluate"):
        await pool.execute(
            "UPDATE batch_stems SET status = 'in_progress', updated_at = now() WHERE id = $1", batch_stem_id
        )
    else:
        await pool.execute(
            "UPDATE batch_stems SET updated_at = now() WHERE id = $1", batch_stem_id
        )
    return _batch_span_to_out(dict(row), seq_label, batch_stem_id)


@app.get("/batch-stems/{batch_stem_id}/spans")
async def list_batch_spans(batch_stem_id: int, request: Request):
    user = await get_current_user(request)
    pool = await get_pool()
    is_reviewer_or_admin = user.get("role") in ("reviewer", "admin")
    bs = await pool.fetchrow(
        "SELECT bs.*, b.owner_id FROM batch_stems bs JOIN batches b ON b.id = bs.batch_id WHERE bs.id = $1",
        batch_stem_id
    )
    if not bs or (bs["owner_id"] != user["id"] and not is_reviewer_or_admin and bs["status"] != "done"):
        raise HTTPException(status_code=404, detail="Batch stem not found")
    await _resequence_spans(pool, batch_stem_id=batch_stem_id)
    spans = await pool.fetch(
        "SELECT * FROM spans WHERE batch_stem_id = $1 ORDER BY created_at, id", batch_stem_id
    )
    return [_batch_span_to_out(dict(s), s["seq_label"], batch_stem_id) for s in spans]


@app.patch("/batch-stems/{batch_stem_id}/spans/{span_id}")
async def update_batch_span(batch_stem_id: int, span_id: int, body: SpanUpdate, request: Request, user=Depends(get_current_user)):
    validate_csrf(request)
    pool = await get_pool()
    bs, is_reviewer_or_admin = await _get_batch_stem_for_edit(pool, batch_stem_id, user, "update spans")
    span = await pool.fetchrow("SELECT * FROM spans WHERE id = $1 AND batch_stem_id = $2", span_id, batch_stem_id)
    if not span:
        raise HTTPException(status_code=404, detail="Span not found")
    tl_start = body.tl_start if body.tl_start is not None else span["tl_start"]
    tl_end = body.tl_end if body.tl_end is not None else span["tl_end"]
    updated = await pool.fetchrow(
        "UPDATE spans SET tl_start=$1, tl_end=$2 WHERE id=$3 RETURNING *",
        tl_start, tl_end, span_id
    )
    await pool.execute("UPDATE batch_stems SET updated_at = now() WHERE id = $1", batch_stem_id)
    return _batch_span_to_out(dict(updated), updated["seq_label"], batch_stem_id)


@app.delete("/batch-stems/{batch_stem_id}/spans/{span_id}", status_code=204)
async def delete_batch_span(batch_stem_id: int, span_id: int, request: Request, user=Depends(get_current_user)):
    validate_csrf(request)
    pool = await get_pool()
    bs, is_reviewer_or_admin = await _get_batch_stem_for_edit(pool, batch_stem_id, user, "delete spans")
    span = await pool.fetchrow("SELECT * FROM spans WHERE id = $1 AND batch_stem_id = $2", span_id, batch_stem_id)
    if not span:
        raise HTTPException(status_code=404, detail="Span not found")
    await pool.execute("DELETE FROM spans WHERE id = $1", span_id)
    await _resequence_spans(pool, batch_stem_id=batch_stem_id)
    await pool.execute("DELETE FROM matrix_snapshots WHERE batch_stem_id = $1", batch_stem_id)
    await pool.execute("UPDATE batch_stems SET updated_at = now() WHERE id = $1", batch_stem_id)
    return None


@app.post("/batch-stems/{batch_stem_id}/matrix/save")
async def save_batch_matrix(batch_stem_id: int, request: Request, user=Depends(get_current_user)):
    validate_csrf(request)
    pool = await get_pool()
    bs, is_reviewer_or_admin = await _get_batch_stem_for_edit(pool, batch_stem_id, user, "modify matrix")
    spans = await pool.fetch(
        "SELECT * FROM spans WHERE batch_stem_id = $1 AND label_type = 'Event' ORDER BY created_at, id",
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

    records = [
        (batch_stem_id, si["id"], sj["id"], matrix[i][j])
        for i, si in enumerate(span_list)
        for j, sj in enumerate(span_list)
    ]
    if records:
        await pool.executemany(
            """INSERT INTO relations (batch_stem_id, span_i_id, span_j_id, relation_code)
               VALUES ($1, $2, $3, $4)
               ON CONFLICT (batch_stem_id, span_i_id, span_j_id) WHERE batch_stem_id IS NOT NULL
               DO UPDATE SET relation_code = EXCLUDED.relation_code""",
            records
        )

    await pool.execute("UPDATE batch_stems SET updated_at = now() WHERE id = $1", batch_stem_id)
    return {"ok": True, "matrix": matrix, "span_order": span_order}


@app.get("/batch-stems/{batch_stem_id}/matrix")
async def get_batch_matrix(batch_stem_id: int, request: Request):
    user = await get_current_user(request)
    pool = await get_pool()
    is_reviewer_or_admin = user.get("role") in ("reviewer", "admin")
    bs = await pool.fetchrow(
        "SELECT bs.*, b.owner_id FROM batch_stems bs JOIN batches b ON b.id = bs.batch_id WHERE bs.id = $1",
        batch_stem_id
    )
    if not bs or (bs["owner_id"] != user["id"] and not is_reviewer_or_admin and bs["status"] != "done"):
        raise HTTPException(status_code=404, detail="Batch stem not found")
    spans = await pool.fetch(
        "SELECT * FROM spans WHERE batch_stem_id = $1 AND label_type = 'Event' ORDER BY created_at, id",
        batch_stem_id
    )
    span_list = [dict(s) for s in spans]
    snapshot = await pool.fetchrow(
        "SELECT * FROM matrix_snapshots WHERE batch_stem_id=$1 ORDER BY updated_at DESC LIMIT 1",
        batch_stem_id
    )
    if snapshot and snapshot["matrix_json"]:
        try:
            saved_matrix = json.loads(snapshot["matrix_json"])
            if len(saved_matrix) == len(span_list):
                matrix = saved_matrix
            else:
                matrix = build_matrix(span_list)
        except Exception:
            matrix = build_matrix(span_list)
    else:
        matrix = build_matrix(span_list)
    span_order = [{"id": s["id"], "seq_label": s["seq_label"]} for s in span_list]
    violations = transitivity_check(matrix, [s["seq_label"] for s in span_list])
    return {"matrix": matrix, "span_order": span_order, "violations": violations}


@app.patch("/batch-stems/{batch_stem_id}/stem")
async def update_batch_stem_text(
    batch_stem_id: int,
    body: BatchStemUpdateText,
    request: Request,
    user=Depends(get_current_user),
):
    validate_csrf(request)
    new_text = body.stem_text.strip()
    if not new_text:
        raise HTTPException(status_code=400, detail="Stem text cannot be empty")

    pool = await get_pool()
    bs, is_reviewer_or_admin = await _get_batch_stem_for_edit(pool, batch_stem_id, user, "update stem text")
    new_word_count = len(new_text.split())

    async with pool.acquire() as conn:
        async with conn.transaction():
            # Update stem text and word_count in stems table
            await conn.execute(
                "UPDATE stems SET text = $1, word_count = $2 WHERE id = $3",
                new_text,
                new_word_count,
                bs["stem_id"],
            )

            # Clear existing spans, relations, and matrix snapshots for this batch stem
            await conn.execute(
                "DELETE FROM relations WHERE batch_stem_id = $1", batch_stem_id
            )
            await conn.execute(
                "DELETE FROM matrix_snapshots WHERE batch_stem_id = $1",
                batch_stem_id,
            )
            await conn.execute(
                "DELETE FROM spans WHERE batch_stem_id = $1", batch_stem_id
            )

            # Touch updated_at on batch_stem
            await conn.execute(
                "UPDATE batch_stems SET updated_at = now() WHERE id = $1",
                batch_stem_id,
            )

    return {
        "ok": True,
        "batch_stem_id": batch_stem_id,
        "stem_id": bs["stem_id"],
        "stem_text": new_text,
        "word_count": new_word_count,
    }


@app.patch("/batch-stems/{batch_stem_id}/matrix/override")
async def override_batch_matrix(batch_stem_id: int, body: MatrixOverride, request: Request, user=Depends(get_current_user)):
    validate_csrf(request)
    pool = await get_pool()
    bs, is_reviewer_or_admin = await _get_batch_stem_for_edit(pool, batch_stem_id, user, "override matrix")
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
    await pool.execute("UPDATE batch_stems SET updated_at = now() WHERE id = $1", batch_stem_id)
    return {"ok": True, "matrix": matrix}


@app.post("/batch-stems/{batch_stem_id}/submit-for-review")
async def submit_batch_stem_for_review(batch_stem_id: int, request: Request, user=Depends(get_current_user)):
    validate_csrf(request)
    pool = await get_pool()
    bs = await pool.fetchrow(
        "SELECT bs.*, b.owner_id, b.expires_at FROM batch_stems bs JOIN batches b ON b.id = bs.batch_id WHERE bs.id = $1",
        batch_stem_id
    )
    if not bs or bs["owner_id"] != user["id"]:
        raise HTTPException(status_code=404, detail="Batch stem not found")
    if bs["status"] not in ("re-evaluate", "pending-review") and _ensure_aware(bs["expires_at"]) <= _now():
        raise HTTPException(status_code=423, detail="Lock expired")

    event_count = await pool.fetchval(
        "SELECT COUNT(*) FROM spans WHERE batch_stem_id = $1 AND label_type = 'Event'", batch_stem_id
    )
    if event_count == 0:
        raise HTTPException(status_code=400, detail="Cannot submit for review without at least one Event span")

    spans = await pool.fetch(
        "SELECT * FROM spans WHERE batch_stem_id = $1 AND label_type = 'Event' ORDER BY created_at",
        batch_stem_id
    )
    span_list = [dict(s) for s in spans]
    matrix = build_matrix(span_list)
    span_order = [{"id": s["id"], "seq_label": s["seq_label"]} for s in span_list]

    existing_snapshot = await pool.fetchrow("SELECT id FROM matrix_snapshots WHERE batch_stem_id=$1", batch_stem_id)
    if existing_snapshot:
        await pool.execute(
            "UPDATE matrix_snapshots SET matrix_json=$1, span_order=$2, updated_at=now() WHERE batch_stem_id=$3",
            json.dumps(matrix), json.dumps(span_order), batch_stem_id
        )
    else:
        await pool.execute(
            "INSERT INTO matrix_snapshots (batch_stem_id, matrix_json, span_order) VALUES ($1,$2,$3)",
            batch_stem_id, json.dumps(matrix), json.dumps(span_order)
        )

    records = [
        (batch_stem_id, si["id"], sj["id"], matrix[i][j])
        for i, si in enumerate(span_list)
        for j, sj in enumerate(span_list)
    ]
    if records:
        await pool.executemany(
            """INSERT INTO relations (batch_stem_id, span_i_id, span_j_id, relation_code)
               VALUES ($1, $2, $3, $4)
               ON CONFLICT (batch_stem_id, span_i_id, span_j_id) WHERE batch_stem_id IS NOT NULL
               DO UPDATE SET relation_code = EXCLUDED.relation_code""",
            records
        )

    await pool.execute(
        "UPDATE batch_stems SET status = 'pending-review', updated_at = now() WHERE id = $1",
        batch_stem_id
    )
    return {"ok": True, "status": "pending-review"}


@app.post("/batch-stems/{batch_stem_id}/mark-done")
async def mark_batch_stem_done(batch_stem_id: int, request: Request, user=Depends(get_current_user)):
    return await submit_batch_stem_for_review(batch_stem_id, request, user)


# ---------------------------------------------------------------------------
# REVIEWS & REVIEWER ENDPOINTS
# ---------------------------------------------------------------------------

@app.get("/reviews/pending")
async def list_pending_reviews(request: Request, user=Depends(require_reviewer)):
    pool = await get_pool()
    rows = await pool.fetch(
        """
        SELECT bs.id AS batch_stem_id, bs.batch_id, b.name AS batch_name,
               bs.stem_id, s.text AS stem_text, s.word_count,
               b.owner_id AS annotator_id, u.username AS annotator_username,
               bs.status, bs.updated_at,
               (SELECT COUNT(*) FROM spans sp WHERE sp.batch_stem_id = bs.id AND sp.label_type = 'Event') AS event_count,
               (SELECT comment FROM stem_reviews sr WHERE sr.batch_stem_id = bs.id ORDER BY sr.created_at DESC LIMIT 1) AS latest_comment
        FROM batch_stems bs
        JOIN batches b ON b.id = bs.batch_id
        JOIN stems s ON s.id = bs.stem_id
        JOIN users u ON u.id = b.owner_id
        WHERE bs.status = 'pending-review'
        ORDER BY bs.updated_at ASC
        """
    )
    result = []
    for r in rows:
        result.append(PendingReviewItemOut(
            batch_stem_id=r["batch_stem_id"],
            batch_id=r["batch_id"],
            batch_name=r["batch_name"],
            stem_id=r["stem_id"],
            stem_text=r["stem_text"],
            word_count=r["word_count"],
            annotator_id=r["annotator_id"],
            annotator_username=r["annotator_username"],
            status=r["status"],
            submitted_at=r["updated_at"],
            updated_at=r["updated_at"],
            event_count=r["event_count"],
            latest_comment=r["latest_comment"],
        ))
    return result


@app.post("/batch-stems/{batch_stem_id}/review")
async def review_batch_stem(
    batch_stem_id: int,
    body: ReviewDecisionRequest,
    request: Request,
    reviewer=Depends(require_reviewer),
):
    validate_csrf(request)
    pool = await get_pool()
    bs = await pool.fetchrow(
        """
        SELECT bs.*, b.owner_id
        FROM batch_stems bs
        JOIN batches b ON b.id = bs.batch_id
        WHERE bs.id = $1
        """,
        batch_stem_id
    )
    if not bs:
        raise HTTPException(status_code=404, detail="Batch stem not found")

    if bs["owner_id"] == reviewer["id"] and reviewer.get("role") != "admin":
        raise HTTPException(
            status_code=400,
            detail="Reviewers cannot review their own annotations. Another reviewer or admin must evaluate this submission."
        )

    decision = body.decision.lower()
    if decision not in ("accept", "re-evaluate", "blacklist", "release_to_pool"):
        raise HTTPException(status_code=400, detail="Decision must be 'accept', 're-evaluate', 'blacklist', or 'release_to_pool'")

    if decision in ("re-evaluate", "blacklist", "release_to_pool") and (not body.comment or not body.comment.strip()):
        raise HTTPException(status_code=400, detail=f"Comment is required when decision is '{decision}'")

    comment = body.comment.strip() if body.comment else None

    async with pool.acquire() as conn:
        async with conn.transaction():
            if decision == "accept":
                await conn.execute(
                    """
                    UPDATE batch_stems
                    SET status = 'done', completed_by = $1, completed_at = now(),
                        reviewer_id = $2, reviewed_at = now(), updated_at = now()
                    WHERE id = $3
                    """,
                    bs["owner_id"], reviewer["id"], batch_stem_id
                )
            elif decision == "re-evaluate":
                await conn.execute(
                    """
                    UPDATE batch_stems
                    SET status = 're-evaluate', reviewer_id = $1, reviewed_at = now(), updated_at = now()
                    WHERE id = $2
                    """,
                    reviewer["id"], batch_stem_id
                )
            elif decision == "blacklist":
                await conn.execute(
                    """
                    UPDATE batch_stems
                    SET status = 'blacklisted', reviewer_id = $1, reviewed_at = now(), updated_at = now()
                    WHERE id = $2
                    """,
                    reviewer["id"], batch_stem_id
                )
                await conn.execute(
                    """
                    UPDATE stems
                    SET is_blacklisted = TRUE, blacklist_reason = $1, blacklisted_by = $2, blacklisted_at = now()
                    WHERE id = $3
                    """,
                    comment, reviewer["id"], bs["stem_id"]
                )
            elif decision == "release_to_pool":
                # Delete all previous failed/unacceptable annotations so the new annotator starts fresh
                await conn.execute("DELETE FROM relations WHERE batch_stem_id = $1", batch_stem_id)
                await conn.execute("DELETE FROM matrix_snapshots WHERE batch_stem_id = $1", batch_stem_id)
                await conn.execute("DELETE FROM spans WHERE batch_stem_id = $1", batch_stem_id)
                # Release this batch_stem so it is freed from the current batch and public pool reclaims it
                await conn.execute(
                    """
                    UPDATE batch_stems
                    SET status = 'released', completed_by = NULL, completed_at = NULL,
                        reviewer_id = $1, reviewed_at = now(), updated_at = now()
                    WHERE id = $2
                    """,
                    reviewer["id"], batch_stem_id
                )

            await conn.execute(
                """
                INSERT INTO stem_reviews (batch_stem_id, stem_id, reviewer_id, decision, comment)
                VALUES ($1, $2, $3, $4, $5)
                """,
                batch_stem_id, bs["stem_id"], reviewer["id"], decision, comment
            )

    return {"ok": True, "decision": decision, "status": "done" if decision == "accept" else "released" if decision == "release_to_pool" else decision}


@app.get("/batch-stems/{batch_stem_id}/reviews")
async def get_stem_reviews(batch_stem_id: int, request: Request):
    user = await get_current_user(request)
    pool = await get_pool()
    bs = await pool.fetchrow(
        "SELECT bs.*, b.owner_id FROM batch_stems bs JOIN batches b ON b.id = bs.batch_id WHERE bs.id = $1",
        batch_stem_id
    )
    if not bs:
        raise HTTPException(status_code=404, detail="Batch stem not found")
    if bs["owner_id"] != user["id"] and user.get("role") not in ("reviewer", "admin"):
        raise HTTPException(status_code=403, detail="Forbidden")

    rows = await pool.fetch(
        """
        SELECT sr.*, u.username AS reviewer_username
        FROM stem_reviews sr
        JOIN users u ON u.id = sr.reviewer_id
        WHERE sr.batch_stem_id = $1
        ORDER BY sr.created_at DESC
        """,
        batch_stem_id
    )
    return [
        StemReviewOut(
            id=r["id"],
            batch_stem_id=r["batch_stem_id"],
            stem_id=r["stem_id"],
            reviewer_id=r["reviewer_id"],
            reviewer_username=r["reviewer_username"],
            decision=r["decision"],
            comment=r["comment"],
            created_at=r["created_at"],
        ).model_dump()
        for r in rows
    ]


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
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["batch_id", "batch_name", "stem_id", "stem_text", "span_i", "span_j",
                     "relation_code", "relation_name", "is_override"])
    relations = await pool.fetch(
        """SELECT r.*, si.seq_label as label_i, sj.seq_label as label_j, s.text as stem_text, bs.id as batch_stem_id
           FROM relations r
           JOIN batch_stems bs ON bs.id = r.batch_stem_id
           JOIN stems s ON s.id = bs.stem_id
           JOIN spans si ON r.span_i_id = si.id
           JOIN spans sj ON r.span_j_id = sj.id
           WHERE bs.batch_id = $1 AND bs.status = 'done'""",
        batch_id
    )
    for r in relations:
        writer.writerow([
            batch_id, batch["name"], r["batch_stem_id"], r["stem_text"][:80],
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
    bs_ids = [bs["id"] for bs in bs_list]
    spans_by_bs: dict[int, list] = {bs_id: [] for bs_id in bs_ids}
    snapshots_by_bs: dict[int, dict] = {}
    if bs_ids:
        all_spans = await pool.fetch(
            "SELECT * FROM spans WHERE batch_stem_id = ANY($1::int[]) ORDER BY created_at",
            bs_ids
        )
        for sp in all_spans:
            spans_by_bs[sp["batch_stem_id"]].append({k: _serialize(v) for k, v in dict(sp).items()})

        all_snapshots = await pool.fetch(
            """SELECT DISTINCT ON (batch_stem_id) * FROM matrix_snapshots
               WHERE batch_stem_id = ANY($1::int[])
               ORDER BY batch_stem_id, updated_at DESC""",
            bs_ids
        )
        for sn in all_snapshots:
            snapshots_by_bs[sn["batch_stem_id"]] = sn

    for bs in bs_list:
        snapshot = snapshots_by_bs.get(bs["id"])
        batch_data["stems"].append({
            "batch_stem_id": bs["id"],
            "stem_id": bs["stem_id"],
            "stem_text": bs["stem_text"],
            "spans": spans_by_bs.get(bs["id"], []),
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
    is_reviewer_or_admin = user.get("role") in ("reviewer", "admin")
    batch = await pool.fetchrow("SELECT * FROM batches WHERE id=$1", bs["batch_id"])
    if not batch or (batch["owner_id"] != user["id"] and not is_reviewer_or_admin and bs["status"] != "done"):
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
            "SELECT bs.*, s.text AS stem_text, b.owner_id, b.expires_at FROM batch_stems bs JOIN stems s ON s.id = bs.stem_id JOIN batches b ON b.id = bs.batch_id WHERE bs.id=$1",
            batch_stem_id
        )
        if not bs:
            raise HTTPException(status_code=404, detail="Batch stem not found")
        is_reviewer_or_admin = user.get("role") in ("reviewer", "admin")
        if not is_reviewer_or_admin:
            if bs["owner_id"] != user["id"]:
                raise HTTPException(status_code=404, detail="Batch stem not found")
            if bs["status"] in ("pending-review", "done", "blacklisted"):
                raise HTTPException(status_code=400, detail=f"Cannot update timeline while stem status is '{bs['status']}'")
            if _ensure_aware(bs["expires_at"]) <= _now():
                raise HTTPException(status_code=423, detail="Lock expired")
        else:
            if bs["status"] == "blacklisted":
                raise HTTPException(status_code=400, detail="Cannot edit a blacklisted stem")
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

    if session_id < 0:
        await pool.execute("UPDATE batch_stems SET updated_at = now() WHERE id = $1", -session_id)

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
    if not bs:
        raise HTTPException(status_code=404, detail="Batch stem not found")
    is_reviewer_or_admin = user.get("role") in ("reviewer", "admin")
    if not is_reviewer_or_admin:
        if bs["owner_id"] != user["id"]:
            raise HTTPException(status_code=404, detail="Batch stem not found")
        if bs["status"] in ("pending-review", "done", "blacklisted"):
            raise HTTPException(status_code=400, detail=f"Cannot run LLM while stem status is '{bs['status']}'")
        if _ensure_aware(bs["expires_at"]) <= _now():
            raise HTTPException(status_code=423, detail="Lock expired")
    else:
        if bs["status"] == "blacklisted":
            raise HTTPException(status_code=400, detail="Cannot edit a blacklisted stem")
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

            await _resequence_spans(conn, batch_stem_id=batch_stem_id)
            existing = await conn.fetch(
                "SELECT * FROM spans WHERE batch_stem_id = $1 AND label_type = 'Event' ORDER BY created_at, id", batch_stem_id
            )
            event_count = len(existing)
            span_insert_data = []
            for event in accepted_events:
                event_count += 1
                seq_label = f"E{event_count}"
                span_insert_data.append((
                    batch_stem_id, "Event", seq_label,
                    event["span_text"], event["char_start"], event["char_end"],
                    10.0, 30.0, "llm"
                ))

            if span_insert_data:
                rows = await conn.fetch(
                    """INSERT INTO spans (batch_stem_id, label_type, seq_label, span_text, char_start, char_end, tl_start, tl_end, source)
                       SELECT x.bs_id, x.lt, x.sl, x.st, x.cs, x.ce, x.ts, x.te, x.src
                       FROM unnest(
                           $1::int[], $2::text[], $3::text[], $4::text[], $5::int[], $6::int[], $7::float8[], $8::float8[], $9::text[]
                       ) AS x(bs_id, lt, sl, st, cs, ce, ts, te, src)
                       RETURNING *""",
                    [d[0] for d in span_insert_data],
                    [d[1] for d in span_insert_data],
                    [d[2] for d in span_insert_data],
                    [d[3] for d in span_insert_data],
                    [d[4] for d in span_insert_data],
                    [d[5] for d in span_insert_data],
                    [d[6] for d in span_insert_data],
                    [d[7] for d in span_insert_data],
                    [d[8] for d in span_insert_data],
                )
                created_spans = [dict(r) for r in rows]
            else:
                created_spans = []

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
            to_update_positions = []

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

                to_update_positions.append((start, end, span_id))
                timeline_updated.append({
                    "span_id": span_id,
                    "seq_label": r["seq_label"],
                    "span_text": r["span_text"],
                    "tl_start": start,
                    "tl_end": end,
                })

            if to_update_positions:
                await conn.executemany(
                    "UPDATE spans SET tl_start=$1, tl_end=$2, source='llm' WHERE id=$3",
                    to_update_positions
                )

            if bs["owner_id"] == user["id"] and bs["status"] in ("not_started", "re-evaluate"):
                await conn.execute(
                    "UPDATE batch_stems SET status = 'in_progress', updated_at = now() WHERE id = $1", batch_stem_id
                )
            else:
                await conn.execute(
                    "UPDATE batch_stems SET updated_at = now() WHERE id = $1", batch_stem_id
                )

            return LLMLabelAndTimelineResponse(
                events=accepted_events,
                skipped_events=skipped_events,
                timeline_updated=timeline_updated,
                timeline_skipped=timeline_skipped
            ).model_dump()
