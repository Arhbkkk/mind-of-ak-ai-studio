# Cloudflare R2 setup for Mind of AK Studio

## Render environment variables

Add these in the Render service environment (never commit credentials):

- `R2_ACCOUNT_ID`: Cloudflare account ID
- `R2_ACCESS_KEY_ID`: R2 token Access Key ID
- `R2_SECRET_ACCESS_KEY`: R2 token Secret Access Key
- `R2_BUCKET`: `mind-of-ak-media`

Keep the token scoped to this bucket with Object Read & Write. Do not expose these values to the browser or Cloudflare Worker.

## Bucket CORS

In R2 bucket settings, add a CORS policy allowing the Studio origin:

```json
[
  {
    "AllowedOrigins": ["https://studio.ammaappallub.workers.dev"],
    "AllowedMethods": ["PUT", "GET", "HEAD"],
    "AllowedHeaders": ["*"],
    "ExposeHeaders": ["ETag"],
    "MaxAgeSeconds": 3600
  }
]
```

For local development, add the exact local origin separately (for example `http://localhost:8787`). Do not use wildcard origins for the production bucket.

## Automatic cleanup

Create an R2 lifecycle rule for prefix `temporary/` to expire objects after 2 days. Also configure incomplete multipart uploads to abort after 1 day if the dashboard exposes that option. This keeps temporary source uploads from accumulating. Never apply this expiry rule to a future `saved/` prefix.

## Current scope and limits

The browser uploads source files directly to R2 in 8 MiB multipart chunks. Render still downloads a temporary working copy for FFmpeg, so processing remains limited by Render disk, memory, CPU and request timeouts. When R2 is configured, completed MP4 exports are copied to the `saved/` prefix and downloads use a short-lived (15-minute) presigned URL. Do not configure lifecycle expiry on `saved/`. The app does not yet provide user accounts, per-user ownership, a private export library, or a delete/manage screen; an unguessable filename is not a substitute for authentication. Do not expose this as a multi-user public service until upload and export endpoints have authentication/ownership checks and abuse controls. R2 does not make uploads or processing unlimited. Configure lifecycle cleanup only on `temporary/`.
