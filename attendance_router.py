from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from auth.dependencies import get_current_student
from db.database import get_db
from db.models import AttendanceRecord, ClassSession, Student, Subject
from db.schemas import AttendanceMark, AttendanceStatusItem, AttendanceStatusResponse


router = APIRouter(prefix="/attendance", tags=["attendance"])


def session_has_finished(session: ClassSession) -> bool:
    return datetime.now() >= datetime.combine(session.class_date, session.end_time)


def build_status_item(session, record, subject, can_mark):
    return AttendanceStatusItem(
        session_id=session.session_id,
        subject_id=subject.subject_id,
        subject_code=subject.subject_code,
        subject_name=subject.subject_name,
        class_date=session.class_date,
        start_time=str(session.start_time),
        end_time=str(session.end_time),
        status=record.status if record else "pending",
        can_mark=can_mark,
    )


def find_student_session(session_id: int, student: Student, db: Session):
    return (
        db.query(ClassSession, AttendanceRecord, Subject)
        .join(Subject, Subject.subject_id == ClassSession.subject_id)
        .outerjoin(
            AttendanceRecord,
            (AttendanceRecord.session_id == ClassSession.session_id)
            & (AttendanceRecord.student_id == student.student_id),
        )
        .filter(
            ClassSession.session_id == session_id,
            Subject.department == student.department,
            Subject.semester == student.semester,
        )
        .first()
    )


@router.get("/status", response_model=AttendanceStatusResponse)
def get_attendance_status(
    current_student: Student = Depends(get_current_student),
    db: Session = Depends(get_db),
):
    rows = (
        db.query(ClassSession, AttendanceRecord, Subject)
        .join(Subject, Subject.subject_id == ClassSession.subject_id)
        .outerjoin(
            AttendanceRecord,
            (AttendanceRecord.session_id == ClassSession.session_id)
            & (AttendanceRecord.student_id == current_student.student_id),
        )
        .filter(
            Subject.department == current_student.department,
            Subject.semester == current_student.semester,
        )
        .order_by(ClassSession.class_date, ClassSession.start_time)
        .all()
    )
    return AttendanceStatusResponse(
        items=[
            build_status_item(session, record, subject, session_has_finished(session) and (not record or record.status == "pending"))
            for session, record, subject in rows
        ]
    )


@router.post("/{session_id}/mark", response_model=AttendanceStatusItem)
def mark_attendance(
    session_id: int,
    attendance: AttendanceMark,
    current_student: Student = Depends(get_current_student),
    db: Session = Depends(get_db),
):
    if attendance.status not in {"present", "absent"}:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Status must be present or absent",
        )

    row = find_student_session(session_id, current_student, db)
    if not row:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Class session not found")

    session, record, subject = row
    if not session_has_finished(session):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Attendance can be marked after the class ends",
        )
    if record and record.status != "pending":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Attendance is already marked for this class",
        )

    if not record:
        record = AttendanceRecord(
            session_id=session_id,
            student_id=current_student.student_id,
        )
        db.add(record)
    record.status = attendance.status
    record.marked_at = datetime.now()
    db.commit()

    return build_status_item(session, record, subject, False)
