"""Load the campus data Campus Copilot answers from.

Usage:
    python seed_data.py                          # Computer Science, semester 4
    python seed_data.py --all                    # Seed all departments and semesters in catalogue
    python seed_data.py --reindex                # Re-index campus policy documents with embeddings
    python seed_data.py --department "Mechanical Engineering" --semester 4
"""

import argparse
import random
from datetime import date, datetime, time, timedelta

import document_index
from auth.auth_service import hash_password
from db.database import Base, SessionLocal, engine, init_db_and_migrations
from db.models import (
    Assignment,
    AttendanceRecord,
    CampusEvent,
    CampusInfo,
    ClassSession,
    Exam,
    FeeStructure,
    Student,
    Subject,
    TimetableSlot,
)
from enrollment import ensure_fee_account

# --------------------------------------------------------------------------
# Course catalogue
# --------------------------------------------------------------------------
SUBJECT_CATALOGUE = {
    ("Computer Science", 4): [
        ("CS401", "Database Management Systems"),
        ("CS402", "Operating Systems"),
        ("CS403", "Artificial Intelligence"),
        ("CS404", "Discrete Mathematics"),
    ],
    ("Computer Science", 3): [
        ("CS301", "Data Structures"),
        ("CS302", "Computer Organisation"),
        ("CS303", "Object Oriented Programming"),
        ("CS304", "Probability and Statistics"),
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

WEEKLY_PATTERN = [
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

ASSIGNMENT_TITLES = [
    ("Normalization exercise set", 3),
    ("Process scheduling report", 5),
    ("Search algorithms lab record", 8),
    ("Problem set 4", 12),
]

POLICY_DOCUMENTS = [
    (
        "Academic Attendance Policy",
        "policy",
        """Minimum attendance requirement

Every student must maintain at least 75 percent attendance in each registered subject to be
eligible to appear for the end semester examination of that subject. Attendance is calculated
from the classes that have already been conducted, not from the classes planned for the term.

Counting of attendance

Attendance is recorded per class session. A session counts towards a student's percentage only
after the session has finished. Sessions scheduled later in the term are not included in the
calculation and cannot be marked in advance.

Condonation of attendance shortage

A student whose attendance in a subject falls between 65 percent and 75 percent may apply to the
Head of Department for condonation. The application must be supported by medical certificates or
documented evidence of an unavoidable personal situation, and must be submitted before the start
of the examination.

Attendance below 65 percent

Attendance below 65 percent in a subject cannot be condoned. The student is marked as detained in
that subject and must repeat it in a later term.

Duty leave

Students representing the college in approved sports, cultural or technical events may apply for
duty leave. Approved duty leave is counted as attended, provided the request is filed within one
week of the event.""",
    ),
    (
        "Fee Structure & Payment Policy",
        "policy",
        """Semester fee payment

Semester fees must be paid in full before the last working day of the semester. A student with
outstanding fees is not issued an examination hall ticket.

Late payment

A late fee of Rs 500 is charged for payment made after the published due date. Continued
non payment beyond thirty days after the due date results in the student's registration for the
term being placed on hold.

Instalments

Students may request to pay in two instalments by applying to the accounts office before the
start of the semester. The first instalment must clear at least half of the semester fee.

Refunds

Fees are refunded only when a student withdraws before the commencement of classes, less an
administrative charge of Rs 2,000.""",
    ),
    (
        "Examination Regulations",
        "regulation",
        """Eligibility

A student is eligible to appear for an end semester examination if attendance in the subject is at
least 75 percent, or a condonation has been approved, and all fees due have been paid.

Examination schedule

The mid semester examination is held in the middle of the term and the end semester examination at
its close. The detailed schedule is published at least two weeks before the first paper.

Re examination

A student who fails a subject may appear for the supplementary examination held at the start of the
following semester. A student absent without approved medical grounds is not eligible for the
supplementary examination in that term.

Conduct

Possession of any unauthorised material in the examination hall is treated as malpractice and is
referred to the examination committee.""",
    ),
    (
        "Assignment and Internal Assessment Rules",
        "regulation",
        """Submission deadlines

Assignments must be submitted on or before the due date published by the subject teacher. Work
submitted up to three days late is accepted with a penalty of ten percent of the assignment marks.

Late submission beyond three days

Assignments submitted more than three days after the due date are not accepted, and the student is
awarded zero for that assignment unless a medical certificate is produced.

Internal assessment

Internal assessment carries forty marks per subject, made up of assignments, class tests and the
laboratory record. A student must score at least sixteen of the forty internal marks to be eligible
for the end semester examination.""",
    ),
]

DEMO_CAMPUS_INFO = [
    (
        "library",
        "library_hours",
        "The Central Library is open Monday to Saturday from 8:00 AM to 9:00 PM. On Sundays and public holidays, the reading hall is open from 10:00 AM to 5:00 PM.",
        None,
    ),
    (
        "administration",
        "office_timings",
        "The Student Affairs and Administrative Office operates Monday to Friday from 9:30 AM to 5:00 PM, with lunch break from 1:00 PM to 2:00 PM.",
        None,
    ),
    (
        "health",
        "health_center",
        "The Campus Health Center is located near Block B and operates 24/7 with a resident physician and basic medical assistance.",
        None,
    ),
    (
        "cafeteria",
        "cafeteria_hours",
        "The Main Cafeteria is open daily from 7:30 AM to 9:30 PM serving breakfast, lunch, snacks, and dinner.",
        None,
    ),
]

DEMO_CAMPUS_EVENTS = [
    (
        "[DEMO] Annual Tech Symposium 2026",
        "Annual inter-college engineering symposium featuring project showcases, coding challenges, and keynotes by industry researchers.",
        "Main Auditorium & Innovation Lab",
        timedelta(days=5, hours=9),
        timedelta(days=6, hours=18),
        "technical",
    ),
    (
        "[DEMO] Hackathon: AI for Campus Life",
        "36-hour hackathon to build intelligent tools and mobile solutions improving university student experience.",
        "Computer Science Lab 3",
        timedelta(days=10, hours=10),
        timedelta(days=11, hours=22),
        "hackathon",
    ),
    (
        "[DEMO] Cultural Fest: Rhythms 2026",
        "The campus flagship cultural fest featuring music, drama, art exhibitions, and celebrity guest performances.",
        "Open Air Theatre",
        timedelta(days=20, hours=17),
        timedelta(days=22, hours=23),
        "cultural",
    ),
    (
        "[DEMO] Career Fair & Campus Placement Drive",
        "Over 40 tech and core engineering companies visiting for final year placements and pre-final year summer internships.",
        "Sports Complex",
        timedelta(days=14, hours=9),
        timedelta(days=15, hours=17),
        "placement",
    ),
]


def seed_subjects(db, department: str, semester: int) -> list[Subject]:
    catalogue = SUBJECT_CATALOGUE.get((department, semester))
    if not catalogue:
        raise SystemExit(
            f"No subject catalogue for {department} semester {semester}. "
            f"Add one to SUBJECT_CATALOGUE in seed_data.py first."
        )

    subjects = []
    for code, name in catalogue:
        subject = db.query(Subject).filter(Subject.subject_code == code).first()
        if not subject:
            subject = Subject(subject_code=code, subject_name=name, department=department, semester=semester)
            db.add(subject)
        else:
            subject.subject_name, subject.department, subject.semester = name, department, semester
        subjects.append(subject)
    db.commit()
    for subject in subjects:
        db.refresh(subject)
    return subjects


def seed_timetable(db, subjects: list[Subject]) -> None:
    subject_ids = [s.subject_id for s in subjects]
    db.query(TimetableSlot).filter(TimetableSlot.subject_id.in_(subject_ids)).delete(synchronize_session=False)
    for index, (day, start, end, room) in enumerate(WEEKLY_PATTERN):
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


def seed_class_sessions(db, subjects: list[Subject], weeks_back: int = 4, weeks_ahead: int = 1) -> None:
    subject_ids = [s.subject_id for s in subjects]
    db.query(ClassSession).filter(ClassSession.subject_id.in_(subject_ids)).delete(synchronize_session=False)

    today = date.today()
    monday_of_this_week = today - timedelta(days=today.weekday())

    for week in range(-weeks_back, weeks_ahead + 1):
        week_start = monday_of_this_week + timedelta(weeks=week)
        for index, (day, start, end, _room) in enumerate(WEEKLY_PATTERN):
            class_date = week_start + timedelta(days=WEEKDAY_INDEX[day])
            db.add(
                ClassSession(
                    subject_id=subjects[index % len(subjects)].subject_id,
                    class_date=class_date,
                    start_time=start,
                    end_time=end,
                )
            )
    db.commit()


def seed_attendance_for_students(db, subjects: list[Subject], department: str, semester: int) -> None:
    students = (
        db.query(Student).filter(Student.department == department, Student.semester == semester).all()
    )
    if not students:
        return

    subject_ids = [s.subject_id for s in subjects]
    sessions = db.query(ClassSession).filter(ClassSession.subject_id.in_(subject_ids)).all()
    finished = [s for s in sessions if datetime.now() >= datetime.combine(s.class_date, s.end_time)]

    for student in students:
        generator = random.Random(student.student_id)
        for session in finished:
            record = (
                db.query(AttendanceRecord)
                .filter(
                    AttendanceRecord.session_id == session.session_id,
                    AttendanceRecord.student_id == student.student_id,
                )
                .first()
            )
            if record:
                continue
            if (date.today() - session.class_date).days <= 1:
                continue
            db.add(
                AttendanceRecord(
                    session_id=session.session_id,
                    student_id=student.student_id,
                    status="present" if generator.random() < 0.82 else "absent",
                    marked_at=datetime.combine(session.class_date, session.end_time),
                )
            )
    db.commit()


def seed_assignments_and_exams(db, subjects: list[Subject]) -> None:
    subject_ids = [s.subject_id for s in subjects]
    db.query(Assignment).filter(Assignment.subject_id.in_(subject_ids)).delete(synchronize_session=False)
    db.query(Exam).filter(Exam.subject_id.in_(subject_ids)).delete(synchronize_session=False)

    today = date.today()
    for index, (title, days_ahead) in enumerate(ASSIGNMENT_TITLES):
        subject = subjects[index % len(subjects)]
        db.add(
            Assignment(
                subject_id=subject.subject_id,
                title=title,
                description=f"{title} for {subject.subject_name}.",
                due_date=today + timedelta(days=days_ahead),
            )
        )

    for index, subject in enumerate(subjects):
        db.add(
            Exam(
                subject_id=subject.subject_id,
                exam_type="Mid-Semester",
                exam_date=today + timedelta(days=10 + index * 2),
                start_time=time(10, 0),
                room=f"Hall {index + 1}",
            )
        )
    db.commit()


def seed_fees(db, department: str, semester: int) -> None:
    structure = (
        db.query(FeeStructure)
        .filter(FeeStructure.department == department, FeeStructure.semester == semester)
        .first()
    )
    due_date = date.today() + timedelta(days=45)
    if structure:
        structure.total_amount, structure.due_date = 42000, due_date
    else:
        db.add(
            FeeStructure(department=department, semester=semester, total_amount=42000, due_date=due_date)
        )
    db.commit()

    for student in db.query(Student).all():
        account = ensure_fee_account(db, student)
        if account and float(account.paid_amount) == 0:
            account.paid_amount = 30000
    db.commit()


def seed_documents(db) -> None:
    for title, category, text in POLICY_DOCUMENTS:
        document_index.ingest_document(db, title=title, category=category, raw_text=text)
        print(f"  indexed: {title}")


def seed_demo_admin(db) -> None:
    admin_email = "admin@campus.edu"
    existing = db.query(Student).filter(Student.email == admin_email).first()
    if not existing:
        admin_student = Student(
            roll_number="ADMIN01",
            full_name="Campus Administrator",
            email=admin_email,
            department="Computer Science",
            semester=4,
            password_hash=hash_password("Admin@123456"),
            role="admin",
        )
        db.add(admin_student)
        db.commit()
        print("  seeded demo admin: admin@campus.edu (password: Admin@123456)")
    else:
        existing.role = "admin"
        db.commit()


def seed_campus_info_and_events(db) -> None:
    for cat, key, val, dept in DEMO_CAMPUS_INFO:
        existing = db.query(CampusInfo).filter(CampusInfo.key == key).first()
        if not existing:
            db.add(CampusInfo(category=cat, key=key, value=val, department=dept))
        else:
            existing.value = val
    db.commit()

    now = datetime.now()
    for title, desc, loc, start_delta, end_delta, cat in DEMO_CAMPUS_EVENTS:
        existing = db.query(CampusEvent).filter(CampusEvent.title == title).first()
        if not existing:
            db.add(
                CampusEvent(
                    title=title,
                    description=desc,
                    location=loc,
                    starts_at=now + start_delta,
                    ends_at=now + end_delta,
                    category=cat,
                    is_demo=1,
                )
            )
        else:
            existing.description = desc
            existing.location = loc
            existing.starts_at = now + start_delta
            existing.ends_at = now + end_delta
    db.commit()
    print("  seeded demo campus info and events")


def seed_target(db, department: str, semester: int) -> None:
    print(f"Seeding {department}, semester {semester}")
    subjects = seed_subjects(db, department, semester)
    seed_timetable(db, subjects)
    seed_class_sessions(db, subjects)
    seed_attendance_for_students(db, subjects, department, semester)
    seed_assignments_and_exams(db, subjects)
    seed_fees(db, department, semester)
    print(f"  {len(subjects)} subjects, timetable, sessions, assignments, exams and fees ready")


def main() -> None:
    parser = argparse.ArgumentParser(description="Seed Campus Copilot with campus data.")
    parser.add_argument("--department", default="Computer Science")
    parser.add_argument("--semester", type=int, default=4)
    parser.add_argument("--all", action="store_true", help="Seed all departments and semesters in catalogue.")
    parser.add_argument("--reindex", action="store_true", help="Re-index policy documents with vector embeddings.")
    parser.add_argument("--skip-documents", action="store_true", help="Do not index policy documents.")
    args = parser.parse_args()

    init_db_and_migrations(bind=engine)
    db = SessionLocal()
    try:
        if args.all:
            print("Seeding all catalogue entries...")
            for dept, sem in SUBJECT_CATALOGUE.keys():
                seed_target(db, dept, sem)
        else:
            seed_target(db, args.department, args.semester)

        seed_demo_admin(db)
        seed_campus_info_and_events(db)

        if args.reindex or not args.skip_documents:
            print("Indexing campus documents with vector embeddings...")
            seed_documents(db)

        print("Done.")
    finally:
        db.close()


if __name__ == "__main__":
    main()
