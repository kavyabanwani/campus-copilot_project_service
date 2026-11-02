import json
from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from ai_agent import run_agent
from auth.dependencies import get_current_student
from db.database import get_db
from db.models import ChatMessage, ChatSession, Student
from db.schemas import ChatRequest, ChatResponse, ChatTurn
from llm_client import LLMUnavailable
from slowapi import Limiter
from slowapi.util import get_remote_address

limiter = Limiter(key_func=get_remote_address)
router = APIRouter(tags=["ai"])


def _handle_chat_turn(
    request: Request,
    payload: ChatRequest,
    current_student: Student,
    db: Session,
) -> ChatResponse:
    if not payload.message.strip():
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Please type a question.",
        )

    # 1. Resolve or create ChatSession
    session: ChatSession | None = None
    history_turns: list[ChatTurn] = []

    if payload.session_id:
        session = (
            db.query(ChatSession)
            .filter(
                ChatSession.id == payload.session_id,
                ChatSession.student_id == current_student.student_id,
            )
            .first()
        )
        if not session:
            # Check if it belongs to someone else -> 404
            other_session = db.query(ChatSession).filter(ChatSession.id == payload.session_id).first()
            if other_session:
                raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Session not found")
            # If invalid ID that doesn't exist, create a fresh session
            session = None

    if session is None:
        title = payload.message.strip().replace("\n", " ")
        if len(title) > 60:
            title = title[:57] + "..."
        session = ChatSession(
            student_id=current_student.student_id,
            title=title or "New Conversation",
        )
        db.add(session)
        db.commit()
        db.refresh(session)
        # Use client history only on brand new session without existing db records if provided
        history_turns = payload.history or []
    else:
        # Load the last 10 messages from DB
        db_messages = (
            db.query(ChatMessage)
            .filter(ChatMessage.session_id == session.id)
            .order_by(ChatMessage.created_at.desc(), ChatMessage.id.desc())
            .limit(10)
            .all()
        )
        db_messages.reverse()
        history_turns = [ChatTurn(role=m.role, content=m.content) for m in db_messages]

    # 2. Record User message in DB
    user_msg = ChatMessage(
        session_id=session.id,
        role="user",
        content=payload.message.strip(),
        type="text",
    )
    db.add(user_msg)
    db.commit()

    # 3. Execute AI Agent Loop
    try:
        answer = run_agent(payload.message, current_student, db, history=history_turns)
    except LLMUnavailable as error:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(error))
    except SQLAlchemyError as error:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Campus records are unavailable right now. Please try again in a moment.",
        )

    # 4. Record Assistant response in DB
    asst_msg = ChatMessage(
        session_id=session.id,
        role="assistant",
        content=answer.content,
        type=answer.card_type or "text",
        data=json.dumps(answer.card_data) if answer.card_data else None,
        sources=json.dumps(answer.sources) if answer.sources else None,
        activity_steps=json.dumps(answer.activity_steps) if answer.activity_steps else None,
    )
    db.add(asst_msg)
    session.updated_at = datetime.now()
    db.commit()

    return ChatResponse(
        content=answer.content,
        type=answer.card_type or "text",
        data=answer.card_data,
        activitySteps=answer.activity_steps,
        sources=answer.sources,
        session_id=session.id,
        cards=answer.cards,
    )


@router.post("/ai/chat", response_model=ChatResponse)
@limiter.limit("30/minute")
def ai_chat(
    request: Request,
    payload: ChatRequest,
    current_student: Student = Depends(get_current_student),
    db: Session = Depends(get_db),
):
    """One turn of conversation with Campus Copilot, grounded in this student's campus data."""
    return _handle_chat_turn(request, payload, current_student, db)


@router.post("/api/chat", response_model=ChatResponse)
@limiter.limit("30/minute")
def api_chat_alias(
    request: Request,
    payload: ChatRequest,
    current_student: Student = Depends(get_current_student),
    db: Session = Depends(get_db),
):
    """Alias of /ai/chat for unified API routing."""
    return _handle_chat_turn(request, payload, current_student, db)
