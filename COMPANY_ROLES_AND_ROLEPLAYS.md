# Company roles and account corrections

Apply this patch over the latest React UI build, preserving paths. Commit and push to the Render branch, then deploy the latest commit. The current Dockerfile builds React. Startup adds an account revision counter and the employee_requests table.

## Permissions

| Role | Responsibilities |
|---|---|
| Company super admin | Invite the company owner, configure its schema and document rules, correct its accounts, disable/restore accounts and resend unactivated invitations. Limited to this company. |
| Owner | Appoint and manage HR accounts, view employees, submissions and requests. Configuration and employee mutations are denied. |
| HR admin | Add/import employees, correct their accounts, review requests and submissions, onboard/offboard, restore access and resend unactivated invitations. |
| Employee | View their own profile, upload documents, submit for review, request contact corrections or HR permission, view decisions and cancel a pending request. |

Employee name/email/phone corrections take effect after HR approval. Generic permission requests record a decision and reason. A generic approval does not grant a new application role or execute an unspecified task.

The super admin is assigned to the new company's tenant when the owner is invited. It cannot create another company. An older engineer left in the default tenant is automatically linked when its history identifies exactly one company. If an older build created several companies under one engineer, set SUPER_ADMIN_COMPANY_ID to the chosen tenant ID alongside SUPER_ADMIN_EMAIL. Existing non-default assignments are retained.

## Correcting a mistaken email

Use + > Company accounts as super admin, + > Manage HR accounts as owner, or + > Manage employee accounts as HR. Choose Correct details, edit name/email and confirm the preview. Chat supports "Change email of old@example.org to corrected@example.org".

- Super admin corrects owner accounts and can correct its own email.
- Owner corrects HR accounts.
- HR corrects employee accounts.
- Employee requests their correction through HR.
- An activated account keeps its password. Previous sessions are revoked and the old email stops authenticating.
- For an unactivated account, correct the email and select Resend invitation. A fresh temporary password goes to the corrected address.
- Duplicate emails roll back the whole correction.
- Corrections and resends check revisions. Stale previews must be refreshed.
- Disable access reversibly disables/offboards. Employee sessions are revoked. Restoring an employee returns onboarding to draft.
- A super admin cannot disable its own account.
- Changes and decisions are audited.

## Four executed role-plays

### 1. Company setup and delegation

Super admin invites owner > super admin creates fields in chat > owner appoints HR > HR adds Karthik > employee signs in.

Passed owner/HR schema denial, owner employee-creation denial, employee directory denial, HR appointment denial, and owner read-only employee oversight.

### 2. Wrong emails and account updates

Owner invites HR with a wrong email > corrects it > invitation expires > resends > HR activates > HR adds employee > HR corrects employee email > super admin corrects owner email > owner corrects activated HR email > super admin corrects its own email.

Passed corrected login, previous-session revocation, failed old-email login, unchanged passwords for activated users, duplicate-email rollback, stale-update rejection, and name/phone corrections.

### 3. Employee requests and HR decisions

Employee requests email correction > owner approval is denied > HR approves with reason > employee signs in at new email > repeated approval is rejected > HR rejects a generic permission request > employee creates and cancels another.

A duplicate-email approval fails atomically while the old email and pending request remain intact. Direct employee profile editing is denied.

### 4. Isolation, submission and offboarding

Create two companies > attempt cross-company changes > employee uploads PAN, Aadhaar and cheque > submits > HR onboards > HR disables > HR restores.

Passed foreign account/configuration/employee denial, one-company engineer binding, document minimum enforcement, owner onboarding denial, employee extracted-field editing denial, access revocation and restoration to draft.

## Verification

Run python -m pytest -q -s tests/test_company_roleplays.py

The role-plays execute real FastAPI requests, password changes, session validation, SQL transactions and assertions. They use temporary SQLite, simulated MongoDB, simulated Gmail delivery and simulated OCR output. Hosted PostgreSQL, real Gmail/OCR and local-model language quality require deployment testing.

The targeted suite including name matching and Google Vision adapter checks passed 16 tests. Four React browser checks with mocked APIs passed: owner menu and HR email correction, HR request review, employee permission request, and super-admin-only configuration. The production React build completed.
