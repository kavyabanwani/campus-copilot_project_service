from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from auth.auth_service import hash_password, verify_password
from auth.dependencies import get_current_student
from auth.jwt_handler import create_access_token
from enrollment import ensure_student_environment
from db.database import get_db
from db.models import Student
from db.schemas import AuthResponse, PasswordChangeRequest, StudentCreate, StudentLogin, StudentOut
from slowapi import Limiter
from slowapi.util import get_remote_address

limiter = Limiter(key_func=get_remote_address)
router = APIRouter(prefix="/auth", tags=["auth"])

VALID_DEPARTMENTS = {
    "Computer Science",
    "Electronics & Communication",
    "Mechanical Engineering",
    "Civil Engineering",
    "Electrical Engineering",
}


def _validate_password(password: str) -> None:
    if len(password) < 8:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Password must be at least 8 characters long.",
        )
    if len(password.encode("utf-8")) > 72:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Password must not exceed 72 bytes.",
        )


@router.post("/login", response_model=AuthResponse)
@limiter.limit("20/minute")
def login_student(request: Request, credentials: StudentLogin, db: Session = Depends(get_db)):
    identifier = credentials.email.strip().lower()
    student = (
        db.query(Student)
        .filter((Student.email == identifier) | (Student.roll_number == credentials.email.strip()))
        .first()
    )
    if not student or not verify_password(credentials.password, student.password_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email/roll number or password.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    ensure_student_environment(db, student)
    return AuthResponse(access_token=create_access_token(student.student_id), student=student)


@router.post("/register", response_model=AuthResponse, status_code=status.HTTP_201_CREATED)
@limiter.limit("10/minute")
def register_student(request: Request, student_data: StudentCreate, db: Session = Depends(get_db)):
    clean_email = student_data.email.strip().lower()
    clean_roll = student_data.roll_number.strip().upper()
    clean_dept = student_data.department.strip()

    _validate_password(student_data.password)

    if clean_dept not in VALID_DEPARTMENTS:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Invalid department '{clean_dept}'. Allowed departments: {', '.join(sorted(VALID_DEPARTMENTS))}",
        )

    if student_data.semester < 1 or student_data.semester > 8:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Semester must be an integer between 1 and 8.",
        )

    existing_student = (
        db.query(Student)
        .filter(
            (Student.email == clean_email) | (Student.roll_number == clean_roll)
        )
        .first()
    )
    if existing_student:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="A student with this email or roll number already exists.",
        )

    new_student = Student(
        roll_number=clean_roll,
        full_name=student_data.full_name.strip(),
        email=clean_email,
        department=clean_dept,
        semester=student_data.semester,
        password_hash=hash_password(student_data.password),
        role="student",
    )
    db.add(new_student)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="A student with this email or roll number already exists.",
        )

    db.refresh(new_student)
    ensure_student_environment(db, new_student)
    return AuthResponse(access_token=create_access_token(new_student.student_id), student=new_student)


@router.post("/change-password")
def change_password(
    req: PasswordChangeRequest,
    current_student: Student = Depends(get_current_student),
    db: Session = Depends(get_db),
):
    """Change the signed-in student's password."""
    if not verify_password(req.current_password, current_student.password_hash):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Current password is incorrect.",
        )

    _validate_password(req.new_password)

    current_student.password_hash = hash_password(req.new_password)
    db.commit()
    return {"status": "ok", "message": "Password changed successfully."}


@router.get("/me", response_model=StudentOut)
def get_signed_in_student(current_student: Student = Depends(get_current_student)):
    """Returns the student the token belongs to, so a page refresh keeps them signed in."""
    return current_student
