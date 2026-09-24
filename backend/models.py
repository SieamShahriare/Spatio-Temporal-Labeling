"""
Pydantic schemas for request/response models.
"""
from pydantic import BaseModel, Field
from typing import Optional, List, Dict, Any
from datetime import datetime


# ---------------------------------------------------------------------------
# Existing models (kept for backward compatibility)
# ---------------------------------------------------------------------------

class SessionCreate(BaseModel):
    username: str
    stem_text: str


class SessionStatusUpdate(BaseModel):
    status: str  # 'in_progress' | 'done'


class SpanCreate(BaseModel):
    label_type: str       # 'Event' | 'Time'
    span_text: str
    char_start: int
    char_end: int
    tl_start: float = 10.0
    tl_end: float = 30.0
    source: str = 'manual'  # 'manual' | 'llm'


class SpanUpdate(BaseModel):
    tl_start: Optional[float] = None
    tl_end: Optional[float] = None


class MatrixOverride(BaseModel):
    i: int
    j: int
    relation_code: int


class SkippedEvent(BaseModel):
    text: str
    reason: str


class ExtractEventsRequest(BaseModel):
    text: str


class ExtractEventsResponse(BaseModel):
    events: List[Dict[str, Any]]
    skipped: List[SkippedEvent]


class ExtractTimelineRequest(BaseModel):
    session_id: int


class ExtractTimelineResponse(BaseModel):
    updated: List[Dict[str, Any]]
    skipped: List[Dict[str, Any]]


class LLMLabelAndTimelineRequest(BaseModel):
    batch_stem_id: int
    text: str


class LLMLabelAndTimelineResponse(BaseModel):
    events: List[Dict[str, Any]]
    skipped_events: List[Dict[str, Any]]
    timeline_updated: List[Dict[str, Any]]
    timeline_skipped: List[Dict[str, Any]]


class SpanOut(BaseModel):
    id: int
    session_id: int
    label_type: str
    seq_label: str
    span_text: str
    char_start: int
    char_end: int
    tl_start: float
    tl_end: float
    source: str = 'manual'
    created_at: datetime


class SessionOut(BaseModel):
    id: int
    username: str
    stem_text: str
    status: str
    completed_at: Optional[datetime]
    created_at: datetime
    spans: List[SpanOut] = []


# ---------------------------------------------------------------------------
# Auth models
# ---------------------------------------------------------------------------

class SignupRequest(BaseModel):
    email: str
    password: str
    username: str
    role: Optional[str] = "annotator"


class LoginRequest(BaseModel):
    email: str
    password: str


class UserOut(BaseModel):
    id: int
    email: str
    username: str
    role: str = "annotator"
    created_at: datetime


class UserRoleUpdate(BaseModel):
    role: str  # 'annotator' | 'reviewer' | 'admin'


class AuthMeResponse(BaseModel):
    user: UserOut
    csrf_token: str


# ---------------------------------------------------------------------------
# Stems models
# ---------------------------------------------------------------------------

class StemOut(BaseModel):
    id: int
    text: str
    word_count: int
    state: str  # 'available' | 'booked' | 'pending-review' | 're-evaluate' | 'completed' | 'blacklisted'
    booked_by: Optional[Dict[str, Any]] = None
    locked_until: Optional[datetime] = None
    completed_by: Optional[Dict[str, Any]] = None
    completed_at: Optional[datetime] = None
    completed_batch_stem_id: Optional[int] = None
    completed_batch_id: Optional[int] = None
    is_blacklisted: bool = False
    blacklist_reason: Optional[str] = None
    blacklisted_by: Optional[Dict[str, Any]] = None
    blacklisted_at: Optional[datetime] = None
    latest_review: Optional[Dict[str, Any]] = None


class StemsListResponse(BaseModel):
    items: List[StemOut]
    total: int
    page: int
    page_size: int


class CompletedStemItem(BaseModel):
    batch_stem_id: int
    batch_id: int
    batch_name: str
    stem_id: int
    stem_text: str
    word_count: int
    status: str = "done"
    completed_by: Optional[Dict[str, Any]] = None
    completed_at: Optional[datetime] = None
    reviewer: Optional[Dict[str, Any]] = None
    reviewed_at: Optional[datetime] = None
    event_count: int = 0
    time_count: int = 0
    latest_review: Optional[Dict[str, Any]] = None


class CompletedStemsResponse(BaseModel):
    items: List[CompletedStemItem]
    total: int
    page: int
    page_size: int


class StemsImportResponse(BaseModel):
    created: int
    skipped: int


# ---------------------------------------------------------------------------
# Batch models
# ---------------------------------------------------------------------------

class BatchCreate(BaseModel):
    name: str
    stem_ids: List[int]


class BatchOut(BaseModel):
    id: int
    name: str
    owner_id: int
    owner_username: str
    created_at: datetime
    locked_at: datetime
    expires_at: datetime
    rebook_count: int
    status: str
    remaining_seconds: int
    progress: Dict[str, int]  # {"done": N, "total": M, "pending_review": P, "re_evaluate": R}


class BatchDetailOut(BatchOut):
    stems: List[Dict[str, Any]]


class BatchStemOut(BaseModel):
    id: int
    stem_id: int
    stem_text: str
    word_count: int
    status: str  # 'not_started' | 'in_progress' | 'pending-review' | 'done' | 're-evaluate' | 'blacklisted'
    completed_by: Optional[Dict[str, Any]] = None
    completed_at: Optional[datetime] = None
    reviewer: Optional[Dict[str, Any]] = None
    reviewed_at: Optional[datetime] = None
    latest_review: Optional[Dict[str, Any]] = None
    updated_at: Optional[datetime] = None


# ---------------------------------------------------------------------------
# Batch annotation (spans/relations scoped to batch_stem)
# ---------------------------------------------------------------------------

class BatchSpanCreate(BaseModel):
    batch_stem_id: Optional[int] = None
    label_type: str
    span_text: str
    char_start: int
    char_end: int
    tl_start: float = 10.0
    tl_end: float = 30.0
    source: str = 'manual'


class BatchSpanOut(BaseModel):
    id: int
    batch_stem_id: int
    label_type: str
    seq_label: str
    span_text: str
    char_start: int
    char_end: int
    tl_start: float
    tl_end: float
    source: str
    created_at: datetime


class ConflictResponse(BaseModel):
    message: str
    conflict_stem_ids: List[int]


# ---------------------------------------------------------------------------
# Review models
# ---------------------------------------------------------------------------

class ReviewDecisionRequest(BaseModel):
    decision: str  # 'accept' | 're-evaluate' | 'blacklist' | 'release_to_pool'
    comment: Optional[str] = None


class StemReviewOut(BaseModel):
    id: int
    batch_stem_id: int
    stem_id: int
    reviewer_id: int
    reviewer_username: str
    decision: str
    comment: Optional[str] = None
    created_at: datetime


class PendingReviewItemOut(BaseModel):
    batch_stem_id: int
    batch_id: int
    batch_name: str
    stem_id: int
    stem_text: str
    word_count: int
    annotator_id: int
    annotator_username: str
    status: str
    submitted_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    event_count: int = 0
    latest_comment: Optional[str] = None


class BatchStemUpdateText(BaseModel):
    stem_text: str

