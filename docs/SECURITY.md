# Security design and scope

## Implemented controls

- Argon2id password hashing (64 MiB memory, three iterations, parallelism two); no plaintext password in the database. Legacy scrypt hashes are verified only to migrate an existing account, then rehashed on successful sign-in.
- Random 256-bit session tokens; only SHA-256 token hashes are stored. Cookies are HttpOnly, SameSite=Strict, path=/ and Secure when configured for HTTPS/production.
- Eight-hour default absolute expiry and 30-minute default idle expiry. Logout revokes the current session; password change/recovery revokes all account sessions.
- HMAC CSRF token tied to the session and APP_SECRET. Every authenticated mutation requires its header; browser-supplied origins are checked separately. Login accepts structured JSON, and cross-origin unsafe requests are rejected.
- Explicit trusted hosts, production HTTPS public origin, no wildcard CORS, content-security policy, no frame embedding, nosniff, no-referrer and no-store headers. Production responses include HSTS for the TLS-facing deployment.
- Login attempts are rate-limited by persistent HMAC-hashed IP/account subjects. No process-local dictionary is the only throttle. Subjects older than one minute are cleaned as login requests arrive.
- Parameterized SQL; allowlisted schemas and actions; no model-generated SQL or Python; no model-generated confirmation operation.
- One employee target at a time, single-use scoped confirmations, expiration and stale-version rejection. Mutation audit writes share their database transaction.
- Bounded upload/body/image/PDF limits and OCR slots. Original files use temporary storage and are removed after processing. The source filename is not used as a filesystem destination.
- Model provider keys stay in the server environment. Configured URLs require HTTPS and redirects are not followed. The application does not silently switch providers or extraction modes.
- JSON errors avoid echoing passwords, tokens, provider responses and submitted field values. Request logs include request ID, method, path, status and duration, not headers, bodies, filenames or query text.

## Boundaries

This week 1 build is a single-tenant operator system, not a multi-tenant authorization layer. There is no public signup, MFA, SSO, external password recovery, authoritative government/background/DL verification, antivirus scanner, immutable audit store or automated privacy-law compliance certification. Use an organization-approved identity gateway if those controls are required before exposure.

SQLite and extracted employee values/chat are not application-encrypted at rest. Protect the host volume, backups, environment, operating-system account and access to the source fixture. Use full-volume encryption and your organization's retention controls. Soft-deletion retains data; it does not implement a statutory erasure process.

Cloud provider use sends typed chat and selected basic employee context to the chosen endpoint. Uploaded images and extracted fields are not added to provider context by the application, but a user can type those values in chat. Review the account's retention and data-sharing settings before enabling real accounts. `store=false` is not a universal cross-provider no-retention guarantee.

The exact-PAN fixture is a manually annotated mock. Its values and provenance marker remain distinct from genuine OCR; an audit always identifies mock data as needing review. A parsed PAN format, name match or extraction success is not identity authentication.

## Operations

Serve only behind TLS. Keep the internal application port on loopback or a private container network. Do not trust arbitrary X-Forwarded-For headers: the reference launcher ignores forwarded headers. A TLS reverse proxy therefore appears as one client address to the app's IP throttle, which is conservative for the single-operator profile.

Protect `.env`; rotate APP_SECRET by restarting (existing CSRF tokens become invalid). Revoke existing sessions when rotating credentials. Run dependency/security scanning, platform-specific acceptance, restore testing and an independent security review before deployment. Never label passing functional tests as a penetration test.

Primary middleware reference: https://www.starlette.io/middleware/
