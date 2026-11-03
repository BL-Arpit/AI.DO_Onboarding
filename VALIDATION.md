# AI.DO MiniLM INT8 and PAN demo — 3 November 2026

## Current checks

- Bundled pretrained encoder: `sentence-transformers/all-MiniLM-L6-v2`, revision `1110a243fdf4706b3f48f1d95db1a4f5529b4d41`, upstream `onnx/model_quint8_avx2.onnx`. Source checksums, Apache-2.0 license and attribution are included. Encoder size: 23,046,789 bytes.
- Encoder remains frozen. A linear intent head was trained on 273 synthetic English phrases. No PAN data was used for model training.
- Offline held-out evaluation: 72 separate messages; 94.44% top-label accuracy, 91.67% correct guarded routing, 90.625% accepted coverage on known-task examples. Thresholds were not tuned on this held-out set. This is not a production-language benchmark.
- Offline application suites: week-1 37 passed; week-2 44 passed; week-3 49 passed. The ONNX NumPy reference interpreter replaces the native execution backend during these checks. The runner asserts that native ONNX Runtime is never imported. Tokenization, INT8 graph evaluation, pooling, normalization, trained intent head, database, permissions and workflows still execute.
- Five frontend response-handling tests passed. Python compilation, JavaScript syntax and Git whitespace checks passed.
- Chromium with simulated APIs passed: AI.DO text wordmark, only upload visible initially, upload → field review → confirm → audit → next-document progression, explicit MOCK labels, and no mobile horizontal overflow. Native browser-to-server model inference was not exercised.
- The supplied PAN image's exact hash matched the demo fixture. Returned values are manually annotated and explicitly marked MOCK. Unit tests verify mismatched-image rejection, review-required validation and mock provenance in the master worksheet. The photograph is not copied into the archive.

## Limits

The initial reference-training attempt still imported native ONNX Runtime and was rejected by automatic approval review due to reported Microsoft telemetry. It was stopped. The completed training and test runner do not import the native runtime; they use the offline ONNX graph interpreter. Native startup, CPU latency, the new launcher in a live environment and Docker remain unverified. Normal application inference is configured for ONNX Runtime with its telemetry opt-out requested before creating sessions.

The PAN demo does not perform OCR, government verification, background checks or driving-licence checks. Its fixture records only the exact supplied sample and remains marked as mocked in chat, audit and exported document fields. Set `EXTRACTION_MODE=tesseract` for real OCR; other files are rejected while mock mode is active. The previous real-OCR implementation is retained, but this update does not certify extraction accuracy on the supplied PAN.

The encoder/reference adapter uses the original opset-14 graph and a scalar/per-axis DequantizeLinear reference implementation because the installed ONNX interpreter omitted that older implementation. The actual shipped model is unchanged. Native speed and bit-for-bit agreement with that implementation remain unmeasured.
