"""
routers/dashboard.py
─────────────────────
All dashboard analytics endpoints.

GET /api/projects                              → projects with release + testcase counts
GET /api/dashboard/releases?project_id=       → all releases for a project with P1/P2/P3
GET /api/dashboard/compare?release1=&release2= → side-by-side release comparison
GET /api/dashboard/module-risk?release_id=     → avg risk score per module
GET /api/dashboard/execution-history?project_id= → trend data for line chart
GET /api/dashboard/top-risk?release_id=        → top 10 highest risk test cases
GET /api/dashboard/summary?project_id=         → single-card summary for hero stats
DELETE /api/releases/{release_id}              → delete release + cascade executions
"""

from fastapi import APIRouter, HTTPException, Query
from sqlalchemy import func, case
from sqlalchemy.orm import Session

from database import SessionLocal
from models import Project, Release, TestCase, TestExecution

router = APIRouter()


def _get_db() -> Session:
    return SessionLocal()


# ── 1. Projects list with counts ──────────────────────────────────────────────
@router.get("/api/projects")
def list_projects():
    """
    All projects with total_releases and total_testcases aggregated.
    Uses two sub-queries so no Python-side loops.
    """
    db = _get_db()
    try:
        # Subquery: releases per project
        rel_sq = (
            db.query(
                Release.project_id,
                func.count(Release.id).label("total_releases"),
            )
            .group_by(Release.project_id)
            .subquery()
        )

        # Subquery: unique test cases per project
        tc_sq = (
            db.query(
                TestCase.project_id,
                func.count(TestCase.id).label("total_testcases"),
            )
            .group_by(TestCase.project_id)
            .subquery()
        )

        rows = (
            db.query(
                Project.id,
                Project.name,
                Project.created_at,
                func.coalesce(rel_sq.c.total_releases,  0).label("total_releases"),
                func.coalesce(tc_sq.c.total_testcases,  0).label("total_testcases"),
            )
            .outerjoin(rel_sq, Project.id == rel_sq.c.project_id)
            .outerjoin(tc_sq,  Project.id == tc_sq.c.project_id)
            .order_by(Project.created_at.desc())
            .all()
        )

        return [
            {
                "id":              r.id,
                "name":            r.name,
                "created_at":      r.created_at.isoformat(),
                "total_releases":  r.total_releases,
                "total_testcases": r.total_testcases,
            }
            for r in rows
        ]
    finally:
        db.close()


# ── 2. Release overview for a project ─────────────────────────────────────────
@router.get("/api/dashboard/releases")
def release_overview(project_id: int = Query(..., description="Project ID")):
    """
    All releases for a project.
    Each row contains total tests + P1/P2/P3 counts — all in one SQL query.
    """
    db = _get_db()
    try:
        project = db.query(Project).filter(Project.id == project_id).first()
        if not project:
            raise HTTPException(status_code=404, detail="Project not found")

        rows = (
            db.query(
                Release.id.label("release_id"),
                Release.release_name,
                Release.release_date,
                func.count(TestExecution.id).label("total_tests"),
                func.sum(
                    case((TestExecution.priority == "P1", 1), else_=0)
                ).label("p1"),
                func.sum(
                    case((TestExecution.priority == "P2", 1), else_=0)
                ).label("p2"),
                func.sum(
                    case((TestExecution.priority == "P3", 1), else_=0)
                ).label("p3"),
                func.coalesce(
                    func.avg(TestExecution.risk_score), 0
                ).label("avg_risk"),
            )
            .join(TestExecution, Release.id == TestExecution.release_id, isouter=True)
            .filter(Release.project_id == project_id)
            .group_by(Release.id)
            .order_by(Release.release_date.asc())
            .all()
        )

        return [
            {
                "release_id":   r.release_id,
                "release_name": r.release_name,
                "date":         r.release_date.strftime("%Y-%m-%d"),
                "total_tests":  r.total_tests or 0,
                "p1":           r.p1 or 0,
                "p2":           r.p2 or 0,
                "p3":           r.p3 or 0,
                "avg_risk":     round(float(r.avg_risk or 0), 2),
            }
            for r in rows
        ]
    finally:
        db.close()


# ── 3. Release comparison ──────────────────────────────────────────────────────
@router.get("/api/dashboard/compare")
def compare_releases(
    release1: int = Query(..., description="First release ID"),
    release2: int = Query(..., description="Second release ID"),
):
    """
    Side-by-side comparison of two releases.
    Computes P1/P2/P3 deltas and derives risk_trend label.
    """
    db = _get_db()
    try:
        def _release_stats(rid: int):
            row = (
                db.query(
                    Release.release_name,
                    Release.release_date,
                    func.count(TestExecution.id).label("total"),
                    func.sum(case((TestExecution.priority == "P1", 1), else_=0)).label("p1"),
                    func.sum(case((TestExecution.priority == "P2", 1), else_=0)).label("p2"),
                    func.sum(case((TestExecution.priority == "P3", 1), else_=0)).label("p3"),
                    func.coalesce(func.avg(TestExecution.risk_score), 0).label("avg_risk"),
                )
                .join(TestExecution, Release.id == TestExecution.release_id, isouter=True)
                .filter(Release.id == rid)
                .group_by(Release.id)
                .first()
            )
            if not row:
                raise HTTPException(status_code=404, detail=f"Release {rid} not found")
            return row

        r1 = _release_stats(release1)
        r2 = _release_stats(release2)

        p1_change = int((r2.p1 or 0) - (r1.p1 or 0))
        p2_change = int((r2.p2 or 0) - (r1.p2 or 0))
        p3_change = int((r2.p3 or 0) - (r1.p3 or 0))

        # Risk trend: based on P1 delta — P1 going down = improved
        if p1_change < 0:
            risk_trend = "improved"
        elif p1_change > 0:
            risk_trend = "worsened"
        else:
            risk_trend = "stable"

        avg_risk_change = round(float(r2.avg_risk or 0) - float(r1.avg_risk or 0), 2)

        return {
            "release1":        r1.release_name,
            "release2":        r2.release_name,
            "release1_date":   r1.release_date.strftime("%Y-%m-%d"),
            "release2_date":   r2.release_date.strftime("%Y-%m-%d"),
            "release1_stats":  {"total": r1.total or 0, "p1": r1.p1 or 0, "p2": r1.p2 or 0, "p3": r1.p3 or 0, "avg_risk": round(float(r1.avg_risk or 0), 2)},
            "release2_stats":  {"total": r2.total or 0, "p1": r2.p1 or 0, "p2": r2.p2 or 0, "p3": r2.p3 or 0, "avg_risk": round(float(r2.avg_risk or 0), 2)},
            "p1_change":       p1_change,
            "p2_change":       p2_change,
            "p3_change":       p3_change,
            "avg_risk_change": avg_risk_change,
            "risk_trend":      risk_trend,
        }
    finally:
        db.close()


# ── 4. Module risk analysis ────────────────────────────────────────────────────
@router.get("/api/dashboard/module-risk")
def module_risk(release_id: int = Query(..., description="Release ID")):
    """
    Average risk score per module for a release.
    Sorted descending so the riskiest module is always first.
    """
    db = _get_db()
    try:
        release = db.query(Release).filter(Release.id == release_id).first()
        if not release:
            raise HTTPException(status_code=404, detail="Release not found")

        rows = (
            db.query(
                TestCase.module.label("module"),
                func.round(func.avg(TestExecution.risk_score), 2).label("avg_risk"),
                func.count(TestExecution.id).label("test_count"),
                func.sum(case((TestExecution.priority == "P1", 1), else_=0)).label("p1_count"),
            )
            .join(TestExecution, TestCase.id == TestExecution.test_case_id)
            .filter(TestExecution.release_id == release_id)
            .filter(TestCase.module.isnot(None))
            .group_by(TestCase.module)
            .order_by(func.avg(TestExecution.risk_score).desc())
            .all()
        )

        return [
            {
                "module":     r.module or "Unknown",
                "avg_risk":   float(r.avg_risk or 0),
                "test_count": r.test_count,
                "p1_count":   r.p1_count or 0,
            }
            for r in rows
        ]
    finally:
        db.close()


# ── 5. Execution trend (line chart data) ──────────────────────────────────────
@router.get("/api/dashboard/execution-history")
def execution_history(project_id: int = Query(..., description="Project ID")):
    """
    P1/P2/P3 trend across all releases for line chart.
    Returns parallel arrays: labels + three trend arrays.
    """
    db = _get_db()
    try:
        project = db.query(Project).filter(Project.id == project_id).first()
        if not project:
            raise HTTPException(status_code=404, detail="Project not found")

        rows = (
            db.query(
                Release.release_name,
                Release.release_date,
                func.count(TestExecution.id).label("total"),
                func.sum(case((TestExecution.priority == "P1", 1), else_=0)).label("p1"),
                func.sum(case((TestExecution.priority == "P2", 1), else_=0)).label("p2"),
                func.sum(case((TestExecution.priority == "P3", 1), else_=0)).label("p3"),
                func.coalesce(func.avg(TestExecution.risk_score), 0).label("avg_risk"),
            )
            .join(TestExecution, Release.id == TestExecution.release_id, isouter=True)
            .filter(Release.project_id == project_id)
            .group_by(Release.id)
            .order_by(Release.release_date.asc())
            .all()
        )

        return {
            "labels":    [r.release_name for r in rows],
            "p1_trend":  [int(r.p1 or 0) for r in rows],
            "p2_trend":  [int(r.p2 or 0) for r in rows],
            "p3_trend":  [int(r.p3 or 0) for r in rows],
            "total_trend":    [int(r.total or 0) for r in rows],
            "avg_risk_trend": [round(float(r.avg_risk or 0), 2) for r in rows],
        }
    finally:
        db.close()


# ── 6. Top risk test cases ─────────────────────────────────────────────────────
@router.get("/api/dashboard/top-risk")
def top_risk(
    release_id: int = Query(..., description="Release ID"),
    limit: int = Query(10, description="Number of results", ge=1, le=50),
):
    """
    Top N highest risk test cases for a release.
    Uses adjusted_score if available, falls back to risk_score.
    """
    db = _get_db()
    try:
        release = db.query(Release).filter(Release.id == release_id).first()
        if not release:
            raise HTTPException(status_code=404, detail="Release not found")

        rows = (
            db.query(
                TestCase.title,
                TestCase.module,
                TestCase.severity,
                TestExecution.risk_score,
                TestExecution.adjusted_score,
                TestExecution.priority,
                TestExecution.ai_source,
                TestExecution.recommended,
                TestExecution.adj_reason,
            )
            .join(TestExecution, TestCase.id == TestExecution.test_case_id)
            .filter(TestExecution.release_id == release_id)
            .order_by(
                func.coalesce(
                    TestExecution.adjusted_score, TestExecution.risk_score
                ).desc()
            )
            .limit(limit)
            .all()
        )

        return [
            {
                "title":          r.title,
                "module":         r.module or "—",
                "severity":       r.severity or "—",
                "risk_score":     r.risk_score,
                "adjusted_score": r.adjusted_score,
                "final_score":    r.adjusted_score if r.adjusted_score is not None else r.risk_score,
                "priority":       r.priority,
                "ai_source":      r.ai_source,
                "recommended":    r.recommended,
                "adj_reason":     r.adj_reason,
            }
            for r in rows
        ]
    finally:
        db.close()


# ── 7. Summary hero stats (single project) ────────────────────────────────────
@router.get("/api/dashboard/summary")
def dashboard_summary(project_id: int = Query(..., description="Project ID")):
    """
    Single-call hero stats for the top summary cards.
    Returns latest release stats + overall project totals.
    """
    db = _get_db()
    try:
        project = db.query(Project).filter(Project.id == project_id).first()
        if not project:
            raise HTTPException(status_code=404, detail="Project not found")

        # Latest release for this project
        latest_release = (
            db.query(Release)
            .filter(Release.project_id == project_id)
            .order_by(Release.release_date.desc())
            .first()
        )

        if not latest_release:
            return {
                "project_name":    project.name,
                "total_releases":  0,
                "total_testcases": 0,
                "latest_release":  None,
            }

        # Stats for latest release
        stats = (
            db.query(
                func.count(TestExecution.id).label("total"),
                func.sum(case((TestExecution.priority == "P1", 1), else_=0)).label("p1"),
                func.sum(case((TestExecution.priority == "P2", 1), else_=0)).label("p2"),
                func.sum(case((TestExecution.priority == "P3", 1), else_=0)).label("p3"),
                func.coalesce(func.avg(TestExecution.risk_score), 0).label("avg_risk"),
                func.sum(case((TestExecution.recommended == "Yes", 1), else_=0)).label("recommended"),
            )
            .filter(TestExecution.release_id == latest_release.id)
            .first()
        )

        total_releases  = db.query(func.count(Release.id)).filter(Release.project_id == project_id).scalar()
        total_testcases = db.query(func.count(TestCase.id)).filter(TestCase.project_id == project_id).scalar()

        return {
            "project_name":    project.name,
            "total_releases":  total_releases,
            "total_testcases": total_testcases,
            "latest_release": {
                "id":           latest_release.id,
                "name":         latest_release.release_name,
                "date":         latest_release.release_date.strftime("%Y-%m-%d"),
                "total":        stats.total or 0,
                "p1":           stats.p1 or 0,
                "p2":           stats.p2 or 0,
                "p3":           stats.p3 or 0,
                "avg_risk":     round(float(stats.avg_risk or 0), 2),
                "recommended":  stats.recommended or 0,
            },
        }
    finally:
        db.close()


# ── 8. Delete release (cascade deletes all executions) ────────────────────────
@router.delete("/api/releases/{release_id}")
def delete_release(release_id: int):
    """
    Delete a release and ALL its TestExecution records (CASCADE).
    TestCase records are NOT deleted — they belong to the Project.
    """
    db = _get_db()
    try:
        release = db.query(Release).filter(Release.id == release_id).first()
        if not release:
            raise HTTPException(status_code=404, detail="Release not found")

        exec_count = (
            db.query(func.count(TestExecution.id))
            .filter(TestExecution.release_id == release_id)
            .scalar()
        )

        db.delete(release)
        db.commit()

        return {
            "success":           True,
            "message":           f"Release '{release.release_name}' deleted successfully",
            "release_id":        release_id,
            "executions_deleted": exec_count,
        }
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        db.close()