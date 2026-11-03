# AI.DO — Week 1, single-server onboarding

A minimal chat interface for employee onboarding and CRUD. The web UI, authentication, document classification, OCR extraction, field prefill, audit and Excel export run in **one Python application on one port**. There is no extraction server on port 8001.

This release rebuilds `week-1`. Historical `week-2` and `week-3` branches remain in the repository for reference; they are not ported to this new architecture and must not be used as upgrade targets for its database.

## Start locally

Python 3.12 is the reference environment.

```bash
python -m venv .venv
# Windows Git Bash: source .venv/Scripts/activate
# Linux/macOS: source .venv/bin/activate
python -m pip install -r requirements.txt
python scripts/init_env.py --email you@example.com
python scripts/check_config.py
python run.py
```

Open the `APP_URL` configured in `.env`, initially `http://127.0.0.1:8000`. Open `.env` privately to obtain the generated initial password. The initialization script creates random secrets and refuses to overwrite an existing environment. Never commit `.env`.

The default configuration is a **labelled demo chat engine** and an **explicit PAN mock**. It is fully usable without API credentials or Tesseract, but it is not a generative language model or real extraction. See [USER_GUIDE.md](docs/USER_GUIDE.md).

## Real document extraction on the same server

Install the Tesseract executable and English language data. Set these values in the **root** `.env` and restart:

```env
DOCUMENT_MODE=tesseract
DOCUMENT_CLASSIFIER=ocr
TESSERACT_PATH=C:/Program Files/Tesseract-OCR/tesseract.exe
TESSERACT_LANG=eng
```

On Linux, leave `TESSERACT_PATH` blank if `tesseract` is on PATH. `DOCUMENT_CLASSIFIER=ocr` uses local OCR evidence to identify the type before choosing its extractor. The optional retained image classifier uses `DOCUMENT_CLASSIFIER=onnx` and `requirements-onnx.txt`; it also runs in this process. OCR remains authoritative for automatic field extraction.

Upload via the chat **+** button or drag and drop. The application classifies the document and fills available fields automatically. If no employee is selected, it prefills a new draft and asks only for missing name/email/phone. Review and confirm before creating the employee; then review the document values. Partial extraction never becomes verified identity.

Accepted document formats: JPEG, PNG, WEBP and **single-page PDF**, up to the configured 10 MB default and 20 megapixels. Split a multipage PDF first. There is no external OCR/Gemini extraction fallback.

## Configure a conversational model

The new `week-1` working tree no longer includes or loads a legacy chat ANN, MiniLM, or chat ONNX model. Historical branches retain their prior versions. Edit one file, `config/models.toml`, and select:

```toml
active_provider = "openai" # or "gemini", "claude", "demo"
```

Set the selected provider's key and model ID in `.env`:

| Provider | Key | Model ID |
| --- | --- | --- |
| OpenAI | `OPENAI_API_KEY` | `OPENAI_MODEL` |
| Gemini | `GEMINI_API_KEY` | `GEMINI_MODEL` |
| Claude | `ANTHROPIC_API_KEY` | `CLAUDE_MODEL` |

Use a tool-capable model available to your account; no model ID is guessed. Restart after configuration changes. Credentials stay on the server. The UI does not show operator or model badges. Provider request/response contracts are tested with simulated upstream responses; real model accounts and output quality require acceptance testing with your selected model.

Model proposals cannot execute arbitrary code or SQL. Create, update and delete requests become server-held previews with single-use confirmations and version checks. The configured model helps interpret natural language; authoritative operations and resulting status are application code.

## Try chat CRUD

```text
add Ravi Kumar, ravi@example.com, 9876543210
confirm
find Ravi
change phone to 9876543211
confirm
delete Ravi
confirm
```

`list` opens the master employee sheet. `export` downloads one workbook with all active employees across conversations. Deletion removes an employee from the active register and export; it retains their data and audit history as a soft deletion. It is not an erasure/retention-policy operation.

## Structure

```text
app/
  api/                  HTTP routes: auth, chat, employees, imports
  chat/                 Provider adapters, demo parser, guarded orchestration
  core/                 Settings, authentication, CSRF, request security
  extraction/           In-process OCR, classification and type-specific extractors
  fixtures/             Exact supplied-PAN mock annotation
  repositories/         SQLite connection and additive schema migration
  schemas/              Validated API inputs and provider action schema
  services/             Employee CRUD, fields/audit and Excel logic
  static/               Minimal UI and locally hosted API documentation assets
config/                 Provider TOML; no secrets
model/                  Optional document image classifier only
scripts/                Environment initialization, config checks, recovery, backup, OpenAPI export
tests/                  API, authentication, action and provider contract checks
docs/                   Architecture, API, operator/user guide, security, deployment and validation
```

## Authentication and deployment

Argon2id passwords; hashed opaque session tokens; HttpOnly, SameSite cookies; CSRF tokens for authenticated mutations; absolute and idle session expiry; persistent login throttling; host/origin checks; parameterized SQL; optimistic record versions; sanitized errors and request IDs. Production startup rejects the demo provider, mock extraction and a non-HTTPS public origin.

The deployment profile is **one operator/tenant, one application worker, SQLite WAL, bounded local OCR concurrency**, behind a TLS reverse proxy. This is production-oriented code with explicit limits, not a security certification or a horizontally scaled SaaS. Cloud models receive the typed conversation and selected employee's basic details, but not uploaded images or extracted document fields through the tool-planning context. A user can still type sensitive information in chat; configure an appropriate provider account and data policy.

Read [DEPLOYMENT.md](docs/DEPLOYMENT.md), [SECURITY.md](docs/SECURITY.md) and [ENVIRONMENT.md](docs/ENVIRONMENT.md) before deployment. Docker assets are provided; their execution status is reported in [VALIDATION.md](docs/VALIDATION.md).

## Documentation and tests

- [User guide](docs/USER_GUIDE.md)
- [API reference](docs/API.md), [OpenAPI JSON](docs/openapi.json)
- [Architecture and data flow](docs/ARCHITECTURE.md)
- [Provider configuration](docs/PROVIDERS.md)
- [Environment reference](docs/ENVIRONMENT.md)
- [Deployment and backups](docs/DEPLOYMENT.md)
- [Security and limitations](docs/SECURITY.md)
- [Validation and release notes](docs/VALIDATION.md)

After signing in, `/docs` provides locally hosted Swagger UI, and `/openapi.json` provides the live schema when `ENABLE_API_DOCS=true`. Both require authentication and are disabled by default in the production template. There is no CDN dependency.

```bash
python -m pip install -r requirements-dev.txt
python -m pytest -q tests
python scripts/export_openapi.py
```
