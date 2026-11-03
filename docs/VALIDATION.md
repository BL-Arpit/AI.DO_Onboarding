# Week 1 release validation — 3 November 2026

## Verified

- Python 3.12.14; Tesseract 5.3.4 on Linux.
- 28 automated tests passed. Coverage includes authentication/session expiry, CSRF/origin/host enforcement, scoped single-use CRUD confirmations, stale and expired actions, upload prefill/provenance, atomic imports, literal-safe workbook export, request limits and three simulated cloud-provider contracts.
- Black formatting, Ruff lint and Git whitespace checks passed.
- Real browser acceptance against the actual single-server application passed: login → chat + upload → classification/extraction → employee draft → prefilled document review → audit → confirmed phone update → actual Excel download → confirmed deletion. Mobile layout was checked; no browser page errors were reported.
- Real Tesseract extraction of the supplied PAN matched all four manually checked fields: name, father's name, date of birth and PAN. This test used genuine OCR, not the mock fixture. The original photograph and downloaded test workbook are excluded from the deliverable.
- The explicit mock is separately tested for exact-image matching and visible mock provenance. It is not identity verification.
- Authenticated OpenAPI documentation is generated from the application; Swagger assets are local.

## Boundaries

These checks do not certify production readiness for every environment or document. Real OpenAI, Gemini and Claude accounts were not called: their adapters were tested with simulated HTTP responses. Configure a tool-capable model and perform account-specific acceptance testing before deployment. Default chat is a labelled deterministic demo, not a generative model.

Docker, Windows deployment, optional ONNX document classification, load capacity and broad OCR accuracy were not tested. The successful supplied-image result does not establish accuracy on other documents. Review extraction values before confirmation; partial extraction remains unverified. Production deployment also requires real TLS, protected backups, a retention policy, secrets and monitoring as described in DEPLOYMENT.md and SECURITY.md.

The acceptance-test server was stopped after the test. This archive does not start a hosted application automatically.

## Release scope

The new architecture is on week-1. Week-2 and week-3 are historical branches, not upgraded releases. Legacy chat models remain only in repository history/historical branches; the new week-1 application does not load them. Existing users, employees, documents and audit records use additive migration; old sessions are invalidated and old chat state is not migrated. Back up before upgrading.
