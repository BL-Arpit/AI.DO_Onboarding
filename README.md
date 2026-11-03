# AI.DO onboarding

One dark chat window, one master employee register, and one task at a time.

## Three cumulative branches

| Branch | Includes |
| --- | --- |
| `week-1` | MiniLM INT8 intent agent, chat-based onboarding, raw Excel import/export, document extraction/mock and audit |
| `week-2` | Everything in week 1 plus Owner-managed users, invitations and role permissions |
| `week-3` | Everything in week 2 plus employee → HR → Operations workflow and email queue |

The repository opens on `week-1`. Use `git switch week-2` or `git switch week-3` for later milestones. There are no separate weekly app folders.

## Start the PAN demo

1. Create a Python 3.12 virtual environment and activate it.
2. Install application dependencies:

   ```bash
   python -m pip install -r requirements.txt
   ```

3. Copy `.env.example` to `.env`. Set `BOOTSTRAP_EMAIL` and a new `BOOTSTRAP_PASSWORD`. Keep `APP_URL` equal to the browser address you use. Leave `EXTRACTION_MODE=mock_pan` for the demo.
4. Start the app:

   ```bash
   python run.py
   ```

The demo does not start ADVO or require Tesseract. Sign in with your configured account. Existing accounts keep their saved passwords; changing the bootstrap password does not reset an existing account.

## One task at a time

1. Start a conversation and choose **Add person**, or type `add`.
2. Answer the name, email and phone prompts. Review the preview and confirm.
3. The next card asks for a document. Choose the exact `PAN.jpeg` supplied with this project conversation, or drag it into the chat.
4. Only the extracted-field review is shown next. Correct the values and choose **Confirm and continue**.
5. Only the audit action is shown next. Run it to see consistency issues.
6. Add the next document when ready. In week 3, authorized workflow actions appear at the appropriate stage.

The **AI.DO** identity is a text placeholder wordmark. The home action buttons disappear once a conversation starts. Document forms, corrections and audit results stay inside the chat; no separate windows open.

Conversations separate messages and pending drafts, not employee data. Transcripts stay in browser-tab memory and clear on reload. Saved employees remain in the database and master sheet. Drafts are isolated by authenticated user and conversation ID.

## MiniLM INT8 chat and intent agent

The pretrained encoder is **sentence-transformers/all-MiniLM-L6-v2**, using the upstream `onnx/model_quint8_avx2.onnx` export. Its pinned revision, source paths and SHA-256 checksums are in `model/minilm/source.json`. The model is Apache-2.0 licensed; license and attribution are included.

- ONNX encoder: 23,046,789 bytes, about 23 MB; CPU export optimized for AVX2.
- Tokenizer: about 466 KB. No Transformers or PyTorch package is required for normal inference.
- Intent head and training-example vectors: about 414 KB in `intent_head.npz`.
- The encoder stays frozen. A small linear intent head is trained on 273 synthetic English examples covering 17 labels. PAN information is not used to train the model.
- MiniLM produces sentence embeddings; the application agents produce short, grounded replies. This does not generate open-ended LLM conversation.
- Low-confidence, ambiguous or unsupported messages ask for clarification. Model predictions cannot save a record, bypass permissions or approve a task on their own.
- Model files are bundled. Runtime chat does not download models or call a cloud service.

The 72 held-out examples produced 94.44% top-label accuracy and 91.67% correct guarded routing in offline reference validation. This small English set does not establish production accuracy or latency. Native CPU performance has not been benchmarked here.

### Program flow

`Message → MiniLM INT8 → masked mean pooling and normalization → trained intent head → router → role-specific agent → validated data operation → template reply / inline task`

| File | Responsibility |
| --- | --- |
| `app/agents/chat.py` | Local encoder, pooling, intent head and confidence guard |
| `app/agents/router.py` | Agent dispatch and workflow action guards |
| `app/agents/onboarding.py` | Collect details, show preview, require confirmation |
| `app/agents/document.py` | Choose mock or real extraction, validate files and surface errors |
| `app/agents/mock_document.py` | Exact-image PAN demo fixture only |
| `app/agents/audit.py` | Consistency checks and optional TXT-prompt audit endpoint |
| `app/excel.py` | Import preview, duplicate handling and master workbook |
| `app/policy.py` | Server-side role and record access |

The optional audit prompt is `app/prompts/verification.txt`. No audit-model endpoint is needed for the PAN demo.

## PAN mock: explicit demonstration data

The demo fixture matches the SHA-256 of the supplied PAN file. It returns manually transcribed fields, not OCR output. Other files are rejected in mock mode; even a resized or re-encoded copy will have a different hash.

The source photograph is not included in the project archive. `app/fixtures/pan_demo.json` contains the expected image hash and annotated fields. The document response, chat, employee review, audit and master-sheet field marker identify the data as **MOCK**. The result is `partial`, its validation is false, and the audit remains `needs_review`. It does not verify government records, identity, background or a driving licence.

## Real Tesseract extraction

For real extraction, set `EXTRACTION_MODE=tesseract` in the root `.env` and install:

```bash
python -m pip install -r requirements-advo.txt
```

Install the Tesseract executable and English language data separately. In `vendor/advo/.env`, set the actual executable path, for example on Windows:

```env
TESSERACT_PATH=C:/Program Files/Tesseract-OCR/tesseract.exe
TESSERACT_LANG=eng
GEMINI_EXTRACTION_FALLBACK_ENABLED=false
OCR_REQUEST_TIMEOUT_SECONDS=20
```

Restart `python run.py`. It starts and checks ADVO before the app, or reuses a healthy configured service. In real mode the supplied document classifier is advisory; OCR evidence identifies the document type unless you choose it explicitly. Empty extraction is reported as an error. Correct partial fields before confirming. Uploading a document does not authenticate it.

## One master sheet

Every confirmed chat entry and Excel import uses the same employee register. Choose **Master sheet** at the start of a conversation, or type `list` / `export`. `master_employees.xlsx` contains exactly one **Master Employees** worksheet, with one row per saved employee and columns for contact details, client, track, status, verification and document fields. Mock fields include a demo marker.

Downloads are generated from current saved data. Formulas and invalid Excel control characters are handled as literal/sanitized text. Existing duplicate-email checks and role visibility remain enforced: the Owner sees all employees; employees and recruiters retain restricted access.

Raw `.xlsx` and `.xls` imports require `name`, `email`, `phone`; optional columns are `client` and `track`. Preview first, then confirm. Nothing is imported at preview time. Keep a single workbook upload per preview/confirmation task.

## Train and verify

```bash
python -m pip install -r requirements-dev.txt
python training/train.py --reference
python tests/run_offline.py
node --test tests/test_api_errors.cjs
```

Training updates only the intent head and its evaluation report. It uses the frozen included INT8 encoder. Keep new evaluation phrases separate from training examples.

Reference mode uses an offline ONNX graph interpreter and does not import native ONNX Runtime. It is a correctness check, not a native latency test. Normal application inference uses ONNX Runtime.

**Verification limit:** automatic approval review reported Microsoft telemetry during earlier native-runtime initialization, including the first training attempt. That attempt was stopped. The completed training and application checks used the reference interpreter without native runtime imports. Live native-runtime startup remains unverified here. See `VALIDATION.md` for exact results.

For week 3 email delivery, configure SMTP and run `python -m app.worker`; delivery is not required for week 1. Never use the bootstrap sample password for deployment. Database and downloaded master files contain employee information and should stay within your authorized environment.
