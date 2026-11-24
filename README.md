# AI.DO customer onboarding

A forward engineer signs in as super admin, configures an organization from a customer workbook, and reviews the owner invitation. HR is optional. Each user has one private conversation. The employee uploads documents in that conversation, reviews extracted fields and submits them to HR.

## Deploy the update

1. Overlay this archive on the existing Week 3 Google Vision repository, retaining relative paths. Commit the changes on the branch used by the Render Docker service.
2. Add SUPER_ADMIN_EMAIL and SUPER_ADMIN_PASSWORD to the service environment. Use a unique email and a private password. Existing owner accounts keep their role. A new database can start with just the super admin by leaving BOOTSTRAP_PASSWORD unset. Keep the existing PostgreSQL, MongoDB, Qdrant, Gmail OAuth, Google Vision and APP_SECRET values.
3. Build with the Dockerfile defaults. Remove old overrides that disable INSTALL_GGUF or blank out GGUF_MODEL_URL, GGUF_MODEL_SHA256 or GGUF_MODEL_PATH. Use GGUF_CONTEXT_TOKENS=1024, GGUF_THREADS=1, GGUF_MAX_REPLY_TOKENS=128 and MAX_DOCUMENT_JOBS=1. DOCUMENT_MODE is google_vision and DOCUMENT_CLASSIFIER is ocr. The build downloads checksum-verified chat and memory weights. Runtime inference stays in the web container.
4. Deploy the commit. Open the app as the super admin, choose **+ → Use customer workbook**, and upload examples/customer-onboarding.xlsx. This reads headers only. Set the document rules, review the fields and enter the owner and optional HR. Review and confirm the invitation to create the organization. Gmail delivery results appear individually.
5. Sign in as the invited owner, change the temporary password, and appoint HR or start adding employees. Employees upload their own documents. An additional middle name prompts review. An HR reviewer can record a reasoned decision or request correction. An employee edit after submission returns the record to draft for resubmission. In the document drawer, reviewers can compare original OCR, edited values and revision history.

## How the parts fit together

- **app/chat/** — SmolLM2-135M-Instruct GGUF generates conversational replies locally. A small pretrained Model2Vec encoder ranks tool descriptions. The decoder resolves ambiguous choices under a role-specific output grammar. The backend validates typed arguments and handles confirmation. Ordinary onboarding requests can go directly to the relevant tool after a confident semantic match. Multi-step workflows progress over chat turns.
- **app/services/tenant_metadata.py and app/api/organizations.py** — PostgreSQL holds organization-specific field definitions, accepted document types and counts, and versioned configurations. Customer fields are stored in employee metadata. Queries validate field names against the published configuration and bind values. Core login, employee identity and audit operations retain fixed SQL. The release supports an employee entity with configurable fields and the draft, submitted and onboarded lifecycle.
- **Schema changes** — Super admin uses **+ → Edit organization**. Renaming a custom key migrates employee values in the same transaction as the configuration revision. A same-key type change converts existing values or rejects the whole migration. Removing fields requires a separate reviewed migration. Existing employees belong to the default organization after upgrade. New rules apply when open cases are submitted or approved.
- **app/repositories/conversations.py** — MongoDB keeps one thread per account. Older pages are archived inside the same conversation. This build starts a fresh namespace. Previous chat collections remain in storage and are excluded from this workspace.
- **app/services/chat_memory.py** — Qdrant indexes learned 64-dimensional message embeddings. Search filters by user and thread, then verifies returned text against MongoDB. Current employee data comes from tenant-scoped SQL. If Qdrant is unavailable, the recent conversation still works. Indexing during an outage is best effort.
- **app/extraction/ and app/api/onboarding.py** — Google Vision supplies OCR text. The application classifies supported documents and extracts fields. The supported types are PAN, Aadhaar, passbook and cheque. Uploads support images and single-page PDFs. OCR can leave fields blank. Names are compared against original OCR, and each middle-name decision is tied to the particular document and name values.
- **app/static/workspace.*** — Role-specific chat actions, inline configuration, employee drafts, private thread and a right-side raster preview. The server checks document access. The UI offers no document download control. A browser displaying a preview can still capture it.

## Validation

The tests run with synthetic employee data. The real GGUF plus the real embedding model were exercised through the HTTP chat flow for greeting, creating a draft, correcting a middle name, confirming an invitation and listing HR. That test mocked MongoDB and Gmail delivery and used SQLite. Peak process memory in that run was about 342 MiB. Hosted latency, memory during concurrent OCR, and live external integrations still require a Render smoke test.

Run the current feature tests with:

    python -m pytest -q tests/test_customer_workspace.py tests/test_onboarding.py tests/test_employee_search.py tests/test_name_matching.py tests/test_conversation_workspace.py tests/test_hr_directory.py tests/test_google_vision_ocr.py tests/test_smollm_agent.py tests/test_conversational_model.py

The repository also contains older tests for previous API contracts. See the reported validation results before using the full suite as a release gate.
