from sqlalchemy import (
    Column,
    Date,
    Enum,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
    TIME,
    TIMESTAMP,
    UniqueConstraint,
)
from sqlalchemy.sql import func

from db.database import Base


class Student(Base):
    __tablename__ = "students"

    student_id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    roll_number = Column(String(50), unique=True, nullable=False, index=True)
    full_name = Column(String(100), nullable=False)
    email = Column(String(100), unique=True, nullable=False)
    department = Column(String(50), nullable=False)
    semester = Column(Integer, nullable=False)
    password_hash = Column(String(255), nullable=False)
    role = Column(String(20), nullable=False, default="student", server_default="student")
    created_at = Column(TIMESTAMP, server_default=func.current_timestamp())


class Subject(Base):
    __tablename__ = "subjects"

    subject_id = Column(Integer, primary_key=True, index=True)
    subject_code = Column(String(20), unique=True, nullable=False)
    subject_name = Column(String(100), nullable=False)
    department = Column(String(50), nullable=False)
    semester = Column(Integer, nullable=False)


class ClassSession(Base):
    __tablename__ = "class_sessions"

    session_id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    subject_id = Column(Integer, ForeignKey("subjects.subject_id", ondelete="CASCADE"), nullable=False)
    class_date = Column(Date, nullable=False, index=True)
    start_time = Column(TIME, nullable=False)
    end_time = Column(TIME, nullable=False)


class AttendanceRecord(Base):
    __tablename__ = "attendance_records"
    __table_args__ = (UniqueConstraint("session_id", "student_id", name="unique_session_student"),)

    attendance_record_id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    session_id = Column(Integer, ForeignKey("class_sessions.session_id", ondelete="CASCADE"), nullable=False)
    student_id = Column(Integer, ForeignKey("students.student_id", ondelete="CASCADE"), nullable=False)
    status = Column(Enum("present", "absent", "pending"), nullable=False, default="pending")
    marked_at = Column(TIMESTAMP, nullable=True)


class TimetableSlot(Base):
    """A recurring weekly class slot, e.g. DBMS every Tuesday at 10:00 in Room 204."""

    __tablename__ = "timetable_slots"

    slot_id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    subject_id = Column(Integer, ForeignKey("subjects.subject_id", ondelete="CASCADE"), nullable=False)
    day_of_week = Column(String(10), nullable=False)  # Monday ... Saturday
    start_time = Column(TIME, nullable=False)
    end_time = Column(TIME, nullable=False)
    room = Column(String(50), nullable=True)


class Assignment(Base):
    __tablename__ = "assignments"

    assignment_id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    subject_id = Column(Integer, ForeignKey("subjects.subject_id", ondelete="CASCADE"), nullable=False)
    title = Column(String(150), nullable=False)
    description = Column(Text, nullable=True)
    due_date = Column(Date, nullable=False, index=True)


class AssignmentSubmission(Base):
    """Marks an assignment as submitted by one student."""

    __tablename__ = "assignment_submissions"
    __table_args__ = (UniqueConstraint("assignment_id", "student_id", name="unique_assignment_student"),)

    submission_id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    assignment_id = Column(Integer, ForeignKey("assignments.assignment_id", ondelete="CASCADE"), nullable=False)
    student_id = Column(Integer, ForeignKey("students.student_id", ondelete="CASCADE"), nullable=False)
    submitted_at = Column(TIMESTAMP, server_default=func.current_timestamp())


class Exam(Base):
    __tablename__ = "exams"

    exam_id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    subject_id = Column(Integer, ForeignKey("subjects.subject_id", ondelete="CASCADE"), nullable=False)
    exam_type = Column(String(50), nullable=False)  # Mid-Semester, End-Semester, ...
    exam_date = Column(Date, nullable=False, index=True)
    start_time = Column(TIME, nullable=True)
    room = Column(String(50), nullable=True)


class FeeStructure(Base):
    """What a semester costs for a given department - used when a new student registers."""

    __tablename__ = "fee_structures"
    __table_args__ = (UniqueConstraint("department", "semester", name="unique_department_semester"),)

    fee_structure_id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    department = Column(String(50), nullable=False)
    semester = Column(Integer, nullable=False)
    total_amount = Column(Numeric(10, 2), nullable=False)
    due_date = Column(Date, nullable=False)


class FeeAccount(Base):
    """One student's fee ledger for one semester."""

    __tablename__ = "fee_accounts"
    __table_args__ = (UniqueConstraint("student_id", "semester", name="unique_student_semester"),)

    fee_account_id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    student_id = Column(Integer, ForeignKey("students.student_id", ondelete="CASCADE"), nullable=False)
    semester = Column(Integer, nullable=False)
    total_amount = Column(Numeric(10, 2), nullable=False)
    paid_amount = Column(Numeric(10, 2), nullable=False, default=0)
    due_date = Column(Date, nullable=False)


class CampusDocument(Base):
    """A campus document (policy, regulation, notice) the assistant can quote from."""

    __tablename__ = "campus_documents"

    document_id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    title = Column(String(150), nullable=False)
    category = Column(String(50), nullable=False)  # policy, regulation, notice, syllabus
    department = Column(String(50), nullable=True)  # null means it applies college-wide
    owner_student_id = Column(Integer, ForeignKey("students.student_id", ondelete="CASCADE"), nullable=True)
    created_at = Column(TIMESTAMP, server_default=func.current_timestamp())


class DocumentChunk(Base):
    """One retrievable passage of a campus document, with its embedding vector."""

    __tablename__ = "document_chunks"

    chunk_id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    document_id = Column(Integer, ForeignKey("campus_documents.document_id", ondelete="CASCADE"), nullable=False)
    page_number = Column(Integer, nullable=True)
    content = Column(Text, nullable=False)
    embedding = Column(Text, nullable=True)  # JSON array of floats, kept for SQL fallback


class ChatSession(Base):
    """A persistent conversation session for a student."""

    __tablename__ = "chat_sessions"

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    student_id = Column(Integer, ForeignKey("students.student_id", ondelete="CASCADE"), nullable=False, index=True)
    title = Column(String(200), nullable=False)
    created_at = Column(TIMESTAMP, server_default=func.current_timestamp())
    updated_at = Column(TIMESTAMP, server_default=func.current_timestamp(), onupdate=func.current_timestamp())


class ChatMessage(Base):
    """One message within a student's chat session."""

    __tablename__ = "chat_messages"

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    session_id = Column(Integer, ForeignKey("chat_sessions.id", ondelete="CASCADE"), nullable=False, index=True)
    role = Column(String(20), nullable=False)  # "user" or "assistant"
    content = Column(Text, nullable=False)
    type = Column(String(50), nullable=True, default="text")
    data = Column(Text, nullable=True)  # JSON string
    sources = Column(Text, nullable=True)  # JSON string
    activity_steps = Column(Text, nullable=True)  # JSON string
    created_at = Column(TIMESTAMP, server_default=func.current_timestamp())


class CampusInfo(Base):
    """General campus knowledge (e.g. office hours, library timings)."""

    __tablename__ = "campus_info"

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    category = Column(String(50), nullable=False, index=True)
    key = Column(String(100), nullable=False, index=True)
    value = Column(Text, nullable=False)
    department = Column(String(50), nullable=True)
    updated_at = Column(TIMESTAMP, server_default=func.current_timestamp(), onupdate=func.current_timestamp())


class CampusEvent(Base):
    """Campus events, activities, and workshops."""

    __tablename__ = "campus_events"

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    title = Column(String(150), nullable=False)
    description = Column(Text, nullable=True)
    location = Column(String(100), nullable=True)
    starts_at = Column(TIMESTAMP, nullable=False, index=True)
    ends_at = Column(TIMESTAMP, nullable=True)
    category = Column(String(50), nullable=False, index=True)
    is_demo = Column(Integer, nullable=False, default=1)
