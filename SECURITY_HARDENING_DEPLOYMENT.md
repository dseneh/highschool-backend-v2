# Security Hardening Deployment Notes

This change intentionally fails closed in production. Complete these deployment steps before setting `DEBUG=false` on a new environment.

## Required production configuration

- `SECRET_KEY`: strong, unique Django/JWT signing secret. No development fallback is accepted.
- `SECRET_AES_KEY`: existing valid encryption key. Do **not** rotate this casually; existing encrypted data depends on it.
- `ALLOWED_HOSTS`: comma-separated exact hosts/suffixes accepted by Django. `*` is rejected in production.
- `RAILWAY_PUBLIC_DOMAIN`: optional; when present it is added to `ALLOWED_HOSTS` automatically.

## Private R2/S3 storage

When `USE_S3_STORAGE=true`, bucket, access key, secret key, and endpoint are required. Default media storage now uses private objects and presigned URLs. Signed URLs expire after `PRIVATE_FILE_URL_EXPIRY_SECONDS` (default 300 seconds).

The application no longer sets `public-read`, no longer disables query-string authentication, and no longer uses the public custom domain for default media URLs.

**Important:** changing Django storage settings does not retroactively disable an R2 bucket's public-access/custom-domain setting. In Cloudflare R2, disable public bucket access/custom-domain exposure for the bucket that contains private EzySchool media. Existing objects that were previously public must be treated as exposed until bucket-level public access is disabled.

If public branding assets are needed, use a separate explicitly public storage backend/bucket rather than making the default tenant-media bucket public.

## Authenticated encryption

New encrypted security payloads use versioned AES-GCM envelopes (`v=2`). The shared decrypt helper can read historical unversioned AES-GCM envelopes and legacy AES-CFB envelopes so existing data can be migrated safely. New sensitive values must not be written using AES-CFB.

## API throttling

Defaults can be overridden through environment variables:

- `API_THROTTLE_ANON=60/min`
- `API_THROTTLE_USER=300/min`
- `API_THROTTLE_LOGIN=5/min`
- `API_THROTTLE_PASSWORD_RESET=12/hour`
- `API_THROTTLE_ACTIVATION=12/hour`
- `API_THROTTLE_PUBLIC_SEARCH=20/min`

DRF throttling uses Django's cache. For multi-replica production deployments, configure `USE_REDIS=true` with a shared `REDIS_URL`; otherwise per-process local-memory caches cannot enforce a reliable platform-wide rate limit. The same shared cache can be used by future payment webhook replay protection.

## JWT/session revocation

The `User.security_version` value is embedded in newly-issued JWTs. Incrementing it invalidates older access/refresh tokens. The revoke-all-sessions endpoint also revokes existing central and tenant SSO sessions and refresh-token families.

SimpleJWT's blacklist app is enabled in the public/shared schema so refresh-token rotation and `BLACKLIST_AFTER_ROTATION` are persisted rather than configuration-only.

Run shared/public migrations before serving application traffic.

## Deferred items

MFA is intentionally **not included in this hardening release**. It will be designed, integrated with the frontend, and tested as a separate feature later.

Password strength and password-complexity changes are also intentionally deferred.

## Payment-readiness primitives

`common.payment_security` provides provider-neutral helpers for constant-time HMAC-SHA256 webhook signature checks, webhook timestamp freshness checks, deterministic idempotency keys, and atomic webhook event replay claims using Django's cache.

Provider adapters must still follow the selected payment provider's exact signing specification.

## Rollout checklist

1. Confirm `SECRET_KEY` and the current `SECRET_AES_KEY` exist in Railway.
2. Set `ALLOWED_HOSTS` to the backend hosts actually used in production.
3. Confirm R2 credentials and endpoint variables are present.
4. Disable R2 public bucket/custom-domain access for private tenant media.
5. Configure shared Redis before relying on throttling or payment replay protection across replicas.
6. Run public/shared migrations, including the user security-version and SimpleJWT blacklist migrations.
7. Deploy and verify login, refresh-token rotation, password reset, school search, tenant media, and authenticated uploads/downloads.
8. Verify the revoke-all-sessions endpoint invalidates prior JWTs and server-side sessions.
9. Confirm repeated sensitive requests return HTTP 429 at the configured limits.
10. Run tenant-boundary and public-endpoint security tests before enabling online payment integrations.
