"""
SQLite database module for audit logging of document conversions.

This module provides functions to:
- Track conversion jobs with user attribution
- Store job metadata (file_type, file_size, pages, etc.)
- Record LLM postprocessing results (summary, category, tags)
- Query job history and statistics
"""

import json
import logging
import os
import sqlite3
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# Database path - can be overridden via environment variable
DB_PATH = os.getenv("MDCONVERT_AUDIT_DB", "/opt/mdconvert/data/audit.db")


class Status(str, Enum):
    """Job status values."""
    PENDING = "PENDING"
    IN_PROGRESS = "IN_PROGRESS"
    SUCCESS = "SUCCESS"
    FAILURE = "FAILURE"


@dataclass
class JobStatus:
    """
    Consistent job status structure used across all MCP tools.

    All fields are optional except job_id and status to allow
    partial responses (e.g., NOT_FOUND returns only job_id and status).
    """
    job_id: str
    status: str
    filename: Optional[str] = None
    file_type: Optional[str] = None
    file_size: Optional[int] = None
    created_at: Optional[str] = None
    completed_at: Optional[str] = None
    pages: Optional[int] = None
    processing_time_ms: Optional[int] = None
    result_url: Optional[str] = None
    error: Optional[str] = None
    user_id: Optional[str] = None  # Only in admin responses
    # LLM postprocessing
    summary: Optional[str] = None
    category: Optional[str] = None
    tags: Optional[List[str]] = None
    language: Optional[str] = None

    def to_dict(self, include_user_id: bool = False) -> Dict[str, Any]:
        """Convert to dictionary, excluding None values."""
        result = {}
        for key, value in self.__dict__.items():
            if value is not None:
                if key == "user_id" and not include_user_id:
                    continue
                if key == "tags" and isinstance(value, str):
                    # Parse JSON string to list
                    try:
                        value = json.loads(value)
                    except json.JSONDecodeError:
                        value = []
                result[key] = value
        return result


def get_db() -> sqlite3.Connection:
    """Get database connection with row factory."""
    # Ensure directory exists
    Path(DB_PATH).parent.mkdir(parents=True, exist_ok=True)

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    """Initialize database schema."""
    with get_db() as conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS conversions (
                -- Identification
                job_id TEXT PRIMARY KEY,
                user_id TEXT NOT NULL,

                -- File info
                filename TEXT NOT NULL,
                file_type TEXT,
                file_size INTEGER,

                -- Status
                status TEXT DEFAULT 'PENDING',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                started_at TIMESTAMP,
                completed_at TIMESTAMP,

                -- Results
                pages INTEGER,
                processing_time_ms INTEGER,
                result_url TEXT,
                error TEXT,

                -- LLM postprocessing
                summary TEXT,
                category TEXT,
                tags TEXT,
                language TEXT
            );

            CREATE INDEX IF NOT EXISTS idx_user_created
                ON conversions(user_id, created_at DESC);
            CREATE INDEX IF NOT EXISTS idx_status
                ON conversions(status);
            CREATE INDEX IF NOT EXISTS idx_user_status
                ON conversions(user_id, status);
        """)
        logger.info(f"Database initialized at {DB_PATH}")


def insert_job(
    job_id: str,
    user_id: str,
    filename: str,
    file_type: Optional[str] = None,
    file_size: Optional[int] = None,
) -> None:
    """Insert a new job record with PENDING status."""
    with get_db() as conn:
        conn.execute(
            """
            INSERT INTO conversions (job_id, user_id, filename, file_type, file_size, status)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (job_id, user_id, filename, file_type, file_size, Status.PENDING.value)
        )
        logger.debug(f"Inserted job {job_id} for user {user_id}")


def update_job_status(job_id: str, status: str) -> None:
    """Update job status."""
    with get_db() as conn:
        conn.execute(
            "UPDATE conversions SET status = ? WHERE job_id = ?",
            (status, job_id)
        )
        logger.debug(f"Updated job {job_id} status to {status}")


def update_job_started(job_id: str) -> None:
    """Mark job as started (IN_PROGRESS)."""
    with get_db() as conn:
        conn.execute(
            """
            UPDATE conversions
            SET status = ?, started_at = ?
            WHERE job_id = ?
            """,
            (Status.IN_PROGRESS.value, datetime.utcnow().isoformat(), job_id)
        )
        logger.debug(f"Job {job_id} started")


def update_job_complete(
    job_id: str,
    status: str,
    pages: Optional[int] = None,
    processing_time_ms: Optional[int] = None,
    result_url: Optional[str] = None,
    error: Optional[str] = None,
    summary: Optional[str] = None,
    category: Optional[str] = None,
    tags: Optional[List[str]] = None,
    language: Optional[str] = None,
) -> None:
    """Update job with completion data."""
    tags_json = json.dumps(tags) if tags else None

    with get_db() as conn:
        conn.execute(
            """
            UPDATE conversions SET
                status = ?,
                completed_at = ?,
                pages = ?,
                processing_time_ms = ?,
                result_url = ?,
                error = ?,
                summary = ?,
                category = ?,
                tags = ?,
                language = ?
            WHERE job_id = ?
            """,
            (
                status,
                datetime.utcnow().isoformat(),
                pages,
                processing_time_ms,
                result_url,
                error,
                summary,
                category,
                tags_json,
                language,
                job_id
            )
        )
        logger.debug(f"Job {job_id} completed with status {status}")


def get_job(job_id: str, user_id: Optional[str] = None) -> Optional[JobStatus]:
    """
    Get job by ID.

    If user_id is provided, only returns the job if it belongs to that user.
    Returns None if job not found or doesn't belong to user.
    """
    with get_db() as conn:
        if user_id:
            row = conn.execute(
                "SELECT * FROM conversions WHERE job_id = ? AND user_id = ?",
                (job_id, user_id)
            ).fetchone()
        else:
            row = conn.execute(
                "SELECT * FROM conversions WHERE job_id = ?",
                (job_id,)
            ).fetchone()

        if not row:
            return None

        return _row_to_job_status(row)


def get_active_jobs(user_id: str) -> List[JobStatus]:
    """Get all active (PENDING or IN_PROGRESS) jobs for a user."""
    with get_db() as conn:
        rows = conn.execute(
            """
            SELECT * FROM conversions
            WHERE user_id = ? AND status IN (?, ?)
            ORDER BY created_at ASC
            """,
            (user_id, Status.PENDING.value, Status.IN_PROGRESS.value)
        ).fetchall()

        return [_row_to_job_status(row) for row in rows]


def get_user_history(user_id: str, days: int = 30) -> List[JobStatus]:
    """Get completed jobs (SUCCESS or FAILURE) for a user within specified days."""
    with get_db() as conn:
        rows = conn.execute(
            """
            SELECT * FROM conversions
            WHERE user_id = ?
              AND status IN (?, ?)
              AND created_at >= datetime('now', '-' || ? || ' days')
            ORDER BY created_at DESC
            """,
            (user_id, Status.SUCCESS.value, Status.FAILURE.value, days)
        ).fetchall()

        return [_row_to_job_status(row) for row in rows]


def search_user_history(user_id: str, query: str) -> List[JobStatus]:
    """Search user's completed jobs by filename, summary, or tags."""
    search_pattern = f"%{query}%"

    with get_db() as conn:
        rows = conn.execute(
            """
            SELECT * FROM conversions
            WHERE user_id = ?
              AND status IN (?, ?)
              AND (
                  filename LIKE ?
                  OR summary LIKE ?
                  OR tags LIKE ?
              )
            ORDER BY created_at DESC
            """,
            (
                user_id,
                Status.SUCCESS.value,
                Status.FAILURE.value,
                search_pattern,
                search_pattern,
                search_pattern
            )
        ).fetchall()

        return [_row_to_job_status(row) for row in rows]


def get_user_stats(user_id: str) -> Dict[str, Any]:
    """Get aggregated statistics for a user."""
    with get_db() as conn:
        # Basic stats
        basic = conn.execute(
            """
            SELECT
                COUNT(*) as total_jobs,
                SUM(pages) as total_pages,
                SUM(file_size) as total_files_size,
                SUM(processing_time_ms) as total_processing_time_ms,
                SUM(CASE WHEN status = ? THEN 1 ELSE 0 END) as success_count,
                SUM(CASE WHEN status = ? THEN 1 ELSE 0 END) as failure_count
            FROM conversions
            WHERE user_id = ?
            """,
            (Status.SUCCESS.value, Status.FAILURE.value, user_id)
        ).fetchone()

        # By file type
        by_file_type = conn.execute(
            """
            SELECT file_type, COUNT(*) as count
            FROM conversions
            WHERE user_id = ? AND file_type IS NOT NULL
            GROUP BY file_type
            """,
            (user_id,)
        ).fetchall()

        return {
            "total_jobs": basic["total_jobs"] or 0,
            "total_pages": basic["total_pages"] or 0,
            "total_files_size": basic["total_files_size"] or 0,
            "total_processing_time_ms": basic["total_processing_time_ms"] or 0,
            "success_count": basic["success_count"] or 0,
            "failure_count": basic["failure_count"] or 0,
            "by_file_type": {row["file_type"]: row["count"] for row in by_file_type}
        }


def get_queue_stats() -> Dict[str, Any]:
    """Get queue statistics (admin only)."""
    with get_db() as conn:
        # Counts
        counts = conn.execute(
            """
            SELECT
                SUM(CASE WHEN status = ? THEN 1 ELSE 0 END) as pending_count,
                SUM(CASE WHEN status = ? THEN 1 ELSE 0 END) as in_progress_count
            FROM conversions
            WHERE status IN (?, ?)
            """,
            (
                Status.PENDING.value,
                Status.IN_PROGRESS.value,
                Status.PENDING.value,
                Status.IN_PROGRESS.value
            )
        ).fetchone()

        # Oldest pending
        oldest = conn.execute(
            """
            SELECT MIN(created_at) as oldest_pending
            FROM conversions
            WHERE status = ?
            """,
            (Status.PENDING.value,)
        ).fetchone()

        # Calculate oldest pending minutes
        oldest_pending_minutes = None
        if oldest["oldest_pending"]:
            oldest_dt = datetime.fromisoformat(oldest["oldest_pending"])
            oldest_pending_minutes = int((datetime.utcnow() - oldest_dt).total_seconds() / 60)

        # Average wait time (last hour)
        avg_wait = conn.execute(
            """
            SELECT AVG(
                (julianday(completed_at) - julianday(created_at)) * 24 * 60
            ) as avg_wait_minutes
            FROM conversions
            WHERE status = ?
              AND completed_at >= datetime('now', '-1 hour')
            """,
            (Status.SUCCESS.value,)
        ).fetchone()

        pending = counts["pending_count"] or 0
        in_progress = counts["in_progress_count"] or 0

        return {
            "pending_count": pending,
            "in_progress_count": in_progress,
            "total_active": pending + in_progress,
            "oldest_pending_minutes": oldest_pending_minutes,
            "avg_wait_time_minutes": round(avg_wait["avg_wait_minutes"] or 0, 2)
        }


def get_all_active_jobs() -> List[JobStatus]:
    """Get all active jobs (admin only)."""
    with get_db() as conn:
        rows = conn.execute(
            """
            SELECT * FROM conversions
            WHERE status IN (?, ?)
            ORDER BY created_at ASC
            """,
            (Status.PENDING.value, Status.IN_PROGRESS.value)
        ).fetchall()

        return [_row_to_job_status(row, include_user_id=True) for row in rows]


def _row_to_job_status(row: sqlite3.Row, include_user_id: bool = False) -> JobStatus:
    """Convert database row to JobStatus object."""
    tags = None
    if row["tags"]:
        try:
            tags = json.loads(row["tags"])
        except json.JSONDecodeError:
            tags = []

    return JobStatus(
        job_id=row["job_id"],
        status=row["status"],
        filename=row["filename"],
        file_type=row["file_type"],
        file_size=row["file_size"],
        created_at=row["created_at"],
        completed_at=row["completed_at"],
        pages=row["pages"],
        processing_time_ms=row["processing_time_ms"],
        result_url=row["result_url"],
        error=row["error"],
        user_id=row["user_id"] if include_user_id else None,
        summary=row["summary"],
        category=row["category"],
        tags=tags,
        language=row["language"],
    )
