# Security Hardening Deployment Notes

This change intentionally fails closed in production. Complete these deployment steps before setting `DEBUG=false` on a new environment.

## Required production configuration

- `SECRET_KEY`: strong, unique Django/JWT signing secret. No development fallback is accepted.
- `SECRET_AES_KEY`: existing valid encryption key. Do **not** rotate this casually; existing encrypted data depends on it.
- `ALLOWED_HOSTS`: comma-separated exact hosts/suffixes accepted by Django, for example the backend custom domain and Railway service domain. `*` is rejected in production.
- `RAILWAY_PUBLIC_DOMAIN`: optional; when present it is added to `ALLOWED_HOSTS` automatically.

## Private R2/S3 storage

When `USE_S3_STORAGE=true`, bucket, access key, secret key, and endpoint are required. Default media storage now uses private objects and presigned URLs. Signed URLs expire after `PRIVATE_FILE_URL_EXPIRY_SECONDS` (default 300 seconds).

The application no longer sets `public-read`, no longer disables query-string authentication, and no longer uses the public custom domain for default media URLs.

**Important:** changing Django storage settings does not retroactively disable an R2 bucket's public-access/custom-domain setting. In Cloudflare R2, disable public bucket access/custom-domain exposure for the bucket that contains private EzySchool media. Existing objects that were previously public must be treated as exposed until bucket-level public access is disabled.

If public branding assets are needed later, use a separate explicitly public storage backend/bucket rather than making the default tenant-media bucket public.

## API throttling

Defaults can be overridden through environment variables:

- `API_THROTTLE_ANON=60/min`
- `API_THROTTLE_USER=300/min`
- `API_THROTTLE_LOGIN=5/min`
- `API_THROTTLE_PASSWORD_RESET=12/hour`
- `API_THROTTLE_ACTIVATION=12/hour`
- `API_THROTTLE_PUBLIC_SEARCH=20/min`

DRF throttling uses Django's cache. For multi-replica production deployments, configure `USE_REDIS=true` with a shared `REDIS_URL`; otherwise per-process local-memory caches cannot enforce a reliable platform-wide rate limit.

## Rollout checklist

1. Confirm `SECRET_KEY` and the current `SECRET_AES_KEY` exist in Railway.
2. Set `ALLOWED_HOSTS` to the backend hosts actually used in production.
3. Confirm R2 credentials and endpoint variables are present.
4. Disable R2 public bucket/custom-domain access for private tenant media.
5. Configure shared Redis before relying on throttling across replicas.
6. Deploy and verify login, password reset, school search, tenant logos/media, and authenticated uploads/downloads.
7. Confirm repeated requests return HTTP 429 at the configured limits.
