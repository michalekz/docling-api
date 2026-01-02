from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from document_converter.route import router as document_converter_router
from document_converter.health import router as health_router

app = FastAPI(
    title="Document Converter API",
    description="Convert documents (PDF, DOCX, images) to Markdown with OCR support",
    version="1.0.0",
)


app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
    allow_credentials=True,
)


app.include_router(health_router, prefix="", tags=["health"])
app.include_router(document_converter_router, prefix="", tags=["document-converter"])
