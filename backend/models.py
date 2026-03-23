"""
models.py
─────────
SQLAlchemy ORM models.

Tables
──────
  Project       — top-level grouping (e.g. "E-Commerce App")
  Release       — one row per release cycle (e.g. "v2.3.0")
  TestCase      — deduplicated test cases identified by (project_id, title, module)
  TestExecution — one row per test case per release — stores AI analysis results

Relationships
─────────────
  Project   1──* Release
  Project   1──* TestCase
  Release   1──* TestExecution
  TestCase  1──* TestExecution
"""

from datetime import datetime, timezone
from sqlalchemy import (
    Column, Integer, String, Float, Text,
    DateTime, ForeignKey, UniqueConstraint, Index,
)
from sqlalchemy.orm import relationship
from database import Base


def _now() -> datetime:
    """UTC-aware current timestamp."""
    return datetime.now(timezone.utc)


# ── Project ───────────────────────────────────────────────────────────────────
class Project(Base):
    __tablename__ = "projects"

    id         = Column(Integer, primary_key=True, index=True)
    name       = Column(String(255), unique=True, nullable=False)
    created_at = Column(DateTime, default=_now, nullable=False)

    # Relationships
    releases   = relationship("Release",  back_populates="project", cascade="all, delete-orphan")
    test_cases = relationship("TestCase", back_populates="project", cascade="all, delete-orphan")

    def __repr__(self):
        return f"<Project id={self.id} name={self.name!r}>"


# ── Release ───────────────────────────────────────────────────────────────────
class Release(Base):
    __tablename__ = "releases"

    id           = Column(Integer, primary_key=True, index=True)
    project_id   = Column(Integer, ForeignKey("projects.id", ondelete="CASCADE"), nullable=False)
    release_name = Column(String(255), nullable=False)   # e.g. "v2.3.0" or "Sprint-14"
    release_date = Column(DateTime, default=_now, nullable=False)

    # Relationships
    project    = relationship("Project",       back_populates="releases")
    executions = relationship("TestExecution", back_populates="release", cascade="all, delete-orphan")

    # A project cannot have two releases with the same name
    __table_args__ = (
        UniqueConstraint("project_id", "release_name", name="uq_project_release"),
    )

    def __repr__(self):
        return f"<Release id={self.id} name={self.release_name!r} project={self.project_id}>"


# ── TestCase ──────────────────────────────────────────────────────────────────
class TestCase(Base):
    __tablename__ = "test_cases"

    id          = Column(Integer, primary_key=True, index=True)
    project_id  = Column(Integer, ForeignKey("projects.id", ondelete="CASCADE"), nullable=False)
    module      = Column(String(255), nullable=True)
    title       = Column(String(500), nullable=False)
    description = Column(Text,        nullable=True)
    severity    = Column(String(50),  nullable=True)
    created_at  = Column(DateTime, default=_now, nullable=False)
    updated_at  = Column(DateTime, default=_now, onupdate=_now, nullable=False)

    # Relationships
    project    = relationship("Project",       back_populates="test_cases")
    executions = relationship("TestExecution", back_populates="test_case", cascade="all, delete-orphan")

    # Same title+module is one logical test case inside a project
    __table_args__ = (
        UniqueConstraint("project_id", "title", "module", name="uq_project_testcase"),
        Index("ix_test_cases_project_module", "project_id", "module"),
    )

    def __repr__(self):
        return f"<TestCase id={self.id} title={self.title[:40]!r}>"


# ── TestExecution ─────────────────────────────────────────────────────────────
class TestExecution(Base):
    __tablename__ = "test_executions"

    id             = Column(Integer, primary_key=True, index=True)
    test_case_id   = Column(Integer, ForeignKey("test_cases.id", ondelete="CASCADE"), nullable=False)
    release_id     = Column(Integer, ForeignKey("releases.id",   ondelete="CASCADE"), nullable=False)

    # AI analysis results
    risk_score     = Column(Integer,      nullable=True)   # 1-10
    priority       = Column(String(10),   nullable=True)   # P1 / P2 / P3
    ai_explanation = Column(Text,         nullable=True)
    ai_source      = Column(String(50),   nullable=True)   # gemini / openai / ollama / heuristic

    # Release-aware fields (nullable — only populated in release-aware mode)
    base_score     = Column(Integer,      nullable=True)
    adjusted_score = Column(Integer,      nullable=True)
    adj_reason     = Column(Text,         nullable=True)

    # Execution plan
    recommended    = Column(String(5),    nullable=True)   # "Yes" / "No"
    execution_date = Column(DateTime, default=_now, nullable=False)

    # Relationships
    test_case = relationship("TestCase", back_populates="executions")
    release   = relationship("Release",  back_populates="executions")

    # One execution record per test case per release
    __table_args__ = (
        UniqueConstraint("test_case_id", "release_id", name="uq_execution_per_release"),
        Index("ix_executions_release", "release_id"),
        Index("ix_executions_testcase", "test_case_id"),
    )

    def __repr__(self):
        return (
            f"<TestExecution id={self.id} "
            f"tc={self.test_case_id} release={self.release_id} "
            f"priority={self.priority}>"
        )