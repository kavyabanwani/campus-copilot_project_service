"""The tools Campus Copilot's AI is allowed to call.

Each tool is a plain Python function over the database / vector store.
Tools take `student` from the JWT session, never from model arguments.
Returns a ToolResult holding:
    result   - facts for the model to reason over
    activity - line for the agent activity trace
    card_type / card_data - optional UI card payload
    sources  - retrieval-grounded citations with title, page, and snippet
"""

from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
import logging

import requests
from sqlalchemy.orm import Session

from config import settings
import document_index

from db.models import (
    Assignment,
    AssignmentSubmission,
    AttendanceRecord,
    CampusEvent,
    CampusInfo,
    ClassSession,
    Exam,
    FeeAccount,
    Student,
    Subject,
    TimetableSlot,
)

logger = logging.getLogger("campus_copilot.tools")

MINIMUM_ATTENDANCE_PERCENTAGE = 75

WEEKDAY_NAMES = [
    "Monday",
    "Tuesday",
    "Wednesday",
    "Thursday",
    "Friday",
    "Saturday",
    "Sunday",
]


@dataclass
class ToolResult:
    result: dict
    activity: str
    card_type: str | None = None
    card_data: dict | None = None
    sources: list[dict] = field(default_factory=list)


def _format_date(value: date) -> str:
    return value.strftime("%b %d, %Y (%A)")


def _format_time(value) -> str:
    return (
        datetime.strptime(str(value)[:5], "%H:%M")
        .strftime("%I:%M %p")
        .lstrip("0")
    )


def _student_subjects(
    db: Session,
    student: Student,
) -> list[Subject]:
    return (
        db.query(Subject)
        .filter(
            Subject.department == student.department,
            Subject.semester == student.semester,
        )
        .order_by(Subject.subject_code)
        .all()
    )


def _finished(session: ClassSession) -> bool:
    return datetime.now() >= datetime.combine(
        session.class_date,
        session.end_time,
    )


def _policy_sources_for_query(
    db: Session,
    student: Student,
    query: str,
    threshold: float = 0.3,
) -> list[dict]:
    """Retrieve grounded policy citations from RAG index."""

    try:
        passages = document_index.search_documents(
            db,
            query,
            student=student,
            top_k=1,
        )

        sources = []

        for p in passages:
            if p.get("score", 0) >= threshold:
                sources.append(
                    {
                        "title": p["title"],
                        "page": p["page"],
                        "snippet": (
                            p.get("snippet")
                            or p["content"][:200]
                        ),
                    }
                )

        return sources

    except Exception as e:
        logger.warning(
            "Could not retrieve policy source for '%s': %s",
            query,
            e,
        )
        return []


# ---------------------------------------------------------------------------
# Attendance
# ---------------------------------------------------------------------------

def get_attendance_summary(
    db: Session,
    student: Student,
    subject: str | None = None,
) -> ToolResult:
    """Attendance percentage per subject."""

    rows = (
        db.query(ClassSession, AttendanceRecord, Subject)
        .join(
            Subject,
            Subject.subject_id == ClassSession.subject_id,
        )
        .outerjoin(
            AttendanceRecord,
            (
                AttendanceRecord.session_id
                == ClassSession.session_id
            )
            & (
                AttendanceRecord.student_id
                == student.student_id
            ),
        )
        .filter(
            Subject.department == student.department,
            Subject.semester == student.semester,
        )
        .all()
    )

    per_subject: dict[str, dict] = {}

    for session, record, subject_row in rows:
        if not _finished(session):
            continue

        entry = per_subject.setdefault(
            subject_row.subject_code,
            {
                "subject": subject_row.subject_name,
                "subject_code": subject_row.subject_code,
                "attended": 0,
                "total": 0,
                "not_yet_marked": 0,
            },
        )

        if record and record.status == "present":
            entry["attended"] += 1
            entry["total"] += 1

        elif record and record.status == "absent":
            entry["total"] += 1

        else:
            entry["not_yet_marked"] += 1

    items = []

    for entry in per_subject.values():
        percentage = (
            round(
                entry["attended"] / entry["total"] * 100,
                1,
            )
            if entry["total"]
            else 0.0
        )

        items.append(
            {
                **entry,
                "percentage": percentage,
                "minRequired": MINIMUM_ATTENDANCE_PERCENTAGE,
            }
        )

    if subject:
        needle = subject.lower()

        items = [
            item
            for item in items
            if needle in item["subject"].lower()
            or needle in item["subject_code"].lower()
        ] or items

    items.sort(key=lambda item: item["percentage"])

    if not items:
        return ToolResult(
            result={
                "message": (
                    "No finished classes are recorded "
                    "for this student's subjects yet."
                )
            },
            activity="Checked attendance records",
        )

    attended_total = sum(
        item["attended"] for item in items
    )

    classes_total = sum(
        item["total"] for item in items
    )

    overall = (
        round(attended_total / classes_total * 100, 1)
        if classes_total
        else 0.0
    )

    result = {
        "overall_percentage": overall,
        "classes_not_yet_marked": sum(
            item["not_yet_marked"] for item in items
        ),
        "minimum_required": MINIMUM_ATTENDANCE_PERCENTAGE,
        "subjects": items,
        "below_requirement": [
            item["subject"]
            for item in items
            if item["percentage"]
            < MINIMUM_ATTENDANCE_PERCENTAGE
        ],
    }

    if len(items) == 1:
        item = items[0]
        card_type = "attendance"
        card_data = {
            "kind": "attendance",
            **item,
        }

    else:
        card_type = "attendance_summary"
        card_data = {
            "kind": "attendance_summary",
            "overall": overall,
            "items": items,
        }

    sources = _policy_sources_for_query(
        db,
        student,
        "Academic Attendance Policy minimum requirement condonation",
    )

    return ToolResult(
        result=result,
        activity="Checked attendance records",
        card_type=card_type,
        card_data=card_data,
        sources=sources,
    )


def get_class_sessions(
    db: Session,
    student: Student,
    only_unmarked: bool = False,
) -> ToolResult:
    """Individual class sessions and their attendance state."""

    rows = (
        db.query(ClassSession, AttendanceRecord, Subject)
        .join(
            Subject,
            Subject.subject_id == ClassSession.subject_id,
        )
        .outerjoin(
            AttendanceRecord,
            (
                AttendanceRecord.session_id
                == ClassSession.session_id
            )
            & (
                AttendanceRecord.student_id
                == student.student_id
            ),
        )
        .filter(
            Subject.department == student.department,
            Subject.semester == student.semester,
        )
        .order_by(
            ClassSession.class_date,
            ClassSession.start_time,
        )
        .all()
    )

    items = []

    for session, record, subject_row in rows:
        finished = _finished(session)
        status = record.status if record else "pending"
        can_mark = finished and status == "pending"

        if only_unmarked and not can_mark:
            continue

        items.append(
            {
                "session_id": session.session_id,
                "subject_code": subject_row.subject_code,
                "subject_name": subject_row.subject_name,
                "class_date": str(session.class_date),
                "start_time": str(session.start_time),
                "end_time": str(session.end_time),
                "status": status,
                "can_mark": can_mark,
            }
        )

    if not items:
        return ToolResult(
            result={
                "message": "No class sessions match that request."
            },
            activity="Checked class sessions",
        )

    return ToolResult(
        result={
            "sessions": items[-40:],
            "unmarked_finished_classes": sum(
                1 for item in items if item["can_mark"]
            ),
        },
        activity="Checked class sessions",
        card_type="attendance_status",
        card_data={
            "kind": "attendance_status",
            "items": items[-12:],
        },
    )


def simulate_attendance_change(
    db: Session,
    student: Student,
    subject: str,
    classes_to_miss: int = 1,
) -> ToolResult:
    """Calculate attendance if the student misses upcoming classes."""

    summary = get_attendance_summary(
        db,
        student,
        subject=subject,
    )

    subjects = summary.result.get("subjects")

    if not subjects:
        return ToolResult(
            result=summary.result,
            activity="Calculated attendance impact",
        )

    target = subjects[0]

    classes_to_miss = max(
        1,
        int(classes_to_miss or 1),
    )

    projected_total = target["total"] + classes_to_miss

    projected = (
        round(
            target["attended"] / projected_total * 100,
            1,
        )
        if projected_total
        else 0.0
    )

    safe = projected >= MINIMUM_ATTENDANCE_PERCENTAGE

    can_still_miss = 0

    while (
        target["attended"]
        / (target["total"] + can_still_miss + 1)
        * 100
        >= MINIMUM_ATTENDANCE_PERCENTAGE
    ):
        can_still_miss += 1

        if can_still_miss > 200:
            break

    sources = _policy_sources_for_query(
        db,
        student,
        "Academic Attendance Policy 75 percent condonation",
    )

    return ToolResult(
        result={
            "subject": target["subject"],
            "current_percentage": target["percentage"],
            "classes_to_miss": classes_to_miss,
            "projected_percentage": projected,
            "minimum_required": MINIMUM_ATTENDANCE_PERCENTAGE,
            "stays_above_requirement": safe,
            "classes_that_can_still_be_missed": can_still_miss,
        },
        activity="Calculated attendance impact",
        card_type="attendance",
        card_data={
            "kind": "attendance",
            **target,
            "whatIf": {
                "afterSkip": projected,
                "safe": safe,
                "classesMissed": classes_to_miss,
            },
        },
        sources=sources,
    )


# ---------------------------------------------------------------------------
# Timetable, assignments, exams, fees
# ---------------------------------------------------------------------------

def get_timetable(
    db: Session,
    student: Student,
    day: str = "today",
) -> ToolResult:
    """The student's weekly timetable, optionally for one day."""

    slots = (
        db.query(TimetableSlot, Subject)
        .join(
            Subject,
            Subject.subject_id == TimetableSlot.subject_id,
        )
        .filter(
            Subject.department == student.department,
            Subject.semester == student.semester,
        )
        .order_by(TimetableSlot.start_time)
        .all()
    )

    if not slots:
        return ToolResult(
            result={
                "message": (
                    "No timetable is published for this "
                    "student's department and semester."
                )
            },
            activity="Checked the timetable",
        )

    requested = (day or "today").strip().lower()
    today = date.today()

    if requested in {"today", ""}:
        day_name = WEEKDAY_NAMES[today.weekday()]
        label = "Today"

    elif requested == "tomorrow":
        tomorrow = today + timedelta(days=1)
        day_name = WEEKDAY_NAMES[tomorrow.weekday()]
        label = "Tomorrow"

    elif requested in {"week", "all"}:
        day_name = None
        label = "This week"

    else:
        matched = next(
            (
                name
                for name in WEEKDAY_NAMES
                if name.lower().startswith(requested[:3])
            ),
            None,
        )

        day_name = matched
        label = matched or "This week"

    selected = [
        (slot, subject)
        for slot, subject in slots
        if not day_name or slot.day_of_week == day_name
    ]

    items = [
        {
            "time": _format_time(slot.start_time),
            "subject": subject.subject_name,
            "room": slot.room,
            "day": slot.day_of_week,
        }
        for slot, subject in selected
    ]

    if not items:
        return ToolResult(
            result={
                "day": label,
                "classes": [],
                "message": (
                    f"There are no classes scheduled on "
                    f"{label.lower()}."
                ),
            },
            activity="Checked the timetable",
        )

    return ToolResult(
        result={
            "day": label,
            "classes": items,
        },
        activity="Checked the timetable",
        card_type="schedule",
        card_data={
            "kind": "schedule",
            "label": label,
            "items": items,
        },
    )


def get_assignments(
    db: Session,
    student: Student,
    include_submitted: bool = False,
) -> ToolResult:
    """Assignments for the student's subjects and submission state."""

    rows = (
        db.query(
            Assignment,
            Subject,
            AssignmentSubmission,
        )
        .join(
            Subject,
            Subject.subject_id == Assignment.subject_id,
        )
        .outerjoin(
            AssignmentSubmission,
            (
                AssignmentSubmission.assignment_id
                == Assignment.assignment_id
            )
            & (
                AssignmentSubmission.student_id
                == student.student_id
            ),
        )
        .filter(
            Subject.department == student.department,
            Subject.semester == student.semester,
        )
        .order_by(Assignment.due_date)
        .all()
    )

    items = []

    for assignment, subject, submission in rows:
        submitted = submission is not None

        if submitted and not include_submitted:
            continue

        items.append(
            {
                "id": assignment.assignment_id,
                "title": assignment.title,
                "subject": subject.subject_name,
                "dueDate": _format_date(assignment.due_date),
                "days_remaining": (
                    assignment.due_date - date.today()
                ).days,
                "status": (
                    "submitted" if submitted else "pending"
                ),
            }
        )

    if not items:
        return ToolResult(
            result={
                "message": (
                    "No pending assignments are recorded "
                    "for this student."
                )
            },
            activity="Checked the assignment tracker",
        )

    return ToolResult(
        result={"assignments": items},
        activity="Checked the assignment tracker",
        card_type="assignments",
        card_data={
            "kind": "assignments",
            "items": items,
        },
    )


def get_exams(
    db: Session,
    student: Student,
    include_past: bool = False,
) -> ToolResult:
    """The student's exam schedule."""

    query = (
        db.query(Exam, Subject)
        .join(
            Subject,
            Subject.subject_id == Exam.subject_id,
        )
        .filter(
            Subject.department == student.department,
            Subject.semester == student.semester,
        )
    )

    if not include_past:
        query = query.filter(
            Exam.exam_date >= date.today()
        )

    rows = query.order_by(Exam.exam_date).all()

    if not rows:
        return ToolResult(
            result={
                "message": (
                    "No exams are scheduled for this "
                    "student's semester yet."
                )
            },
            activity="Checked the exam schedule",
        )

    items = [
        {
            "subject": subject.subject_name,
            "date": _format_date(exam.exam_date),
            "type": exam.exam_type,
            "room": exam.room,
            "days_remaining": (
                exam.exam_date - date.today()
            ).days,
        }
        for exam, subject in rows
    ]

    return ToolResult(
        result={"exams": items},
        activity="Checked the exam schedule",
        card_type="exams",
        card_data={
            "kind": "exams",
            "items": items,
        },
    )


def get_fees(
    db: Session,
    student: Student,
) -> ToolResult:
    """The student's fee ledger for the current semester."""

    account = (
        db.query(FeeAccount)
        .filter(
            FeeAccount.student_id == student.student_id
        )
        .order_by(FeeAccount.semester.desc())
        .first()
    )

    if not account:
        return ToolResult(
            result={
                "message": (
                    "No fee account has been created "
                    "for this student yet."
                )
            },
            activity="Checked the fee ledger",
        )

    total = float(account.total_amount)
    paid = float(account.paid_amount)
    remaining = round(total - paid, 2)

    sources = _policy_sources_for_query(
        db,
        student,
        "Fee Structure & Payment Policy payment instalments late fee",
    )

    return ToolResult(
        result={
            "semester": account.semester,
            "total": total,
            "paid": paid,
            "remaining": remaining,
            "due_date": _format_date(account.due_date),
            "currency": "INR",
        },
        activity="Checked the fee ledger",
        card_type="fees",
        card_data={
            "kind": "fees",
            "semester": account.semester,
            "total": total,
            "paid": paid,
            "remaining": remaining,
            "dueDate": _format_date(account.due_date),
        },
        sources=sources,
    )


# ---------------------------------------------------------------------------
# Campus Info & Campus Events Provider
# ---------------------------------------------------------------------------

class CampusEventsProvider:

    @staticmethod
    def get_events(
        db: Session,
        days_ahead: int = 14,
        category: str | None = None,
    ) -> list[dict]:

        api_url = getattr(
            settings,
            "CAMPUS_EVENTS_API_URL",
            "",
        ).strip()

        if api_url:
            try:
                headers = {}

                api_key = getattr(
                    settings,
                    "CAMPUS_EVENTS_API_KEY",
                    "",
                ).strip()

                if api_key:
                    headers["Authorization"] = (
                        f"Bearer {api_key}"
                    )

                params = {"days_ahead": days_ahead}

                if category:
                    params["category"] = category

                resp = requests.get(
                    api_url,
                    headers=headers,
                    params=params,
                    timeout=5,
                )

                if resp.status_code == 200:
                    raw_data = resp.json()

                    raw_items = (
                        raw_data.get("events", raw_data)
                        if isinstance(raw_data, dict)
                        else raw_data
                    )

                    if isinstance(raw_items, list):
                        mapped = []

                        for item in raw_items:
                            mapped.append(
                                {
                                    "id": item.get("id"),
                                    "title": item.get("title", ""),
                                    "description": item.get(
                                        "description", ""
                                    ),
                                    "location": item.get(
                                        "location", ""
                                    ),
                                    "starts_at": str(
                                        item.get("starts_at", "")
                                    ),
                                    "ends_at": (
                                        str(item.get("ends_at", ""))
                                        if item.get("ends_at")
                                        else None
                                    ),
                                    "category": item.get(
                                        "category", "general"
                                    ),
                                    "is_demo": bool(
                                        item.get("is_demo", False)
                                    ),
                                }
                            )

                        return mapped

            except Exception as e:
                logger.warning(
                    "Error fetching events from external API: %s",
                    e,
                )

        now = datetime.now()
        cutoff = now + timedelta(days=days_ahead)

        query = (
            db.query(CampusEvent)
            .filter(
                CampusEvent.starts_at >= now,
                CampusEvent.starts_at <= cutoff,
            )
        )

        if category:
            query = query.filter(
                CampusEvent.category == category.lower()
            )

        events = query.order_by(
            CampusEvent.starts_at
        ).all()

        return [
            {
                "id": event.id,
                "title": event.title,
                "description": event.description,
                "location": event.location,
                "starts_at": event.starts_at.strftime(
                    "%b %d, %Y %I:%M %p"
                ),
                "ends_at": (
                    event.ends_at.strftime("%b %d, %Y %I:%M %p")
                    if event.ends_at
                    else None
                ),
                "category": event.category,
                "is_demo": bool(event.is_demo),
            }
            for event in events
        ]


def get_campus_events(
    db: Session,
    student: Student,
    days_ahead: int = 14,
    category: str | None = None,
) -> ToolResult:
    """Upcoming campus events and activities."""

    events = CampusEventsProvider.get_events(
        db,
        days_ahead=days_ahead,
        category=category,
    )

    if not events:
        return ToolResult(
            result={
                "message": (
                    f"No campus events are recorded for "
                    f"the next {days_ahead} days."
                ),
                "events": [],
            },
            activity="Checked campus events schedule",
        )

    return ToolResult(
        result={
            "events": events,
            "count": len(events),
        },
        activity="Checked campus events schedule",
        card_type="events",
        card_data={
            "kind": "events",
            "items": events,
        },
    )


def get_campus_info(
    db: Session,
    student: Student,
    topic: str,
) -> ToolResult:
    """General campus knowledge and facility details."""

    needle = topic.lower().strip()

    records = (
        db.query(CampusInfo)
        .filter(
            (CampusInfo.department.is_(None))
            | (CampusInfo.department == student.department)
        )
        .all()
    )

    matched = [
        record
        for record in records
        if (
            needle in record.key.lower()
            or needle in record.category.lower()
            or needle in record.value.lower()
        )
    ]

    if not matched:
        return ToolResult(
            result={
                "message": (
                    f"No campus information is recorded "
                    f"regarding '{topic}'. Please consult "
                    "the campus admin desk."
                )
            },
            activity="Looked up campus information",
        )

    primary = matched[0]

    return ToolResult(
        result={
            "topic": primary.key,
            "category": primary.category,
            "details": primary.value,
        },
        activity="Looked up campus information",
        card_type="info",
        card_data={
            "kind": "info",
            "title": primary.key.replace("_", " ").title(),
            "category": primary.category,
            "content": primary.value,
        },
    )


# ---------------------------------------------------------------------------
# Campus Documents (RAG)
# ---------------------------------------------------------------------------

def search_campus_documents(
    db: Session,
    student: Student,
    query: str,
) -> ToolResult:
    """Semantic search over campus policies and uploaded documents."""

    # Correct function name from document_index.py
    passages = document_index.search_documents(
        db,
        query,
        student=student,
        top_k=4,
    )

    if not passages:
        return ToolResult(
            result={
                "message": "No campus document covers that topic."
            },
            activity="Searched campus documents",
        )

    formatted_passages = [
        {
            "text": (
                f'"""\n[UNTRUSTED CAMPUS DOCUMENT: '
                f'{p["title"]} (Page {p["page"]})]\n'
                f'{p["content"]}\n"""'
            ),
            "document": p["title"],
            "page": p["page"],
        }
        for p in passages
    ]

    top = passages[0]

    return ToolResult(
        result={
            "passages": formatted_passages,
        },
        activity="Searched campus documents",
        card_type="policy",
        card_data={
            "kind": "policy",
            "title": top["title"],
            "summary": (
                top["content"][:280].strip()
                + (
                    "..."
                    if len(top["content"]) > 280
                    else ""
                )
            ),
            "page": top["page"],
        },
        sources=[
            {
                "title": passage["title"],
                "page": passage["page"],
                "snippet": (
                    passage.get("snippet")
                    or passage["content"][:200]
                ),
            }
            for passage in passages
        ],
    )


# ---------------------------------------------------------------------------
# Registry: what the model sees, and how each name maps to a function
# ---------------------------------------------------------------------------

TOOL_FUNCTIONS = {
    "get_attendance_summary": get_attendance_summary,
    "get_class_sessions": get_class_sessions,
    "simulate_attendance_change": simulate_attendance_change,
    "get_timetable": get_timetable,
    "get_assignments": get_assignments,
    "get_exams": get_exams,
    "get_fees": get_fees,
    "get_campus_info": get_campus_info,
    "get_campus_events": get_campus_events,
    "search_campus_documents": search_campus_documents,
}


TOOL_DECLARATIONS = [
    {
        "name": "get_attendance_summary",
        "description": (
            "Attendance percentage for the student, per subject, "
            "counting only classes that have already finished. "
            "Use for attendance questions and requirement checks."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "subject": {
                    "type": ["string", "null"],
                    "description": (
                        "Optional subject name or code."
                    ),
                }
            },
        },
    },
    {
        "name": "get_class_sessions",
        "description": (
            "Individual class sessions with attendance state. "
            "Use for specific classes or unmarked attendance."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "only_unmarked": {
                    "type": ["boolean", "null"],
                    "description": (
                        "Only return finished classes "
                        "whose attendance is not marked."
                    ),
                }
            },
        },
    },
    {
        "name": "simulate_attendance_change",
        "description": (
            "Calculate attendance if the student misses "
            "one or more classes of a subject."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "subject": {
                    "type": "string",
                    "description": "Subject name or code.",
                },
                "classes_to_miss": {
                    "type": ["integer", "null"],
                    "description": "Number of classes to miss.",
                },
            },
            "required": ["subject"],
        },
    },
    {
        "name": "get_timetable",
        "description": (
            "The student's class timetable for a given day "
            "or the whole week."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "day": {
                    "type": ["string", "null"],
                    "description": (
                        "today, tomorrow, weekday name, or week."
                    ),
                }
            },
        },
    },
    {
        "name": "get_assignments",
        "description": (
            "Assignments for the student's subjects "
            "with due dates and submission state."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "include_submitted": {
                    "type": ["boolean", "null"],
                    "description": (
                        "Include already submitted assignments."
                    ),
                }
            },
        },
    },
    {
        "name": "get_exams",
        "description": (
            "The student's exam schedule, upcoming exams first."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "include_past": {
                    "type": ["boolean", "null"],
                    "description": (
                        "Include exams that have already happened."
                    ),
                }
            },
        },
    },
    {
        "name": "get_fees",
        "description": (
            "The student's fee total, amount paid, "
            "amount remaining and due date."
        ),
        "parameters": {
            "type": "object",
            "properties": {},
        },
    },
    {
        "name": "get_campus_info",
        "description": (
            "Look up official campus information such as "
            "library hours and administrative office timings."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "topic": {
                    "type": "string",
                    "description": (
                        "Campus information topic to look up."
                    ),
                }
            },
            "required": ["topic"],
        },
    },
    {
        "name": "get_campus_events",
        "description": (
            "Get upcoming college events, workshops, "
            "hackathons, seminars, or cultural fests."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "days_ahead": {
                    "type": ["integer", "null"],
                    "description": "Look-ahead window in days.",
                },
                "category": {
                    "type": ["string", "null"],
                    "description": "Optional event category.",
                },
            },
        },
    },
    {
        "name": "search_campus_documents",
        "description": (
            "Search college policies, academic regulations, "
            "notices, and uploaded syllabi."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": (
                        "What to look for in the student's own words."
                    ),
                }
            },
            "required": ["query"],
        },
    },
]


def run_tool(
    name: str,
    arguments: dict,
    db: Session,
    student: Student,
) -> ToolResult:
    """Execute one tool by name. Unknown names fail safely."""

    function = TOOL_FUNCTIONS.get(name)

    if not function:
        return ToolResult(
            result={"error": f"Unknown tool: {name}"},
            activity="Unknown request",
        )

    clean_args = {
        key: value
        for key, value in (arguments or {}).items()
        if value is not None
    }

    try:
        return function(
            db,
            student,
            **clean_args,
        )

    except TypeError as e:
        logger.warning(
            "Tool %s argument error: %s",
            name,
            e,
        )

        return ToolResult(
            result={
                "error": (
                    "That tool was called with arguments "
                    "it does not accept."
                )
            },
            activity="Checked campus data",
        )