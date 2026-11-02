import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from ai_router import router as ai_router
from attendance_router import router as attendance_router
from auth.auth_router import router as auth_router
from chat_router import router as chat_router
from config import settings
from db import models  # noqa: F401
from db.database import engine, init_db_and_migrations
from document_router import router as document_router
import llm_client
from meta_router import router as meta_router
from student_router import router as student_router

logger = logging.getLogger("campus_copilot")

limiter = Limiter(key_func=get_remote_address)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Lifespan event handler: prepare tables and run schema migrations safely."""
    try:
        init_db_and_migrations(bind=engine)
        logger.info("Database initialized and verified.")
    except SQLAlchemyError as error:
        logger.error(
            "Could not connect to the database at %s: %s",
            engine.url,
            error,
        )
        raise
    yield


app = FastAPI(title="Campus Copilot Service", lifespan=lifespan)

# Rate limiting
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

# CORS restricted to configured origins
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    """Catch unhandled exceptions and return safe, consistent error JSON without leaking stack traces or keys."""
    logger.exception("Unhandled server exception on %s %s: %s", request.method, request.url.path, exc)
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={"detail": "An internal error occurred. Please try again shortly."},
    )


# Register routers
app.include_router(auth_router)
app.include_router(student_router)
app.include_router(attendance_router)
app.include_router(ai_router)
app.include_router(document_router)
app.include_router(chat_router)
app.include_router(meta_router)


@app.get("/health")
def health_check():
    """Service health and component status check."""
    database_ok = True
    try:
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))
    except SQLAlchemyError:
        database_ok = False

    return {
        "status": "ok",
        "database": "connected" if database_ok else "unavailable",
        "ai": "configured" if llm_client.is_configured() else "not configured",
        "provider": llm_client.provider(),
        "model": llm_client.model_name(),
    }
