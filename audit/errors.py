"""
Standardized error handling for MCP tools.

Provides consistent error response format across all tools.
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, Optional


class ErrorCode(str, Enum):
    """Standardized error codes for MCP tools."""
    UNSUPPORTED_FORMAT = "UNSUPPORTED_FORMAT"
    FILE_NOT_FOUND = "FILE_NOT_FOUND"
    FILE_TOO_LARGE = "FILE_TOO_LARGE"
    JOB_NOT_FOUND = "JOB_NOT_FOUND"
    ACCESS_DENIED = "ACCESS_DENIED"
    CONVERSION_FAILED = "CONVERSION_FAILED"
    INVALID_PARAMETER = "INVALID_PARAMETER"
    INTERNAL_ERROR = "INTERNAL_ERROR"


@dataclass
class MCPError:
    """
    Standardized error response for MCP tools.

    All MCP tools should return this structure for errors.
    """
    code: ErrorCode
    message: str
    details: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON response."""
        return {
            "error": {
                "code": self.code.value,
                "message": self.message,
                "details": self.details
            }
        }


# Pre-defined error factories for common cases

def unsupported_format_error(filename: str, detected_format: Optional[str] = None) -> MCPError:
    """Create error for unsupported file format (including legacy Office)."""
    details = {"filename": filename}
    if detected_format:
        details["detected_format"] = detected_format

    return MCPError(
        code=ErrorCode.UNSUPPORTED_FORMAT,
        message=f"Soubor '{filename}' má nepodporovaný formát. "
                "Podporované formáty: DOCX, XLSX, PPTX, PDF, PNG, JPEG, TIFF.",
        details=details
    )


def legacy_format_error(filename: str) -> MCPError:
    """Create error for legacy Office formats (.doc, .xls, .ppt)."""
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""

    return MCPError(
        code=ErrorCode.UNSUPPORTED_FORMAT,
        message=f"Soubor '{filename}' je ve starém Office formátu. "
                "Převeďte na .docx/.xlsx/.pptx.",
        details={
            "filename": filename,
            "detected_format": ext
        }
    )


def file_not_found_error(file_path: str) -> MCPError:
    """Create error for missing file."""
    return MCPError(
        code=ErrorCode.FILE_NOT_FOUND,
        message=f"Soubor '{file_path}' nenalezen.",
        details={"file_path": file_path}
    )


def file_too_large_error(filename: str, size_bytes: int, max_bytes: int) -> MCPError:
    """Create error for file exceeding size limit."""
    return MCPError(
        code=ErrorCode.FILE_TOO_LARGE,
        message=f"Soubor '{filename}' překračuje limit velikosti "
                f"({size_bytes / 1024 / 1024:.1f} MB > {max_bytes / 1024 / 1024:.0f} MB).",
        details={
            "filename": filename,
            "size_bytes": size_bytes,
            "max_bytes": max_bytes
        }
    )


def job_not_found_error(job_id: str) -> MCPError:
    """Create error for missing job."""
    return MCPError(
        code=ErrorCode.JOB_NOT_FOUND,
        message=f"Job '{job_id}' nenalezen.",
        details={"job_id": job_id}
    )


def access_denied_error(job_id: Optional[str] = None, reason: Optional[str] = None) -> MCPError:
    """Create error for access denied."""
    details: Dict[str, Any] = {}
    if job_id:
        details["job_id"] = job_id

    message = reason or "Nemáte oprávnění k této operaci."

    return MCPError(
        code=ErrorCode.ACCESS_DENIED,
        message=message,
        details=details
    )


def admin_required_error(user_id: str) -> MCPError:
    """Create error for admin-only operation."""
    return MCPError(
        code=ErrorCode.ACCESS_DENIED,
        message="Tato operace vyžaduje admin oprávnění.",
        details={
            "required_role": "admin",
            "user_id": user_id
        }
    )


def conversion_failed_error(job_id: str, error_message: str) -> MCPError:
    """Create error for failed conversion."""
    return MCPError(
        code=ErrorCode.CONVERSION_FAILED,
        message=f"Konverze selhala: {error_message}",
        details={
            "job_id": job_id,
            "original_error": error_message
        }
    )


def invalid_parameter_error(param_name: str, value: Any, reason: str) -> MCPError:
    """Create error for invalid parameter."""
    return MCPError(
        code=ErrorCode.INVALID_PARAMETER,
        message=f"Neplatný parametr '{param_name}': {reason}",
        details={
            "parameter": param_name,
            "value": value,
            "reason": reason
        }
    )


def internal_error(message: str = "Interní chyba serveru.") -> MCPError:
    """Create error for internal server error."""
    return MCPError(
        code=ErrorCode.INTERNAL_ERROR,
        message=message,
        details={}
    )
