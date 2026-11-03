# Conversation understanding and onboarding workflow

The conversational agent and onboarding agent are separate responsibilities. The chat provider interprets language and proposes a typed action. The onboarding agent derives requirements and next steps from authoritative records. It never trusts a model's assertion that a person is complete. Neither agent can bypass confirmation, identity resolution or version checks.

## Natural language and context

Choose OpenAI, Gemini or Claude in config/models.toml and supply its credentials/model ID in .env. The provider receives the current message, last 20 persisted turns scoped to this user/conversation, selected employee summary, draft, pending-confirmation flag, unresolved clarification, workflow facts, and the editable config/intents.json catalog. This is a structured conversation context layer, not fuzzy string routing or a newly trained local model. The catalog contains 15 intent families with 50+ example utterances; expanding examples alone does not train a model.

Supported intent families: create, read, update, delete, list, upload, status, next, missing, documents, history, audit, export, cancel and reply. Employee fields include name/email/phone/client/track. Existing extracted fields may be corrected through a confirmed proposal. Lists can filter by exact client, track or workflow stage (in_progress/complete). Multi-action requests are clarified one action at a time. Broader language behavior depends on the configured model and requires real-account acceptance testing. Demo mode supports a limited command vocabulary and does not claim semantic understanding.

Employee targets bind only by full exact name, email or ID, case-insensitively. Partial names and similar spellings never automatically select a record. Duplicate full names produce choices; choosing one resumes the original action. Pronouns may refer to the selected employee; absent or ambiguous referents require clarification. Selecting an employee does not alter its data. Context is persisted per conversation, not implicitly shared across chats; the employee register is shared across chats. Imported employees are the same records as individually created employees.

## Workflow

1. Create or import basic employee details; confirm creation/import.
2. Select the employee using exact identity or open their master-sheet row.
3. Attach a government or bank document using + or drag-and-drop.
4. Classification and OCR prefill the fields; review and correct them.
5. Continue attaching documents. A minimum of two DISTINCT government document types and one bank document is required. Repeated PAN uploads count as one type. Mock or partial extractions do not satisfy the minimum.
6. Confirm the latest extracted fields, then run the consistency audit.
7. Resolve reported issues and rerun the audit. The derived checklist becomes complete only when the minimum, review and consistency checks pass. Checklist completion is not government identity verification.

Ask “what is missing”, “what next”, “show documents”, “show history” or their natural equivalents with a configured provider. The inline employee view displays counts and the next requirement. Additional uploads are always allowed on editable records. Every upload is retained as document history; the latest version of each type supplies current fields and checklist evidence. A new upload or field change invalidates the previous audit and requires fresh review. Historical failed uploads are retained but do not block a corrected latest version. Locked historical records still obey existing edit restrictions.

Currently automatic extraction supports PAN, Aadhaar, cheque and passbook. Policy recognizes passport, driving licence and voter ID as government categories for future extractor adapters, but their extraction is NOT implemented; unsupported uploads do not satisfy the checklist. The working two-government path today is PAN + Aadhaar. Raw image files are processed, not retained; “document history” means classification/extraction records, not downloadable source images.

The context includes employee contact information and chat history sent to your chosen cloud provider. Do not place secrets in chat; configure the provider and data handling for your deployment before using real employee records.
