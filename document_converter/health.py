"""Health check endpoints for monitoring and readiness probes."""

import logging
from typing import Dict, Any
from fastapi import APIRouter, Response, status

router = APIRouter()

logger = logging.getLogger(__name__)


@router.get(
    "/health",
    summary="Basic health check",
    description="Returns 200 if the service is running. Used for liveness probes.",
    tags=["Health"],
)
async def health_check() -> Dict[str, str]:
    """Basic health check - service is alive."""
    return {
        "status": "healthy",
        "service": "document-converter-api",
        "version": "1.0.0",
    }


@router.get(
    "/ready",
    summary="Readiness check",
    description="Returns 200 if the service is ready to accept requests. Checks dependencies.",
    tags=["Health"],
)
async def readiness_check(response: Response) -> Dict[str, Any]:
    """
    Readiness check - service is ready to accept requests.

    Checks:
    - Redis connection (Celery broker)
    - Celery workers availability
    """
    checks = {
        "status": "ready",
        "checks": {}
    }

    all_healthy = True

    # Check Redis/Celery
    try:
        from worker.celery_config import celery_app

        # Ping Celery - check if workers are available
        inspect = celery_app.control.inspect()
        stats = inspect.stats()

        if stats:
            checks["checks"]["celery_workers"] = {
                "status": "healthy",
                "workers": len(stats),
                "worker_names": list(stats.keys()),
            }
        else:
            checks["checks"]["celery_workers"] = {
                "status": "unhealthy",
                "error": "No workers available"
            }
            all_healthy = False

    except Exception as e:
        logger.error(f"Celery health check failed: {e}")
        checks["checks"]["celery_workers"] = {
            "status": "unhealthy",
            "error": str(e)
        }
        all_healthy = False

    # Set overall status
    if not all_healthy:
        checks["status"] = "degraded"
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE

    return checks


@router.get(
    "/metrics",
    summary="Metrics endpoint",
    description="Returns basic metrics about the service. Can be extended for Prometheus.",
    tags=["Health"],
)
async def metrics() -> Dict[str, Any]:
    """
    Metrics endpoint for monitoring.

    Returns basic metrics that can be extended for Prometheus integration.
    """
    metrics_data = {
        "service": "document-converter-api",
        "version": "1.0.0",
        "converters": {
            "docling": {
                "enabled": True,
                "ocr_engine": "EasyOCR",
                "ocr_languages": ["cs", "en"],
                "hierarchical_postprocessor": True,
            },
            "markitdown": {
                "enabled": True,
                "formats": ["docx", "xlsx", "pptx", "doc", "xls", "ppt"],
            },
        },
    }

    # Try to get Celery metrics
    try:
        from worker.celery_config import celery_app

        inspect = celery_app.control.inspect()
        stats = inspect.stats()
        active = inspect.active()

        if stats:
            metrics_data["celery"] = {
                "workers": len(stats),
                "active_tasks": sum(len(tasks) for tasks in (active or {}).values()),
            }
    except Exception as e:
        logger.warning(f"Could not fetch Celery metrics: {e}")
        metrics_data["celery"] = {"error": str(e)}

    return metrics_data
