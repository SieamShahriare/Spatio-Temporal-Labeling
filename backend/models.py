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


class LoginRequest(BaseModel):
    email: str
    password: str


class UserOut(BaseModel):
    id: int
    email: str
    username: str
    created_at: datetime


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
    state: str  # 'available' | 'booked' | 'completed'
    booked_by: Optional[Dict[str, Any]] = None
    locked_until: Optional[datetime] = None
    completed_by: Optional[Dict[str, Any]] = None
    completed_at: Optional[datetime] = None


class StemsListResponse(BaseModel):
    items: List[StemOut]
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
    progress: Dict[str, int]  # {"done": N, "total": M}


class BatchDetailOut(BatchOut):
    stems: List[Dict[str, Any]]


class BatchStemOut(BaseModel):
    id: int
    stem_id: int
    stem_text: str
    word_count: int
    status: str
    completed_by: Optional[Dict[str, Any]] = None
    completed_at: Optional[datetime] = None
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
# Group annotation workflow (inter-annotator agreement)
# ---------------------------------------------------------------------------

class GroupTaskCreate(BaseModel):
    stem_id: int
    event_user_id: int
    timeline_user_ids: List[int] = Field(..., min_length=2)


class GroupMemberOut(BaseModel):
    id: int
    user_id: int
    username: str
    role: str
    status: str
    annotator_index: Optional[int] = None
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    reassigned_from: Optional[int] = None
    reassigned_at: Optional[datetime] = None


class GroupTaskOut(BaseModel):
    id: int
    stem_id: int
    stem_text: str
    status: str
    outcome: Optional[str] = None
    decision: Optional[str] = None
    scores_stale: bool = False
    created_by: int
    created_at: datetime
    updated_at: datetime
    acceptance_threshold: float
    members: List[GroupMemberOut] = []


class GroupTaskDetailOut(GroupTaskOut):
    krippendorff_alpha: Optional[float] = None
    cohens_kappa_avg: Optional[float] = None
    fleiss_kappa: Optional[float] = None
    agreement_details: Optional[Dict[str, Any]] = None
    scores_hidden: bool = False


class GroupEventSpanCreate(BaseModel):
    label_type: str = "Event"
    span_text: str
    char_start: int
    char_end: int


class GroupEventSpanOut(BaseModel):
    id: int
    group_task_id: int
    label_type: str
    seq_label: str
    span_text: str
    char_start: int
    char_end: int
    created_at: datetime


class TimelinePositionIn(BaseModel):
    span_id: int
    tl_start: float
    tl_end: float
    source: str = 'manual'  # 'manual' | 'llm' — see context/group_workflow_redesign.md §8


class TimelineUpsertRequest(BaseModel):
    positions: List[TimelinePositionIn]


class TimelinePositionOut(BaseModel):
    span_id: int
    seq_label: str
    span_text: str
    tl_start: float
    tl_end: float


class GroupAgreementOut(BaseModel):
    task_id: int
    status: str
    krippendorff_alpha: Optional[float] = None
    cohens_kappa_avg: Optional[float] = None
    fleiss_kappa: Optional[float] = None
    acceptance_threshold: float
    agreement_details: Optional[Dict[str, Any]] = None
    scores_stale: bool = False


class GroupTaskDecision(BaseModel):
    decision: Optional[str] = None  # 'accepted' | 'accepted_flagged' | 'adjudication' | 'rejected' | None to reopen


class UserBriefOut(BaseModel):
    id: int
    username: str
    email: str


# ---------------------------------------------------------------------------
# Distribution (bulk group-task creation)
# See context/group_workflow_redesign.md §3, §9.6, §10.
# ---------------------------------------------------------------------------

class DistributeRequest(BaseModel):
    stem_ids: List[int] = Field(..., min_length=1)
    pool_user_ids: Optional[List[int]] = None  # defaults to all registered users


class DistributeSkip(BaseModel):
    stem_id: int
    reason: str


class DistributeResponse(BaseModel):
    distribution_run_id: int
    created_task_ids: List[int]
    skipped: List[DistributeSkip]
    pool_size: int


class ReassignRequest(BaseModel):
    user_id: int


class MyTaskOut(BaseModel):
    task_id: int
    member_id: int
    stem_id: int
    stem_text: str
    role: str
    annotator_index: Optional[int] = None
    member_status: str
    task_status: str
    blocked: bool
    blocked_reason: Optional[str] = None
