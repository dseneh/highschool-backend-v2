"""
Defaults app for creating default tenant data.

This app contains functions to create default data for a tenant when it's first created.
The data is imported from the data/ folder and includes:
- Academic years
- Semesters  
- Divisions
- Grade levels
- Subjects
- Periods
- And more...

Note: Finance models (Currency, PaymentMethod, TransactionType, Fee, SectionFee)
will be initialized when the finance app is migrated to backend-v2.

Usage:
    from defaults import setup_tenant_defaults
    
    # After creating a tenant
    success = setup_tenant_defaults(tenant_instance, user_instance)
    
    # Or use the lower-level function
    from defaults.run import run_data_creation
    run_data_creation(tenant_instance, user_instance)
"""

from .run import run_data_creation
from .utils import get_default_data_info, setup_tenant_defaults

__all__ = ["run_data_creation", "setup_tenant_defaults", "get_default_data_info"]
