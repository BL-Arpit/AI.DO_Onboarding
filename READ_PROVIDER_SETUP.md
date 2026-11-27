# Build B — Groq Qwen

These are changed files only, not the full project. Apply over your latest AI.DO Guided Onboarding build (with company roles) or the Full SmolLM Agent Prototype. Preserve the directory paths; put app, frontend, scripts and Dockerfile at the repository root, not inside a new nested application directory.

Create two Git branches from the SAME current application commit: week3-smollm135 and week3-groq-qwen. Apply only the corresponding archive to each branch, commit and push. In Render Settings select the intended branch and deploy its latest commit. The Dockerfile differs between builds, so copying only Python files is not sufficient. No database reset or new database schema is required. Existing PostgreSQL, MongoDB, Qdrant, Google Vision, Gmail and super-admin environment values stay in place.

How execution works:
- The authenticated user's current company configuration, selected employee, private conversation, retrieved context and saved task details are supplied to the selected LLM.
- The LLM decides whether to answer, read records, or request a registered onboarding operation. Free-text business requests do not use the CNN/keyword router when CHAT_PROVIDER is selected.
- The application validates role/company access, fields, contact evidence and revision/version checks. The model never runs arbitrary SQL or Python. Database writes and email invitations require a user confirmation.
- The tool result returns to the model for a natural-language answer. Cards remain authoritative. Missing invitation details are saved in MongoDB so a later email continues the named person's task.
- Queries use existing registered operations and configured employee metadata. This does not give the model unlimited table access or permission to invent new business operations. One application tool request is accepted per conversational turn; writes stop at confirmation.

The chat remains natural language. Groq's native function-call arguments are API metadata, not a hand-maintained intent dictionary or forced JSON conversational response.

Source changes include the provider selector, inference transport, shared chat agent, context/company-plan modules, entry point, guided-help hook and company/task UI cards. Compiled React assets and source are included. Existing dependencies are sufficient for Groq; no Groq SDK is required because HTTPX is already installed. No API keys or GGUF weights are included in these archives.

Validation: 57 targeted local tests passed, including synthetic Groq HTTP function-call transport, no local-model loading in Groq mode, no silent fallback, preserved draft context, confirmation-gated invitations/schema changes, role boundaries, contact evidence, provider errors and existing onboarding/OCR/reset checks. No live Groq account was called because no key was available. Full Docker images were not built in this workspace. React source was production-built in the shared prototype; the compiled assets are supplied.

Groq setup sources, checked 27 November 2026:
https://console.groq.com/docs/model/qwen/qwen3.8-27b
https://console.groq.com/docs/tool-use/local-tool-calling
https://console.groq.com/docs/models

The documented current Qwen model is preview and availability can change. Verify your account's model access. The old qwen/qwen3-32b has been retired; this build does not default to it. Model access, quota and billing depend on your Groq account; this patch does not create an account or promise free inference.

## Render environment

CHAT_PROVIDER=groq
GROQ_API_KEY=<set your actual key in Render Environment only>
GROQ_MODEL=qwen/qwen3.8-27b

Optional:
GROQ_MAX_REPLY_TOKENS=1536
GROQ_REASONING_EFFORT=none
GROQ_MAX_INPUT_CHARS=48000

1. Create a server API key at https://console.groq.com/keys.
2. Apply this archive on week3-groq-qwen, commit and push.
3. Render → your service → Environment: set the three required values above. Do not commit the actual key, put it in frontend code, or paste it into chat.
4. Render → Settings → branch: choose week3-groq-qwen. Deploy the latest commit. Existing environment values override Docker defaults, so explicitly set CHAT_PROVIDER=groq even if a previous branch used smollm.
5. The Groq Dockerfile skips llama-cpp-python installation and SmolLM weights entirely. It keeps OCR and the small Qdrant memory encoder. GGUF settings are ignored in Groq mode; you may remove old GGUF environment overrides.
6. After deployment, run the optional synthetic live probe from a Render shell if available:

python scripts/check_groq_model.py

The probe uses your Groq quota, sends only fictional test data and does not execute database or email tools. If your Render plan has no shell, test the application directly by asking "add Aishwarya in HR", supplying a test email when requested, and reviewing the confirmation before sending an invitation.

Test role-play:
- Owner: add Aishwarya in HR → system retains name and requests missing email → provide the email → confirmation → invite → list HR.
- Super admin: make bank proof optional → review proposed schema change → confirm → ask current requirements.
- HR: add an employee using natural language → correct a draft detail → confirm invitation. Later query submitted employees for review.
- Employee: ask required document types and upload instructions → upload accepted files → submit to HR → ask approval status.

Native tool responses are role filtered. A model/provider failure does not silently fall back to local keyword matching or SmolLM. An error while wording an already completed tool result preserves the actual backend result.

Important data boundary: private chat/context text (which can include names, emails and details entered in chat) is sent to Groq for inference. Raw uploaded document/image bytes are not sent to Groq by this chat adapter; document OCR continues through your existing Google Vision setup. This provider was transport-tested with simulated responses; real model understanding and your account limits remain to be checked with your key.
