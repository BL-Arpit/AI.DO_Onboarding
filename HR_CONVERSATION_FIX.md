# HR conversation correction

Apply these files over AI_DO_Company_Roles_CRUD_Update, preserving paths. Push to the deployed Git branch and redeploy Render. No environment values, database migration or model download changes are required.

Changes:
- HR invitation collection saves a draft between messages, including partial and invalid details.
- Add/appoint/invite HR commands start an invitation. HR listing commands query the company directory directly.
- “yes invite”, “yes please” and “go ahead” confirm an existing HR invitation without model reclassification.
- List HR, list all the HR admin and show all HR administrators use the same company-filtered directory.
- Existing active HR accounts return the current HR team without sending another temporary password. Disabled accounts require explicit restoration. Other-role or other-company email conflicts explain why the invitation cannot proceed, without moving accounts across companies.
- Starting a new invitation clears an older pending confirmation.

The added regression test replays the reported sequence with the model enabled but deliberately prevented from routing HR actions. It verifies valid and invalid email input, natural-language confirmation, HR listing, invitation resend and an already active account. Email delivery and MongoDB are simulated. Live Render data and Gmail delivery have not been inspected.

Run: python -m pytest -q tests/test_company_roleplays.py

If an email exists outside this company's HR directory, the patch reports a role/company conflict. It does not automatically transfer that account or change its role.
