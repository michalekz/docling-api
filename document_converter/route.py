from io import BytesIO
from typing import List, Optional
from fastapi import APIRouter, File, HTTPException, UploadFile, Query, Header

from document_converter.schema import (
    BatchConversionJobResult,
    ConversationJobResult,
    ConversionResult,
    BatchCancelRequest,
    BatchCancelResponse,
    JobStatusEnum
)
from document_converter.service import DocumentConverterService, DoclingDocumentConversion
from document_converter.utils import is_file_format_supported, is_legacy_office_format, guess_format
from worker.tasks import convert_document_task, convert_documents_task
from worker.celery_config import celery_app

# Import audit module for SQLite logging
try:
    from audit import insert_job, get_job, Status
    AUDIT_ENABLED = True
except ImportError:
    AUDIT_ENABLED = False

router = APIRouter()

# Could be docling or another converter as long as it implements DocumentConversionBase
converter = DoclingDocumentConversion()
document_converter_service = DocumentConverterService(document_converter=converter)


# Document direct conversion endpoints
@router.post(
    '/documents/convert',
    response_model=ConversionResult,
    response_model_exclude_unset=True,
    description="Convert a single document synchronously",
)
async def convert_single_document(
    document: UploadFile = File(...),
    extract_tables_as_images: bool = False,
    image_resolution_scale: int = Query(4, ge=1, le=4),
):
    file_bytes = await document.read()

    # Check for legacy Office formats and provide helpful error
    if is_legacy_office_format(document.filename):
        raise HTTPException(
            status_code=400,
            detail=(
                f"Legacy Office format not supported: {document.filename}. "
                f"Please convert to modern format (.docx, .xlsx, or .pptx) first. "
                f"Supported formats: DOCX, XLSX, PPTX, PDF, PNG, JPEG, TIFF"
            )
        )

    if not is_file_format_supported(file_bytes, document.filename):
        raise HTTPException(status_code=400, detail=f"Unsupported file format: {document.filename}")

    return document_converter_service.convert_document(
        (document.filename, BytesIO(file_bytes)),
        extract_tables=extract_tables_as_images,
        image_resolution_scale=image_resolution_scale,
    )


@router.post(
    '/documents/batch-convert',
    response_model=List[ConversionResult],
    response_model_exclude_unset=True,
    description="Convert multiple documents synchronously",
)
async def convert_multiple_documents(
    documents: List[UploadFile] = File(...),
    extract_tables_as_images: bool = False,
    image_resolution_scale: int = Query(4, ge=1, le=4),
):
    doc_streams = []
    for document in documents:
        file_bytes = await document.read()

        # Check for legacy Office formats and provide helpful error
        if is_legacy_office_format(document.filename):
            raise HTTPException(
                status_code=400,
                detail=(
                    f"Legacy Office format not supported: {document.filename}. "
                    f"Please convert to modern format (.docx, .xlsx, or .pptx) first. "
                    f"Supported formats: DOCX, XLSX, PPTX, PDF, PNG, JPEG, TIFF"
                )
            )

        if not is_file_format_supported(file_bytes, document.filename):
            raise HTTPException(status_code=400, detail=f"Unsupported file format: {document.filename}")
        doc_streams.append((document.filename, BytesIO(file_bytes)))

    return document_converter_service.convert_documents(
        doc_streams,
        extract_tables=extract_tables_as_images,
        image_resolution_scale=image_resolution_scale,
    )


# Asynchronous conversion jobs endpoints
@router.post(
    '/conversion-jobs',
    response_model=ConversationJobResult,
    description="Create a conversion job for a single document",
)
async def create_single_document_conversion_job(
    document: UploadFile = File(...),
    extract_tables_as_images: bool = False,
    image_resolution_scale: int = Query(4, ge=1, le=4),
    x_user_id: Optional[str] = Header(None, alias="X-User-ID"),
):
    file_bytes = await document.read()

    # Check for legacy Office formats and provide helpful error
    if is_legacy_office_format(document.filename):
        raise HTTPException(
            status_code=400,
            detail=(
                f"Legacy Office format not supported: {document.filename}. "
                f"Please convert to modern format (.docx, .xlsx, or .pptx) first. "
                f"Supported formats: DOCX, XLSX, PPTX, PDF, PNG, JPEG, TIFF"
            )
        )

    if not is_file_format_supported(file_bytes, document.filename):
        raise HTTPException(status_code=400, detail=f"Unsupported file format: {document.filename}")

    # Detect file type for audit
    detected_format = guess_format(file_bytes, document.filename)
    file_type = detected_format.value if detected_format else None

    task = convert_document_task.delay(
        (document.filename, file_bytes),
        extract_tables=extract_tables_as_images,
        image_resolution_scale=image_resolution_scale,
        user_id=x_user_id,
    )

    # Insert job into SQLite audit log
    if AUDIT_ENABLED and x_user_id:
        try:
            insert_job(
                job_id=task.id,
                user_id=x_user_id,
                filename=document.filename,
                file_type=file_type,
                file_size=len(file_bytes),
            )
        except Exception:
            pass  # Don't fail the request if audit logging fails

    return ConversationJobResult(
        job_id=task.id,
        status=JobStatusEnum.PENDING,
        filename=document.filename,
        file_type=file_type,
        file_size=len(file_bytes),
    )


@router.get(
    '/conversion-jobs/{job_id}',
    response_model=ConversationJobResult,
    description="Get the status of a single document conversion job",
    response_model_exclude_unset=True,
)
async def get_conversion_job_status(
    job_id: str,
    x_user_id: Optional[str] = Header(None, alias="X-User-ID"),
):
    # Get Celery task result
    celery_result = document_converter_service.get_single_document_task_result(job_id)

    # Enrich with SQLite data if available
    if AUDIT_ENABLED:
        try:
            # Pass user_id for access control
            job_data = get_job(job_id, user_id=x_user_id)
            if job_data:
                # Merge SQLite data with Celery result
                if job_data.filename:
                    celery_result.filename = job_data.filename
                if job_data.file_type:
                    celery_result.file_type = job_data.file_type
                if job_data.file_size:
                    celery_result.file_size = job_data.file_size
                if job_data.created_at:
                    celery_result.created_at = job_data.created_at
                if job_data.completed_at:
                    celery_result.completed_at = job_data.completed_at
                if job_data.pages:
                    celery_result.pages = job_data.pages
                if job_data.processing_time_ms:
                    celery_result.processing_time_ms = job_data.processing_time_ms
        except Exception:
            pass  # Don't fail if SQLite lookup fails

    return celery_result


@router.post(
    '/conversion-jobs/batch/cancel',
    response_model=BatchCancelResponse,
    description="Cancel multiple conversion jobs by their task IDs"
)
async def cancel_batch_conversion_jobs(request: BatchCancelRequest):
    """
    Cancel multiple Celery conversion tasks.

    This will terminate the running tasks immediately.
    Tasks that are already completed or failed will be ignored.
    """
    cancelled_tasks = []

    for task_id in request.task_ids:
        try:
            # Revoke task with terminate=True to kill the worker process
            celery_app.control.revoke(task_id, terminate=True, signal='SIGKILL')
            cancelled_tasks.append(task_id)
        except Exception as e:
            # Log but continue with other tasks
            print(f"Failed to cancel task {task_id}: {e}")

    return BatchCancelResponse(
        cancelled_count=len(cancelled_tasks),
        task_ids=cancelled_tasks
    )


@router.post(
    '/batch-conversion-jobs',
    response_model=BatchConversionJobResult,
    response_model_exclude_unset=True,
    description="Create a conversion job for multiple documents",
)
async def create_batch_conversion_job(
    documents: List[UploadFile] = File(...),
    extract_tables_as_images: bool = False,
    image_resolution_scale: int = Query(4, ge=1, le=4),
    x_user_id: Optional[str] = Header(None, alias="X-User-ID"),
):
    """Create a batch conversion job for multiple documents."""
    doc_data = []
    total_size = 0
    for document in documents:
        file_bytes = await document.read()
        total_size += len(file_bytes)

        # Check for legacy Office formats and provide helpful error
        if is_legacy_office_format(document.filename):
            raise HTTPException(
                status_code=400,
                detail=(
                    f"Legacy Office format not supported: {document.filename}. "
                    f"Please convert to modern format (.docx, .xlsx, or .pptx) first. "
                    f"Supported formats: DOCX, XLSX, PPTX, PDF, PNG, JPEG, TIFF"
                )
            )

        if not is_file_format_supported(file_bytes, document.filename):
            raise HTTPException(status_code=400, detail=f"Unsupported file format: {document.filename}")
        doc_data.append((document.filename, file_bytes))

    task = convert_documents_task.delay(
        doc_data,
        extract_tables=extract_tables_as_images,
        image_resolution_scale=image_resolution_scale,
        user_id=x_user_id,
    )

    # Insert batch job into SQLite audit log
    if AUDIT_ENABLED and x_user_id:
        try:
            filenames = ", ".join([d[0] for d in doc_data])
            insert_job(
                job_id=task.id,
                user_id=x_user_id,
                filename=f"[BATCH: {len(doc_data)} files] {filenames[:100]}",
                file_type="batch",
                file_size=total_size,
            )
        except Exception:
            pass  # Don't fail the request if audit logging fails

    return BatchConversionJobResult(job_id=task.id, status=JobStatusEnum.PENDING)


@router.get(
    '/batch-conversion-jobs/{job_id}',
    response_model=BatchConversionJobResult,
    response_model_exclude_unset=True,
    description="Get the status of a batch conversion job",
)
async def get_batch_conversion_job_status(job_id: str):
    """Get the status and results of a batch conversion job."""
    return document_converter_service.get_batch_conversion_task_result(job_id)
