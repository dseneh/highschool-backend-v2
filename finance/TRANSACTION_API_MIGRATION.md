# Transaction API URL Migration Guide

This document maps the old APIView-based transaction endpoints to the new ModelViewSet-based endpoints.

## Overview

The transaction views have been refactored from individual `APIView` classes to a single `TransactionViewSet` using Django REST Framework's router. All endpoints are now scoped under `/schools/<school_id>/transactions/` for consistency.

---

## Endpoint Mappings

### 1. List Transactions

**Old:**
```
GET /schools/<school_id>/transactions/
```
- View: `TransactionListView.get()`
- Query params: `ordering`, plus filters via `get_transaction_queryparams()`
- Response: Paginated list of transactions

**New:**
```
GET /schools/<school_id>/transactions/
```
- ViewSet action: `TransactionViewSet.list()`
- Query params: Same as old (ordering, filters)
- Response: Paginated list of transactions (same format)
- **No change** - URL and behavior remain identical

---

### 2. Create Transaction

**Old:**
```
POST /schools/<school_id>/transactions/
```
- View: `TransactionListView.post()`
- Body: Transaction data (student, type, account, payment_method, amount, etc.)
- Response: Created transaction detail

**New:**
```
POST /schools/<school_id>/transactions/
```
- ViewSet action: `TransactionViewSet.create()`
- Body: Same as old
- Response: Same format
- **No change** - URL and behavior remain identical

---

### 3. Retrieve Transaction

**Old:**
```
GET /transactions/<id>/
```
- View: `TransactionDetailView.get()`
- ID can be: transaction `id` or `transaction_id`
- Response: Transaction detail

**New:**
```
GET /schools/<school_id>/transactions/<id>/
```
- ViewSet action: `TransactionViewSet.retrieve()`
- ID can be: transaction `id` or `transaction_id` (same as old)
- Response: Same format
- **Change**: Now requires `school_id` in URL path

---

### 4. Update Transaction

**Old:**
```
PUT /transactions/<id>/
```
- View: `TransactionDetailView.put()`
- Body: Fields to update (amount, reference, description, account, payment_method, type, notes, date, status)
- Response: Updated transaction detail
- Note: Status is automatically set to "pending" on update

**New:**
```
PUT /schools/<school_id>/transactions/<id>/
PATCH /schools/<school_id>/transactions/<id>/
```
- ViewSet actions: `TransactionViewSet.update()` or `TransactionViewSet.partial_update()`
- Body: Same fields as old
- Response: Same format
- **Change**: 
  - Now requires `school_id` in URL path
  - Supports both PUT (full update) and PATCH (partial update)

---

### 5. Delete Transaction

**Old:**
```
DELETE /transactions/<id>/
```
- View: `TransactionDetailView.delete()`
- Validation: Cannot delete approved transactions
- Response: `204 No Content`

**New:**
```
DELETE /schools/<school_id>/transactions/<id>/
```
- ViewSet action: `TransactionViewSet.destroy()`
- Validation: Same (cannot delete approved transactions)
- Response: Same (`204 No Content`)
- **Change**: Now requires `school_id` in URL path

---

### 6. Update Transaction Status

**Old:**
```
PUT /transactions/<id>/status/
```
- View: `TransactionStatusView.put()`
- Body: `{"status": "pending|approved|rejected|canceled", "notes": "optional"}`
- Response: Updated transaction detail
- Validations:
  - Cannot approve rejected/canceled transactions
  - Transaction amount cannot exceed student balance when approving

**New:**
```
PUT /schools/<school_id>/transactions/<id>/status/
```
- ViewSet action: `TransactionViewSet.set_status()`
- Body: Same as old
- Response: Same format
- Validations: Same as old
- **Change**: Now requires `school_id` in URL path

**Additional New Actions:**

```
PUT /schools/<school_id>/transactions/<id>/approve/
PUT /schools/<school_id>/transactions/<id>/cancel/
```
- ViewSet actions: `TransactionViewSet.approve()` and `TransactionViewSet.cancel()`
- These are convenience endpoints that set status to "approved" or "canceled" respectively
- Body: Optional `{"notes": "..."}`
- **New**: Dedicated endpoints for common status changes

---

### 7. Student Transaction History

**Old:**
```
GET /students/<student_id>/transactions/
```
- View: `StudentTransactionListView.get()`
- Query params:
  - `academic_year` (optional, defaults to current)
  - `status` (optional)
  - `transaction_type` (optional)
- Response: List of transactions for the student

**New:**
```
GET /schools/<school_id>/transactions/student/<student_id>/
```
- ViewSet action: `TransactionViewSet.student_transactions()`
- Query params: Same as old
- Response: Same format
- **Change**: 
  - Now requires `school_id` in URL path
  - URL pattern changed from `/students/...` to `/transactions/student/...`

---

### 8. Account-to-Account Transfer

**Old:**
```
POST /schools/<school_id>/transactions/transfer/
```
- View: `AccountToAccountTransferView.post()`
- Body: `{"from_account": "...", "to_account": "...", "amount": ..., "date": "...", "notes": "optional"}`
- Response: Array of two transactions `[transfer_out, transfer_in]`
- Creates two transactions: TRANSFER_OUT (negative) and TRANSFER_IN (positive)
- Both transactions are automatically approved

**New:**
```
POST /schools/<school_id>/transactions/account-transfer/
```
- ViewSet action: `TransactionViewSet.account_transfer()`
- Body: Same as old
- Response: Same format (array of two transactions)
- **Change**: URL path changed from `/transfer/` to `/account-transfer/`

---

### 9. Delete Transactions by Reference

**Old:**
```
DELETE /transactions/<reference_id>/transfer/
```
- View: `AccountTransactionsDetailView.delete()`
- Deletes all transactions with the given `reference`
- Response: `204 No Content`

**New:**
```
DELETE /schools/<school_id>/transactions/by-reference/<reference_id>/
```
- ViewSet action: `TransactionViewSet.delete_by_reference()`
- Behavior: Same (deletes all transactions with matching reference)
- Response: Same (`204 No Content`)
- **Change**: 
  - Now requires `school_id` in URL path
  - URL path changed from `/transactions/<reference_id>/transfer/` to `/transactions/by-reference/<reference_id>/`

---

### 10. Bulk Create Transactions

**Old:**
```
POST /schools/<school_id>/transactions/bulk/<transaction_type_id>/
```
- View: `BulkTransactionCreateView.post()`
- Body: Either `{"transactions": [...]}` or `[...]` (array at root)
- Query params: `override_existing=true` (optional, can also be in body)
- Response:
  ```json
  {
    "success": true/false,
    "data": {"transactions": [...]},
    "meta": {
      "created": 10,
      "deleted": 2,
      "total_processed": 12,
      "succeeded": 10,
      "failed": 2
    },
    "errors": [...] // if any failures
  }
  ```
- Features:
  - All transactions use the specified `transaction_type_id`
  - Validates each transaction individually
  - Continues processing even if some fail
  - Can delete existing transactions by reference if `override_existing=true`

**New:**
```
POST /schools/<school_id>/transactions/bulk/<transaction_type_id>/
```
- ViewSet action: `TransactionViewSet.bulk_create()`
- Body: Same as old
- Query params: Same as old
- Response: Same format
- **No change** - URL and behavior remain identical

---

## Summary of Changes

### URL Pattern Changes

1. **School ID Required**: Most endpoints now require `school_id` in the URL path for consistency:
   - Old: `/transactions/<id>/`
   - New: `/schools/<school_id>/transactions/<id>/`

2. **Student Transactions**: URL pattern changed:
   - Old: `/students/<student_id>/transactions/`
   - New: `/schools/<school_id>/transactions/students/<student_id>/`

3. **Account Transfer**: URL path renamed:
   - Old: `/schools/<school_id>/transactions/transfer/`
   - New: `/schools/<school_id>/transactions/account-transfer/`

4. **Delete by Reference**: URL path restructured:
   - Old: `/transactions/<reference_id>/transfer/`
   - New: `/schools/<school_id>/transactions/by-reference/<reference_id>/`

### New Features

1. **PATCH Support**: Update endpoint now supports both PUT (full update) and PATCH (partial update)

2. **Dedicated Status Actions**: New convenience endpoints:
   - `PUT /schools/<school_id>/transactions/<id>/approve/`
   - `PUT /schools/<school_id>/transactions/<id>/cancel/`

### Unchanged Endpoints

- List transactions: `/schools/<school_id>/transactions/`
- Create transaction: `/schools/<school_id>/transactions/`
- Bulk create: `/schools/<school_id>/transactions/bulk/<transaction_type_id>/`

---

## Migration Checklist

- [ ] Update frontend API client to include `school_id` in transaction detail/update/delete URLs
- [ ] Update student transaction history endpoint URL pattern
- [ ] Update account transfer endpoint URL from `/transfer/` to `/account-transfer/`
- [ ] Update delete-by-reference endpoint URL pattern
- [ ] Consider using new dedicated approve/cancel endpoints for better permission control
- [ ] Test all endpoints with new URL patterns
- [ ] Update API documentation/Swagger

---

## Permission Changes

All endpoints now use `TransactionAccessPolicy` with the following action names:
- `list`, `retrieve`, `create`, `update`, `partial_update`, `destroy`
- `set_status`, `approve`, `cancel`
- `bulk_create`, `account_transfer`, `delete_by_reference`, `student_transactions`

Special privileges map to actions:
- `TRANSACTION_CREATE` → create, bulk_create, account_transfer
- `TRANSACTION_UPDATE` → update, partial_update
- `TRANSACTION_DELETE` → destroy, delete_by_reference
- `TRANSACTION_APPROVE` → approve, set_status
- `TRANSACTION_CANCEL` → cancel, set_status


