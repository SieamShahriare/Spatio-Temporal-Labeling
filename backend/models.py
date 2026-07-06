"""
Pydantic schemas for request/response models.
"""

from pydantic import BaseModel
from typing import Optional, List, Dict, Any
from datetime import datetime


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


class ExtractEventsRequest(BaseModel):
    text: str


class SkippedEvent(BaseModel):
    text: str
    reason: str


class ExtractEventsResponse(BaseModel):
    events: List[Dict[str, Any]]
    skipped: List[SkippedEvent]


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
