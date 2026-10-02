# User account deletion

User detail and list/bulk confirmations default to deactivation (`hard=false`).
Superadmin and the active tenant Admin role can explicitly check **Permanently
delete account (hard delete)** to request `hard=true`. The API independently
checks the actor's active role and rejects self-deletion.

Tenant administrators can delete accounts confined to their school. Accounts
with other school memberships or parent records require platform Superadmin
access. Workspace ownership must be transferred before hard deletion. Tenant
cleanup is limited to the current and public schemas, and deletion runs in a
transaction to roll back cleanup if the final database deletion fails.

Hard deletion removes the shared login and associated account data. It is
separate from disconnecting an individual parent/student relationship.
Bulk deletion retains failed selections for retry and refreshes the list after
partial success. The shared confirmation box supports optional content and
keeps asynchronous failures open.

Permission and UI tests use mocked deletion operations. PostgreSQL verification is recorded below; live browser checks remain
outstanding. No real account was deleted during implementation.


## PostgreSQL lock budget

The shared user has foreign keys in every school schema. Even a user without
records in those schools requires PostgreSQL to check those constraints on final
deletion. Configure `max_locks_per_transaction=512` and restart PostgreSQL; a
configuration reload alone is insufficient. The Docker Compose service includes
this setting. Size the budget again as the tenant count/concurrency grows.
See https://www.postgresql.org/docs/17/runtime-config-locks.html.

Cleanup probes run in rolled-back savepoints to release their read locks and
skip empty tables. Shared tables are handled once in public, and cleanup errors
propagate to roll back the deletion. The UI performs bulk deletions sequentially.

Local PostgreSQL 17 validation: reproduced exhaustion at 64, then verified a
rolled-back disposable-account deletion at 512 with a school membership and role
assignment. All deferred constraints were forced before rollback; the completed
delete held approximately 14,945 locks. No existing user was deleted. Ten focused
permission/lock regression tests pass. Live UI deletion remains unverified.

## Disconnected memberships

A school membership can remain after the shared account's school-access link is
removed. Catalog cleanup must use ORM deletion for known non-null references in
the referencing schema, so dependent role assignments are removed before their
membership. Raw SQL deletion of the membership alone violates its assignment FK.

Validated with an inactive disposable user with no school-access link but a
school membership, role assignment, and legacy school permissions. Hard deletion
and deferred FK checks passed, and all test writes were rolled back. Eleven
focused regression tests pass. The reported existing account was not modified.

### Stale source account indicators

Hard deletion also clears `user_account_id_number` references in school person
records, including records whose account membership was already disconnected.
This cleanup runs in the deletion transaction and preserves employees, staff,
students, and school guardian history. Tenant-admin cleanup stays within its
permitted schema; platform deletion can clean cross-school references. Read-only
probes release locks before updating matching rows.

Employee serialization checks that the referenced shared account still exists;
legacy dangling references are returned as null. Account-picker filters check
actual shared user IDs, rather than just a nonempty reference. Inactive accounts
that still exist remain distinguishable from permanently deleted accounts.
The UI invalidates user, employee, staff, and student caches after deletion.
Missing user detail requests now show a destructive error with back/retry controls,
even when stale detail data was previously cached.

Verification: the rollback-only PostgreSQL hard-delete smoke test passed with a
disposable employee and a disconnected tenant membership. The employee survived,
its account reference became null, and the no-account picker included it. All test
writes were rolled back. Focused backend regression tests and UI mutation/detail
page tests cover missing references, cache invalidation, and the 404 error state.
