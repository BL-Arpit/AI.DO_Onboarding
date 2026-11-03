# User guide

## Sign in

Use the operator email and password from the private environment setup. Login creates an HttpOnly cookie; passwords and session tokens are not stored in browser local storage. **Account** changes your password and signs out all sessions. **Sign out** revokes the current session.

The interface contains AI.DO branding, conversation history, a message composer and the **+** attachment button. There is no operator/model badge and no separate upload form. Enter sends a message; Shift+Enter inserts a line break. Mobile conversations open from the menu button.

## Start with a document

1. Start **New chat**.
2. Use **+** to attach a supported document, or drop it into the chat.
3. The same application validates it, identifies the type and extracts fields.
4. A new draft receives the extracted name and document fields. The assistant asks for missing contact information one question at a time.
5. Review the proposed employee and choose **Confirm**. No employee was created before this confirmation.
6. The next task displays editable document values already filled from extraction. Correct any partial or wrong OCR and choose **Confirm fields**.
7. Run the consistency audit. It reports missing documents, partial data, name disagreements and mock provenance. It does not authenticate a government document.

Uploaded files are processed in temporary local storage and removed at the end of extraction. The database retains extracted values, document metadata, chat and audit entries. A pending pre-create preview expires after ten minutes.

## Start with chat

Type `add`, or provide the name, email and phone together. Missing details are collected, a preview is shown, and confirmation creates the record. Then attach documents through **+**. Reads can use name, email or ID. If several records match, choose one and repeat the intended operation; the application never updates or deletes every match.

The demo engine supports the documented example commands and simple variations. OpenAI/Gemini/Claude configuration enables a real language model to propose actions. No provider is silently substituted when another provider fails. An error applies no unconfirmed action.

## Update and delete

After selecting an employee, try `change phone to 9876543211`. Review the exact field change and confirm. You can also address an employee explicitly, for example `update Ravi phone: 9876543211`. In configured model mode, existing document-field changes can be proposed through chat too. The demo parser's documented CRUD commands focus on basic details; document corrections use the prefilled review task.

`delete Ravi` shows a specific employee preview. Confirming soft-deletes that employee from the active register. Reusing a confirmation is rejected. If another tab changed the record, request a fresh preview. Soft-deletion is retained data, not permanent erasure, and the email remains reserved by duplicate protection.

## PAN demonstration

The mock accepts only the exact PAN.jpeg supplied in this project conversation. Its hash and manually annotated fields are in the fixture. The photograph is not included in the app archive. The resulting card and exported field marker say **MOCK**. The audit remains `needs_review`; no OCR or identity verification occurred. An edited, recompressed or different image is rejected in mock mode. Real files require `DOCUMENT_MODE=tesseract`.

## Excel and the master sheet

Attach raw `.xlsx` or `.xls` with headers `name`, `email`, `phone`; optional `client`, `track`. The first worksheet is previewed. Up to 1,000 employee rows and 100 columns are accepted. Invalid/formula/duplicate rows are shown as skipped. **Confirm import** saves all valid rows in one transaction; previewing saves no employee. Finish one attachment/import task before uploading another file.

Use `list`, **Master sheet**, or `export`. One **Master Employees** worksheet contains all active employees, regardless of conversation. Extracted document fields become separate columns. A deleted employee is excluded from this sheet. Click **Open** to select a specific employee before changing them or attaching more documents.

## Errors

- **401:** sign in again; a password change revokes every session.
- **403 / CSRF:** reload the session; check that APP_URL matches your browser origin.
- **409:** stale record, used confirmation or expired preview; request a fresh preview.
- **413:** reduce file size/image dimensions; split a PDF into single pages.
- **422:** review the indicated fields or provide a clearer document.
- **429:** wait before retrying login or OCR.
- **502/503/504:** provider or local extraction failed; no unconfirmed write was applied. Give the operator the request ID, not a password or API key.
