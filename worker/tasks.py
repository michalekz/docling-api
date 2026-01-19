import logging
import time
from typing import Any, Dict, List, Optional, Tuple
from document_converter.service import IMAGE_RESOLUTION_SCALE, DoclingDocumentConversion, DocumentConverterService
from worker.celery_config import celery_app

# Import audit module for SQLite logging
try:
    from audit import update_job_started, update_job_complete, Status, analyze_document_sync
    AUDIT_ENABLED = True
except ImportError:
    AUDIT_ENABLED = False
    analyze_document_sync = None

logger = logging.getLogger(__name__)


@celery_app.task(name="celery.ping")
def ping():
    print("Ping task received!")  # or use a logger
    return "pong"


@celery_app.task(bind=True, name="convert_document")
def convert_document_task(
    self,
    document: Tuple[str, bytes],
    extract_tables: bool = False,
    image_resolution_scale: int = IMAGE_RESOLUTION_SCALE,
    user_id: Optional[str] = None,
) -> Dict[str, Any]:
    job_id = self.request.id
    start_time = time.time()

    # Mark job as started in SQLite
    if AUDIT_ENABLED and user_id:
        try:
            update_job_started(job_id)
        except Exception as e:
            logger.warning(f"Failed to update job started in audit: {e}")

    try:
        document_service = DocumentConverterService(document_converter=DoclingDocumentConversion())
        result = document_service.convert_document_task(
            document, extract_tables=extract_tables, image_resolution_scale=image_resolution_scale
        )

        processing_time_ms = int((time.time() - start_time) * 1000)
        result_dict = result.model_dump(exclude_unset=True)

        # Mark job as completed in SQLite
        if AUDIT_ENABLED and user_id:
            try:
                # LLM postprocessing for metadata extraction
                summary = None
                category = None
                tags = None
                language = None

                if analyze_document_sync and result.markdown:
                    try:
                        analysis = analyze_document_sync(result.markdown)
                        if analysis:
                            summary = analysis.summary
                            category = analysis.category
                            tags = analysis.tags
                            language = analysis.language
                            logger.info(f"LLM postprocessing done: category={category}, language={language}")
                    except Exception as llm_error:
                        logger.warning(f"LLM postprocessing failed (non-fatal): {llm_error}")

                # Extract pages from conversion result (Docling provides this for PDF/images)
                pages = getattr(result, 'pages', None)

                update_job_complete(
                    job_id=job_id,
                    status=Status.SUCCESS.value,
                    pages=pages,
                    processing_time_ms=processing_time_ms,
                    result_url=None,  # Will be OneDrive URL
                    error=None,
                    summary=summary,
                    category=category,
                    tags=tags,
                    language=language,
                )
            except Exception as e:
                logger.warning(f"Failed to update job complete in audit: {e}")

        return result_dict

    except Exception as e:
        processing_time_ms = int((time.time() - start_time) * 1000)

        # Mark job as failed in SQLite
        if AUDIT_ENABLED and user_id:
            try:
                update_job_complete(
                    job_id=job_id,
                    status=Status.FAILURE.value,
                    processing_time_ms=processing_time_ms,
                    error=str(e),
                )
            except Exception as audit_error:
                logger.warning(f"Failed to update job failure in audit: {audit_error}")

        raise


@celery_app.task(bind=True, name="convert_documents")
def convert_documents_task(
    self,
    documents: List[Tuple[str, bytes]],
    extract_tables: bool = False,
    image_resolution_scale: int = IMAGE_RESOLUTION_SCALE,
    user_id: Optional[str] = None,
) -> List[Dict[str, Any]]:
    job_id = self.request.id
    start_time = time.time()

    # Mark job as started in SQLite
    if AUDIT_ENABLED and user_id:
        try:
            update_job_started(job_id)
        except Exception as e:
            logger.warning(f"Failed to update batch job started in audit: {e}")

    try:
        document_service = DocumentConverterService(document_converter=DoclingDocumentConversion())
        results = document_service.convert_documents_task(
            documents, extract_tables=extract_tables, image_resolution_scale=image_resolution_scale
        )

        processing_time_ms = int((time.time() - start_time) * 1000)

        # Mark job as completed in SQLite
        if AUDIT_ENABLED and user_id:
            try:
                update_job_complete(
                    job_id=job_id,
                    status=Status.SUCCESS.value,
                    processing_time_ms=processing_time_ms,
                )
            except Exception as e:
                logger.warning(f"Failed to update batch job complete in audit: {e}")

        return [result.model_dump(exclude_unset=True) for result in results]

    except Exception as e:
        processing_time_ms = int((time.time() - start_time) * 1000)

        # Mark job as failed in SQLite
        if AUDIT_ENABLED and user_id:
            try:
                update_job_complete(
                    job_id=job_id,
                    status=Status.FAILURE.value,
                    processing_time_ms=processing_time_ms,
                    error=str(e),
                )
            except Exception as audit_error:
                logger.warning(f"Failed to update batch job failure in audit: {audit_error}")

        raise
