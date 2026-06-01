from .models import BenefitSettings


def get_tenant_benefit_settings() -> BenefitSettings:
    settings = BenefitSettings.objects.select_related(
        "transaction_type",
        "transaction_type__default_ledger_account",
        "transaction_type__managed_ledger_account",
    ).first()
    if settings is None:
        settings = BenefitSettings.objects.create()
    return settings
