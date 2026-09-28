# Parent portal foundation

Status: implementation plan; parent portal endpoints and screens are not yet implemented.

## Existing foundation

- `users` and `core` are shared apps; `students` and `authorization` are tenant apps (`api/settings/base.py`).
- `students.StudentGuardian` currently stores one school's student relationship and contact information. Its optional `user_account_id_number` references the shared account without a cross-schema foreign key.
- Guardian creation currently records contact information only. It does not verify ownership, invite an account, or create a shared parent profile.
- Multiple roles already support school-specific Parent grants and protect removal when guardian links exist. Legacy parent accounts also retain protection pending migration.

## Identity and relationships

Introduce a shared ParentProfile with a unique link to the existing User. An employee, platform employee, or parent uses the same User and credentials. Do not change account_type or create another login when adding Parent access.

Keep StudentGuardian in each school as the authoritative relationship record. Add a reference to the shared profile plus explicit portal-link state, verification metadata, and suspension/revocation timestamps. Relationship, primary-contact designation, school notes, and school-managed contact information remain school-specific.

Add a shared link index keyed by parent profile, tenant, and guardian UUID. Enforce uniqueness for that tuple. This index supports cross-school discovery without scanning every school. It is not sufficient authorization: every student request must recheck the active relationship in the target school. Deleted, suspended, disabled-school, or stale links must fail closed.

Use immutable UUIDs for references. Student ID numbers and names are display fields and can repeat between schools. Maintain existing account references during an additive migration; do not merge existing people by name or by an unverified email address.

## Enrollment and invitations

1. Authorized school staff record a guardian using the existing guardian-management permission. Student-submitted changes can request review but cannot grant portal access.
2. Issue a single-use, expiring invitation tied to that guardian relationship and intended verified contact. Store the token hash, issuer, expiry, and acceptance audit data; limit resend and acceptance attempts.
3. An existing account signs in and proves it owns the intended contact. A new account can register only through a valid invitation. Never disclose account existence in public responses.
4. Acceptance creates or reuses ParentProfile, activates the relationship, updates the shared index, and idempotently grants the school's Parent role. Use one database transaction where possible and a retryable reconciliation process for multi-step provisioning.
5. Once a school has established a verified identity link, later approved student links can attach automatically to that profile. Matching contact text alone does not authorize linking.

## Parent API and student selector

Provide an authenticated parent summary endpoint with an explicit safe serializer. Suggested response:

```json
{
  "id": "parent-profile-uuid",
  "linked_students": [
    {
      "link_id": "link-uuid",
      "student": {
        "id": "student-uuid",
        "id_number": "20001",
        "display_name": "Example Student",
        "photo": null
      },
      "school": {
        "id": "tenant-uuid",
        "schema_name": "school-a",
        "name": "Example School"
      },
      "relationship": "mother",
      "is_primary": true
    }
  ]
}
```

Only return verified, authorized links. Do not include guardian notes, other guardians' private contact details, employee data, or full student records in the selector payload. Define pagination before enabling large lists.

Group the selector by school. Switching students selects both school and student context, validates membership/Parent role with the server, clears school-specific cached data, and loads the selected student's overview. Persist selection per account, and discard it when the link is no longer valid. Do not carry employee/platform privileges into Parent requests or union role permissions.

## Permissions and unlinking

Parent pages expose linked-student overview, permitted personal details, attendance, published grades/reports, fees, and school communications. Define field-level visibility and editable fields before reusing school administration serializers. Every endpoint must reject unrelated student IDs, including IDs supplied in filters and nested routes.

Parent removal means disconnecting portal access or requesting school review; it must not delete the student or silently erase the school's guardian record. Distinguish voluntary disconnection from school suspension and legal relationship changes. Preserve audit history. Prevent independent Parent-role revocation while eligible links remain; reconcile the role after the last authorized link ends, accounting for legacy protected accounts.

The employee “Parent of…” indicator is resolved within the current school only, and only for viewers authorized to see the relationship. It must never reveal children or schools from the shared cross-school selector.

## Delivery sequence and acceptance checks

1. Shared profile, link lifecycle/index, additive migrations, and reconciliation. Test uniqueness, existing employee account reuse, and conservative legacy backfill.
2. Invitation acceptance and guardian administration integration. Test expired/replayed/wrong-account tokens and concurrent acceptance; no email delivery during automated tests.
3. Parent summary endpoint and server authorization. Test multiple schools, unrelated students, stale links, disabled tenants, and role-context isolation.
4. Dedicated Parent navigation, school/student selector, overview, and approved student detail sections. Test empty/loading/error states, reload persistence, and mobile layout.
5. Controlled disconnect, automatic role reconciliation, school-local employee badges, and end-to-end tests across two schools.

Before migrating legacy data, report ambiguous/unverified links for review. Do not activate all existing guardian contacts automatically.
