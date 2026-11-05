"""Environment parsing. Secrets never appear in model configuration or API responses."""

import os
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[2]


def project_path(value):
    path = Path(value)
    return (path if path.is_absolute() else ROOT / path).resolve()


def boolean(name, default=False):
    value = os.getenv(name, str(default)).strip().lower()
    if value not in ("true", "false", "1", "0", "yes", "no"):
        raise ValueError(f"{name} must be true or false.")
    return value in ("true", "1", "yes")


@dataclass(frozen=True)
class Settings:
    environment: str
    app_url: str
    secret: str
    database: Path
    model_config: Path
    document_mode: str
    classifier: str
    session_seconds: int
    idle_seconds: int
    max_upload_bytes: int
    max_document_jobs: int
    api_docs: bool
    trusted_hosts: tuple[str, ...]

    @property
    def production(self):
        return self.environment == "production"

    @classmethod
    def load(cls):
        env = os.getenv("APP_ENV", "demo")
        url = (
            os.getenv("APP_URL") or os.getenv("RENDER_EXTERNAL_URL") or "http://127.0.0.1:8000"
        ).strip().rstrip("/")
        parsed = urlsplit(url)
        # The public origin must also pass the Host header check.
        hosts = tuple(dict.fromkeys(
            host.strip().lower()
            for host in (parsed.hostname or "localhost", *os.getenv("TRUSTED_HOSTS", "").split(","))
            if host.strip()
        ))
        return cls(
            env,
            url,
            os.getenv("APP_SECRET", ""),
            project_path(os.getenv("DATABASE_PATH", "data/onboarding.sqlite")),
            project_path(os.getenv("MODEL_CONFIG", "config/models.toml")),
            os.getenv("DOCUMENT_MODE", "mock_pan"),
            os.getenv("DOCUMENT_CLASSIFIER", "ocr"),
            int(os.getenv("SESSION_SECONDS", "28800")),
            int(os.getenv("SESSION_IDLE_SECONDS", "1800")),
            int(os.getenv("MAX_UPLOAD_MB", "10")) * 1024 * 1024,
            int(os.getenv("MAX_DOCUMENT_JOBS", "2")),
            boolean("ENABLE_API_DOCS", env != "production"),
            hosts,
        )

    def validate(self):
        parsed = urlsplit(self.app_url)
        if self.environment not in ("demo", "production"):
            raise ValueError("APP_ENV must be demo or production.")
        if (
            parsed.scheme not in ("http", "https")
            or not parsed.hostname
            or parsed.username
            or parsed.password
            or parsed.path not in ("", "/")
            or parsed.query
            or parsed.fragment
        ):
            raise ValueError("APP_URL must be an HTTP(S) origin without a path or credentials.")
        if len(self.secret) < 32 or "replace" in self.secret.lower():
            raise ValueError(
                "Set a random APP_SECRET of at least 32 characters; run scripts/init_env.py."
            )
        if self.document_mode not in ("mock_pan", "tesseract"):
            raise ValueError("DOCUMENT_MODE must be mock_pan or tesseract.")
        if self.classifier not in ("ocr", "onnx"):
            raise ValueError("DOCUMENT_CLASSIFIER must be ocr or onnx.")
        if (
            not 300 <= self.session_seconds <= 86400
            or not 60 <= self.idle_seconds <= self.session_seconds
        ):
            raise ValueError("Invalid session expiry settings.")
        if (
            not 1 <= self.max_document_jobs <= 8
            or not 1 <= self.max_upload_bytes <= 20 * 1024 * 1024
        ):
            raise ValueError("Invalid document resource limits.")
        if not self.trusted_hosts or "*" in self.trusted_hosts:
            raise ValueError("Set explicit TRUSTED_HOSTS; wildcard access is not supported.")
        if self.production and (parsed.scheme != "https" or self.document_mode != "tesseract"):
            raise ValueError("Production requires HTTPS APP_URL and DOCUMENT_MODE=tesseract.")
