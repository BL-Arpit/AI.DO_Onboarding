# Extraction, download and ONNX update — 3 November 2026

- The exported `intent_ann.onnx` was checked with ONNX checker. Predictions matched the original ANN weights on all 345 included training/evaluation phrases; the maximum probability difference was 1.79e-7. This is format/inference parity, not evidence of improved intent accuracy.
- Direct local Tesseract extraction of a synthetic PAN returned PAN_CARD/success and the correct synthetic PAN identifier. The failed real user document was not supplied, so its scan quality and extraction cannot be certified.
- ADVO extraction checks: 31 passed; 3 unavailable image-fixture tests deselected.
- Four document-agent regressions passed for auto typing, manual PAN retry, detailed service errors and rejecting empty extraction.
- Browser verification of the download used the actual generated XLSX bytes and the application's CSP with simulated API responses. A valid workbook downloaded successfully; a simulated 401 displayed its message in chat. This was not a live server end-to-end run.
- Latest offline application suites used ONNX's NumPy reference evaluator instead of native ONNX Runtime: week-1 34 passed; week-2 41 passed; week-3 46 passed. One native runtime-specific test was deliberately deselected in each offline suite. Run `python tests/run_offline.py` after installing requirements-dev.txt to reproduce this mode.
- Before the final telemetry opt-out change, week-1's native-runtime application suite passed 35 tests, including ONNX parity and the export-control-character regression. The five frontend response-handling tests also passed. Python compilation and JavaScript syntax passed.

**Live verification blocked:** automatic approval review rejected live app startup due to reported outbound Microsoft telemetry, even after adding the runtime's `disable_telemetry_events()` opt-out. No further live startup attempts were made. Latest checks used direct OCR, simulated browser APIs and the offline ONNX graph interpreter. Native runtime startup, supervisor lifecycle and an actual browser-to-app-to-OCR flow remain unverified here. Docker and live SMTP remain unverified.

The runtime model is a custom domain ANN exported to ONNX, not an externally sourced pretrained chat LLM. `weights.npz` remains training input only. The included weights, vocabulary, normalization, labels and confidence guard are preserved. Explicit user confirmation, role permissions and workflow guards remain enforced by code.

# Master employee sheet update

All conversations and confirmed Excel imports use the same saved employee register. One master workbook contains one worksheet and one row per employee. Extracted fields appear in document-specific columns. Tests combine entries from two independent chats plus an Excel import and verify that all three appear once in the same worksheet. A second test verifies document columns, verification status and literal spreadsheet cells. Chromium checks passed for opening the master table and its Excel download link, alongside the existing chat and attachment interactions. Existing role visibility applies to both master table and export.

# AIDO single-window update

The frontend adapts the supplied `aido-chat.zip` design. Desktop and mobile screenshots were inspected. A real Chromium interaction check passed for chat entry, new conversations, history switching, inline employee fields, drag-and-drop Excel previews, document attachment and mobile width. Browser API responses were mocked for these UI checks; the application suites below exercise the real backend separately. The five JavaScript response-handling tests also passed.

Conversation transcripts are held in memory for the browser tab and clear on reload. Saved employee records remain persistent. Pending intake drafts are scoped by authenticated user and conversation ID. Week 2 role drafts use the same scope. New conversations cannot interrupt an in-flight chat or attachment request.

PAN processing uses both block and sparse OCR, with a default 20-second shared OCR budget. Real Tesseract recovered a PAN identifier from a synthetic image across four views. This is not a real-document accuracy benchmark. Existing ADVO `.env` files must set `OCR_REQUEST_TIMEOUT_SECONDS=20` and restart the extraction service to use the longer budget. No Tesseract executable upgrade is bundled. Gemini fallback remains disabled by default.

# Validation — 2 November 2026

| Check | Result |
| --- | --- |
| week-1 application suite | 29 passed |
| week-2 application suite | 36 passed |
| week-3 application suite | 41 passed |
| Pruned ADVO extraction subset | 31 passed, 3 missing-image tests deselected |
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

Not executed: Docker build/run, live SMTP, live optional audit-model endpoint,
authoritative government/background/DL checks. These still
need deployment-specific acceptance. No provider authentication or document
accuracy certification is implied by the passing tests.

Three original ADVO image-fixture tests remain unavailable because the supplied
archive omitted their images. They were explicitly deselected, not counted as
passing: test_pan_front_crop_extracts_required_fields_from_stacked_scan,
test_cheque_candidates_keep_labeled_ifsc_and_account_fields, and
test_aadhaar_address_crop_reduces_known_tesseract_spillover.

One upstream TestClient deprecation warning was reported without test failures.

Origin-error fix: local loopback aliases are accepted only on the same scheme and
port. Public origins still require APP_URL. Rejections are JSON with setup guidance,
and frontend parsing handles plain-text/HTML failures without a JSON SyntaxError.
Ten backend origin regressions and five Node tests of the real API helper pass.
