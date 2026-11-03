# Deployment and operations

## Supported release profile

Python 3.12, one Uvicorn worker with a 16-connection concurrency limit and five-second keep-alive, one operator/tenant, SQLite WAL and one local OCR job by default. The single process exposes one application port. HTTP extraction, model servers for the old chat ANN, worker/email services and port 8001 are absent. External chat API calls happen only after selecting/configuring a provider and sending a chat request.

This is a production-oriented baseline. Cloud account/model behavior, Windows deployment, capacity, security review and the Docker image require deployment-specific acceptance; see VALIDATION.md. Do not assume horizontal scaling or multiple workers are supported by the documented capacity profile.

## Prepare

1. Select a protected host and install Python, Tesseract and English trained data.
2. Create a dedicated OS account, private environment/data directories and a virtual environment.
3. Install `requirements.lock` for the recorded Linux/Python reference dependency set, or resolve `requirements.txt` and run the checks on your target platform.
4. Run `python scripts/init_env.py --email YOUR_EMAIL --production`. Edit `.env` privately to set the real HTTPS APP_URL, explicit TRUSTED_HOSTS and provider/model credentials.
5. Edit `config/models.production.toml` to select your supported provider and account model. Production refuses the demo provider and mock extraction.
6. Run `python scripts/check_config.py`, then `python -m pytest -q tests` in a separate test environment. Config checks do not send a cloud request.
7. Start `python run.py` under a process supervisor with a private environment. Bind internally, then configure TLS reverse proxying to that one port. A reference Nginx snippet is in deploy/.
8. Verify real sign-in, expiry/CSRF, selected-provider tool output, document upload/prefill, record update/deletion, master export, backups and restore using non-production data first.

The public APP_URL may be HTTPS while Uvicorn is HTTP on loopback behind TLS termination. Secure cookies use the configured public origin. Keep backend access private, because direct HTTP login would otherwise carry credentials without TLS. Set the proxy's Host header to the configured application host.

## Docker

The Dockerfile installs local Tesseract and runs the application as UID 10001. Compose defines exactly one app service with loopback publishing, read-only root filesystem, bounded writable /tmp, a data volume, dropped capabilities and no-new-privileges. The image health check allows the internal loopback Host through the compose TRUSTED_HOSTS environment value.

```bash
docker compose build
docker compose up -d
```

Prepare the root `.env` before running compose. The volume must be writable by UID 10001. Mount secrets using your deployment secret system or a protected environment file. Pin the base image by a verified digest and scan the built image according to your deployment process. The included Docker assets are not a claim that the image was built/tested in this environment.

## Migration and rollback

Back up first. On startup, the application adds its new auth/chat tables and deleted_at column without removing existing employee/document/audit records. Legacy sessions are invalidated; successful legacy scrypt sign-in upgrades the password hash to Argon2id. Existing users are not reset by BOOTSTRAP_PASSWORD. Existing role data must be operator/owner; arbitrary week 2/3 roles are not supported here.

Historical week-2/week-3 branches remain reference milestones and have not been ported to this architecture. Do not switch an active database between them and the new week 1 build. For rollback, stop the app and restore the matching code plus pre-upgrade backup together.

## Backup and recovery

```bash
python scripts/backup.py /PRIVATE/BACKUPS/onboarding-YYYYMMDD.sqlite
```

This uses SQLite's online backup API, so active WAL data is included consistently. A simple copy of the main SQLite file while WAL is active is not the documented backup method. The utility refuses to overwrite its destination. Protect backups as employee data. Restore into a new private database path while the app is stopped, verify the backup's integrity and permissions, start the matching release and test authentication/data.

For local credential recovery:

```bash
python scripts/reset_password.py --email YOUR_EMAIL
```

It prompts without echoing the new password and revokes all account sessions. It requires administrator-level filesystem/environment access; no public recovery bypass is exposed.

## Monitoring and retention

Use /health/live for process monitoring and /health/ready for local database/startup readiness. These do not make billable provider health calls. Monitor request IDs, 429/5xx rates, response time, OCR saturation, disk space and backup/restore results. Logs exclude bodies and credentials. The reference release retains chat/audit/deleted records; apply an approved retention process separately. Expired temporary previews are cleaned at startup (and expired import previews on new imports); no background erasure job is implied.
