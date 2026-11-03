# Environment reference

One root `.env` configures the entire server. There is no `vendor/advo/.env`. Values already present in the process environment take precedence. Relative database/model-config paths resolve from the project root, independent of the shell's working directory. Restart after edits.

| Variable | Default / required | Purpose |
| --- | --- | --- |
| APP_ENV | demo | demo or production |
| APP_URL | http://127.0.0.1:8000 | Exact public browser origin; HTTPS required in production |
| APP_SECRET | Required, 32+ random characters | CSRF HMAC; generate with init_env.py |
| BIND_HOST | 127.0.0.1 | Internal bind address; do not expose the backend publicly |
| PORT | 8000 | Only application port |
| TRUSTED_HOSTS | APP_URL hostname | Explicit comma-separated hosts; no wildcard |
| DATABASE_PATH | data/onboarding.sqlite | SQLite file, WAL and protected writable directory |
| BOOTSTRAP_EMAIL | Required for empty database | Initial operator account |
| BOOTSTRAP_PASSWORD | Required for empty database, 16+ characters | Initial password only; not a reset mechanism |
| MODEL_CONFIG | config/models.toml | Provider configuration path |
| DOCUMENT_MODE | mock_pan | mock_pan or tesseract; production rejects mock |
| DOCUMENT_CLASSIFIER | ocr | OCR-evidence classifier, or optional onnx image classifier |
| TESSERACT_PATH | PATH lookup | Actual executable path, not a pip package path |
| TESSERACT_LANG | eng | Installed Tesseract language data |
| MAX_UPLOAD_MB | 10 | Allowed file bytes; 1–20 MB supported; OCR image cap remains 20 MP |
| MAX_DOCUMENT_JOBS | 1 in template | Concurrent extraction slots, maximum 8 |
| SESSION_SECONDS | 28800 | Absolute session lifetime, up to 24 hours |
| SESSION_IDLE_SECONDS | 1800 | Idle timeout, no longer than absolute lifetime |
| ENABLE_API_DOCS | true in demo | Authenticated /docs and /openapi.json; production template disables |
| OPENAI_API_KEY / OPENAI_MODEL | Blank | Required only for selected OpenAI provider |
| GEMINI_API_KEY / GEMINI_MODEL | Blank | Required only for selected Gemini provider |
| ANTHROPIC_API_KEY / CLAUDE_MODEL | Blank | Required only for selected Claude provider |

`config/models.production.toml` initially selects OpenAI. Set a model ID that your account supports. Production startup validates keys/models are configured, but does not perform a billable test request or certify provider availability. API docs do not expose these values.

Use `python scripts/init_env.py --email you@example.com --production` for the production template, then set the real host, provider/model and credentials. The script refuses to overwrite `.env`; keep secrets in your deployment secret store or a private file with appropriate OS permissions. Never use the sample host as a real configuration.
