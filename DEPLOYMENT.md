# AI.DO onboarding deployment

Use the `onboarding-postgres` branch with the repository Dockerfile. Create a new PostgreSQL database for this release. Existing Render SQLite data is unavailable, so initialize the owner and test HR accounts with fresh passwords.

## Render environment

| Variable | Value |
| --- | --- |
| `APP_ENV` | `production` |
| `APP_URL` | The service's public HTTPS origin |
| `APP_SECRET` | A freshly generated private random string of at least 32 characters |
| `TRUSTED_HOSTS` | The public hostname and `127.0.0.1` |
| `DATABASE_URL` | PostgreSQL connection URL for accounts, employee records, original uploads, sessions and audit |
| `MONGODB_URI` | MongoDB connection URI for private conversation threads |
| `MONGODB_DATABASE` | `aido` or an environment-specific name |
| `QDRANT_URL` and `QDRANT_API_KEY` | Qdrant endpoint and API key for employee search |
| `QDRANT_COLLECTION` | Optional distinct collection name per environment |
| `BOOTSTRAP_EMAIL` | `you@yourcompany.com` |
| `BOOTSTRAP_PASSWORD` | Owner test password, 8 or more characters |
| `TEST_HR_EMAIL` | `hr-test@example.com` |
| `TEST_HR_PASSWORD` | A separate HR test password, 8 or more characters |
| `DOCUMENT_MODE` | `google_vision` or `tesseract` |
| `GOOGLE_VISION_API_KEY` | Required with Google Vision |
| `INVITE_FROM` | Mailbox that authorized the Gmail OAuth client |
| `GMAIL_CLIENT_ID`, `GMAIL_CLIENT_SECRET`, `GMAIL_REFRESH_TOKEN` | Credentials belonging to the same Gmail OAuth client |
| `MAX_DOCUMENT_JOBS` | Start at `1` when measuring memory on a small instance |

Account seeding happens on startup and preserves later password changes on the same PostgreSQL database. Bootstrap values are initial values only. Use `scripts/reset_password.py --email <account>` from a properly configured app environment for a deliberate password reset. Keep test credentials out of source control and replace them before granting access to real employee data.

1. Configure access to the managed data services from your host, and set the variables above.
2. Deploy the Docker build. Check `/health/live` and `/health/ready`.
3. Sign in as test HR and enter `add arpit sahu, qw@123"gmail.com, 1231231231`. The chat should show the submitted values and ask HR to correct the malformed email. Retry with an inbox you control, confirm the draft and check Gmail delivery.
4. Refresh the browser and reopen the thread from history. Then sign in with the other test account and verify that the conversation is private.
5. Test a new employee's password change, document checklist, upload, submission and HR review.

Gmail HTTP 403 during sending can coexist with a successful OAuth token refresh. The app logs a recognized Gmail error reason, when available. Use the existing employee's resend action once delivery is fixed.

## Local reply model

TextCNN runs locally from `model/onboarding_intents.npz`. A separate optional GGUF model phrases low-risk conversational help. The structured onboarding service owns confirmation, permissions and all data writes.

The Docker build accepts `INSTALL_GGUF=1` to install the CPU runtime. To include a model in the image, also pass `GGUF_MODEL_URL` with a public GGUF download URL and `GGUF_MODEL_SHA256` with the file's verified SHA-256. Set runtime `GGUF_MODEL_PATH=/project/model/replies.gguf`. A mounted, readable GGUF file can also be configured through that path variable.

Start with 4-bit SmolLM2-135M-Instruct, 512 context tokens, one thread and 48 reply tokens. Measure resident memory and latency with OCR and chats active. SmolLM2-360M-Instruct is an optional quality experiment using the same integration. Increase the instance size if it cannot meet the memory and latency targets. Leaving the GGUF path empty uses deterministic replies. GGUF weights are downloaded separately.

## Code map

- `app/api/conversations.py` serves the private thread API.
- `app/chat/onboarding_agent.py` interprets a turn and dispatches typed onboarding actions.
- `app/chat/local_models.py` runs the intent CNN and optionally phrases replies.
- `app/api/onboarding.py` implements role checks, invitations, profiles, document review and employee operations.
- `app/repositories/postgres_schema.sql` defines the persistent records and `app/repositories/conversations.py` stores private MongoDB threads.
- `app/services/employee_search.py` performs contextual retrieval and verifies candidates against authoritative employee records.
- `app/static/workspace.html`, `workspace.css`, and `workspace.js` implement the single-window chat UI.

### Model files for the Docker build

Set `INSTALL_GGUF=1` and `GGUF_MODEL_PATH=/project/model/replies.gguf` in Render Environment. Choose one row and use its download URL and SHA-256 as `GGUF_MODEL_URL` and `GGUF_MODEL_SHA256`. Trigger a rebuild after changing the selection.

| Model | Download URL | SHA-256 |
| --- | --- | --- |
| SmolLM2-135M Q4_K_S, 102 MB | [Download](https://huggingface.co/bartowski/SmolLM2-135M-Instruct-GGUF/resolve/main/SmolLM2-135M-Instruct-Q4_K_S.gguf) | `a8654d8eb14c45ef3c6170b3f0c6ccd02ba3e1a6b406ca02f4ffadf0b1b222a0` |
| SmolLM2-360M Q4_K_M, 271 MB | [Download](https://huggingface.co/bartowski/SmolLM2-360M-Instruct-GGUF/resolve/main/SmolLM2-360M-Instruct-Q4_K_M.gguf) | `2fa3f013dcdd7b99f9b237717fa0b12d75bbb89984cc1274be1471a465bac9c2` |

## Fix for missing DATABASE_URL on Render

The reported Docker build succeeded. The service stopped at startup because no PostgreSQL URL was supplied. This build now serves an administrator setup page with HTTP 503 until persistent storage is configured. Account and document APIs remain unavailable during setup. /health/live returns HTTP 200 with ready false, and /health/ready returns HTTP 503.

Create or choose a PostgreSQL database. For Render Postgres, open its Info page, copy the Internal Database URL if the web service shares its region, and save that value as DATABASE_URL in the web service Environment page. For external PostgreSQL, use the provider full URL including required SSL options. Select Save and deploy.

This build also recognizes POSTGRES_URL and POSTGRESQL_URL when DATABASE_URL is empty. It requires a real database to preserve accounts. Configure MongoDB and Qdrant using the earlier sections before testing conversations and vector search.

The supplied logs show INSTALL_GGUF=0 and an empty model URL, so that deployment used deterministic replies with the CNN. To run the optional local language model, apply the model settings above and rebuild.
