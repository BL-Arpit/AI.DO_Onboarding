# React onboarding interface

Apply this archive over the current Week 3 Google Vision project, preserving the paths.

## Deploy

1. Copy the frontend folder, Dockerfile, .dockerignore and included app files into the repository.
2. Commit and push to the branch used by the Render Docker service.
3. Deploy the latest commit. The first Docker stage uses Node 22 and npm ci to compile React. The final Python image serves the compiled interface through the existing FastAPI root route.
4. Refresh the page after deployment. The header should show AI.DO at the left, Onboarding beside it, and a compact account menu on the right.

The updated app/static/workspace.html loads bundled React assets. Commit frontend/package-lock.json with the source. The included compiled assets also allow the Python entry point to serve the UI locally before rebuilding. For local React development, start the Python backend on 127.0.0.1:8000, then run npm ci and npm run dev from frontend. Open the address Vite prints, including /assets/react/ if needed.

The previous chat/model, database, Gmail and Google Vision environment values remain applicable. This update adds a Node build stage. Runtime remains one Python service.

## Interface

- A single private conversation and a fixed-height header with account menu.
- Compact owner invitation using company name, owner name and email. Schema questions follow the invitation.
- Role-specific + actions, Excel/document attachments, file preview before sending and drag-and-drop on the composer.
- A visible user message and thinking dots while a request is pending. The completed reply is revealed progressively. Progressive reveal is a frontend animation.
- Employee drafts, confirmation cards, HR directory, submission lists, original-document drawer, editable extracted fields, name review and before/after revision history.
- A side drawer on desktop and a full-height inspector on mobile.
- Keyboard focus management, reduced-motion support and native form validation.

The small owner workflow files are included so users updating from the earlier customer-onboarding ZIP receive the compact invitation flow as well.

## Files

frontend/src/main.jsx holds React components, API integration and session/chat state.
frontend/src/style.css holds layout, components, mobile rules and animation.
frontend/vite.config.js points the build into app/static/react.
app/static/workspace.html is the generated entry point served by FastAPI.
Dockerfile compiles the frontend and copies it into the Python image.

## Verification

The production build completed. Browser checks with mocked API responses passed for owner invitation, form payload, confirmation, desktop and mobile overflow, opening the document drawer, editing fields with versioned payload, viewing revision history and closing the drawer. No browser JavaScript errors appeared in those checks.

Live Render deployment, actual email delivery, OCR and model inference were outside this frontend validation.
