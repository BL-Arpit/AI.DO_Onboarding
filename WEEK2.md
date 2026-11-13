# AI.DO Week 2

Deploy the Google Vision folder to the existing Render web service. The Tesseract folder is a separate checkout for local work. Both use one application URL for the owner, HR admins and employees.

## Render setup

Use the existing Dockerfile. Keep the app URL, secret, trusted hosts and bootstrap settings from your working service. For a new database, BOOTSTRAP_EMAIL and BOOTSTRAP_PASSWORD create the owner. An existing Week 1 database promotes its first legacy operator to owner if no owner already exists. The remaining legacy operators need separate account migration.

| Setting | Google Vision deployment |
| --- | --- |
| APP_URL | The full HTTPS address used in every invitation |
| TRUSTED_HOSTS | The Render hostname, plus 127.0.0.1 for the container health check |
| DOCUMENT_MODE | google_vision |
| GOOGLE_VISION_API_KEY | Your Cloud Vision key, stored in Render |
| RESEND_API_KEY | A Resend sending key, stored in Render |
| INVITE_FROM | A sender address on your verified Resend domain |
| DATABASE_PATH | SQLite file inside a persistent, writable mount, for example /project/data/week2.sqlite |

Keep the database mount writable by the Docker app user (UID 10001). Render Free cannot attach a persistent disk. For real submissions with this SQLite build, use a disk-backed service and take database backups. An ephemeral deployment can lose invitations, accounts, uploads and submissions when it restarts. This release stores original uploads and extracted fields in SQLite. Google Vision receives the uploaded image or rendered PDF page during extraction.

Verify your sender domain in Resend before inviting arbitrary recipients. Resend's HTTP API is used instead of SMTP because the free Render service blocks standard SMTP ports. See https://resend.com/docs/dashboard/domains/introduction and https://render.com/docs/free.

## Default HR account for testing

Set `TEST_HR_EMAIL` and `TEST_HR_PASSWORD` in Render Environment or in your local untracked `.env` file. Use the credentials supplied separately. Restart or redeploy, then sign in directly as Test HR. This setup does not use Resend. Employee invitations still require the Resend settings above.

The app stores a password hash in SQLite and creates this account only if the email is new. Restarting preserves any later password change. To preserve the account on Render, attach a persistent disk at `/project/data` and use `DATABASE_PATH=/project/data/week2.sqlite`. If you already have a persistent database, keep its existing path.

## Test with email addresses you control

1. Sign in as owner and enter **appoint hr**. Use a test HR mailbox.
2. Check the inbox and spam folder. Sign in with the temporary password and set a new password. Temporary passwords expire after 24 hours.
3. As HR, enter **add** to invite one employee or **add list** to preview an XLS/XLSX workbook with Name, Email and Phone. Confirm invitations. If a send fails, use **Resend invitation** under **submissions**. For HR, repeat **appoint hr** with the same email before activation.
4. Sign in as the employee, change the temporary password, update the profile and upload PAN, Aadhaar and a bank document. Use a JPEG, PNG, WEBP or a single-page PDF. Click **Submit for review**.
5. As HR, enter **verify**, open the employee and inspect the originals and extracted details. Use **Request correction** to reopen the submission. Onboarding requires at least one matching readable government name and no readable mismatches.
6. Click **Onboard** in the review list. Then use **submissions → Delete / Offboard** to remove the test employee from the active list and revoke their access immediately. Documents and audit history are retained in the database. The employee email remains reserved.

The employee can edit their name and phone while preparing a submission. After onboarding, they can edit their phone. Their login email is fixed. The name check compares OCR text with the employee profile.

The Week 2 routes replace Week 1 chat CRUD routes. Run the relevant tests with:

```sh
python -m pip install -r requirements.lock pytest xlwt
python -m pytest -q tests/test_week2.py tests/test_google_vision_ocr.py
```

Tests use simulated invitations and OCR. Run the mailbox and upload test on Render to verify live delivery and OCR.
