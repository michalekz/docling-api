from pydantic import BaseModel, Field
from typing import List, Literal, Optional


# Status constants - unified across API and MCP
class JobStatusEnum:
    PENDING = "PENDING"
    IN_PROGRESS = "IN_PROGRESS"
    SUCCESS = "SUCCESS"
    FAILURE = "FAILURE"


class ImageData(BaseModel):
    type: Optional[Literal["table", "picture"]] = Field(None, description="The type of the image")
    filename: Optional[str] = Field(None, description="The filename of the image")
    image: Optional[str] = Field(None, description="The image data")


class ConversionResult(BaseModel):
    filename: str = Field(None, description="The filename of the document")
    markdown: str = Field(None, description="The markdown content of the document")
    images: List[ImageData] = Field(default_factory=list, description="The images in the document")
    pages: Optional[int] = Field(None, description="Number of pages in the document (PDF, DOCX, etc.)")
    error: Optional[str] = Field(None, description="The error that occurred during the conversion")


class BatchConversionResult(BaseModel):
    conversion_results: List[ConversionResult] = Field(
        default_factory=list, description="The results of the conversions"
    )


class ConversationJobResult(BaseModel):
    job_id: Optional[str] = Field(None, description="The id of the conversion job")
    result: Optional[ConversionResult] = Field(None, description="The result of the conversion job")
    error: Optional[str] = Field(None, description="The error that occurred during the conversion job")
    status: Literal["PENDING", "IN_PROGRESS", "SUCCESS", "FAILURE"] = Field(None, description="The status of the conversion job")
    # Extended metadata (Phase 1)
    filename: Optional[str] = Field(None, description="Original filename")
    file_type: Optional[str] = Field(None, description="Detected file type")
    file_size: Optional[int] = Field(None, description="File size in bytes")
    created_at: Optional[str] = Field(None, description="ISO 8601 timestamp of job creation")
    completed_at: Optional[str] = Field(None, description="ISO 8601 timestamp of job completion")
    pages: Optional[int] = Field(None, description="Number of pages (if available from Docling)")
    processing_time_ms: Optional[int] = Field(None, description="Processing time in milliseconds")


class BatchConversionJobResult(BaseModel):
    job_id: str = Field(..., description="The id of the conversion job")
    conversion_results: List[ConversationJobResult] = Field(
        default_factory=list, description="The results of the conversion job"
    )
    status: Literal["IN_PROGRESS", "SUCCESS", "FAILURE"] = Field(
        None, description="The status of the entire conversion jobs in the batch"
    )
    error: Optional[str] = Field(None, description="If the entire batch failed, this will be the error message")


class BatchCancelRequest(BaseModel):
    task_ids: List[str] = Field(..., description="List of Celery task IDs to cancel")


class BatchCancelResponse(BaseModel):
    cancelled_count: int = Field(..., description="Number of tasks successfully cancelled")
    task_ids: List[str] = Field(..., description="List of task IDs that were cancelled")
