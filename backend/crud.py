"""
crud.py
───────
All database Create / Read / Update / Delete operations.

Rules
─────
  - No FastAPI imports here — pure SQLAlchemy + Python.
  - All functions accept a Session as their first argument.
  - Route handlers call these functions; they never touch the DB directly.
  - Upsert pattern used for TestCase so re-uploading the same Excel
    updates description/severity instead of creating duplicates.
"""

from datetime import datetime, timezone
from typing import Optional

from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError

from models import Project, Release, TestCase, TestExecution
from config import logger


# ── Project ───────────────────────────────────────────────────────────────────

def get_or_create_project(db: Session, name: str) -> Project:
    """
    Return existing project by name, or create it if it doesn't exist.
    Safe to call on every upload — idempotent.
    """
    project = db.query(Project).filter(Project.name == name).first()
    if not project:
        project = Project(name=name)
        db.add(project)
        db.flush()   # get id without committing
        logger.info(f"[DB] Created project: {name!r} (id={project.id})")
    return project


def get_all_projects(db: Session) -> list[Project]:
    return db.query(Project).order_by(Project.created_at.desc()).all()


def get_project_by_id(db: Session, project_id: int) -> Optional[Project]:
    return db.query(Project).filter(Project.id == project_id).first()


# ── Release ───────────────────────────────────────────────────────────────────

def create_release(db: Session, project_id: int, release_name: str) -> Release:
    """
    Create a new release record.
    If a release with the same name already exists for this project,
    return the existing one (handles duplicate uploads gracefully).
    """
    existing = (
        db.query(Release)
        .filter(Release.project_id == project_id, Release.release_name == release_name)
        .first()
    )
    if existing:
        logger.info(f"[DB] Release {release_name!r} already exists for project {project_id} — reusing")
        return existing

    release = Release(
        project_id   = project_id,
        release_name = release_name,
        release_date = datetime.now(timezone.utc),
    )
    db.add(release)
    db.flush()
    logger.info(f"[DB] Created release: {release_name!r} (id={release.id})")
    return release


def get_releases_for_project(db: Session, project_id: int) -> list[Release]:
    return (
        db.query(Release)
        .filter(Release.project_id == project_id)
        .order_by(Release.release_date.desc())
        .all()
    )


def get_release_by_id(db: Session, release_id: int) -> Optional[Release]:
    return db.query(Release).filter(Release.id == release_id).first()


# ── TestCase ──────────────────────────────────────────────────────────────────

def upsert_test_case(
    db:          Session,
    project_id:  int,
    title:       str,
    module:      str       = "",
    description: str       = "",
    severity:    str       = "",
) -> TestCase:
    """
    Insert a new test case or update description/severity if it already exists.
    Uniqueness is defined by (project_id, title, module).
    Returns the TestCase ORM object with a valid id.
    """
    tc = (
        db.query(TestCase)
        .filter(
            TestCase.project_id == project_id,
            TestCase.title      == title,
            TestCase.module     == (module or None),
        )
        .first()
    )

    if tc:
        # Update mutable fields in case they changed
        tc.description = description or tc.description
        tc.severity    = severity    or tc.severity
        tc.updated_at  = datetime.now(timezone.utc)
    else:
        tc = TestCase(
            project_id  = project_id,
            title       = title,
            module      = module      or None,
            description = description or None,
            severity    = severity    or None,
        )
        db.add(tc)
        db.flush()

    return tc


def get_test_cases_for_project(db: Session, project_id: int) -> list[TestCase]:
    return (
        db.query(TestCase)
        .filter(TestCase.project_id == project_id)
        .order_by(TestCase.module, TestCase.title)
        .all()
    )


# ── TestExecution ─────────────────────────────────────────────────────────────

def upsert_execution(
    db:             Session,
    test_case_id:   int,
    release_id:     int,
    risk_score:     Optional[int]   = None,
    priority:       Optional[str]   = None,
    ai_explanation: Optional[str]   = None,
    ai_source:      Optional[str]   = None,
    base_score:     Optional[int]   = None,
    adjusted_score: Optional[int]   = None,
    adj_reason:     Optional[str]   = None,
    recommended:    Optional[str]   = None,
) -> TestExecution:
    """
    Insert or update a TestExecution record.
    If the same test_case_id + release_id already exists, update its AI fields.
    This allows re-running analysis on the same release without duplicates.
    """
    execution = (
        db.query(TestExecution)
        .filter(
            TestExecution.test_case_id == test_case_id,
            TestExecution.release_id   == release_id,
        )
        .first()
    )

    if execution:
        execution.risk_score     = risk_score
        execution.priority       = priority
        execution.ai_explanation = ai_explanation
        execution.ai_source      = ai_source
        execution.base_score     = base_score
        execution.adjusted_score = adjusted_score
        execution.adj_reason     = adj_reason
        execution.recommended    = recommended
        execution.execution_date = datetime.now(timezone.utc)
    else:
        execution = TestExecution(
            test_case_id   = test_case_id,
            release_id     = release_id,
            risk_score     = risk_score,
            priority       = priority,
            ai_explanation = ai_explanation,
            ai_source      = ai_source,
            base_score     = base_score,
            adjusted_score = adjusted_score,
            adj_reason     = adj_reason,
            recommended    = recommended,
        )
        db.add(execution)
        db.flush()

    return execution


def get_executions_for_release(db: Session, release_id: int) -> list[TestExecution]:
    return (
        db.query(TestExecution)
        .filter(TestExecution.release_id == release_id)
        .order_by(TestExecution.risk_score.desc())
        .all()
    )


def get_execution_history(db: Session, test_case_id: int) -> list[TestExecution]:
    """Return all executions for a test case across all releases, newest first."""
    return (
        db.query(TestExecution)
        .filter(TestExecution.test_case_id == test_case_id)
        .order_by(TestExecution.execution_date.desc())
        .all()
    )


# ── NEW: Historical adjustment helpers ────────────────────────────────────────

def get_previous_release_execution(
    db: Session,
    test_case_id: int,
    current_release_id: int,
) -> Optional[TestExecution]:
    """
    Return the most recent TestExecution for this test case from any release
    that was created BEFORE the current release (same project).

    Used for Rule 1: if it failed in the previous release → +2.
    Returns None if no prior execution exists.
    """
    current_release = db.query(Release).filter(Release.id == current_release_id).first()
    if not current_release:
        return None

    result = (
        db.query(TestExecution)
        .join(Release, TestExecution.release_id == Release.id)
        .filter(
            TestExecution.test_case_id == test_case_id,
            Release.id                 != current_release_id,
            Release.project_id         == current_release.project_id,
            Release.release_date       <  current_release.release_date,
        )
        .order_by(Release.release_date.desc())
        .first()
    )
    return result


def get_unexecuted_release_count(
    db: Session,
    test_case_id: int,
    current_release_id: int,
) -> int:
    """
    Look at the 3 most recent releases (before the current one, same project).
    Return how many of those releases had NO execution record for this test case.

    Used for Rule 2: if not executed for 3 releases → +2.
    Returns 0 if fewer than 3 prior releases exist (not enough history).
    """
    current_release = db.query(Release).filter(Release.id == current_release_id).first()
    if not current_release:
        return 0

    # Fetch the 3 most recent releases before this one (same project)
    prior_releases = (
        db.query(Release)
        .filter(
            Release.project_id   == current_release.project_id,
            Release.id           != current_release_id,
            Release.release_date <  current_release.release_date,
        )
        .order_by(Release.release_date.desc())
        .limit(3)
        .all()
    )

    # Need exactly 3 prior releases to apply this rule
    if len(prior_releases) < 3:
        return 0

    prior_ids = [r.id for r in prior_releases]

    executed_count = (
        db.query(TestExecution)
        .filter(
            TestExecution.test_case_id == test_case_id,
            TestExecution.release_id.in_(prior_ids),
        )
        .count()
    )

    # Return number of releases where this test case was NOT executed
    return len(prior_ids) - executed_count


# ── Bulk save helper (called from regression route) ───────────────────────────

def save_regression_results(
    db:           Session,
    project_name: str,
    release_name: str,
    rows:         list[dict],    # original Excel rows as dicts
    results:      list[dict],    # AI analysis results (one per row)
    df_sorted,                   # final sorted DataFrame (has Recommended col)
    release_mode: bool = False,
) -> tuple[int, int, int]:
    """
    Persist an entire regression analysis run to the database.

    Steps:
      1. Get or create Project
      2. Create Release
      3. Upsert each TestCase
      4. Upsert each TestExecution with AI results

    Returns (project_id, release_id, saved_count).
    Commits the transaction at the end.
    Rolls back and logs on any error — never raises so the Excel report
    is always returned to the user even if DB save fails.
    """
    try:
        # 1. Project
        project = get_or_create_project(db, project_name)

        # 2. Release
        release = create_release(db, project.id, release_name)

        # Build a lookup: original row index → "Recommended" value from sorted df
        # df_sorted has a reset index so we match by title
        recommended_titles = set(
            df_sorted[df_sorted["Recommended for Execution"] == "Yes"]
            .apply(lambda r: str(r.get("Title") or r.get("title") or ""), axis=1)
            .tolist()
        )

        saved = 0
        for i, (row, result) in enumerate(zip(rows, results)):
            from utils.helpers import safe_str
            title       = safe_str(row.get("title") or row.get("Title") or row.get("Test Case Title"), f"TC-{i+1}")
            module      = str(row.get("module") or row.get("Module") or row.get("Module Name") or "")
            description = safe_str(row.get("description") or row.get("Description") or row.get("Test Description"), "")
            severity    = safe_str(row.get("severity") or row.get("Severity"), "")

            # 3. TestCase upsert
            tc = upsert_test_case(
                db          = db,
                project_id  = project.id,
                title       = title,
                module      = module,
                description = description,
                severity    = severity,
            )

            # 4. TestExecution upsert
            recommended = "Yes" if title in recommended_titles else "No"

            upsert_execution(
                db             = db,
                test_case_id   = tc.id,
                release_id     = release.id,
                risk_score     = result.get("risk_score"),
                priority       = result.get("priority"),
                ai_explanation = result.get("explanation"),
                ai_source      = result.get("source") or result.get("mode"),
                base_score     = result.get("base_score"),
                adjusted_score = result.get("adjusted_score"),
                adj_reason     = result.get("adj_reason"),
                recommended    = recommended,
            )
            saved += 1

        db.commit()
        logger.info(f"[DB] Saved {saved} executions → project={project.id}, release={release.id}")
        return project.id, release.id, saved

    except Exception as e:
        db.rollback()
        logger.error(f"[DB] Failed to save regression results: {e}")
        return 0, 0, 0