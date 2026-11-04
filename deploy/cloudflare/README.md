# Cloudflare deployment

This deployment path uses a Worker for API routing, Worker Static Assets for the browser UI, and Cloudflare Containers for the existing Python/FastAPI + FFmpeg application.

## Cost

Cloudflare Workers Free cannot host the FFmpeg process. Cloudflare Containers are not available on the Free plan. Workers Paid starts at US$5/month and includes a limited Containers allowance; extra CPU, memory, disk and egress can be billed. Check current pricing before enabling billing:
https://developers.cloudflare.com/containers/platform/pricing/

R2 standard storage currently includes 10 GB-month, 1 million Class A operations and 10 million Class B operations per month, with no egress fees. Usage above the allowance is billed:
https://developers.cloudflare.com/r2/pricing/

## Current implementation scope

- Worker routes /api/* to one named Container instance.
- Static asset binding serves the existing web/ interface.
- Container image reuses the repository Dockerfile.
- Wrangler config declares the Container Durable Object binding.

## Production blockers

1. The current FastAPI app writes uploads, exports and SQLite job state to local filesystem paths. Container-local files must not be treated as durable media storage. R2 media integration and durable job-state design are still required.
2. FastAPI and the render worker must run together in the Container. The Cloudflare entrypoint added here starts both; Docker Compose can still override the container command locally.
3. There is no authentication, user isolation, ownership, CSRF protection or quota enforcement. Do not publish the app publicly until these are implemented and reviewed.
4. This starter config uses one Container instance; it is not yet a multi-user production architecture.
5. Docker must be running locally when Wrangler builds the image. First deployment can take several minutes to provision.

## Prerequisites

- Cloudflare account with Workers Paid enabled for Containers.
- Node.js and npm.
- Docker Desktop or another Docker-compatible engine running.
- Wrangler authenticated with the Cloudflare account using npx wrangler login.

## Local checks

```bash
npm install
npx wrangler types
npx wrangler dev
```

## Deploy

Only after reviewing billing and creating required Cloudflare resources:

```bash
npx wrangler deploy
npx wrangler containers list
```

This repository change does not log in to Cloudflare, create buckets, enable billing, or deploy resources. Those actions require account-owner authorization.
