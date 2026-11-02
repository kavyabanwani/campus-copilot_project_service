from datetime import datetime, timedelta, timezone

from jose import jwt

from config import settings


def create_access_token(student_id: int) -> str:
	expires_at = datetime.now(timezone.utc) + timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
	payload = {"sub": str(student_id), "exp": expires_at}
	return jwt.encode(payload, settings.SECRET_KEY, algorithm=settings.ALGORITHM)
