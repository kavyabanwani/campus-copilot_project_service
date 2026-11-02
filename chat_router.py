import json
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from auth.dependencies import get_current_student
from db.database import get_db
from db.models import ChatMessage, ChatSession, Student
from db.schemas import ChatMessageOut, ChatSessionDetail, ChatSessionOut

router = APIRouter(prefix="/chat", tags=["chat_history"])


def _deserialize_json(val: str | None, default=None):
    if not val:
        return default
    try:
        return json.loads(val)
    except Exception:
        return default


@router.get("/sessions", response_model=list[ChatSessionOut])
def get_chat_sessions(
    current_student: Student = Depends(get_current_student),
    db: Session = Depends(get_db),
):
    """Retrieve all chat sessions belonging to the signed-in student, newest first."""
    sessions = (
        db.query(ChatSession)
        .filter(ChatSession.student_id == current_student.student_id)
        .order_by(ChatSession.updated_at.desc(), ChatSession.id.desc())
        .all()
    )
    return sessions


@router.get("/sessions/{session_id}", response_model=ChatSessionDetail)
def get_chat_session_detail(
    session_id: int,
    current_student: Student = Depends(get_current_student),
    db: Session = Depends(get_db),
):
    """Retrieve one chat session with its full message history. 404 if not found or belongs to another student."""
    session = (
        db.query(ChatSession)
        .filter(ChatSession.id == session_id, ChatSession.student_id == current_student.student_id)
        .first()
    )
    if not session:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Chat session not found")

    messages = (
        db.query(ChatMessage)
        .filter(ChatMessage.session_id == session.id)
        .order_by(ChatMessage.created_at.asc(), ChatMessage.id.asc())
        .all()
    )

    out_messages = [
        ChatMessageOut(
            id=m.id,
            session_id=m.session_id,
            role=m.role,
            content=m.content,
            type=m.type or "text",
            data=_deserialize_json(m.data, None),
            sources=_deserialize_json(m.sources, []),
            activity_steps=_deserialize_json(m.activity_steps, []),
            created_at=m.created_at,
        )
        for m in messages
    ]

    return ChatSessionDetail(
        id=session.id,
        title=session.title,
        created_at=session.created_at,
        updated_at=session.updated_at,
        messages=out_messages,
    )


@router.delete("/sessions/{session_id}")
def delete_chat_session(
    session_id: int,
    current_student: Student = Depends(get_current_student),
    db: Session = Depends(get_db),
):
    """Delete a chat session and its messages. 404 if not found or belongs to another student."""
    session = (
        db.query(ChatSession)
        .filter(ChatSession.id == session_id, ChatSession.student_id == current_student.student_id)
        .first()
    )
    if not session:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Chat session not found")

    db.query(ChatMessage).filter(ChatMessage.session_id == session.id).delete()
    db.delete(session)
    db.commit()

    return {"status": "ok", "message": f"Session {session_id} deleted successfully."}

