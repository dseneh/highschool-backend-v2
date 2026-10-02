# Multiple-role smoke check — 2026-09-28

Environment: local UI at `ldtc.lvh.me:3000`; existing platform administrator session. No account or role assignments changed.

## Passed

- Desktop and 390×844 mobile account dropdown renders and fits the viewport.
- Switch role is hidden for the available platform-only account.
- Fresh navigation displayed the sidebar's `Loading navigation` / `Loading sidebar navigation…` state, followed by the full menu.
- User detail loads without the previous `revokeUserRoleForTenant` exception.
- Tenant accordion expands to show three existing assigned roles.
- Each role has a destructive X control. Revoke confirmation opens; cancel preserves all assignments.
- Add-role catalog opens and excludes the three roles already assigned.
- 19 tests passed across seven UI test files: dropdown, role dialog, workspace navigation, tenant card, users API hook, active role preference, and linked employee ID resolution.
- TypeScript `tsc --noEmit --pretty false` passed.
- 38 backend tests passed: `authorization.tests.test_multiple_roles`, `authorization.tests.test_role_assignment_rules`, `hr.tests.test_self_service`, and `students.tests.test_my_student`.

## Still requiring a linked account session

- Live switching between two assigned roles and back, including reload and resulting permission/nav changes.
- Live employee/student My Workspace navigation and editing with the user's own linked record.

These paths have automated coverage but were not verified end-to-end in the available platform-only browser session. No real user's permissions were granted or revoked for testing. Browser viewport was restored after the mobile check.

The browser console reported extension-style asynchronous listener/channel errors; no application exception was observed during the checked interactions.
