import base64
import logging
from abc import ABC, abstractmethod
from io import BytesIO
from typing import List, Tuple

from celery.result import AsyncResult
from docling.datamodel.base_models import InputFormat, DocumentStream
from docling.datamodel.pipeline_options import PdfPipelineOptions, EasyOcrOptions
from docling.document_converter import PdfFormatOption, ImageFormatOption, DocumentConverter
from docling_core.types.doc import ImageRefMode, TableItem, PictureItem
from fastapi import HTTPException
from hierarchical.postprocessor import ResultPostprocessor
from markitdown import MarkItDown

from document_converter.schema import BatchConversionJobResult, ConversationJobResult, ConversionResult, ImageData
from document_converter.utils import handle_csv_file

logging.basicConfig(level=logging.INFO)
IMAGE_RESOLUTION_SCALE = 4


class DocumentConversionBase(ABC):
    @abstractmethod
    def convert(self, document: Tuple[str, BytesIO], **kwargs) -> ConversionResult:
        pass

    @abstractmethod
    def convert_batch(self, documents: List[Tuple[str, BytesIO]], **kwargs) -> List[ConversionResult]:
        pass


class DoclingDocumentConversion(DocumentConversionBase):
    """Document conversion implementation using Docling.

    You can initialize with default pipeline options or provide your own:

    Example:
        ```python
        # Using default options
        converter = DoclingDocumentConversion()

        # Or customize with your own pipeline options
        pipeline_options = PdfPipelineOptions()
        pipeline_options.do_ocr = True
        pipeline_options.ocr_options = EasyOcrOptions(lang=['cs', 'en'])  # Czech + English support
        pipeline_options.generate_page_images = True

        converter = DoclingDocumentConversion(pipeline_options=pipeline_options)
        ```
    """

    def __init__(self, pipeline_options: PdfPipelineOptions = None):
        self.pipeline_options = pipeline_options if pipeline_options else self._setup_default_pipeline_options()

    def _update_pipeline_options(self, extract_tables: bool, image_resolution_scale: int) -> PdfPipelineOptions:
        self.pipeline_options.images_scale = image_resolution_scale
        self.pipeline_options.generate_table_images = extract_tables
        return self.pipeline_options

    @staticmethod
    def _setup_default_pipeline_options() -> PdfPipelineOptions:
        pipeline_options = PdfPipelineOptions()
        pipeline_options.generate_page_images = False
        pipeline_options.generate_picture_images = True
        pipeline_options.ocr_options = EasyOcrOptions(lang=["cs", "en"])  # Czech + English

        return pipeline_options

    @staticmethod
    def _is_office_document(filename: str) -> bool:
        """Check if file is Office document that should use MarkItDown.

        MarkItDown excels at Office formats (DOCX, XLSX, PPTX) with proper
        structure preservation (headings, lists, tables).
        """
        office_extensions = {'.docx', '.xlsx', '.pptx', '.doc', '.xls', '.ppt'}
        return any(filename.lower().endswith(ext) for ext in office_extensions)

    @staticmethod
    def _convert_with_markitdown(filename: str, file: BytesIO) -> ConversionResult:
        """Convert Office documents using MarkItDown.

        MarkItDown is Microsoft's official tool for converting Office documents
        to Markdown, providing superior structure preservation compared to Docling
        for DOCX/XLSX/PPTX files.
        """
        try:
            md = MarkItDown()

            # MarkItDown needs file-like object with name attribute
            file.name = filename
            result = md.convert_stream(file)

            # MarkItDown returns text_content (markdown string)
            markdown = result.text_content

            # Extract filename without extension
            from pathlib import Path
            doc_filename = Path(filename).stem

            return ConversionResult(
                filename=doc_filename,
                markdown=markdown,
                images=[]  # MarkItDown doesn't extract images separately
            )

        except Exception as e:
            logging.error(f"MarkItDown failed to convert {filename}: {str(e)}")
            from pathlib import Path
            return ConversionResult(filename=Path(filename).stem, error=str(e))

    @staticmethod
    def _process_document_images(conv_res) -> Tuple[str, List[ImageData]]:
        images = []
        table_counter = 0
        picture_counter = 0
        content_md = conv_res.document.export_to_markdown(image_mode=ImageRefMode.PLACEHOLDER)

        for element, _level in conv_res.document.iterate_items():
            if isinstance(element, (TableItem, PictureItem)) and element.image:
                img_buffer = BytesIO()
                element.image.pil_image.save(img_buffer, format="PNG")

                if isinstance(element, TableItem):
                    table_counter += 1
                    image_name = f"table-{table_counter}.png"
                    image_type = "table"
                else:
                    picture_counter += 1
                    image_name = f"picture-{picture_counter}.png"
                    image_type = "picture"
                    content_md = content_md.replace("<!-- image -->", image_name, 1)

                image_bytes = base64.b64encode(img_buffer.getvalue()).decode('utf-8')
                images.append(ImageData(type=image_type, filename=image_name, image=image_bytes))

        return content_md, images

    def convert(
        self,
        document: Tuple[str, BytesIO],
        extract_tables: bool = False,
        image_resolution_scale: int = IMAGE_RESOLUTION_SCALE,
    ) -> ConversionResult:
        filename, file = document

        # Office documents (DOCX, XLSX, PPTX) → MarkItDown for better structure preservation
        if self._is_office_document(filename):
            return self._convert_with_markitdown(filename, file)

        # PDF/IMAGE documents → Docling with EasyOCR + ResultPostprocessor
        pipeline_options = self._update_pipeline_options(extract_tables, image_resolution_scale)
        doc_converter = DocumentConverter(
            format_options={
                InputFormat.PDF: PdfFormatOption(pipeline_options=pipeline_options),
                InputFormat.IMAGE: ImageFormatOption(pipeline_options=pipeline_options),
            }
        )

        if filename.lower().endswith('.csv'):
            file, error = handle_csv_file(file)
            if error:
                return ConversionResult(filename=filename, error=error)

        conv_res = doc_converter.convert(DocumentStream(name=filename, stream=file), raises_on_error=False)

        # Apply hierarchical postprocessing to improve document structure
        ResultPostprocessor(conv_res).process()

        doc_filename = conv_res.input.file.stem

        if conv_res.errors:
            logging.error(f"Failed to convert {filename}: {conv_res.errors[0].error_message}")
            return ConversionResult(filename=doc_filename, error=conv_res.errors[0].error_message)

        content_md, images = self._process_document_images(conv_res)
        return ConversionResult(filename=doc_filename, markdown=content_md, images=images)

    def convert_batch(
        self,
        documents: List[Tuple[str, BytesIO]],
        extract_tables: bool = False,
        image_resolution_scale: int = IMAGE_RESOLUTION_SCALE,
    ) -> List[ConversionResult]:
        results = []

        # Split documents by type: Office vs PDF/IMAGE
        office_docs = []
        docling_docs = []

        for filename, file in documents:
            if self._is_office_document(filename):
                office_docs.append((filename, file))
            else:
                docling_docs.append((filename, file))

        # Process Office documents with MarkItDown
        for filename, file in office_docs:
            results.append(self._convert_with_markitdown(filename, file))

        # Process PDF/IMAGE documents with Docling + EasyOCR + ResultPostprocessor
        if docling_docs:
            pipeline_options = self._update_pipeline_options(extract_tables, image_resolution_scale)
            doc_converter = DocumentConverter(
                format_options={
                    InputFormat.PDF: PdfFormatOption(pipeline_options=pipeline_options),
                    InputFormat.IMAGE: ImageFormatOption(pipeline_options=pipeline_options),
                }
            )

            conv_results = doc_converter.convert_all(
                [DocumentStream(name=filename, stream=file) for filename, file in docling_docs],
                raises_on_error=False,
            )

            for conv_res in conv_results:
                # Apply hierarchical postprocessing to improve document structure
                ResultPostprocessor(conv_res).process()

                doc_filename = conv_res.input.file.stem

                if conv_res.errors:
                    logging.error(f"Failed to convert {conv_res.input.name}: {conv_res.errors[0].error_message}")
                    results.append(ConversionResult(filename=conv_res.input.name, error=conv_res.errors[0].error_message))
                    continue

                content_md, images = self._process_document_images(conv_res)
                results.append(ConversionResult(filename=doc_filename, markdown=content_md, images=images))

        return results


class DocumentConverterService:
    def __init__(self, document_converter: DocumentConversionBase):
        self.document_converter = document_converter

    def convert_document(self, document: Tuple[str, BytesIO], **kwargs) -> ConversionResult:
        result = self.document_converter.convert(document, **kwargs)
        if result.error:
            logging.error(f"Failed to convert {document[0]}: {result.error}")
            raise HTTPException(status_code=500, detail=result.error)
        return result

    def convert_documents(self, documents: List[Tuple[str, BytesIO]], **kwargs) -> List[ConversionResult]:
        return self.document_converter.convert_batch(documents, **kwargs)

    def convert_document_task(
        self,
        document: Tuple[str, bytes],
        **kwargs,
    ) -> ConversionResult:
        document = (document[0], BytesIO(document[1]))
        return self.document_converter.convert(document, **kwargs)

    def convert_documents_task(
        self,
        documents: List[Tuple[str, bytes]],
        **kwargs,
    ) -> List[ConversionResult]:
        documents = [(filename, BytesIO(file)) for filename, file in documents]
        return self.document_converter.convert_batch(documents, **kwargs)

    def get_single_document_task_result(self, job_id: str) -> ConversationJobResult:
        """Get the status and result of a document conversion job.

        Returns:
        - IN_PROGRESS: When task is still running
        - SUCCESS: When conversion completed successfully
        - FAILURE: When task failed or conversion had errors
        """

        task = AsyncResult(job_id)
        if task.state == 'PENDING':
            return ConversationJobResult(job_id=job_id, status="IN_PROGRESS")

        elif task.state == 'SUCCESS':
            result = task.get()
            # Check if the conversion result contains an error
            if result.get('error'):
                return ConversationJobResult(job_id=job_id, status="FAILURE", error=result['error'])

            return ConversationJobResult(job_id=job_id, status="SUCCESS", result=ConversionResult(**result))

        else:
            return ConversationJobResult(job_id=job_id, status="FAILURE", error=str(task.result))

    def get_batch_conversion_task_result(self, job_id: str) -> BatchConversionJobResult:
        """Get the status and results of a batch conversion job.

        Returns:
        - IN_PROGRESS: When task is still running
        - SUCCESS: A batch is successful as long as the task is successful
        - FAILURE: When the task fails for any reason
        """

        task = AsyncResult(job_id)
        if task.state == 'PENDING':
            return BatchConversionJobResult(job_id=job_id, status="IN_PROGRESS")

        # Task completed successfully, but need to check individual conversion results
        if task.state == 'SUCCESS':
            conversion_results = task.get()
            job_results = []

            for result in conversion_results:
                if result.get('error'):
                    job_result = ConversationJobResult(status="FAILURE", error=result['error'])
                else:
                    job_result = ConversationJobResult(
                        status="SUCCESS", result=ConversionResult(**result).model_dump(exclude_unset=True)
                    )
                job_results.append(job_result)

            return BatchConversionJobResult(job_id=job_id, status="SUCCESS", conversion_results=job_results)

        return BatchConversionJobResult(job_id=job_id, status="FAILURE", error=str(task.result))
