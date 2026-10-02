> Current enrollment flow: [Account setup and parent access](account-setup-and-parent-access.md) replaces invitations with verified self-service setup and school Give access approval. Invitation sections below describe the earlier implementation.

# Parent portal implementation

## Identity and authorization

`users.ParentProfile` is a shared one-to-one identity for the existing User. `ParentStudentLink` is a shared discovery index; a unique `(profile, tenant, guardian UUID)` key prevents duplicates. Each school's `StudentGuardian` remains authoritative. UUID references are used across schemas. Account categories, credentials, school guardian notes, and students are preserved.

The additive migrations are `users.0011` and `students.0020`. They do not activate or match any legacy contacts. After reviewing normal deployment migration status, apply shared migrations before tenant migrations:

```sh
python manage.py migrate_schemas users --shared --noinput
python manage.py migrate_schemas students --tenant --noinput
```

Discovery rechecks each indexed guardian, school operational status, active student, active membership, enabled Parent assignment and its students.view grant. Reading details and disconnecting additionally require the selected Parent assignment in the selected school. Employee/platform roles cannot supply additional privileges. School administration student/grading/finance/report serializers are deliberately unavailable in the Parent role; parent responses have explicit field allowlists. Existing account/profile and role-switch APIs remain available.

## Enrollment and lifecycle

Authorized school staff use the existing guardian panel's **Approve & invite** control. Issuance records explicit approval, issuer, intended email and expiry. Invitations use 256-bit random secrets, SHA-256 hashes at rest, a 48-hour expiry, single-use acceptance, row locks, and per-user/IP acceptance throttles. Resend has a database-backed one-minute cooldown and revokes old tokens. Delivery uses the existing transactional email service. Delivery must succeed before acceptance is permitted. Tokens travel in the invitation URL fragment and are removed from browser history immediately. A same-origin endpoint stores them in a host-only, HttpOnly, SameSite=Lax cookie for one hour (Secure in production), and clears the cookie on acceptance. Tokens are never shown in the card, returned to staff, or stored in local storage. Reopen the email link if the cookie expires.

`PARENT_INVITATIONS_ENABLED` defaults to false. Set it explicitly in a reviewed deployment with email configured. Development and tests do not send real invitations.

An existing user signs in and accepts with the same email as the approved invitation. Token possession after delivery verifies the contact; merely matching contact text does not. An invitation holder without an account follows an email-first wizard. Both email verification and final account creation revalidate the delivered invitation and exact invited email. Registration validates the password, creates only the shared account, and sends an account-creation confirmation through the existing email service when delivery is enabled. Registration does not consume the invitation or grant school access. The new user signs in and explicitly accepts afterward. If an account already exists, registration cannot reset, replace or duplicate it. Staff/platform employees retain their existing account category and credentials.

For subsequent approved relationships, staff may explicitly supply a `profile_id` to `link_verified`. That profile must already have an active verified relationship **in the same school**. No automatic name/email matching occurs. Ended access requires a fresh invitation; silently restoring a disconnected or suspended link is prohibited. Transferring a relationship to a different identity requires school review and is intentionally not an automatic operation.

Acceptance and lifecycle writes are atomic across shared/tenant schemas on the existing database connection. Changes generate tenant authorization audit events. Save/delete signals schedule index and role repair; `reconcile_parent_links` also supports retry/recovery:

```sh
python manage.py reconcile_parent_links --schema SCHOOL
python manage.py reconcile_parent_links --schema SCHOOL --apply
```

Without `--apply`, the command only reports unverified counts and repair candidates. Even with `--apply`, it never activates legacy rows. The final eligible link ending removes Parent access; other usable roles are retained. Unverified legacy parent accounts retain conservative base-role protection until reviewed. Role protection is based on authoritative verified school links, not the shared index.

Disconnect and suspension preserve students and guardian records. The legacy guardian DELETE route also disconnects portal-linked records rather than erasing them. Ordinary guardian edits cannot move an invited or previously verified relationship to another student; a new relationship must be approved.

## API (under `/api/v1/auth/parent/`)

- `GET summary/?offset=0`: safe `linked_students` objects with student, school, relationship, primary-contact flag and immutable link ID. Pages visit at most 50 indexed candidates; `next_offset` advances even when stale candidates were skipped. Empty pages may have a next page.
- `POST links/{uuid}/select/`: validates the relationship and returns its school and Parent assignment ID, auditing selection. Grants are not changed.
- `GET links/{uuid}/`: safe overview, current enrollment, latest 30 attendance records (no staff notes), latest 50 approved assessment grades, current-year fees, latest 50 verified historical report rows, and up to 30 relevant school communications. Each section respects the selected Parent role's grants. Grade/report visibility also respects the school's existing outstanding-balance policy.
- `DELETE links/{uuid}/`: voluntary disconnection in Parent context.
- `GET guardians/{uuid}/`: staff-only list of up to 50 identities already verified in visible guardian records in this school, for explicit selection.
- `POST guardians/{uuid}/`: staff-only `invite`, `suspend`, `disconnect`, or `link_verified` with an explicit verified `profile_id`. Own-scope permission never constitutes school approval.
- `POST invitations/email/`: checks the supplied email against a live delivered invitation before showing registration details. Existing accounts must sign in.
- `POST invitations/register/`: revalidates token/email and creates an account with name/password, without school roles or student links. Sends account creation confirmation; returns a delivery indicator.
- `POST invitations/accept/`: requires an authenticated account with matching email. Anonymous acceptance is rejected.

The existing password login permits an otherwise unassigned user only when credentials and a live matching-school invitation validate. This grants an authenticated session, not a school role; all school authorization remains denied until acceptance. Normal role-required login behavior is unchanged. The Next.js invitation endpoint handles the secret server-side and rejects cross-origin mutations.

Responses are private/no-store. Unknown/unrelated links return 404. Wrong school or non-Parent role returns 403. The shared index is never sufficient authorization.

## UI and visibility decisions

The portal is `/parent`, also rendered at the school home route when Parent is selected. The searchable school/student selector includes school labels, remembers selection per account, discards stale links, validates every selection server-side, cancels and clears query caches, and makes a full navigation when changing context. Requests reuse the existing authenticated API hook, including school and role headers in BFF and direct API modes. Cross-school navigation uses existing school login/session handling. A user who lands with another active role explicitly chooses **Continue as Parent**. Host-only role preferences are set on the destination school, never copied as credentials across origins.

Employee **Parent of…** indicators use only the current schema and require the viewer's guardian-view permission for each child. No cross-school information appears in employee responses.

Material assumptions:

- Staff issuance is explicit guardian approval; student-submitted contact edits cannot approve relationships.
- The approved invitation email must match the authenticated account's email. Schools must correct contact records before inviting an account under another email.
- `Grade.status=approved` is the existing published grade state; `HistoricalGradeRecord.status=verified` is the historical-report release state.
- Portal details are read-only. Legal/contact corrections go through school staff. Official transcript issuance/download stays under its existing approval workflow; the portal shows approved results and verified historical records rather than bypassing transcript controls.
- Parent communications are delivered announcements/alerts addressed to the user and either school-wide or explicitly scoped to the selected student, grade or section. Employee-only/private campaigns and administrative action URLs are excluded.
- Lists of records in the overview are deliberately bounded recent previews, not full-history exports.

## Verification

Executed locally on 2026-09-28:

- 98-test backend regression suite passed (parent lifecycle/concurrency, multiple roles, assignment rules, employee/student self-service, student filtering and grading scope).
- After final permission and photo-URL changes, all 45 focused parent/multiple-role tests passed; the additional guardian-move regression test also passed.
- All 20 targeted UI tests passed (parent dashboard/selector, active-role preferences, role switching and tenant routing).
- TypeScript, ESLint for the new parent components/helpers, Django system checks and diff whitespace checks passed. Migration generation reported no model changes; its sandboxed history check could not connect to PostgreSQL, while actual migrations and database tests succeeded with local database access.
- Desktop and 390px mobile browser checks covered the empty portal and existing-account invitation form. No invitation was submitted.

 Automated coverage includes shared identity reuse, invitation replay/expiry/contact changes, disabled/stale links, role protection, disconnection preservation, actual two-schema discovery/context isolation, viewer-scoped employee indicators, published-grade visibility, selector persistence and rejected switching. No legacy links or real invitations are activated as test setup.

Local development shared and school migrations were applied successfully. Production migrations, real email delivery, and a signed-in browser walkthrough using verified parent links across school origins require deployment verification. Browser role cookies are preferences only; all authorization remains server-side.

The invitation UI uses the shared brand wordmark and UI components in a card centered horizontally and vertically. Unsigned visitors go to the existing school sign-in page with a Create account button; the secret is not put into sign-in URLs. Account confirmation emails never contain passwords. Development delivery stays disabled and mail is mocked in tests.

### Invitation wizard verification

The follow-up email-first registration change passed 33 backend tests (`users.test_parent_portal` and `users.test_role_required_login`) and six UI/server-route tests. Coverage includes no role grant on account creation, authenticated-only acceptance, invitation-bound login and revocation, duplicate-account refusal, confirmation mail without passwords, email mismatch stopping the wizard, password confirmation, HttpOnly cookie storage and clearing, and cross-origin rejection. TypeScript, targeted ESLint and Django checks passed. The centered branded missing-link state was inspected in the local browser. Full email-to-registration browser delivery remains a deployment verification item; no real messages were sent.

### Invitation registration staff prefill

After validating a delivered, unexpired invitation and its exact email, registration looks only in the inviting school's canonical HR `Employee` table. A single active record supplies first name, last name, gender, and birth date. The form disables these fields; registration re-reads and locks the source record instead of trusting submitted copies. Duplicate email matches and existing account references require school review/sign-in. No other school's HR records are searched or disclosed.

Prefill does not attach an employee account reference or grant employee permissions. Staff portal provisioning remains school-managed; invitation acceptance grants only the approved Parent relationship. Missing staff bio values remain locked for school correction. Birth date is optional and stored on the shared User via additive migration `users.0012`; ordinary parents can enter their own bio. No existing accounts or school records are changed by this migration.

Validation for staff prefill: 25 parent backend tests passed, including cross-school lookup isolation, existing account references, ambiguous staff emails, server-enforced bio, and future birth-date rejection. Four invitation UI tests and 12 invitation BFF tests passed; TypeScript, targeted ESLint, and diff checks passed. The local shared schema is current through users.0012. The live email-to-registration flow was not exercised with a real invitation.
