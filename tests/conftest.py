import os
import sys
import tempfile

BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)

TEMP_DB = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
TEMP_DB_PATH = TEMP_DB.name
TEMP_DB.close()

os.environ["SECRET_KEY"] = "test-secret-key-that-is-long-enough-for-testing-32bytes"
os.environ["DATABASE_URL"] = f"sqlite:///{TEMP_DB_PATH}"

import pytest
from fastapi.testclient import TestClient

from auth.auth_service import hash_password
from auth.jwt_handler import create_access_token
from db.database import Base, SessionLocal, engine, get_db
from db.models import CampusDocument, DocumentChunk, Student
from enrollment import ensure_student_environment
from main import app
import seed_data


@pytest.fixture(scope="session", autouse=True)
def setup_test_database():
    Base.metadata.create_all(bind=engine)
    session = SessionLocal()
    seed_data.seed_subjects(session, "Computer Science", 4)
    seed_data.seed_campus_info_and_events(session)
    for title, cat, text in seed_data.POLICY_DOCUMENTS:
        doc = CampusDocument(title=title, category=cat, department=None)
        session.add(doc)
        session.flush()
        session.add(DocumentChunk(document_id=doc.document_id, page_number=1, content=text))
    session.commit()
    session.close()

    yield

    try:
        if os.path.exists(TEMP_DB_PATH):
            os.remove(TEMP_DB_PATH)
    except OSError:
        pass


@pytest.fixture(scope="function")
def db():
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture(scope="function")
def client():
    def override_get_db():
        session = SessionLocal()
        try:
            yield session
        finally:
            session.close()

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


@pytest.fixture(scope="function")
def student_a(db):
    existing = db.query(Student).filter(Student.email == "alice@campus.edu").first()
    if existing:
        return existing
    student = Student(
        roll_number="CS22B001",
        full_name="Alice Student",
        email="alice@campus.edu",
        department="Computer Science",
        semester=4,
        password_hash=hash_password("Password123"),
        role="student",
    )
    db.add(student)
    db.commit()
    db.refresh(student)
    ensure_student_environment(db, student)
    return student


@pytest.fixture(scope="function")
def student_b(db):
    existing = db.query(Student).filter(Student.email == "bob@campus.edu").first()
    if existing:
        return existing
    student = Student(
        roll_number="CS22B002",
        full_name="Bob Student",
        email="bob@campus.edu",
        department="Computer Science",
        semester=4,
        password_hash=hash_password("Password123"),
        role="student",
    )
    db.add(student)
    db.commit()
    db.refresh(student)
    ensure_student_environment(db, student)
    return student


@pytest.fixture(scope="function")
def admin_user(db):
    existing = db.query(Student).filter(Student.email == "admin_test@campus.edu").first()
    if existing:
        return existing
    admin = Student(
        roll_number="ADMIN001",
        full_name="Administrator User",
        email="admin_test@campus.edu",
        department="Computer Science",
        semester=4,
        password_hash=hash_password("AdminPass123"),
        role="admin",
    )
    db.add(admin)
    db.commit()
    db.refresh(admin)
    return admin


@pytest.fixture(scope="function")
def auth_headers_a(student_a):
    token = create_access_token(student_a.student_id)
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture(scope="function")
def auth_headers_b(student_b):
    token = create_access_token(student_b.student_id)
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture(scope="function")
def auth_headers_admin(admin_user):
    token = create_access_token(admin_user.student_id)
    return {"Authorization": f"Bearer {token}"}
