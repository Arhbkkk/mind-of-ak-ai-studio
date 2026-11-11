# Free-first deployment

This deployment separates the static frontend from the Python/FFmpeg API:

- Cloudflare Worker Static Assets serves the PWA frontend.
- The Cloudflare Worker proxies same-origin `/api/*` requests to the API origin configured in its `API_ORIGIN` variable.
- Render runs the existing Dockerized FastAPI + FFmpeg service using the free web-service plan.

## Cost and reliability limits

This is a free-first prototype, not a production media platform.

- Render free web services can spin down after inactivity and take time to wake.
- The free service has an ephemeral filesystem. Uploaded videos, exports and SQLite job state can disappear after restarts/redeploys. Do not treat it as durable storage.
- Free compute has limited memory/CPU and ephemeral disk. The checked-in Render blueprint sets an application upload limit of 512 MB, a maximum source duration of 600 seconds, and an output long edge of 640 pixels. These are application settings, not guarantees that every upload or render will fit the host's resource limits.
- The Render service may have monthly usage limits or plan changes. Check the current Render dashboard before deploying.
- Cloudflare Worker Static Assets and the API proxy do not require Cloudflare Containers. This configuration removes the paid Container binding.
- Owner-only HTTP Basic authentication is implemented at the Worker and API. This is a single-owner workspace, not a multi-user account system. Keep credentials private and do not use it for confidential footage without an appropriate security review.

## Deploy the API on Render

1. Open the Render dashboard and choose **New → Blueprint**.
2. Connect the GitHub repository `Arhbkkk/mind-of-ak-ai-studio`.
3. Select the `main` branch when deploying the current production configuration. If your existing Render service is already connected to another branch, verify its configured branch before changing it.
4. Review the `mind-of-ak-api` service and confirm the plan is **Free** before applying.
5. Let the Docker build and deploy finish.
6. Open the service's URL and verify `/api/health` returns JSON with `"ok": true`. Save the service origin, for example `https://mind-of-ak-api.onrender.com`.

Do not add a paid instance or persistent disk for this prototype.

## Connect Cloudflare to the API

1. Open Cloudflare → Workers & Pages → `mind-of-ak-ai-studio`.
2. Open **Settings → Variables and Secrets** (the label may vary).
3. Add a plain-text variable named `API_ORIGIN`.
4. Set its value to the Render service origin only, for example `https://mind-of-ak-api.onrender.com` (no trailing path such as `/api`).
5. Save and redeploy the Worker if Cloudflare requests it.

The frontend continues calling same-origin `/api/*`; the Worker forwards those requests and the Authorization header to Render, where the backend checks the owner credentials again. No owner password or API key belongs in browser JavaScript or checked-in Wrangler variables.

## Required owner and storage configuration

- Set `OWNER_PASSWORD` as a Worker secret and as a Render environment secret. The values must match exactly. `OWNER_USERNAME` is optional and defaults to `owner`; if set on one side, set the same value on the other.
- Set Render `ALLOWED_ORIGINS` to the exact public Worker origin, with no path and no trailing slash. The checked-in `render.yaml` currently uses `https://mind-of-ak-ai-studio.ammaappalub.workers.dev`; confirm this is the actual production hostname before changing the Render environment.
- For durable project manifests and media, configure `R2_ACCOUNT_ID`, `R2_ACCESS_KEY_ID`, `R2_SECRET_ACCESS_KEY`, and `R2_BUCKET` in Render. Without these, the local fallback is ephemeral on Render's free service.

## Verify

- Open the Cloudflare `workers.dev` app URL.
- The backend status panel should show FFmpeg and FFprobe availability.
- Test with a small, non-important video first.
- A sleeping free Render service may take a minute or more to wake; wait for the request rather than repeatedly submitting it.

## Local checks

```bash
npm install
npx wrangler types
npx tsc --noEmit
node --check web/local-storage.js
```

The Worker config no longer declares Containers or a Container Durable Object. The old Cloudflare Container deployment is not used by this free-first architecture.
