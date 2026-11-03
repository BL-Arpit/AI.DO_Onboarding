# API reference — v1.0.0

Base URL: your configured origin, e.g. `http://127.0.0.1:8000`. All employee/chat/import endpoints require an operator session. Mutations also require `X-CSRF-Token`. Use TLS in production. Schema: `docs/openapi.json`, authenticated live `/openapi.json`, authenticated local Swagger UI `/docs` when enabled.

## Authentication

`POST /api/auth/login`

```json
{"email":"you@example.com","password":"your-private-password"}
```

Success sets an opaque HttpOnly cookie and returns `{"csrf_token":"..."}`. Send that value in the CSRF header on later POST/PATCH/PUT/DELETE requests. Browser clients use same-origin cookies. `GET /api/auth/session` returns the user and a CSRF token for the current session. `POST /api/auth/logout` revokes it. `POST /api/auth/password` accepts `old_password`, `new_password` (16+ characters), revokes all sessions and clears the cookie. No public account registration or password-reset email endpoint exists; local recovery is in `scripts/reset_password.py`.

Example shell flow (use a private terminal and protect cookie files):

```bash
curl -c cookies.txt -H 'Content-Type: application/json' \
  -d '{"email":"you@example.com","password":"YOUR_PASSWORD"}' \
  http://127.0.0.1:8000/api/auth/login
# Read csrf_token from the response, then supply it without committing it to scripts.
curl -b cookies.txt -H 'X-CSRF-Token: YOUR_CSRF_TOKEN' \
  -H 'Content-Type: application/json' \
  -d '{"message":"add Ravi Kumar, ravi@example.com, 9876543210","conversation_id":"onboarding-1"}' \
  http://127.0.0.1:8000/api/chat
```

Examples contain synthetic data and placeholders, not application credentials.

## Chat and confirmed actions

| Method | Path | Purpose |
| --- | --- | --- |
| POST | /api/chat | Interpret a message and return an action, reply or preview |
| POST | /api/actions/{id}/confirm | Apply one pending user/conversation-scoped change |
| GET | /api/conversations | List the signed-in user's conversations |
| GET | /api/conversations/{id} | Read messages, current selection and an unexpired pending preview |
| POST multipart | /api/chat/{id}/attachments | Upload via chat; XLS/XLSX previews imports, documents classify/extract/prefill |

Chat input: `message` (1–2,000 characters) and `conversation_id` (1–64 letters/digits/underscore/hyphen). A typical mutation proposal:

```json
{
  "reply":"Review this create and confirm to apply it.",
  "action":"confirm",
  "pending_id":"opaque-single-use-id",
  "proposal":{"operation":"create","fields":{"name":"Ravi Kumar","email":"ravi@example.com","phone":"9876543210","client":"","track":"onboard"}}
}
```

Confirm with `POST /api/actions/{pending_id}/confirm`, JSON `{"conversation_id":"onboarding-1"}`, session cookie and CSRF header. A confirmation expires in ten minutes, belongs to one user/conversation and is single-use. A newer proposal invalidates an older one. `confirm` as an exact chat message is also handled by application code, never by a provider tool.

Read/list/audit/export do not require a mutation preview. The audit updates verification metadata. Create/update/delete proposals require confirmation. Ambiguous employee matches return a `choices` list; `select EMPLOYEE_ID` chooses one. Bulk update/delete are not implemented.

A first document upload can precede employee creation. The response includes `draft`, the next missing-field question and `document.prefill`. The server holds that extraction for ten minutes; creating the employee then attaches the extracted fields atomically. No document values are written to an employee until the draft is confirmed.

## Employees

| Method | Path | Body / result |
| --- | --- | --- |
| GET | /api/employees?q=... | Active employees; query filters name/email/ID |
| POST | /api/employees | Explicit direct API create; returns 201 and employee |
| GET | /api/employees/{id} | Employee, document results and audit history |
| PATCH | /api/employees/{id} | `version`, `fields` patch for basic details |
| DELETE | /api/employees/{id} | JSON `version`; soft deletion |
| POST multipart | /api/employees/{id}/documents | File and optional `document_type`; local extraction and automatic field prefill |
| PUT | /api/employees/{id}/fields | `version`, complete document `fields` dictionary |
| POST | /api/employees/{id}/audit | JSON `version`; document consistency checks |
| GET | /api/employees/master | `columns`, `rows`, one row per active employee |
| GET | /api/employees/export | XLSX attachment `master_employees.xlsx` |

Direct REST mutations are explicit operator requests; they do not use the chat preview mechanism. The front end uses preview confirmation for model-proposed basic changes and deletion. All writes require authenticated CSRF protection, and updates/deletes require the current version.

Create fields: `name` (1–120 characters), `email` (valid address, up to 254), `phone` (8–15 digits, optional leading +, spaces/dashes/parentheses normalized), optional `client` (up to 120), optional `track` (`client`, `onboard`, `validate`; default onboard). Emails are normalized to lowercase and unique across active and retained deleted records.

Update example:

```json
{"version":3,"fields":{"phone":"9876543211","client":"Example client"}}
```

Deletion is soft: successful response `{"id":"...","deleted":true}`. The employee leaves active lists/exports, but records and audit remain retained. There is no public permanent-erasure or restore endpoint in week 1.

## Extraction response

Document multipart field name: `file`. Optional `document_type`: PAN_CARD, AADHAAR_CARD, BANK_PASSBOOK, CHEQUE. Auto uses local evidence. Accepted files: JPEG, PNG, WEBP or single-page PDF within configured limits. Empty/unreadable/unsupported files and empty extraction are errors, not successful uploads.

```json
{
  "document":{
    "classification":{"document_type":"PAN_CARD","source":"local_ocr","confidence":null,"needs_review":false},
    "extraction":{"document_type":"PAN_CARD","status":"success","extraction_source":"tesseract","extracted_data":{"name":"SYNTHETIC PERSON","pan_number":"ABCDE1234F"}},
    "prefill":{"name":"SYNTHETIC PERSON","pan_number":"ABCDE1234F"},
    "stages":["validated","classified","extracted","prefilled"],
    "sha256":"source-content-hash"
  },
  "employee":{"id":"...","version":4,"fields":{"PAN_CARD":{"name":"SYNTHETIC PERSON","pan_number":"ABCDE1234F"}}}
}
```

The example is abbreviated. Missing values may be null. `success` means the extractor's required fields/format checks passed; it does not mean authentic identity. `partial` requires review. Mock mode uses `classification.source=mock_fixture`, `extraction_source=mock`, `is_mock=true`, `status=partial` and validation false. Its annotation is never reported as OCR.

OCR text-based typing has no calibrated probability; confidence is null. Optional image-model scores are advisory and returned under `classification.image_model`. Type-specific field values prefill the employee record and are rendered immediately by the chat UI.

## Excel

`POST /api/imports/preview` accepts multipart `file`. The chat attachment route also accepts workbooks. Required columns: name/email/phone; optional client/track. Preview returns accepted/rejected rows and `import_id`; it creates no employees. `POST /api/imports/{id}/confirm` commits all accepted rows atomically. Duplicate races roll back the batch. A preview expires after ten minutes and cannot be replayed.

`GET /api/employees/export` returns `application/vnd.openxmlformats-officedocument.spreadsheetml.sheet` and Content-Disposition attachment. The single Master Employees worksheet includes extracted field columns and preserves mock markers. Strings are literal cells, and invalid Excel control characters are removed.

## Health, documentation and errors

- `/health/live`: unauthenticated process liveness.
- `/health/ready`: unauthenticated local database/startup readiness; it does not make cloud requests.
- `/api/system/status`: authenticated document mode/classifier/provider kind and single-server flag; no secrets.
- `/docs`, `/openapi.json`: authenticated and controlled by ENABLE_API_DOCS.

Application-route errors are JSON with a safe `detail`, a random `request_id`, and optional validation `errors` containing field paths/messages. Secret-bearing input values are excluded. Response header `X-Request-ID` correlates to sanitized server logs. Statuses: 400 invalid host, 401 expired/bad session, 403 CSRF/origin/role, 404 missing/deleted record, 409 version/replay/expiry/duplicate conflict, 413 resource limit, 415 format, 422 validation/empty OCR, 429 login/OCR saturation, 502 malformed/upstream provider, 503 configured service failure, 504 provider timeout. Retry-After is used for throttling.

Host validation can return a plain-text 400 before routing. Non-multipart JSON bodies are capped at 64 KB in addition to individual field limits.
