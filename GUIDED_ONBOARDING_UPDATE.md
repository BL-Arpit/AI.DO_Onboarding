# Guided onboarding and document rules

Apply this update over the latest React build with the Company Roles and HR Conversation patches. Preserve paths, commit, push to the deployed Git branch, and deploy its latest commit on Render. The existing Dockerfile builds React. Compiled assets are included as well. No new environment values, database reset, schema migration or model download is required. Keep purge flags removed after any deliberate reset.

## What an employee sees

On the first conversation, the app opens the employee guide. My checklist and questions such as “What documents do I need?” read the company's current rules and saved profile.

For a company requiring PAN and Aadhaar, both documents are named individually with Received / Not uploaded labels. If the company allows a choice of document types, the guide explains how many different types to choose. The bank section follows the company's actual configuration. A zero requirement says Not required by your company; it does not display 0/0 or invent a mandatory bank document.

The journey is:
1. Use + → Upload document, select an accepted document type, and attach its clear image or single-page PDF. Attach documents individually.
2. Check each uploaded document and the details read from it. Uploading saves the file; it does not submit an application or approve onboarding.
3. When the required document counts are met, select Submit to HR and confirm that named action.
4. Wait for HR. HR can approve onboarding or return a submitted application for correction. A separate contact correction request has its own approval status.

The chat explains the next step after upload and submission. Questions about HR approval read the actual submission and request statuses; they do not create another permission request. A correction form with no changed fields cannot send an empty correction request.

## Documents and schema

The upload selector contains only the company-configured accepted document types. The backend checks the selected type before OCR, the classified type after OCR, and the current company rules before saving. Choosing PAN cannot relabel cheque OCR evidence as PAN. An unknown/unreadable document is rejected rather than counted merely because a type was selected. A recognised document with incomplete extracted fields can still be saved for review. OCR classification is not proof of document authenticity or identity verification.

Counts require distinct accepted types. The card displays the latest document for each type while preserving earlier stored uploads. Preview stays inline, without a document editor, drawer or download control. Extracted scalar fields appear beside the selected preview for checking.

Employee Excel uploads must match company-configured columns. Unknown nonempty headers are rejected instead of silently ignored. Valid employee rows appear in the import preview. Accounts and invitations are created only after confirmation, and HR can then open the employee list. The existing limit of 20 accepted rows per confirmed chat import remains; the app asks larger uploads to be split.

## HR and owner guidance

List employees shows the company directory. Who has submitted for review shows only applications actually submitted by employees. An empty review queue explains that distinction.

After opening an employee, “Who?” identifies that same employee. “Approve” uses the selected employee and refuses to create an approval proposal when their application is still awaiting submission. Confirmations remain server-owned and show action-specific labels, such as Submit to HR, Approve onboarding and Import and invite employees.

Owner guidance covers HR appointments and oversight. Company configuration remains exclusive to the company's super admin. Logout remains at the bottom left.

## Model behavior

Common onboarding questions and workflow transitions use authoritative stored state before action selection. The current rules and checklist remain visible in the card and are included in the explanation context. The local SmolLM generates a separate detailed help explanation, requested as 4–6 paragraphs of roughly 350–500 words. Ordinary chat no longer has an instruction to reply briefly. Greetings remain conversational instead of always receiving document instructions.

Detailed help has a separate default generation allowance of 1,024 tokens, independent of a smaller GGUF_MAX_REPLY_TOKENS setting used for action selection. GGUF_HELP_REPLY_TOKENS optionally adjusts the help allowance within 256–1,536 tokens. No new environment value is required. The actual allowance is reduced if necessary to fit the existing model context. Increasing the token budget is not a larger context window or a larger model. Longer output takes more CPU time, and performance on free Render has not been measured.

The explanation generation job cannot execute a tool or change a record. The app keeps its factual checklist and status text authoritative. If the model is missing, fails, gives an unusably short response or triggers the limited unsupported-claim checks, a detailed step-by-step explanation remains available. These checks do not guarantee that every model sentence is correct. SmolLM also receives current company rules, workflow stage and selected employee context for general chat. This update does not enlarge or retrain the model or claim GPT-level performance.

## Validation

28 targeted tests passed together. The checks cover guided onboarding, company role-plays, name matching, simulated Google Vision OCR and reset protection. The beginner role-play covers help without unintended writes, configured document restrictions, explicit submission, HR review, approval status and bulk employee import. Other checks cover requested-type/OCR mismatch and unreadable-file rejection.

A Chromium desktop/mobile check passed for individually named document requirements, bank-not-required text, restricted upload options, incomplete-submission prevention, unchanged-correction prevention and logout. React's production build passed.

These checks use local SQLite and simulated MongoDB, Gmail, OCR and Qdrant where applicable. The deployed Render instance, real cloud credentials, OCR accuracy on your specific uploaded images, and live model generation have not been tested here.

Run:
python -m pytest -q tests/test_guided_onboarding.py tests/test_company_roleplays.py tests/test_google_vision_ocr.py tests/test_name_matching.py tests/test_data_reset.py
