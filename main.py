import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from document_converter.route import router as document_converter_router
from document_converter.health import router as health_router

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Initialize resources on startup and cleanup on shutdown."""
    # Startup: Initialize SQLite database
    try:
        from audit import init_db
        init_db()
        logger.info("Audit database initialized")
    except ImportError:
        logger.warning("Audit module not available, skipping database initialization")
    except Exception as e:
        logger.error(f"Failed to initialize audit database: {e}")

    yield

    # Shutdown: Cleanup if needed
    pass


app = FastAPI(
    title="Document Converter API",
    description="Convert documents (PDF, DOCX, images) to Markdown with OCR support",
    version="1.0.0",
    lifespan=lifespan,
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
