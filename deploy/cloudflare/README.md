# Free-first deployment

This deployment separates the static frontend from the Python/FFmpeg API:

- Cloudflare Worker Static Assets serves the PWA frontend.
- The Cloudflare Worker proxies same-origin `/api/*` requests to the API origin configured in its `API_ORIGIN` variable.
- Render runs the existing Dockerized FastAPI + FFmpeg service using the free web-service plan.

## Cost and reliability limits

This is a free-first prototype, not a production media platform.

- Render free web services can spin down after inactivity and take time to wake.
- The free service has an ephemeral filesystem. Uploaded videos, exports and SQLite job state can disappear after restarts/redeploys. Do not treat it as durable storage.
- Free compute has limited memory/CPU. The blueprint limits uploads to 50 MB, source duration to 180 seconds and output long edge to 640 pixels. FFmpeg may still fail on some videos.
- The Render service may have monthly usage limits or plan changes. Check the current Render dashboard before deploying.
- Cloudflare Worker Static Assets and the API proxy do not require Cloudflare Containers. This configuration removes the paid Container binding.
- No authentication or per-user project isolation is implemented. Do not upload confidential or sensitive footage to this public prototype.

## Deploy the API on Render

1. Open the Render dashboard and choose **New → Blueprint**.
2. Connect the GitHub repository `Arhbkkk/mind-of-ak-ai-studio`.
3. Select the branch containing this configuration, currently `feat/aws-render-foundation`.
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

The frontend continues calling same-origin `/api/*`; the Worker forwards those requests to Render. No API key is placed in browser JavaScript.

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
