# Validation — 2 November 2026

| Check | Result |
| --- | --- |
| week-1 application suite | 16 passed |
| week-2 application suite | 23 passed |
| week-3 application suite | 28 passed |
| Pruned ADVO extraction subset | 30 passed, 3 missing-image tests deselected |
| Supplied document ONNX | Real CPU inference in the application tests |
| Chat ANN | Trained locally from 273 curated examples; 72 separate held-out examples evaluated |
| Python compilation / JavaScript syntax | Passed |

The ANN has 780 input features, 48 hidden units, 17 outputs and 38,321 parameters.
Its compressed weights are 141,762 bytes. Held-out top-1 accuracy was 97.22%;
confidence-guarded accuracy across the whole held-out set was 80.56%. The guard
accepted 78.13% of known-task examples and deferred the rest. This is a small curated
English domain set, not evidence of production or unrestricted language accuracy.
Confidence scores are not calibrated probabilities. Per-example predictions,
including errors and rejected cases, are preserved in model/chat/evaluation.json.
The training script never uses evaluation examples for gradient updates.

Agent integration checks verify:

- A paraphrased onboarding request is classified by the local ANN and handed to
  the onboarding agent, with chat_model and agent_trace returned by the API.
- Follow-up names/emails/phones are collected using per-user conversation state.
- Unknown/OOV requests do not create or save people; confirmation needs a pending
  preview. Saving still requires explicit confirmation text and validation.
- Excel preview/import/export, real raw XLSX/XLS files, duplicates, atomic imports,
  literal spreadsheet cells and role-scoped exports work through the same data layer.
- Employee visibility, recruiter limits, role changes, invitations and session
  revocation remain enforced in week-2 and week-3.
- Workflow order, stale versions, separate maker/approver and required notes remain
  enforced even when the local model is deliberately forced to make an incorrect
  approval prediction. Negated action text cannot approve the record.
- Invalid optional audit-model output remains needs_review.

Workflow tests mock document extraction and SMTP delivery; model inference is real.
No real employee workbook, document or private chat history is used for training.
The optional audit model is separate from the trained local chat ANN.

Not executed: Docker build/run, visual browser acceptance, live SMTP, live optional
audit-model endpoint, authoritative government/background/DL checks. These still
need deployment-specific acceptance. No provider authentication or document
accuracy certification is implied by the passing tests.

Three original ADVO image-fixture tests remain unavailable because the supplied
archive omitted their images. They were explicitly deselected, not counted as
passing: test_pan_front_crop_extracts_required_fields_from_stacked_scan,
test_cheque_candidates_keep_labeled_ifsc_and_account_fields, and
test_aadhaar_address_crop_reduces_known_tesseract_spillover.

One upstream TestClient deprecation warning was reported without test failures.
