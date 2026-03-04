transaction_types_data = [
    {
        "name": "School Fees Payment",
        "description": "Payment for school fees",
        "type_code": "TUITION",
        "type": "income",
        "is_hidden": False,
        "is_editable": False,
    },
    {
        "name": "Transfer Out",
        "description": "Transfer money to another account",
        "type": "expense",
        "type_id": "TRANSFER_OUT",
        "is_hidden": True,
        "is_editable": False,
    },
    {
        "name": "Transfer In",
        "description": "Transfer money from another account",
        "type": "income",
        "type_id": "TRANSFER_IN",
        "is_hidden": True,
        "is_editable": False,
    },
    {
        "name": "Refund Payment",
        "description": "Refund for overpayment or cancellation",
        "type": "expense",
        "type_id": "REFUND",
        "is_hidden": False,
        "is_editable": False,
    },
    {
        "name": "Donation",
        "description": "Donations made to the school",
        "type": "income",
    },
    {
        "name": "Item Purchase",
        "description": "Purchase of school items",
        "type": "expense",
    },
    {
        "name": "Staff Salary",
        "description": "Staff salary payments",
        "type": "expense",
    },
    {
        "name": "Utility Payment",
        "description": "Utility bills payment",
        "type": "expense",
    },
    {
        "name": "Other Income",
        "description": "Other types of income transactions",
        "type": "income",
    },
    {
        "name": "Other Expense",
        "description": "Other types of expense transactions",
        "type": "expense",
    },
]
