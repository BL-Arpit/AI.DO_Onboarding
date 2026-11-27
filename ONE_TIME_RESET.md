# One-time deployment reset

Apply these files over the latest AI.DO build, preserving paths, commit and push to your Render branch.

This permanently clears all companies and users in this AI.DO installation. The configured super admin is recreated. Existing document binaries stored in document_uploads are deleted too. Database/provider backups and files stored outside these application stores are not deleted.

Before deployment, stop use of the app. Do not keep an old instance accepting writes during the purge. For Render's overlapping deploys, suspend the old service first, save the new environment and commit, then resume/deploy the updated build. Use WEB_CONCURRENCY=1 for this maintenance deployment.

In Render Environment, keep your connection strings, OAuth settings, OCR settings, APP_SECRET, SUPER_ADMIN_EMAIL and SUPER_ADMIN_PASSWORD. Add:

AIDO_RESET_ID=clean-start-2026-11-27
AIDO_RESET_CONFIRM=DELETE_ALL_AIDO_DATA

Remove SUPER_ADMIN_COMPANY_ID if present because the old company is deleted. Remove BOOTSTRAP_PASSWORD, TEST_HR_EMAIL and TEST_HR_PASSWORD so dummy accounts stay disabled after you remove the reset flags.

Deploy the new commit. Look for this log:
AI.DO reset completed. Configured super admin will be recreated at startup.

After the service starts successfully, remove AIDO_RESET_ID and AIDO_RESET_CONFIRM and redeploy. Sign in with SUPER_ADMIN_EMAIL and SUPER_ADMIN_PASSWORD. All previous accounts and sessions are deleted.

If the reset flags accidentally remain, the same reset ID does not purge again. The aido_reset_runs table preserves completed ID hashes and is excluded from resets. Use a NEW ID only when you deliberately want another full deletion. Never delete the reset ledger while leaving reset flags enabled.

Scope:
- Exact AI.DO SQL tables including tenants, schema versions, users, sessions, employees, requests, document data and audit rows. No CASCADE is used. Unexpected foreign key dependencies cause a failure rather than deleting another table.
- Only MONGODB_DATABASE / MONGODB_CONVERSATION_COLLECTION (defaults aido / onboarding_private_threads_v1).
- Only QDRANT_COLLECTION and QDRANT_CHAT_COLLECTION (defaults aido_employee_directory_v1 and aido_private_chat_potion64_v1). Collections are recreated by the app when indexing resumes.

Use AI.DO-dedicated stores/collection names. This is an installation-wide maintenance reset, never a chat command or a company-role operation.

Failure behavior: missing configuration or external errors stop startup. SQL deletion and completion marker commit together. External stores cannot participate in the SQL transaction, so an interrupted attempt may already have removed chats/vectors even if SQL rolled back. Restore connectivity and retry the SAME ID before using the app. Do not remove the flags to bypass an incomplete reset.

Tests cover explicit confirmation, SQL rollback, retry, preservation on repeat startup, super-admin-only recreation and configured external collection scope. SQLite, simulated MongoDB and simulated Qdrant are used. Live PostgreSQL/Render/cloud credentials have not been exercised here.

Run tests:
python -m pytest -q tests/test_data_reset.py tests/test_company_roleplays.py
