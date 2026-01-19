"""
Audit module for tracking document conversions in SQLite.
"""

from .db import (
    init_db,
    get_db,
    insert_job,
    update_job_status,
    update_job_started,
    update_job_complete,
    get_job,
    get_active_jobs,
    get_all_active_jobs,
    get_user_history,
    search_user_history,
    get_user_stats,
    get_queue_stats,
    JobStatus,
    Status,
)

from .errors import (
    ErrorCode,
    MCPError,
    unsupported_format_error,
    legacy_format_error,
    file_not_found_error,
    file_too_large_error,
    job_not_found_error,
    access_denied_error,
    admin_required_error,
    conversion_failed_error,
    invalid_parameter_error,
    internal_error,
)

__all__ = [
    # Database functions
    "init_db",
    "get_db",
    "insert_job",
    "update_job_status",
    "update_job_started",
    "update_job_complete",
    "get_job",
    "get_active_jobs",
    "get_all_active_jobs",
    "get_user_history",
    "search_user_history",
    "get_user_stats",
    "get_queue_stats",
    "JobStatus",
    "Status",
    # Error handling
    "ErrorCode",
    "MCPError",
    "unsupported_format_error",
    "legacy_format_error",
    "file_not_found_error",
    "file_too_large_error",
    "job_not_found_error",
    "access_denied_error",
    "admin_required_error",
    "conversion_failed_error",
    "invalid_parameter_error",
    "internal_error",
]
