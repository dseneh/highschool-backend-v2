# Multiple school roles

A global user has one `TenantMembership` per school schema and multiple
`TenantRoleAssignment` records. A database constraint makes each role unique
within the membership. System role keys unify legacy local system roles and
shared system roles; assigning either representation twice is idempotent.

The existing membership role pointer is retained as the default for older
clients. It is not a global active-role setting. New assignments are additive.
Revocation retains the assignment as inactive for history. If the default is
revoked, another usable assignment becomes the default, or membership becomes
inactive when no assignments remain.

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
category. Parent currently lands on Account; the child selector and full parent
portal are separate work. Platform/public workspace role management remains the
existing single-assignment flow; this change enables multiple roles per school.

## Protection and migration

Parent cannot be revoked manually while active guardian records in this school
reference the user's account ID. Legacy `account_type=parent` accounts also keep
their base Parent role until guardian identity migration establishes reliable
links. Student base roles are protected for legacy student accounts. Other roles
can be added to both identities. Self-assignment/revocation is prohibited, and
revoking the last school administrator is rejected.

Migrations 0004 and 0005 create assignment storage and backfill existing role
pointers without changing their active status. Apply with:

```sh
python manage.py migrate_schemas authorization --noinput
```

The future guardian-verification lifecycle should replace the legacy account-type
fallback and provide the controlled way to end Parent eligibility. This change
does not create central parent profiles or implement invitations.
