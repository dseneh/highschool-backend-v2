from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from accounting.access_policies import AccountingFinanceAccessPolicy
from accounting.models import AccountingBankBalanceRule, AccountingSpendableAllocationRule
from accounting.serializers import (
    AccountingBankBalanceRuleSerializer,
    AccountingRuleEmailPreviewSerializer,
    AccountingSpendableAllocationRuleSerializer,
)
from accounting.services.bank_rules import default_email_template


class AccountingBankBalanceRuleViewSet(viewsets.ModelViewSet):
    queryset = AccountingBankBalanceRule.objects.prefetch_related(
        "bank_accounts",
        "alert_recipients",
    ).order_by("name")
    serializer_class = AccountingBankBalanceRuleSerializer
    permission_classes = [AccountingFinanceAccessPolicy]
    pagination_class = None

    @action(detail=False, methods=["get"], url_path="default-template")
    def default_template(self, _request):
        return Response(default_email_template(), status=status.HTTP_200_OK)

    @action(detail=False, methods=["post"], url_path="preview-template")
    def preview_template(self, request):
        serializer = AccountingRuleEmailPreviewSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        return Response(serializer.render_preview(), status=status.HTTP_200_OK)

    @action(detail=True, methods=["post"], url_path="restore-default-template")
    def restore_default_template(self, _request, pk=None):
        rule = self.get_object()
        defaults = default_email_template()
        rule.use_default_email_template = True
        rule.email_subject_template = defaults["subject"]
        rule.email_body_template = defaults["body"]
        rule.save(
            update_fields=[
                "use_default_email_template",
                "email_subject_template",
                "email_body_template",
                "updated_at",
            ]
        )
        return Response(self.get_serializer(rule).data, status=status.HTTP_200_OK)


class AccountingSpendableAllocationRuleViewSet(viewsets.ModelViewSet):
    queryset = AccountingSpendableAllocationRule.objects.order_by("-updated_at")
    serializer_class = AccountingSpendableAllocationRuleSerializer
    permission_classes = [AccountingFinanceAccessPolicy]
    pagination_class = None
