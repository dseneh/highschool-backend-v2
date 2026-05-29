from rest_framework.response import Response
from rest_framework.views import APIView

from accounting.access_policies import AccountingFinanceAccessPolicy
from accounting.serializers import AccountingSettingsSerializer
from accounting.services.settings_services import get_tenant_accounting_settings


class AccountingSettingsView(APIView):
    """Tenant accounting GL mappings for transfers and payroll posting."""

    permission_classes = [AccountingFinanceAccessPolicy]

    def get(self, request):
        settings = get_tenant_accounting_settings(user=request.user)
        return Response(AccountingSettingsSerializer(settings).data)

    def patch(self, request):
        settings = get_tenant_accounting_settings(user=request.user)
        serializer = AccountingSettingsSerializer(settings, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        settings = serializer.save(updated_by=request.user)
        settings.refresh_from_db()
        return Response(AccountingSettingsSerializer(settings).data)
