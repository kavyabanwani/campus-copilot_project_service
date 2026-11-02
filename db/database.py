import logging
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker, declarative_base
from config import settings

logger = logging.getLogger("campus_copilot.db")

connect_args = {"check_same_thread": False} if settings.DATABASE_URL.startswith("sqlite") else {}
engine = create_engine(settings.DATABASE_URL, connect_args=connect_args)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


def init_db_and_migrations(bind=engine) -> None:
    """Create all missing tables and run idempotent migrations on existing ones."""
    Base.metadata.create_all(bind=bind)

    with bind.connect() as connection:
        # SQLite schema migrations for new columns on existing tables
        if bind.dialect.name == "sqlite":
            try:
                student_cols = [r[1] for r in connection.execute(text("PRAGMA table_info(students)")).fetchall()]
                if student_cols and "role" not in student_cols:
                    logger.info("Migrating students table: adding 'role' column")
                    connection.execute(text("ALTER TABLE students ADD COLUMN role VARCHAR(20) NOT NULL DEFAULT 'student'"))
                    connection.commit()
            except Exception as e:
                logger.warning("Could not check/alter students table: %s", e)

            try:
                doc_cols = [r[1] for r in connection.execute(text("PRAGMA table_info(campus_documents)")).fetchall()]
                if doc_cols and "owner_student_id" not in doc_cols:
                    logger.info("Migrating campus_documents table: adding 'owner_student_id' column")
                    connection.execute(text("ALTER TABLE campus_documents ADD COLUMN owner_student_id INTEGER REFERENCES students(student_id)"))
                    connection.commit()
            except Exception as e:
                logger.warning("Could not check/alter campus_documents table: %s", e)


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()