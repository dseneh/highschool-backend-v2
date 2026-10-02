# Global Parent authentication smoke test — 2026-09-29

## Environment and isolation

Used a separate frontend on port 3001 and backend on port 8001, with a disposable PostgreSQL test database. Two synthetic schools had different students sharing the same student ID (`91001`). An existing synthetic employee had Parent access at both schools. A new-parent record had Give access for only one student. Email delivery was mocked and captured locally; no real messages were sent. The database, temporary servers, captured email, test script, and separate frontend build cache were removed afterward.

## Browser checks passed

- Existing staff account signs in through central Parent login and opens the global family dashboard with two students at two schools.
- Header selector opens the correct student at each school despite identical student IDs, while remaining on the parent host.
- Desktop sidebar shows a separate linked-students group, Link action, My dashboard, My profile, Settings, and Help & support. Student detail retains its own navigation; administrative enrollment actions are unavailable.
- Inline new-parent setup verifies email before displaying school-record details, uses the OTP control, disables controls while submitting, shows invalid-code errors with destructive styling, and separates passwords into their own step.
- New registration produces an account-confirmation email through the mocked delivery function. A subsequent fresh sign-in shows exactly one approved student, not the staff account's other school.
- Logout follows the central Parent logout endpoint. Signed-out and rejected-session screens require deliberate sign-in instead of automatically resuming a session.

## Problems found and corrected

- Parent browser requests now always use the BFF, including when school development is configured for direct API requests.
- SSO callback clears temporary cookies before appending the sealed Parent session; the previous order could discard the session and cause a redirect loop.
- Parent logout avoids racing route guards, clears the selected-student cookie, and prevents automatic re-entry from a signed-out screen.
- A rejected handoff now expires the central Parent cookie and displays a sign-in error. During testing one new-account handoff was rejected; fresh sign-in succeeded, and a separate HTTP round trip also passed. The initial rejection was not reproduced outside the browser; production/staging rollout still needs its own smoke check.
- Missing student birth dates no longer show `NaN` age. Enrollment guidance directs parents to the school; closed administrative dialogs are not mounted unnecessarily.

## HTTP and automated checks

A complete HTTP session test passed against the isolated servers: central login, PKCE redirect/callback, authenticated parent session, exactly one linked student, logout at both origins, and removal of selected-student state. Authentication tokens were not printed.

The focused backend configuration, permission, and dashboard checks passed (11 tests). The final frontend run passed 62 tests across 20 files. TypeScript, targeted lint, and both repository diff checks passed. Earlier backend cross-school, role-protection, replay, expiry, and existing-account reuse results are recorded in `account-setup-and-parent-access.md`.

## Configuration and remaining rollout work

Registered the exact development callbacks for `http://parent.localhost:3000/auth/callback` and `http://parent.lvh.me:3000/auth/callback` on the local OAuth client. Other callbacks, accounts, and student permissions were preserved.

`configure_parent_workspace` defaults to a read-only prerequisite check. `--apply` registers the selected exact callback idempotently. It rejects reserved-workspace collisions, inactive public tenants, disabled clients/callbacks, missing PKCE, and insecure production origins.

No production or staging deployment, DNS change, or live email delivery was performed. The deployment environment/domain remains to be selected. Its DNS/TLS, frontend environment, exact callback registration, and real test-mailbox delivery must then be verified.

## Local database handoff repair — 2026-09-29

A later login against the existing development database failed during token exchange. Its `auth_tenant_session` table already contained a required `device_metadata` column absent from the model and migration state. PostgreSQL rejected new sessions; the frontend incorrectly displayed the school-access-denied page for this server error. The recent authorization record correctly targeted `http://parent.lvh.me:3000/auth/callback`.

Migration `users.0014_tenant_session_device_metadata` adopts the existing column without discarding its data, adds it on fresh databases, and supplies an empty-object database default for older application processes. It was applied to the local shared schema. A synthetic token exchange inside a rolled-back transaction reproduced the failure before the change and succeeded afterward with `parent_workspace: true`. No real accounts or access links were changed.

Parent callback failures now return to central Parent login with a distinct error and no automatic retry loop. Callback redirects use the public Host/protocol rather than Next's potentially internal request origin. Production/staging must apply the additive migration as part of rollout.
