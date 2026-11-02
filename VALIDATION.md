# Validation — 2 November 2026

| Version/check | Executed result |
| --- | --- |
| week-1 | 12 application tests passed |
| week-2 | 19 application tests passed |
| week-3 | 23 application tests passed |
| Supplied ADVO extraction/layout/API subset | 30 passed; 3 unavailable image-fixture tests deselected |
| ONNX classifier | Real local CPU inference executed in each weekly test suite |
| Tesseract extraction | Real synthetic PAN image read and PAN field extracted |
| Python compilation / JavaScript syntax | Passed |

New workbook tests generate actual XLSX and legacy XLS binary files, not mocked
row arrays. Coverage includes:

- Week-1 operator adding another person entirely through multi-turn chat.
- Full prompts, explicit save confirmation, cancellation, invalid-input corrections.
- Raw XLSX/XLS parsing, numeric phone cells, text leading zeros, worksheet selection.
- Missing headers, unreadable/unsupported files, formula-bearing XLSX rows.
- Preview without mutation, rejected/duplicate rows, replay protection and atomic
  rollback when another request creates a duplicate after preview.
- Literal XLSX export, per-employee export visibility and import preview ownership.
- Roles, invitations, one-use activation, user/role chat, last-owner protection,
  session revocation, recruiter limits and the Operator-to-Owner upgrade.
- Employee submission, HR review, separate Operations approval, corrections,
  stale decisions, current documents/fields and required notes.
- Pending email failure/retry and no repeat delivery of already completed jobs.
- Audit model output cannot auto-approve a person.

The previous online-sheet application history is not carried into this fresh
repository. No online-sheet API, credential configuration or sheet-sync job exists
in the new application. The supplied ADVO vendor can optionally use its original
Gemini extraction provider; that is separate from file import and is disabled by
default in the extraction environment example and Docker configuration.

Workflow tests mock extraction and outbound email; ONNX and Tesseract smoke checks
are separate real executions. These checks establish integration behavior, not
classifier accuracy or document authenticity. No real private identity document
or employee workbook is bundled.

Not executed: Docker build/run (Docker unavailable), visual browser acceptance,
live SMTP delivery, live optional prompt-model service, authoritative government/
background/DL provider checks. Configure the optional services and run your own
acceptance pass before external deployment. Excel/chat intake needs none of them.

The supplied ADVO ZIP omits images needed by these three original regression tests:

- test_pan_front_crop_extracts_required_fields_from_stacked_scan
- test_cheque_candidates_keep_labeled_ifsc_and_account_fields
- test_aadhaar_address_crop_reduces_known_tesseract_spillover

The available subset was run from vendor/advo with:

```bash
python -m pytest tests/test_extraction_service.py tests/test_document_layout_regressions.py tests/test_extraction_route.py -q -k 'not test_pan_front_crop_extracts_required_fields_from_stacked_scan and not test_cheque_candidates_keep_labeled_ifsc_and_account_fields and not test_aadhaar_address_crop_reduces_known_tesseract_spillover'
```

One upstream TestClient deprecation warning was reported without failures.
