# Multiple school roles

A global user has one `TenantMembership` per school schema and multiple
`TenantRoleAssignment` records. A database constraint makes each role unique
within the membership. System role keys unify legacy local system roles and
shared system roles; assigning either representation twice is idempotent.

The existing membership role pointer is retained as the default for older
clients. It is not a global active-role setting. New assignments are additive.
Revocation retains the assignment as inactive for history. If the default is
revoked, another usable assignment becomes the default. Revoking a user's last
usable role in a school is rejected: assign another active role first. Disabled
roles and previously revoked assignments do not count as alternatives. The API
exposes this protection to both role-management interfaces.

## API

- `GET authorization/me/roles/`: list the caller's assignments and active role.
- `POST authorization/me/roles/` with `assignment_id`: validate a selection and
  audit the switch. Return `selected_assignment_id`; clients send that value as
  `X-Role-Assignment` on subsequent requests. Selection never grants a role.
- `GET authorization/users/{id_number}/role/`: active/default role plus assignments.
  Users may read their own; reading others requires `roles.view`.
- Existing `PUT authorization/users/{id_number}/role/` with `role_id`: add a role.
- Existing bulk assignment endpoint: add the role to each selected user atomically.
- `DELETE authorization/users/{id_number}/roles/{assignment_id}/`: revoke one role.
  Assignment and revocation require `roles.assign_users`.

The user-detail tenant accordion uses `GET auth/users/{id_number}/tenants/`.
Each tenant includes `can_manage_roles`; each role includes its `assignment_id`,
`can_revoke`, and `revocation_blocked_reason`. The controls use:

- `PUT auth/users/{id_number}/tenants/{schema_name}/role/` to add a role.
- `DELETE auth/users/{id_number}/tenants/{schema_name}/roles/{assignment_id}/`
  to revoke that assignment, preserving the role definition.

Both operations require `roles.assign_users` with `all` scope in the current
school. Only an active platform superadmin context may manage another school's
roles. The API checks this independently of the UI, and existing role protections
still apply. Adding/removing tenant access remains platform-superadmin-only.

An explicit assignment is checked against the authenticated user, current school,
active membership, active assignment, and active role on every request. Selected
roles do not union permissions. A removed or disabled selected assignment fails
closed; only a new/unselected session may choose another available default.
Platform administrators may explicitly choose `platform`, or select a restricted
school role. Legacy platform privilege helpers honor that restriction.

## UI and sessions

Manage Roles lists assigned roles, adds another, and confirms individual
revocation. Switch role appears in the school user dropdown. The selected
assignment is stored in a host-only session cookie keyed by user ID and school.
This cookie is a preference, not an authorization credential. Browser requests,
the BFF, session hydration, and server prefetches forward the selection.

Switching cancels queries, clears the query cache, and navigates with a full page
load. Same-origin tabs receive a storage event and reload. Other school origins
and devices keep their own selection. Session hydration pins a default assignment
so revocation does not silently change the active role of an existing browser.

Teacher and student navigation follows the selected role rather than account
category. Parent lands on `/parent`; its verified child selector and read-only dashboard
are documented in `parent-portal-implementation.md`. Platform/public workspace role management remains the
existing single-assignment flow; this change enables multiple roles per school.

## Protection and migration

Parent cannot be revoked manually while eligible verified guardian relationships
in this school reference the shared parent profile. Legacy `account_type=parent` accounts also keep
their base Parent role until guardian identity migration establishes reliable
links. Student base roles are protected for legacy student accounts. Other roles
can be added to both identities. Self-assignment/revocation is prohibited, and
revoking the last school administrator is rejected.

Migrations 0004 and 0005 create assignment storage and backfill existing role
pointers without changing their active status. Apply with:

```sh
python manage.py migrate_schemas authorization --noinput
```

The parent-portal lifecycle now controls verification, invitation acceptance,
suspension and voluntary disconnection. It reconciles role eligibility without
deleting students or guardian records. Unverified legacy identities remain
conservative and must be reviewed rather than activated by contact matching.

## Global parent role discovery

The Parent portal reads `GET auth/parent/roles/` to discover the signed-in user's
active assignments in their active schools, including staff and Parent roles.
The response contains school and role labels, not role permissions. Parent
sessions remain restricted: discovery does not select or grant a staff role.

The account dropdown offers Switch role when another school role is available.
Selecting a school role opens that school's `/switch-role?assignment=…` page,
uses the existing school/central sign-in flow when needed, and validates the
assignment through the school's existing role-selection API before saving the
host-local preference and clearing cached data. Revoked, foreign-user, and
foreign-school assignments must be rejected by that API. Each school is labelled
in the parent role picker; Parent entries are marked current.

Automated checks cover discovery scoping, active records, parent scope isolation,
and the account dropdown. Live two-school staff-to-parent-to-staff SSO navigation
still needs verification with a linked test account.

## Staff account generation across schools

The canonical `POST /auth/users/` and `/auth/users/recreate/` flows now reuse an existing active global identity for staff records by exact, case-insensitive email. This is an explicit action by a school user with account-creation permission, not public registration or background linking across all tenants. The selected role is resolved in the current school and assigned additively using the existing role-assignment service.

An existing live `user_account_id_number` must agree with the record email. Conflicting links, ambiguous email matches, disabled accounts, disabled school memberships, reserved roles, and self-role changes are rejected. A dangling reference to a deleted account can be repaired through this authorized provisioning flow. Student records do not automatically claim a parent's/shared email account; their existing reference or legacy matching account number must establish the link.

The source record, tenant attachment, and role grant are committed atomically. Staff IDs are school-local and need not equal the shared account number; a new global account gets a distinct number when its source number is already used by an unrelated account. Existing passwords, usernames, identity categories, Parent profiles, and other-school roles remain unchanged. Existing accounts receive no new-account/default-password email. Welcome mail for genuinely new accounts is scheduled after commit.

The response includes `created` and `linked_existing`. The employee Account Info card displays “Account linked” for reuse and follows the explicit account reference for lookup, Open Account, and role management rather than guessing from the employee number.

Validation: 18 provisioning tests (including real tenant-schema tests), 7 adjacent identity-email tests, 8 frontend tests, TypeScript, and a two-school PostgreSQL rollback smoke check. The smoke verified shared identity with different school IDs, idempotent role assignment, unchanged credentials, preservation of Parent/first-school roles, and selected-role isolation. All smoke records were rolled back; email delivery was mocked. Live browser generation was not performed.

In the global Parent portal, Switch role groups active school Parent assignments into one current Parent option, with a distinct-school count. Staff roles remain individual school-specific options. The available-option count reflects the grouped presentation; backend grants and school-role selection are unchanged.
