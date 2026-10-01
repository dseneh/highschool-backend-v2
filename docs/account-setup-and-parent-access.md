# School account setup and parent access

This supersedes the invitation-based enrollment flow. The existing shared User, ParentProfile, school-local guardian records, linked-student selector, and selected-role authorization remain in use.

## Account setup

School login pages offer **Set up account** inside the same tenant auth card as sign-in and password reset. The forms slide in place without page reloads, preserve entered login values, and make offscreen panels inert. Setup completion returns to sign-in in the same card. The five numbered steps are account type (compact selection cards), email, verification code, personal details, and password. The reusable InputOTP component supports entering or pasting the six-digit code. Address is omitted from setup and existing school addresses are preserved. Auth cards scroll internally when their content exceeds the available desktop height. Setup actions, workspace switching, and theme buttons are disabled during requests. The wizard asks for Employee, Student, or Parent/guardian, then the email on the school's record. Matching a record only establishes eligibility. Personal details are returned after an six-digit email code is verified. Codes expire after 15 minutes, permit five wrong attempts, and can be verified once. The completion proof is kept in a host-only HttpOnly cookie; the server binds it to the school, email, record IDs, and account type. Completion is single-use and rechecks that those records remain eligible. Start requests have a per-email cooldown and endpoint throttles.

Employee setup uses canonical HR Employee records, with legacy Staff fallback only when no canonical record uses the email. Student setup uses active eligible student records. Multiple matches, conflicting account references, inactive sources, or changed records require school correction. The server re-reads locked employee/student bio; it ignores submitted changes. New accounts receive the existing Staff self-service or Student role, never administrator/teacher roles inferred from job titles.

Parent setup accepts active StudentGuardian rows and StudentContact rows explicitly classified parent/guardian in the current school. Generic emergency/other contacts are ineligible. Multiple family relationships may share an email, but conflicting names or existing identity references require school review. Parents can edit first/last name, gender, birth date, phone, and address. Changes apply only to the matched school-local rows. Verified email, relationship type, access flags, and school notes are not editable. Existing shared account identity fields are preserved when an employee or another user connects Parent access.

Existing accounts are reused, with their current password or current authenticated identity required after email verification. Passwords and existing roles are not changed. Suspended accounts and revoked/inactive school roles require school review; setup cannot restore them. The setup wizard uses Zod to validate each step and the full completion payload, with destructive error feedback. Its shared password inputs include disabled-aware visibility toggles. New passwords require at least eight characters, matching the backend minimum; existing-account passwords are verified without imposing a new-password length policy. A new account uses Django password validation and the configured transactional-email service for its confirmation. Account setup does not issue a session or bypass the normal sign-in/2FA path.

`ACCOUNT_SETUP_EMAIL_ENABLED` defaults to true and uses the already configured email provider. It may be explicitly disabled by environment. Delivery failures are shown as errors, never as successful verification. Automated tests mock delivery; no real emails are sent during development verification.

## Give access

Authorized school staff enable **Give access to this student** on a parent/guardian card. Only `students.guardians.manage` with all/assigned scope can approve; student/parent own-scope permissions cannot. A qualifying old contact can receive the same approval; this explicitly creates its school guardian relationship and keeps the original contact record.

The flag alone does not prove identity. Approved relationships activate only for an account that has verified the recorded email. Existing verified accounts connect immediately; otherwise, account setup connects them after verification. Guardian rows remain authoritative and role/student selection checks still apply. Disabling the flag ends the link and discovery entry without deleting school records.

Admin-approved active links appear in the parent's family dashboard, sidebar, and header selector without a parent-submitted linking request. The shared linked-students query refreshes every 30 seconds while visible, and on mounting, returning to the tab, or reconnecting. Both guardian and contact approval responses include the resulting portal state so the administrator sees whether linking completed or email verification is still required. Merely recording a contact without approving Give access does not expose student information.

A verified parent registered at a school retains the Parent workspace even with no linked students, so they can submit and track requests. No student information is returned without an eligible verified link. The Parent role remains protected while eligible links exist; this workspace registration grants no additional school-wide student permissions.

## Parent-initiated links

The parent portal accepts student ID (`id_number`), required first and last names, and optional middle name, gender, and relationship. Names use exact case-insensitive matching with whitespace normalization; supplied middle name and gender must also match. A mismatch returns a generic error without disclosing corrected student details. These facts are not authorization credentials.

An existing school-approved `give_access` guardian row matching the parent's verified email activates automatically. Otherwise one pending request per parent/student/school is recorded; no student access is granted. School reviewers see requests on that student's Parents & guardians page. Approval explicitly verifies the relationship and enables access; rejection grants nothing. Reviews are scoped to permitted students, cannot approve the reviewer's own request, and retain reviewer/time metadata. Replayed reviews are rejected.

## Migration and compatibility

- `users.0013`: email challenges, verified-email records, parent-school registrations, and parent-link requests.
- `students.0021`: explicit access flag, parent/contact bio, and an optional contact-to-guardian reference.
- Only already active, approved, verified guardian links receive `give_access=True` during migration. No unverified or ambiguous legacy rows are activated.
- Invitation API routes return 410 with account-setup guidance. Old invitation and account-setup page URLs render the same login layout with its setup panel selected; no invitation secret is reused. Invitation records and internal lifecycle primitives remain for audit/history and regression coverage; no new invitations are issued by the UI or guardian API.

## Verification

See the task's final report for current automated counts. Real email delivery and a complete live account-creation/approval walkthrough require controlled test accounts; no real credentials, invitations, or student permissions were changed for browser checks.

Latest checks: 38 backend tests passed (account setup, prior parent lifecycle/role isolation, approved-record preservation); 22 UI/BFF tests passed. TypeScript, targeted ESLint, Django system checks, migration consistency generation checks, and diff checks passed. Both migrations were applied locally. Browser inspection confirmed the branded setup card and account-type/email steps. Live email delivery, complete sign-in, and live school approval were not exercised with real accounts.

Inline auth layout follow-up: nine targeted UI tests, TypeScript, lint, and diff checks passed. Browser inspection confirmed switching between setup and sign-in preserves the URL and the school auth card, including for an already signed-in session.

## Family dashboard and student navigation

The Parent role opens a family dashboard, including linked students, school counts, outstanding scheduled tuition, birthdays, and delivered announcements. Summary discovery revalidates each link and resolves each destination school's Parent assignment independently; staff permissions are never used to fill dashboard cards. Tuition uses the existing live payment-plan calculation, excludes fully paid installments, and remains labelled by school rather than summed across currencies. Birthday summaries return month/day only. Announcements reuse recipient and student-audience filtering.

The sidebar lists linked students and includes My profile, Parent settings, and Help & support. The shared header selector matches both school and student ID. Selection is validated on the server, then opens the existing `/students/{id_number}` pages and detail navigation with Parent permissions. The roster and administrative mutations remain unavailable. In the global Parent workspace, cross-school selection stays on the parent origin. The server revalidates the selected link and applies its school and Parent role before loading student data. The existing school-context handoff remains for legacy school entry points. Disconnect remains in Parent settings and preserves school records.

Linking now uses `student_id_number` (the student's `id_number`), first and last names, optional middle name, optional gender, and optional relationship. The frontend validates these with Zod; the backend validates independently. Names are compared after case/whitespace normalization. Supplied middle name and gender must match; omitted values are not matching requirements. An omitted relationship is stored as `other` for school review. Removing grade and gender requirements does not grant access: automatic activation still requires a verified account email and an explicitly approved Give access relationship; otherwise a school approval request is created.

Existing student-detail endpoints are enabled through an explicit read-only Parent allowlist that checks the current school's verified guardian link and the selected role's permission. Unrelated students, administrative writes, unpublished grades, and full administrative reports remain inaccessible. Enrollment billing summaries also respect the Parent role's billing permission. Official transcript issuance remains a school-office action.

Dashboard follow-up verification: 38 backend integration/snapshot tests and 21 frontend tests passed; additional focused policy tests cover ownership, mutation denial, unpublished grades, administrative reports, and removed billing permission. TypeScript and targeted lint checks passed (existing unused-variable warnings remain). Local browser navigation reaches the school sign-in screen; a signed-in parent walkthrough and live cross-school navigation still need verification with controlled test accounts.


## Global Parent workspace and central authentication

`parent.<root>` is the family workspace; `auth.<root>/login?mode=parent` provides parent sign-in and inline account setup using the shared auth layout. School login pages offer a Parent login/setup button. Staff keep their existing account and can enter Parent mode through role switching; the central identity session authorizes a fresh destination context after verifying the requested school membership or platform grant. Parent API requests remain parent-scoped.

Parent authentication uses a separate, host-only HttpOnly session cookie on each host. The existing authorization-code/PKCE flow exchanges a single-use code between auth and parent origins; credentials/tokens are not put in parent redirect URLs. Parent token scope survives refresh. Parent student requests revalidate the selected link server-side and force its school-specific Parent assignment, ignoring client-supplied school/role overrides. Global summary discovery independently revalidates every relationship. Sign-out revokes the browser central session and its linked workspace sessions, and clears local and central cookies.

Global setup verifies email ownership before discovering school records or returning personal details. It reuses the existing school account-setup lifecycle atomically across matched schools. Existing accounts require authentication or their password and are reused. Conflicting names across records fail closed for school review; no ambiguous legacy link activates. Give access and verified identity remain separate requirements. The link-request school selector currently offers schools with a parent registration or active link; setup can discover additional eligible school records.

Deployment requirements:
- Route `auth.<root>` and `parent.<root>` to the same frontend with TLS; reserve `parent` as a workspace name. Check for existing workspace-name collisions before rollout.
- Configure the existing OAuth client (`AUTH_SSO_CLIENT_ID`, default `ezyschool-web`) with the exact allowed callback `https://parent.<root>/auth/callback`. Keep the existing public tenant and central SSO configuration.
- Configure `AUTH_SSO_BASE_URL` for the central auth host, the existing root domain, session encryption secret, backend connectivity, and account-setup email delivery.
- Local browser validation uses `auth.localhost:<port>` and `parent.localhost:<port>` (or the configured development wildcard domain). The global flow requires subdomain-capable hosts; bare IP development is not verified.

Material assumptions: guardians use the same verified email across matched school records; discrepant records require school correction. Global discovery currently scans eligible tenant schemas after email proof; a maintained discovery index is a future scaling improvement. No DNS, production OAuth records, real email delivery, or ambiguous legacy records are changed by this implementation.

Global workspace verification (2026-09-29): 49 targeted frontend tests passed; TypeScript, targeted ESLint, and both repository diff checks passed. The 73-case backend run passed 72 cases and exposed a nullable-join PostgreSQL lock error in SSO exchange. Restricting the lock to the authorization-code row fixed it; the subsequent five-case SSO/scope run passed, including code expiry, replay, invalid PKCE, and server-session scope. Nine focused permission/dashboard tests also passed. Browser inspection confirmed the shared parent setup card and parent-host redirect to central auth. A complete authenticated browser walkthrough, live email delivery, and deployed DNS/TLS/OAuth callback registration remain unverified. Initial disk-space-related test failures were resolved by rerunning after temporary space became available; no unrelated data was deleted.

### Repeatable callback configuration

Check prerequisites without changes:

```sh
python manage.py configure_parent_workspace --origin https://parent.example.com
```

After choosing the deployment domain, register its exact callback with `--apply`. The command is idempotent, requires an active public tenant, rejects a school named `parent`, and will not silently reactivate disabled clients or callbacks. It requires PKCE and preserves other callback registrations. For isolated development, `http://parent.localhost:3001` and `http://parent.lvh.me:3001` are accepted. Production origins require HTTPS.

Parent browser requests always use the same-origin BFF, including when `NEXT_PUBLIC_API_MODE=direct` is used for school development. This preserves the parent HttpOnly session and server-controlled student context. A separate frontend smoke server can use `NEXT_DIST_DIR=node_modules/.cache/parent-smoke-next` to avoid sharing the normal development build output.


Follow-up browser and configuration verification: [Global Parent authentication smoke test](parent-auth-smoke-test.md). Replace `example.com` with the selected deployment root before running the configuration command.

## Canonical account email

`User.email` is the login email and the source of truth once a person has an
explicit account link. `users.identity_email` applies account, staff/employee,
student, and linked guardian/contact email edits through the same transaction.
Replication follows `user_account_id_number`, `parent_profile_id`, and the contact's
`portal_guardian_id`; it never links people by matching names or email text.
Schools are discovered through account memberships and the parent's shared school
registrations/link index, including inactive links, plus the current school.

A linked login email change requires `users.update` in the selected role and an
account membership in the current school (or a platform administrator). Guardian
or HR edit permission alone cannot change credentials. Employee account references
are read-only in the employee serializer; account provisioning owns those links.
Unlinked contacts retain independent school-managed email addresses.

Changed addresses are normalized and checked case-insensitively for another
account. Changes clear `User.is_verified` and existing `VerifiedAccountEmail`
proofs. Existing identity/student links remain intact; changing email never grants
access or activates an unverified relationship. New email-based links still require
verification. No automatic message is sent by an administrative email correction.
Self-service email replacement still requires a dedicated verified-change flow;
it is not exposed as an unrestricted parent contact edit.

User responses always display the account email, even if an old source record is
stale. Legacy account-attachment endpoints reject conflicting source emails instead
of silently overwriting an existing login. Conflicting identity references fail
closed and roll back the complete cross-school change. Historical records without
explicit references are not automatically merged or repaired. Direct ORM/import
writers must call `set_account_email` inside their transaction for login changes.

Validation: Django system checks and 18 focused email/deletion tests passed.
A PostgreSQL rollback-only smoke test exercised two schools (`ldtc`, `djr`) with
disposable accounts, students, employees, staff, guardians, and contact bridges:
account-to-record and contact-to-account propagation, unchanged unlinked contacts,
verification clearing, unchanged access flags, case-insensitive duplicate rejection,
and full rollback on conflicting guardian references all passed. No real account
was edited and no message was sent. Browser editing and full verification delivery
remain to be exercised end-to-end.

### Reconnecting after account recreation

School and global setup now issue six-digit codes (including leading zeroes);
request a new code if an older eight-digit challenge was already issued.

Parent eligibility distinguishes live identity references from references whose
User or ParentProfile has been hard-deleted. Lookup does not change those records.
After fresh email proof and authentication of an existing account (or validated
new-account setup), an eligible school-approved guardian can be rebound to the
current identity. A reference to any other existing account/profile still blocks
setup. Suspended/disconnected relationships do not reactivate through setup.
School guardian/student records and the reused employee account's roles remain.

Validation: focused identity/code tests and auth wizard tests pass. A PostgreSQL
rollback-only test covered a recreated staff identity with stale guardian owner
and profile references: six-digit leading-zero code, no reassignment during
lookup, wrong-password rejection, existing-account reuse, restored approved
student access, retained Teacher and Parent roles, replay rejection, and blocking
live conflicting owners and suspended/disconnected relationships. Email delivery
was mocked and all database writes were rolled back. Actual email delivery and
browser sign-in with the affected real account remain unverified.

### Password recovery and backwards navigation

The final setup step explicitly distinguishes creating a new password from
entering the current password for an existing account. Existing users can open
an inline reset-instructions panel using the established password-forgot endpoint,
pre-filled with their verified email and scoped to the parent or school workspace.
Returning preserves personal details but never retains a password. The setup
challenge still expires normally; password recovery does not extend it.

Completed numbered steps are keyboard-accessible buttons and are disabled during
requests. Returning to details preserves verification. Returning to a verified OTP
step shows its verified state without replaying the single-use code. Going back
to email or account type clears dependent progress and requires fresh verification.

### Pre-send eligibility and configured throttling

Both school and global parent setup validate email syntax at the API boundary,
check for eligible school guardian/contact records, and reject an existing
ParentProfile (or legacy parent-type account) before creating a challenge or
sending mail. Existing employee accounts without parent setup remain reusable.
This verifies school-record eligibility, not mailbox deliverability or ownership;
email-code verification is still required before disclosing personal details or
connecting records. Discovery is repeated after verification and completion
rechecks the school snapshot and identity references.

AccountSetupView now uses the configured DRF default throttles. Start, verify, and
complete share the standard activation scope (`API_THROTTLE_ACTIVATION`, default
12/hour/IP), alongside the configured anonymous/user limits. A shared per-email
60-second cooldown uses atomic cache.add plus the challenge history check across
school/global entry points. Throttled responses use 429 and Retry-After, preserved
by the setup BFF. No new independent hard-coded invitation limits apply to setup.

Tests cover no challenge/email for ineligible records or registered parents,
employee-account reuse eligibility, invalid email rejection, atomic resend limits,
and configured endpoint throttling with Retry-After. The rollback-only staff
recovery smoke test continues to use mocked email delivery.

### Parent name-only details step

Parent setup now asks only for first name, optional middle name, and last name.
Gender, date of birth, phone, and address are neither returned for parent prefill
nor submitted by the form. Completion accepts only the three name fields for
parent record updates, preserving existing school demographic/contact data even
if an older client sends it. Employee/student setup remains unchanged.
Additive migrations users.0015 and students.0022 store middle names on shared
accounts and school guardian/contact records; both were applied locally.

Parent name fields are stacked vertically. The details step requires an unchecked
Terms and Conditions checkbox linked to `/terms` in a new tab. Zod blocks progress
without acceptance and the backend independently rejects parent completion without
`terms_accepted=true`. Successful completion records the user ID, timestamp, terms
path, and the current published terms version (2025-05-01) on the consumed setup
challenge. No school/student/staff setup requirement was changed.

School role handoff authentication recovery: when switching from Parent to a school role without a valid staff/central SSO session, `/authorize` now redirects to that school's sign-in form and retains the `/switch-role?assignment=...` destination. After school authentication, the existing role-selection endpoint rechecks the assignment. The parent session remains separate and is not promoted into staff permissions; a rejected school session cookie is cleared without clearing the parent cookie. Login recovery destinations are derived from the current root domain, not the supplied OAuth callback URL. Valid SSO sessions continue through the existing code/PKCE exchange, and membership-denied responses remain denied.


Central identity SSO follow-up (September 30, 2026): parent, staff, and platform roles now share one opaque central login session. Parent login may bootstrap that identity; bootstrap reuses an existing unexpired session for the same user without extending its lifetime. Each handoff still uses a one-use authorization code and PKCE, and rechecks the destination membership at both authorization and exchange. Parent-scoped bearer tokens remain restricted on ordinary API calls. Source role selection is discarded when resolving identity for a new destination. Platform entry requires the platform grant; parent role discovery exposes that option only for platform superusers.

School callback now creates the sealed PortableAuth browser session from the exchanged credentials. School/platform sessions use a new host-only `pa_workspace_session` cookie; Parent remains host-only `pa_parent_session`. Only `ezyschool_sso` is shared across subdomains. Temporary PKCE/state cookies are host-only too, preventing two school handoffs from overwriting each other's state. Legacy shared `pa_session` cookies are no longer read, so older school sessions may need one sign-in when no valid central session remains. Cross-school tabs retain independent school/role contexts; tabs on the same school still intentionally synchronize role selection.

Login screens can resume an existing central identity; a genuinely expired identity falls back to school sign-in with the selected role retained. Parent-to-school switching first establishes/reuses central SSO from the current authenticated Parent session. Central logout revokes linked tenant sessions, and both school and parent JWT authentication check server-side session expiry/revocation. Existing password/security-version revocation is retained.

Validation: focused frontend/backend regression tests plus a real PostgreSQL smoke run using disposable records in a rolled-back transaction. The smoke covered one parent identity opening two schools, parent token separation, replay rejection, revoked assignments at both handoff stages, central expiry, platform grant/denial, and central logout revoking child sessions. No real invitations or emails were sent. End-to-end browser navigation and production OAuth callback allow-lists still need deployment verification; use a shared development domain such as `*.lvh.me` for cross-subdomain cookies (`*.localhost` cannot share browser cookies reliably).

Browser follow-up: central bootstrap, session discovery, and logout BFF calls explicitly send `X-Tenant: admin` because the real Django middleware requires tenant context. Unit view tests had bypassed that middleware. Local development keeps the authorization authority in the current hostname family instead of following an unrelated AUTH_SSO_BASE_URL. For Parent-to-school handoffs on `*.localhost`, where cookies are host-only, the destination creates its PKCE state and authorizes through the already-authenticated Parent host. The identity hint is fixed to Parent, never an arbitrary redirect host; tokens remain out of URLs. Verified in the user's browser: Parent on parent.localhost → Accountant on ldtc.localhost, without entering credentials. Errors now retain the backend's useful explanation instead of always reporting an expired session.

Student-switching UX: header, sidebar, and mobile selectors share the pending student and error state. The clicked student shows a spinner, and the content area shows their photo and “Opening [name]…” instead of generic full-page skeletons. This status remains until both server authorization and the exact destination route (including the link ID for repeated student IDs) are complete. Cached student data is restored only after authorization. Previous-context queries are removed without eagerly refetching old observers against the new context. Switching preserves recognized student sections such as grades, attendance, and billing; record-specific/edit routes fall back to overview. A failed authorization keeps the previous selection and data, with shared destructive error feedback. Regression tests cover repeated IDs, cache isolation, route preservation, pending navigation, and rejected switches.

The switcher identifies the parent workspace from the hostname/route rather than the selected school's tenant store. Family navigation stays visible while school permissions reload. Browser verification confirmed the named loading state, stable family sidebar, and switching between two students while remaining on Grades. TypeScript and the targeted switching tests pass. The broader dashboard suite still has five assertions against student cards that are currently commented out in the existing dashboard; those assertions need to be updated separately.

Student-switching presentation follow-up: replaced the spinner/photo status with a shared `StudentOverviewSkeleton`, also used by the overview page loading state. It follows the profile, metrics, charts, and financial detail layout using the reusable Skeleton component, with responsive columns and reduced-motion support. Navigation stays visible without switching spinners; the destination is still announced to screen readers. Authorization, cache isolation, route preservation, and failure recovery are unchanged.

The switching skeleton also includes the student detail navigation: a 200px profile/menu rail at the same `lg` breakpoint as DetailSideNav, and a compact student/dropdown bar below it. Student detail loading reuses the same navigation skeleton. The overview content uses the existing ScrollArea alongside the rail, while global family navigation stays visible.

### Parent preferences and tuition schedule

Parent Settings (including the `/settings` alias while using the Parent role) shows device appearance, shared-account management, and student connections. School branding and school configuration remain school-role features. Appearance uses the existing persisted theme preference; disconnecting continues to preserve school guardian records.

The family dashboard charts outstanding installment **amounts** by their actual scheduled month, including overdue and distant future dates. A school selector keeps amounts within one school’s billing currency. The area chart displays labeled values and axes, alongside scheduled, overdue, and upcoming balances. It does not assume the school's current academic year falls within the next six calendar months, and does not aggregate monetary amounts across schools/currencies. A school with no outstanding scheduled installments contributes no bars; its full billing account remains available from the student page.

### Iteration verification — 2026-10-01

- Browser: checked the parent dashboard at 390 × 844 in light and dark appearance, readable chart labels, mobile Settings highlighting, and the full responsive student-switch skeleton. Opened linked students at two schools and confirmed destination details replaced the previous student.
- Browser: completed Parent → Accountant → Parent round trips for both local schools without entering credentials. Found and fixed an existing-destination-session mismatch: DNS-based parent-to-school navigation now always starts the destination PKCE/central-identity handoff before selecting its assignment, rather than trusting an already authenticated destination session. Assignment ownership is still validated by the backend. Path-based development fallback is unchanged and was not browser-tested.
- Billing: compared outstanding installment sums against live accounting net bills less effective payments for the two linked students with scheduled balances; both matched to the cent. A third student had no current enrollment/schedule. Inspection used rollback and disabled cache writes. Added regression coverage for partial payment allocation, fully paid accounts, and overpayments.
- Automated: 38 frontend workflow tests passed; 14 focused handoff/callback tests passed (some overlap). Backend: 46 parent/security/session tests, four approval/revocation tests, two tuition calculation tests, and one accounting-source test passed. Approval and revocation were exercised with test fixtures; no real links were approved or revoked and no real invitations were sent.
- Accessibility: associated the parent theme selector with its visible label.
- Scope: local browser and test-database verification only; production-domain cookie behavior and a full account-setup/email-delivery run remain deployment checks.

### Contact-added in-app notices

Creating a parent, guardian, or other student contact now creates a recipient-only system notice for an existing active user account. The recipient is resolved from an explicit guardian account reference, or a unique case-insensitive account email; names never resolve identity. Unverified email-only matches receive a generic school notice without the student's name. No account, membership, role, verified relationship, or student access is created by notification delivery. There is no email channel and no backfill for historical records.

Notices are created after the relationship transaction commits. A deterministic campaign ID makes retries and guardian/contact synchronization idempotent. Guardian synchronization retains its contact reference so ordinary edits do not create another contact/notice. Failed post-commit delivery is logged by Django's robust callback handling.

School staff see the notice in the existing school inbox. The global parent inbox exposes only contact-added system notices addressed to that user across operational schools, including notices before portal access approval. Its list, counts, and mark-read actions do not depend on a selected student and cannot read or mutate another user's notifications. Existing school-specific announcements remain on the family dashboard. This endpoint currently queries operational school schemas for recipient-owned notices; large tenant counts should be profiled before wider rollout.

Validation: three tenant-backed notification integration tests passed (creation/deduplication/rollback, parent and other contact targeting, cross-school inbox and recipient isolation), along with six frontend API/proxy tests and the TypeScript check. No real contact records or notifications were created for verification.

### Staging rollout — 2026-10-01

The existing `staging` branches deploy to Railway (`backend-v2`, staging environment)
and Vercel (`highschool-ui-2`, staging environment). Frontend root:
`https://staging.myezyschool.com`; backend: `https://api.staging.myezyschool.com`.

The Railway staging service is configured with this idempotent pre-deploy command:

```sh
python manage.py configure_parent_workspace --origin https://parent.staging.myezyschool.com --apply
```

This registration is staging-only. An unauthenticated authorization request for
that exact callback should reach `AUTH_REQUIRED`, not `UNKNOWN_CLIENT` or
`REDIRECT_URI_NOT_ALLOWED`. Verify this after a fresh deployment; a redeploy of
an older deployment may retain its original configuration.

Release checks: all 295 frontend tests passed, the local production Webpack build
passed, Django checks passed, and no model changes lacked migrations. Railway
applied shared and school migrations successfully. The default local Turbopack
build was blocked by a worker-port restriction; Vercel built the release successfully.
Authenticated cross-school flows and real email delivery remain staging smoke
checks. A nonfatal MaxMind GeoIP HTTP 401 warning requires separate credential review.
Local media, scratch scripts, and the demo-seeding command were excluded from release.


### Parent/guardian form access and explicit deletion

The school parent/guardian form submits `give_access`, defaulting to false on
creation. Access changes require guardian-management permission with all/assigned
scope and student visibility, and use the existing verified relationship lifecycle.
Saving and approving are atomic; an invalid approval rolls back the form changes.

The UI explicitly deletes a relationship with `DELETE guardians/<id>/?delete_record=true`.
This revokes invitations/access, reconciles the school Parent role, and removes
only that guardian and the contact mirror identified by its guardian ID. It does
not delete the user, student, or unrelated relationships. The access switch and
legacy DELETE without the flag continue to disconnect linked portal access while
preserving school guardian records. Both actions require confirmation; deletion
uses the shared destructive confirmation component.
