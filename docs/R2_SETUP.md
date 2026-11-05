# Cloudflare R2 setup

## Render environment variables

Add these in the Render service environment. Never commit credentials:

- R2_ACCOUNT_ID: Cloudflare account ID
- R2_ACCESS_KEY_ID: R2 token Access Key ID
- R2_SECRET_ACCESS_KEY: R2 token Secret Access Key
- R2_BUCKET: mind-of-ak-media
- MAX_DIRECT_UPLOAD_MB: direct source upload cap (default 512 MB)

Keep the R2 token scoped to this bucket with Object Read & Write. Do not expose credentials to the browser or Cloudflare Worker.

## Bucket CORS

In R2 bucket settings, add a CORS policy allowing the exact Studio origin:

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

For local development, add the exact local origin separately. Do not use wildcard production origins. ETag must be exposed so the browser can complete multipart uploads.

## Automatic cleanup

Create an R2 lifecycle rule for prefix temporary/ to expire objects after 2 days. Configure incomplete multipart uploads to abort after 1 day if the dashboard exposes that option. Never apply this expiry rule to saved/ or owners/.

## Storage layout

- temporary/: source uploads; lifecycle-managed.
- saved/: final MP4 exports; no lifecycle expiry.
- owners/owner/projects/: owner project manifests; no lifecycle expiry.

Source videos are uploaded directly to R2 in 8 MiB chunks when the R2 environment is configured. The backend downloads a temporary working copy for FFmpeg, so CPU, memory and disk limits on Render still apply. Direct uploads are capped by MAX_DIRECT_UPLOAD_MB and source duration remains capped at 10 minutes, but the 512 MB default cap and Render disk space can be lower practical limits.

Completed final MP4 exports are copied to saved/ and downloads use a short-lived 15-minute presigned URL. The authenticated API controls access to the signed download redirect. Project manifests are persisted through the same R2 bucket.

## Security and limitations

The Cloudflare Worker and FastAPI backend both require the owner credentials. Configure OWNER_PASSWORD as a Worker secret and in Render; see OWNER_SETUP.md. The app is a single-owner workspace, not a multi-user service. Do not apply lifecycle expiry to the whole bucket. R2 does not remove Render's processing limits or make uploads unlimited.
