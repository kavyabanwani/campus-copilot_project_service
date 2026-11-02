"""Student-facing endpoints that are not part of a conversation."""

from datetime import date

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

import ai_tools
from auth.dependencies import get_current_student
from db.database import get_db
from db.models import Student
from db.schemas import InsightItem, InsightsResponse

router = APIRouter(prefix="/student", tags=["student"])


@router.get("/insights", response_model=InsightsResponse)
def get_my_insights(
    current_student: Student = Depends(get_current_student),
    db: Session = Depends(get_db),
):
    """The 'Copilot noticed' items - built from this student's real records."""
    items: list[InsightItem] = []

    attendance = ai_tools.get_attendance_summary(db, current_student).result
    for subject in attendance.get("subjects", []):
        if subject["percentage"] < subject["minRequired"]:
            items.append(
                InsightItem(
                    icon="AlertTriangle",
                    tone="warning",
                    text=(
                        f"{subject['subject']} attendance is below {subject['minRequired']}% "
                        f"(currently {subject['percentage']}%)."
                    ),
                )
            )

    unmarked = ai_tools.get_class_sessions(db, current_student, only_unmarked=True).result
    pending_count = unmarked.get("unmarked_finished_classes", 0)
    if pending_count:
        items.append(
            InsightItem(
                icon="CalendarClock",
                tone="warning",
                text=f"{pending_count} finished class{'' if pending_count == 1 else 'es'} still need attendance marked.",
            )
        )

    assignments = ai_tools.get_assignments(db, current_student).result.get("assignments", [])
    due_soon = [a for a in assignments if 0 <= a["days_remaining"] <= 7]
    if due_soon:
        items.append(
            InsightItem(
                icon="BookMarked",
                tone="info",
                text=f"{len(due_soon)} assignment{'' if len(due_soon) == 1 else 's'} due within a week.",
            )
        )

    exams = ai_tools.get_exams(db, current_student).result.get("exams", [])
    if exams:
        items.append(
            InsightItem(icon="CalendarClock", tone="info", text=f"Next exam: {exams[0]['subject']} on {exams[0]['date']}.")
        )

    fees = ai_tools.get_fees(db, current_student).result
    if fees.get("remaining", 0) > 0:
        items.append(
            InsightItem(
                icon="Wallet",
                tone="info",
                text=f"Rs {fees['remaining']:,.0f} of semester fees is still pending (due {fees['due_date']}).",
            )
        )

    return InsightsResponse(items=items[:4])
