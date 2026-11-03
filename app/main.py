"""Application factory for the single-server week 1 build."""

import logging
import os
from contextlib import asynccontextmanager

from dotenv import load_dotenv
from fastapi import Depends, FastAPI, HTTPException
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import ValidationError
from starlette.middleware.trustedhost import TrustedHostMiddleware

from app.chat.providers import Provider
from app.core.auth import bootstrap, current_user
from app.core.config import ROOT, Settings
from app.core.middleware import RequestSecurity
from app.extraction.pipeline import DocumentPipeline
from app.repositories.database import initialize
from app.schemas.responses import ErrorResponse

load_dotenv(ROOT / ".env")

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
log = logging.getLogger("aido")


def create_app():
    settings = Settings.load()

    @asynccontextmanager
    async def lifespan(app):
        os.umask(0o077)
        settings.validate()
        initialize()
        bootstrap()
        app.state.provider = Provider(settings)
        app.state.pipeline = DocumentPipeline(settings)
        app.state.pipeline.ready()
        yield

    app = FastAPI(
        title="AI.DO Onboarding — Week 1",
        version="1.0.0",
        description="Single-server authenticated onboarding, confirmed chat CRUD and local document prefill.",
        lifespan=lifespan,
        responses={
            code: {"model": ErrorResponse}
            for code in (401, 403, 404, 409, 413, 415, 422, 429, 500, 502, 503, 504)
        },
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
    )
    app.state.settings = settings
    app.add_middleware(
        TrustedHostMiddleware,
        allowed_hosts=list(settings.trusted_hosts),
        www_redirect=False,
    )
    app.add_middleware(RequestSecurity, settings=settings)
    from app.api import auth, chat, employees, imports

    for router in (auth.router, employees.router, chat.router, imports.router):
        app.include_router(router)

    @app.exception_handler(HTTPException)
    async def http_error(request, exc):
        return JSONResponse(
            {
                "detail": exc.detail,
                "request_id": getattr(request.state, "request_id", ""),
            },
            status_code=exc.status_code,
            headers=exc.headers,
        )

    @app.exception_handler(RequestValidationError)
    @app.exception_handler(ValidationError)
    async def validation(request, exc):
        errors = [
            {"field": ".".join(str(x) for x in e["loc"]), "message": e["msg"]} for e in exc.errors()
        ]
        return JSONResponse(
            {
                "detail": "Check the supplied fields.",
                "errors": errors,
                "request_id": getattr(request.state, "request_id", ""),
            },
            status_code=422,
        )

    @app.exception_handler(Exception)
    async def unexpected(request, exc):
        rid = getattr(request.state, "request_id", "")
        log.error("request_id=%s error_type=%s", rid, type(exc).__name__)
        return JSONResponse(
            {
                "detail": "The request could not be completed. Use the request ID to contact the operator.",
                "request_id": rid,
            },
            status_code=500,
        )

    @app.get("/", include_in_schema=False)
    def index():
        return FileResponse(ROOT / "app/static/index.html")

    @app.get("/favicon.svg", include_in_schema=False)
    def favicon():
        return FileResponse(ROOT / "app/static/favicon.svg", media_type="image/svg+xml")

    @app.get("/health/live", tags=["Health"], summary="Check that the application is running")
    def live():
        return {"status": "ok"}

    @app.get(
        "/health/ready",
        tags=["Health"],
        summary="Check local database/configuration and OCR readiness",
    )
    def ready():
        from app.repositories.database import connection

        with connection() as db:
            db.execute("SELECT 1").fetchone()
        return {"status": "ready"}

    @app.get("/api/system/status", tags=["System"])
    def status(user=Depends(current_user)):
        return {
            "document_mode": settings.document_mode,
            "classifier": settings.classifier,
            "chat_provider": app.state.provider.entry["kind"],
            "single_server": True,
        }

    @app.get("/openapi.json", include_in_schema=False)
    def schema(user=Depends(current_user)):
        if not settings.api_docs:
            raise HTTPException(404, "API docs are disabled.")
        return JSONResponse(app.openapi())

    @app.get("/docs", include_in_schema=False)
    def docs(user=Depends(current_user)):
        if not settings.api_docs:
            raise HTTPException(404, "API docs are disabled.")
        return HTMLResponse(
            '<!doctype html><html><head><title>AI.DO API</title><link rel="stylesheet" href="/assets/api-docs/swagger-ui.css"></head><body><div id="swagger-ui"></div><script src="/assets/api-docs/swagger-ui-bundle.js"></script><script src="/assets/api-docs/init.js"></script></body></html>'
        )

    original_openapi = app.openapi

    def documented_openapi():
        schema = original_openapi()
        for path in schema.get("paths", {}).values():
            for operation in path.values():
                if isinstance(operation, dict):
                    for parameter in operation.get("parameters", []):
                        if parameter.get("name") == "X-CSRF-Token":
                            parameter["required"] = True
        return schema

    app.openapi = documented_openapi
    app.mount("/assets", StaticFiles(directory=ROOT / "app/static"), name="assets")
    return app


app = create_app()
