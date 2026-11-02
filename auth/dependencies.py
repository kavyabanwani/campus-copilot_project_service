from typing import Optional
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError, jwt
from sqlalchemy.orm import Session

from config import settings
from db.database import get_db
from db.models import Student


bearer_scheme = HTTPBearer(auto_error=False)


def get_current_student(
	credentials: Optional[HTTPAuthorizationCredentials] = Depends(bearer_scheme),
	db: Session = Depends(get_db),
) -> Student:
	unauthorized = HTTPException(
		status_code=status.HTTP_401_UNAUTHORIZED,
		detail="Invalid or expired session. Please sign in again.",
		headers={"WWW-Authenticate": "Bearer"},
	)
	if not credentials or not credentials.credentials:
		raise unauthorized

	try:
		payload = jwt.decode(credentials.credentials, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])
		student_id = int(payload.get("sub"))
	except (JWTError, TypeError, ValueError):
		raise unauthorized

	student = db.query(Student).filter(Student.student_id == student_id).first()
	if not student:
		raise unauthorized
	return student
