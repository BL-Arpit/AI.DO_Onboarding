AI.DO onboarding fixes and conversational SmolLM integration

Apply these files over the existing Week 3 build, preserving their folders. Push to your Render branch and rebuild the Docker image.

Changes
- SmolLM receives the current private thread history and draft/context. It can reply conversationally and propose typed onboarding actions.
- Permissions, validation, SQL operations and explicit confirmations remain enforced by the backend. The model cannot generate a confirmation tool call.
- Corrections such as "change name to Arpit Sahu" update employee drafts and pending HR/employee invitations before confirmation.
- Staff can say "change his name to ..." after selecting an employee. Exact record identity is still required for updates.
- Shared document name checks allow case, spacing and word-order variations, preserve word boundaries and combining marks, and reject missing tokens/initials. Employee profile/upload responses expose checks.
- An onboarded profile name change is rejected explicitly rather than silently ignored.

Render settings
The supplied Dockerfile now defaults to installing llama-cpp-python and downloading checksum-verified SmolLM2-135M-Instruct Q4_K_S. These are quantized pretrained model weights, not a custom distilled intent model. The model file is downloaded during Docker build and is not included in this ZIP. Existing build-argument overrides still take precedence.
GGUF_MODEL_PATH=/project/model/replies.gguf
GGUF_CONTEXT_TOKENS=2048
GGUF_THREADS=1
Remove empty or obsolete overrides of these values. Keep existing PostgreSQL, MongoDB, Qdrant, Gmail and Vision settings.
A larger compatible instruction GGUF model can replace the build URL and checksum. This increases memory and latency requirements. No claim is made that this tiny model matches GPT/Gemini quality.

Validation
21 focused regression tests passed for invitations, role permissions, private threads, draft corrections, confirmations, offboarding, name comparison, employee search, and model routing. Model routing tests use a stubbed GGUF runtime. The real GGUF weights, Docker build, Render latency/memory, live OCR, email delivery and hosted databases were not exercised here.

This patch fixes the reproduced cases. Existing HR account renaming is not added by this patch; HR invitation corrections are supported before creation.
