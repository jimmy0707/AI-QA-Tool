"""
database.py
───────────
SQLAlchemy engine + session factory.

SQLite now — swap DATABASE_URL env var to PostgreSQL later with zero code changes:
  PostgreSQL: postgresql+psycopg2://user:pass@host/dbname
  SQLite:     sqlite:///./qa_platform.db   (default)

Usage in route handlers:
    from database import get_db
    db: Session = next(get_db())          # manual
    # or use FastAPI dependency injection:
    async def my_route(db: Session = Depends(get_db)): ...
"""

import os
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, DeclarativeBase

# ── Connection URL ────────────────────────────────────────────────────────────
DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "sqlite:///./qa_platform.db"   # file lives next to main.py
)

# ── Engine ────────────────────────────────────────────────────────────────────
# connect_args only needed for SQLite (disables same-thread check for FastAPI)
_connect_args = {"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {}

engine = create_engine(
    DATABASE_URL,
    connect_args=_connect_args,
    echo=False,          # set True to log all SQL — useful for debugging
)

# ── Session factory ───────────────────────────────────────────────────────────
SessionLocal = sessionmaker(
    bind=engine,
    autocommit=False,
    autoflush=False,
)

# ── Declarative base (all ORM models inherit from this) ───────────────────────
class Base(DeclarativeBase):
    pass


# ── FastAPI dependency ────────────────────────────────────────────────────────
def get_db():
    """
    Yield a database session and guarantee it is closed after the request,
    even if an exception is raised.

    Use as a FastAPI dependency:
        db: Session = Depends(get_db)
    """
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


# ── Table creation ────────────────────────────────────────────────────────────
def init_db():
    """
    Create all tables that don't exist yet.
    Called once at application startup from main.py.
    Safe to call multiple times — CREATE TABLE IF NOT EXISTS semantics.
    """
    # Import models here so Base.metadata is populated before create_all
    import models  # noqa: F401
    Base.metadata.create_all(bind=engine)