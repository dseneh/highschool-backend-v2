# Employee lookup for creation

The employee creation wizard has a search icon beside its close button. It opens the reusable DialogBox, lists authorized source schools, validates an exact email with Zod, and presents a preview. Choosing **Use these details** replaces the draft's personal/contact fields and returns the wizard to the personal step. The user still reviews and submits the normal creation form. Closing either dialog cancels pending lookup requests; no employee is created by a lookup.

## Authorization and assumptions

- Destination access requires `employees.create` with `all` scope in the current active role.
- Sources are other active, non-maintenance schools in the caller's tenant memberships. A currently active platform-superadmin context can see all eligible schools.
- A source must grant `employees.view:all`. The source's default active assignment (the existing role resolver's normal fallback when needed) is checked individually. Grants from multiple assignments are never combined. A platform user operating in a tenant role is not promoted to platform access during lookup.
- Source authorization is checked again on every lookup. Membership and assignment references are not accepted from the browser. The existing request authorization object is not rebound across schemas.
- Exact case-insensitive email matching is performed only inside the authorized source schema. Zero or multiple matches return an error; no arbitrary record is chosen.

## API and data

- `GET /api/v1/employees/lookup-sources/` returns source school IDs and names.
- `POST /api/v1/employees/lookup-profile/` accepts `tenant_id` and `email`.
- The response explicitly includes names, email, phone, gender, birth details, and address fields. It excludes account references, employee IDs, payroll/bank data, departments, positions, and role grants. Importing details does not establish an identity link or grant access.
- Both endpoints use normal authenticated throttles plus the standard discovery (`public_search`) rate limit. Successful responses have `Cache-Control: no-store`; email is sent in the POST body, not a URL.
- No migration, email, source-record update, or account provisioning is part of this feature.

## Verification

Backend unit tests cover destination permission denial, source denial/revocation, filtered source results, input validation, exact email matching, ambiguous matches, field restrictions, and isolated source-role evaluation. Frontend tests cover validation, explicit review, destructive errors, and aborting requests on close. Live browser and real multi-schema integration verification remain to be performed.
