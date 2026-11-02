"""Student enrollment lifecycle and academic environment provisioning.

Ensures every student - whether registered fresh or logging in - has their
academic ledger, subjects, weekly timetable, class sessions, attendance history,
assignments, exams, and fee account properly established.
"""

from datetime import date, datetime, time, timedelta
import random
from sqlalchemy.orm import Session

from db.models import (
    Assignment,
    AttendanceRecord,
    ClassSession,
    Exam,
    FeeAccount,
    FeeStructure,
    Student,
    Subject,
    TimetableSlot,
)

DEPARTMENT_CODES = {
    "Computer Science": "CS",
    "Electronics & Communication": "EC",
    "Mechanical Engineering": "ME",
    "Civil Engineering": "CE",
    "Electrical Engineering": "EE",
}

DEFAULT_CURRICULUM = {
    ("Computer Science", 1): [
        ("CS101", "Introduction to Programming"),
        ("CS102", "Digital Logic Design"),
        ("CS103", "Engineering Mathematics I"),
        ("CS104", "Engineering Physics"),
    ],
    ("Computer Science", 2): [
        ("CS201", "Data Structures Fundamentals"),
        ("CS202", "Computer Organization"),
        ("CS203", "Engineering Mathematics II"),
        ("CS204", "Basic Electrical Engineering"),
    ],
    ("Computer Science", 3): [
        ("CS301", "Data Structures"),
        ("CS302", "Computer Organisation"),
        ("CS303", "Object Oriented Programming"),
        ("CS304", "Probability and Statistics"),
    ],
    ("Computer Science", 4): [
        ("CS401", "Database Management Systems"),
        ("CS402", "Operating Systems"),
        ("CS403", "Artificial Intelligence"),
        ("CS404", "Discrete Mathematics"),
    ],
    ("Electronics & Communication", 4): [
        ("EC401", "Digital Signal Processing"),
        ("EC402", "Analog Circuits"),
        ("EC403", "Microprocessors"),
        ("EC404", "Electromagnetic Theory"),
    ],
    ("Mechanical Engineering", 4): [
        ("ME401", "Thermodynamics"),
        ("ME402", "Fluid Mechanics"),
        ("ME403", "Machine Design"),
        ("ME404", "Manufacturing Processes"),
    ],
    ("Civil Engineering", 4): [
        ("CE401", "Structural Analysis"),
        ("CE402", "Geotechnical Engineering"),
        ("CE403", "Transportation Engineering"),
        ("CE404", "Surveying"),
    ],
    ("Electrical Engineering", 4): [
        ("EE401", "Power Systems"),
        ("EE402", "Control Systems"),
        ("EE403", "Electrical Machines"),
        ("EE404", "Signals and Systems"),
    ],
}

WEEKLY_SLOTS = [
    ("Monday", time(9, 0), time(10, 0), "Room 101"),
    ("Monday", time(11, 0), time(12, 0), "Room 204"),
    ("Tuesday", time(10, 0), time(11, 0), "Room 204"),
    ("Tuesday", time(12, 0), time(13, 0), "Room 118"),
    ("Wednesday", time(9, 0), time(10, 0), "Room 220"),
    ("Wednesday", time(14, 0), time(16, 0), "Lab 3"),
    ("Thursday", time(10, 0), time(11, 0), "Room 101"),
    ("Friday", time(11, 0), time(12, 0), "Room 118"),
]

WEEKDAY_INDEX = {"Monday": 0, "Tuesday": 1, "Wednesday": 2, "Thursday": 3, "Friday": 4, "Saturday": 5}


def ensure_subjects(db: Session, department: str, semester: int) -> list[Subject]:
    existing = (
        db.query(Subject)
        .filter(Subject.department == department, Subject.semester == semester)
        .order_by(Subject.subject_code)
        .all()
    )
    if existing:
        return existing

    catalog = DEFAULT_CURRICULUM.get((department, semester))
    if not catalog:
        code_prefix = DEPARTMENT_CODES.get(department, "ENG")
        catalog = [
            (f"{code_prefix}{semester}01", f"Core Course {semester}.1"),
            (f"{code_prefix}{semester}02", f"Core Course {semester}.2"),
            (f"{code_prefix}{semester}03", f"Applied Engineering {semester}"),
            (f"{code_prefix}{semester}04", f"Technical Elective {semester}"),
        ]

    created = []
    for code, name in catalog:
        subj = db.query(Subject).filter(Subject.subject_code == code).first()
        if not subj:
            subj = Subject(subject_code=code, subject_name=name, department=department, semester=semester)
            db.add(subj)
        else:
            subj.department = department
            subj.semester = semester
        created.append(subj)
    db.commit()
    for s in created:
        db.refresh(s)
    return created


def ensure_timetable(db: Session, subjects: list[Subject]) -> None:
    if not subjects:
        return
    subject_ids = [s.subject_id for s in subjects]
    existing = db.query(TimetableSlot).filter(TimetableSlot.subject_id.in_(subject_ids)).first()
    if existing:
        return

    for index, (day, start, end, room) in enumerate(WEEKLY_SLOTS):
        db.add(
            TimetableSlot(
                subject_id=subjects[index % len(subjects)].subject_id,
                day_of_week=day,
                start_time=start,
                end_time=end,
                room=room,
            )
        )
    db.commit()


def ensure_class_sessions(db: Session, subjects: list[Subject]) -> list[ClassSession]:
    if not subjects:
        return []
    subject_ids = [s.subject_id for s in subjects]
    existing = db.query(ClassSession).filter(ClassSession.subject_id.in_(subject_ids)).all()
    if existing:
        return existing

    today = date.today()
    monday_this_week = today - timedelta(days=today.weekday())

    sessions = []
    for week in range(-4, 2):
        week_start = monday_this_week + timedelta(weeks=week)
        for index, (day, start, end, _) in enumerate(WEEKLY_SLOTS):
            class_date = week_start + timedelta(days=WEEKDAY_INDEX[day])
            cs = ClassSession(
                subject_id=subjects[index % len(subjects)].subject_id,
                class_date=class_date,
                start_time=start,
                end_time=end,
            )
            db.add(cs)
            sessions.append(cs)
    db.commit()
    return sessions


def ensure_attendance_history(db: Session, student: Student, subjects: list[Subject]) -> None:
    if not subjects:
        return
    subject_ids = [s.subject_id for s in subjects]
    sessions = (
        db.query(ClassSession)
        .filter(ClassSession.subject_id.in_(subject_ids))
        .order_by(ClassSession.class_date, ClassSession.start_time)
        .all()
    )
    finished = [s for s in sessions if datetime.now() >= datetime.combine(s.class_date, s.end_time)]
    if not finished:
        return

    generator = random.Random(student.student_id + 101)
    for session in finished:
        rec = (
            db.query(AttendanceRecord)
            .filter(
                AttendanceRecord.session_id == session.session_id,
                AttendanceRecord.student_id == student.student_id,
            )
            .first()
        )
        if rec:
            continue
        # Leave the classes from the last 2 days unmarked as pending so student can mark them
        if (date.today() - session.class_date).days <= 1:
            continue

        status = "present" if generator.random() < 0.84 else "absent"
        db.add(
            AttendanceRecord(
                session_id=session.session_id,
                student_id=student.student_id,
                status=status,
                marked_at=datetime.combine(session.class_date, session.end_time),
            )
        )
    db.commit()


def ensure_assignments_and_exams(db: Session, subjects: list[Subject]) -> None:
    if not subjects:
        return
    subject_ids = [s.subject_id for s in subjects]
    has_assignments = db.query(Assignment).filter(Assignment.subject_id.in_(subject_ids)).first()
    today = date.today()

    if not has_assignments:
        assignment_templates = [
            ("Lab Exercise & Performance Report", 4),
            ("Problem Set 1 - Core Principles", 7),
            ("Mini Project Progress Review", 12),
            ("Analytical Case Study", 18),
        ]
        for idx, (title, days_ahead) in enumerate(assignment_templates):
            subj = subjects[idx % len(subjects)]
            db.add(
                Assignment(
                    subject_id=subj.subject_id,
                    title=f"{subj.subject_code}: {title}",
                    description=f"Standard academic assignment for {subj.subject_name}.",
                    due_date=today + timedelta(days=days_ahead),
                )
            )

    has_exams = db.query(Exam).filter(Exam.subject_id.in_(subject_ids)).first()
    if not has_exams:
        for idx, subj in enumerate(subjects):
            db.add(
                Exam(
                    subject_id=subj.subject_id,
                    exam_type="Mid-Semester",
                    exam_date=today + timedelta(days=14 + idx * 2),
                    start_time=time(10, 0),
                    room=f"Hall {idx + 1}",
                )
            )
    db.commit()


def ensure_fee_account(db: Session, student: Student) -> FeeAccount | None:
    """Create this student's fee ledger if their department has a published structure."""
    existing = (
        db.query(FeeAccount)
        .filter(FeeAccount.student_id == student.student_id, FeeAccount.semester == student.semester)
        .first()
    )
    if existing:
        return existing

    structure = (
        db.query(FeeStructure)
        .filter(FeeStructure.department == student.department, FeeStructure.semester == student.semester)
        .first()
    )
    due_date = date.today() + timedelta(days=45)
    if not structure:
        structure = FeeStructure(
            department=student.department,
            semester=student.semester,
            total_amount=42000,
            due_date=due_date,
        )
        db.add(structure)
        db.commit()
        db.refresh(structure)

    account = FeeAccount(
        student_id=student.student_id,
        semester=student.semester,
        total_amount=structure.total_amount,
        paid_amount=30000,
        due_date=structure.due_date or due_date,
    )
    db.add(account)
    db.commit()
    db.refresh(account)
    return account


def ensure_student_environment(db: Session, student: Student) -> None:
    """Convenience method to set up all academic relations for a student."""
    subjects = ensure_subjects(db, student.department, student.semester)
    ensure_timetable(db, subjects)
    ensure_class_sessions(db, subjects)
    ensure_attendance_history(db, student, subjects)
    ensure_assignments_and_exams(db, subjects)
    ensure_fee_account(db, student)
