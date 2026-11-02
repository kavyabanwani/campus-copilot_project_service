from pydantic import BaseModel, EmailStr
from typing import Optional, Any
from datetime import date, datetime


# ---------- Student & Auth Schemas ----------
class StudentCreate(BaseModel):
    roll_number: str
    full_name: str
    email: EmailStr
    department: str
    semester: int
    password: str


class StudentLogin(BaseModel):
    email: str
    password: str


class PasswordChangeRequest(BaseModel):
    current_password: str
    new_password: str


class StudentOut(BaseModel):
    student_id: int
    roll_number: str
    full_name: str
    email: EmailStr
    department: str
    semester: int
    role: str = "student"
    created_at: datetime

    class Config:
        from_attributes = True


class Token(BaseModel):
    access_token: str
    token_type: str = "bearer"


class AuthResponse(Token):
    student: StudentOut


class TokenData(BaseModel):
    student_id: Optional[int] = None


# ---------- Attendance Schemas ----------
class AttendanceMark(BaseModel):
    status: str


class AttendanceStatusItem(BaseModel):
    session_id: int
    subject_id: int
    subject_code: str
    subject_name: str
    class_date: date
    start_time: str
    end_time: str
    status: str
    can_mark: bool


class AttendanceStatusResponse(BaseModel):
    items: list[AttendanceStatusItem]


# ---------- Chat & Conversation Schemas ----------
class ChatTurn(BaseModel):
    """One earlier turn of the conversation, for backward compatibility."""
    role: str  # "user" or "assistant"
    content: str


class SourceRef(BaseModel):
    title: str
    page: Optional[int] = None
    snippet: Optional[str] = None


class ChatRequest(BaseModel):
    message: str
    history: list[ChatTurn] = []
    session_id: Optional[int] = None


class ChatResponse(BaseModel):
    content: str
    type: str = "text"
    data: Optional[dict] = None
    activitySteps: list[str] = []
    sources: list[SourceRef] = []
    session_id: Optional[int] = None
    cards: list[dict] = []


class ChatSessionOut(BaseModel):
    id: int
    title: str
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class ChatMessageOut(BaseModel):
    id: int
    session_id: int
    role: str
    content: str
    type: str = "text"
    data: Optional[Any] = None
    sources: Optional[list[Any]] = None
    activity_steps: Optional[list[str]] = None
    created_at: Optional[datetime] = None


class ChatSessionDetail(BaseModel):
    id: int
    title: str
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    messages: list[ChatMessageOut] = []


# ---------- Document Schemas ----------
class DocumentItem(BaseModel):
    id: int
    title: str
    category: str
    department: Optional[str] = None
    owner_student_id: Optional[int] = None
    is_private: bool = False
    chunk_count: int = 0
    created_at: Optional[datetime] = None


class DocumentUploadResponse(BaseModel):
    document_id: int
    title: str
    category: str
    department: Optional[str] = None
    chunk_count: int
    status: str = "indexed"


# ---------- Campus Info & Events ----------
class CampusInfoItem(BaseModel):
    id: int
    category: str
    key: str
    value: str
    department: Optional[str] = None


class CampusEventItem(BaseModel):
    id: int
    title: str
    description: Optional[str] = None
    location: Optional[str] = None
    starts_at: datetime
    ends_at: Optional[datetime] = None
    category: str
    is_demo: bool = True


# ---------- Proactive Insights & Catalogue ----------
class InsightItem(BaseModel):
    icon: str
    tone: str
    text: str


class InsightsResponse(BaseModel):
    items: list[InsightItem] = []


class CatalogueEntry(BaseModel):
    department: str
    semester: int


class CatalogueResponse(BaseModel):
    items: list[CatalogueEntry]