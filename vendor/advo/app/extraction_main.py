"""FastAPI composition root for the extraction service."""
from fastapi import FastAPI
from app.api.v1.routes.extraction import router

app = FastAPI(
    title="ADVO Document Extraction API",
    version="1.0.0",
    description="Local Tesseract OCR, extraction, and structural validation.",
    swagger_ui_parameters={"defaultModelRendering": "model"},
)
app.include_router(router)
