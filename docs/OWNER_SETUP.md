# Owner-only deployment setup

This branch intentionally fails closed until owner access is configured.

## 1. Render backend

In the Render service environment, set:
- OWNER_USERNAME (optional; defaults to owner)
- OWNER_PASSWORD (required; use a strong, unique secret)
- ALLOWED_ORIGINS (comma-separated exact website origins)

The checked-in render.yaml marks OWNER_PASSWORD as sync: false. Enter the secret in the Render dashboard. Never commit it or paste it into chat.

## 2. Cloudflare Worker

In the Worker settings, add:
- OWNER_USERNAME (optional; use the same username as Render)
- OWNER_PASSWORD (secret; must exactly match the Render secret)

Do not put OWNER_PASSWORD in wrangler.jsonc, wrangler.toml, GitHub Actions variables, source code, or frontend JavaScript. The Worker checks authentication before serving both static website assets and proxied API routes. The public /api/health path is the only exception for platform health checks.

The Worker forwards the Authorization header to Render, where the backend independently verifies the same credentials. This is deliberate defence in depth.

## 3. R2 project storage

In Render, configure:
- R2_ACCOUNT_ID
- R2_ACCESS_KEY_ID
- R2_SECRET_ACCESS_KEY
- R2_BUCKET

Use a bucket-scoped Object Read & Write token. Keep the token only in Render environment settings. The Worker does not need R2 credentials.

The project repository stores manifests under owners/owner/projects/. The direct-upload integration uses temporary/ and completed exports use saved/. Lifecycle expiration must apply only to temporary/; do not expire the whole bucket or saved/.

## 4. First-login smoke test

1. Open the Cloudflare Worker website over HTTPS.
2. Confirm the browser requests owner credentials.
3. Confirm the dashboard loads after valid credentials.
4. Confirm the project gallery can create, open, edit, refresh and delete a test project.
5. Confirm an unauthenticated private API request receives HTTP 401.
6. Confirm a state-changing request from a different origin is rejected.
7. Confirm /api/health remains available to the hosting platform.

Do not enable public use until these checks and the CI suite pass. The app is a single-owner workspace, not a multi-user account system.
