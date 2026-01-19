from io import BytesIO
import re
from enum import Enum
from typing import Dict, List, Optional, Tuple

import filetype


class InputFormat(str, Enum):
    DOCX = "docx"
    PPTX = "pptx"
    XLSX = "xlsx"
    HTML = "html"
    IMAGE = "image"
    PDF = "pdf"
    ASCIIDOC = "asciidoc"
    MD = "md"
    CSV = "csv"


class OutputFormat(str, Enum):
    MARKDOWN = "md"
    JSON = "json"
    TEXT = "text"
    DOCTAGS = "doctags"


FormatToExtensions: Dict[InputFormat, List[str]] = {
    InputFormat.DOCX: ["docx", "dotx", "docm", "dotm"],
    InputFormat.PPTX: ["pptx", "potx", "ppsx", "pptm", "potm", "ppsm"],
    InputFormat.XLSX: ["xlsx", "xlsm", "xltx", "xltm"],
    InputFormat.PDF: ["pdf"],
    InputFormat.MD: ["md"],
    InputFormat.HTML: ["html", "htm", "xhtml"],
    InputFormat.IMAGE: ["jpg", "jpeg", "png", "tif", "tiff", "bmp"],
    InputFormat.ASCIIDOC: ["adoc", "asciidoc", "asc"],
    InputFormat.CSV: ["csv"],
}

FormatToMimeType: Dict[InputFormat, List[str]] = {
    InputFormat.DOCX: [
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "application/vnd.openxmlformats-officedocument.wordprocessingml.template",
    ],
    InputFormat.PPTX: [
        "application/vnd.openxmlformats-officedocument.presentationml.template",
        "application/vnd.openxmlformats-officedocument.presentationml.slideshow",
        "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    ],
    InputFormat.XLSX: [
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        "application/vnd.ms-excel.sheet.macroEnabled.12",
        "application/vnd.openxmlformats-officedocument.spreadsheetml.template",
    ],
    InputFormat.HTML: ["text/html", "application/xhtml+xml"],
    InputFormat.IMAGE: [
        "image/png",
        "image/jpeg",
        "image/tiff",
        "image/gif",
        "image/bmp",
    ],
    InputFormat.PDF: ["application/pdf"],
    InputFormat.ASCIIDOC: ["text/asciidoc"],
    InputFormat.MD: ["text/markdown", "text/x-markdown"],
    InputFormat.CSV: ["text/csv"],
}
MimeTypeToFormat = {mime: fmt for fmt, mimes in FormatToMimeType.items() for mime in mimes}


def detect_html_xhtml(content):
    content_str = content.decode("ascii", errors="ignore").lower()
    # Remove XML comments
    content_str = re.sub(r"<!--(.*?)-->", "", content_str, flags=re.DOTALL)
    content_str = content_str.lstrip()

    if re.match(r"<\?xml", content_str):
        if "xhtml" in content_str[:1000]:
            return "application/xhtml+xml"

    if re.match(r"<!doctype\s+html|<html|<head|<body", content_str):
        return "text/html"

    return None


def is_csv_file(filename: str) -> bool:
    """Check if a file is a CSV based on its extension."""
    return filename and filename.lower().endswith('.csv')


def guess_format(obj: bytes, filename: str = None):
    content = b""
    mime = None

    if isinstance(obj, bytes):
        content = obj
        # Special handling for CSV files
        if is_csv_file(filename):
            return InputFormat.CSV

        mime = filetype.guess_mime(content)

        # If MIME detection failed or returned unknown type, try extension fallback
        if mime is None or mime not in MimeTypeToFormat:
            ext = filename.rsplit(".", 1)[-1] if ("." in filename and not filename.startswith(".")) else ""
            extension_mime = mime_from_extension(ext)
            if extension_mime:
                mime = extension_mime

    mime = mime or detect_html_xhtml(content)
    mime = mime or "text/plain"
    return MimeTypeToFormat.get(mime)


def handle_csv_file(file: BytesIO) -> Tuple[BytesIO, Optional[str]]:
    """Handle CSV file encoding by trying multiple encodings.

    Returns:
        Tuple[BytesIO, Optional[str]]: (processed file, error message if any)
    """
    SUPPORTED_CSV_ENCODINGS = ['utf-8', 'latin1', 'cp1252', 'iso-8859-1']
    for encoding in SUPPORTED_CSV_ENCODINGS:
        try:
            file.seek(0)
            content = file.read().decode(encoding)
            return BytesIO(content.encode('utf-8')), None
        except UnicodeDecodeError:
            continue
    return file, f"Could not decode CSV file. Supported encodings: {', '.join(SUPPORTED_CSV_ENCODINGS)}"


def mime_from_extension(ext):
    """Get MIME type from file extension."""
    mime = None

    # Check all format mappings
    for input_format in InputFormat:
        if ext in FormatToExtensions.get(input_format, []):
            mime = FormatToMimeType.get(input_format, [None])[0]
            break

    return mime


def is_legacy_office_format(filename: str) -> bool:
    """Check if file is a legacy Office format (.doc, .xls, .ppt)."""
    legacy_extensions = {'.doc', '.xls', '.ppt'}
    return any(filename.lower().endswith(ext) for ext in legacy_extensions)


def is_file_format_supported(file_bytes: bytes, filename: str) -> bool:
    return guess_format(file_bytes, filename) in FormatToExtensions.keys()
