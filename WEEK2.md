# AI.DO Week 2

Use this Tesseract build for local OCR or deploy it to the existing Render web service. The Google Vision build is a separate variant. Both use one application URL for the owner, HR admins and employees.

## Render setup

Use the existing Dockerfile. Keep the app URL, secret, trusted hosts and bootstrap settings from your working service. For a new database, BOOTSTRAP_EMAIL and BOOTSTRAP_PASSWORD create the owner. An existing Week 1 database promotes its first legacy operator to owner if no owner already exists. The remaining legacy operators need separate account migration.

| Setting | Tesseract deployment |
| --- | --- |
| APP_URL | The full HTTPS address used in every invitation |
| TRUSTED_HOSTS | The Render hostname, plus 127.0.0.1 for the container health check |
| DOCUMENT_MODE | tesseract |
| TESSERACT_LANG | eng by default |
| GMAIL_CLIENT_ID | Google OAuth web application client ID |
| GMAIL_CLIENT_SECRET | Google OAuth client secret |
| GMAIL_REFRESH_TOKEN | Offline OAuth refresh token for the sending mailbox |
| INVITE_FROM | Authorized Google Workspace mailbox, e.g. arpit.sahu@bridgelabz.com |
| DATABASE_PATH | SQLite file inside a persistent, writable mount, for example /project/data/week2.sqlite |

Keep the database mount writable by the Docker app user (UID 10001). Render Free cannot attach a persistent disk. For real submissions with this SQLite build, use a disk-backed service and take database backups. An ephemeral deployment can lose invitations, accounts, uploads and submissions when it restarts. This release stores original uploads and extracted fields in SQLite. OCR runs on this service using Tesseract.

## Authorize Gmail invitations

1. In a [Google Cloud project](https://console.cloud.google.com/), enable the Gmail API. In Google Auth Platform, configure the app audience. Use Internal if the project belongs to the BridgeLabz Workspace and Internal is available. Workspace policy may require the admin to approve the OAuth app. External apps left in Testing can receive refresh tokens that expire after seven days.
2. Create an OAuth client of type **Web application**. Add `https://developers.google.com/oauthplayground` as an authorized redirect URI for the setup below.
3. Open [Google OAuth Playground](https://developers.google.com/oauthplayground). Under the gear icon, select **Use your own OAuth credentials**, enter the client ID and secret, and use **Offline** access. Authorize the scope `https://www.googleapis.com/auth/gmail.send` while signed into the mailbox in `INVITE_FROM`. Exchange the authorization code for tokens and copy the **refresh token**.
4. Save the four values from the table in Render **Environment**. Deploy this build and invite an employee using an inbox you control. Keep the client secret and refresh token in Render. Tesseract is installed by this variant’s Dockerfile.

The app obtains an access token before it creates invitation records. If Gmail rejects a send after the account was saved, use **Resend invitation** to issue a fresh temporary password.

## Default HR account for testing

Set `TEST_HR_EMAIL` and `TEST_HR_PASSWORD` in Render Environment or in your local untracked `.env` file. Use the credentials supplied separately. Restart or redeploy, then sign in directly as Test HR. Test HR can sign in before Gmail is configured. Employee invitations require the Gmail settings above.

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
python -m pytest -q tests/test_week2.py
```

Tests use simulated invitations and OCR. Run the mailbox and upload test on Render to verify live delivery and OCR.
