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

New encrypted security payloads use versioned AES-GCM envelopes (`v=2`). The shared decrypt helper can read both historical unversioned AES-GCM envelopes (12-byte `iv`) and legacy AES-CFB envelopes (16-byte `iv`) so existing data can be migrated safely. New sensitive values must not be written using AES-CFB.

MFA secrets are encrypted at rest with AES-GCM and bind the user id as associated authenticated data.

## API throttling

Defaults can be overridden through environment variables:

- `API_THROTTLE_ANON=60/min`
- `API_THROTTLE_USER=300/min`
- `API_THROTTLE_LOGIN=5/min`
- `API_THROTTLE_PASSWORD_RESET=12/hour`
- `API_THROTTLE_ACTIVATION=12/hour`
- `API_THROTTLE_MFA_CHALLENGE=20/hour`
- `API_THROTTLE_PUBLIC_SEARCH=20/min`

DRF throttling uses Django's cache. For multi-replica production deployments, configure `USE_REDIS=true` with a shared `REDIS_URL`; otherwise per-process local-memory caches cannot enforce a reliable platform-wide rate limit. The same shared cache is used by future payment webhook replay protection.

## JWT/session revocation

The `User.security_version` value is embedded in newly-issued JWTs. Incrementing it invalidates older access/refresh tokens. The security endpoint also revokes existing central and tenant SSO sessions and refresh-token families.

SimpleJWT's blacklist app is now enabled in the public/shared schema so refresh-token rotation and `BLACKLIST_AFTER_ROTATION` are persisted rather than configuration-only.

Run shared/public migrations before serving application traffic.

## MFA

TOTP MFA is available under `/api/v1/auth/security/` endpoints. Setup returns a standard `otpauth://` provisioning URI for authenticator applications. Recovery codes are hashed at rest and shown only once at confirmation.

Once MFA is enabled, password authentication returns an MFA challenge instead of bearer tokens. Enabling MFA also invalidates sessions created before MFA was enabled. Privileged accounts are marked MFA-required when they complete enrollment. Active MFA cannot be silently re-enrolled; a future verified rotation/recovery flow should be used when a factor must be replaced.

This change does **not** alter password strength or password-complexity requirements; that is intentionally deferred.

## Payment-readiness primitives

`common.payment_security` provides provider-neutral helpers for:

- constant-time HMAC-SHA256 webhook signature checks;
- webhook timestamp freshness checks;
- deterministic idempotency keys; and
- atomic webhook event replay claims using Django's cache.

Provider adapters must still follow the selected payment provider's exact signing specification. Never treat these generic helpers as a substitute for provider-specific verification rules.

## Rollout checklist

1. Confirm `SECRET_KEY` and the current `SECRET_AES_KEY` exist in Railway.
2. Set `ALLOWED_HOSTS` to the backend hosts actually used in production.
3. Confirm R2 credentials and endpoint variables are present.
4. Disable R2 public bucket/custom-domain access for private tenant media.
5. Configure shared Redis before relying on throttling or payment replay protection across replicas.
6. Run public/shared migrations, including the user security-state and SimpleJWT blacklist migrations.
7. Deploy and verify login, refresh-token rotation, password reset, school search, tenant media, and authenticated uploads/downloads.
8. Enroll a privileged test account in MFA, confirm pre-MFA sessions are rejected, then validate TOTP and one-time recovery-code login.
9. Verify the revoke-all-sessions endpoint invalidates prior JWTs and server-side sessions.
10. Confirm repeated sensitive requests return HTTP 429 at the configured limits.
11. Run tenant-boundary and public-endpoint security tests before enabling online payment integrations.
