from django.db.models import DecimalField, Sum, Value
from django.db.models.functions import Coalesce
from django.db import transaction
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.parsers import MultiPartParser, FormParser
from rest_framework.response import Response

from accounting.access_policies import AccountingFinanceAccessPolicy
from accounting.models import (
    AccountingCurrency,
    AccountingExchangeRate,
    AccountingJournalEntry,
    AccountingJournalLine,
    AccountingLedgerAccount,
)
from accounting.serializers import (
    AccountingCurrencySerializer,
    AccountingExchangeRateSerializer,
    AccountingJournalEntryDetailSerializer,
    AccountingJournalEntryListSerializer,
    AccountingJournalEntrySerializer,
    AccountingJournalLineSerializer,
    AccountingLedgerAccountSerializer,
)
from accounting.views.base import AccountingErrorFormattingMixin


class AccountingCurrencyViewSet(AccountingErrorFormattingMixin, viewsets.ModelViewSet):
    queryset = AccountingCurrency.objects.order_by("-is_base_currency", "code")
    serializer_class = AccountingCurrencySerializer
    permission_classes = [AccountingFinanceAccessPolicy]
    pagination_class = None


class AccountingExchangeRateViewSet(AccountingErrorFormattingMixin, viewsets.ModelViewSet):
    queryset = AccountingExchangeRate.objects.select_related("from_currency", "to_currency").order_by("-effective_date")
    serializer_class = AccountingExchangeRateSerializer
    permission_classes = [AccountingFinanceAccessPolicy]
    pagination_class = None


class AccountingLedgerAccountViewSet(AccountingErrorFormattingMixin, viewsets.ModelViewSet):
    queryset = AccountingLedgerAccount.objects.select_related("parent_account").order_by("code")
    serializer_class = AccountingLedgerAccountSerializer
    permission_classes = [AccountingFinanceAccessPolicy]
    pagination_class = None

    def _should_delete_children(self):
        raw = (self.request.query_params.get("delete_children") or "").strip().lower()
        return raw in {"1", "true", "yes", "on"}

    def _collect_descendant_ids(self, root_id):
        descendant_ids = []
        frontier = [root_id]

        while frontier:
            child_ids = list(
                AccountingLedgerAccount.objects.filter(parent_account_id__in=frontier).values_list("id", flat=True)
            )
            if not child_ids:
                break

            descendant_ids.extend(child_ids)
            frontier = child_ids

        return descendant_ids

    def destroy(self, request, *args, **kwargs):
        instance = self.get_object()
        if instance.is_system_managed:
            return Response(
                {
                    "detail": (
                        "This chart-of-accounts entry is system-managed and cannot be deleted."
                    )
                },
                status=status.HTTP_400_BAD_REQUEST,
            )
        delete_children = self._should_delete_children()

        with transaction.atomic():
            if delete_children:
                descendant_ids = self._collect_descendant_ids(instance.id)
                if descendant_ids:
                    AccountingLedgerAccount.objects.filter(id__in=descendant_ids).delete()

            self.perform_destroy(instance)

        return Response(status=status.HTTP_204_NO_CONTENT)

    @action(detail=False, methods=["post"], url_path="bulk-upload", parser_classes=[MultiPartParser, FormParser])
    def bulk_upload(self, request):
        from accounting.services.bulk_upload import bulk_upload_ledger_accounts

        uploaded_file = request.FILES.get("file")
        if not uploaded_file:
            return Response({"detail": "No file provided."}, status=status.HTTP_400_BAD_REQUEST)

        replace_existing = str(request.data.get("replace_existing", "false")).lower() in ("true", "1")

        try:
            result = bulk_upload_ledger_accounts(uploaded_file, replace_existing=replace_existing)
            return Response(result, status=status.HTTP_200_OK)
        except ValueError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        except Exception as exc:
            return Response({"detail": f"Upload failed: {str(exc)}"}, status=status.HTTP_400_BAD_REQUEST)


class AccountingJournalEntryViewSet(AccountingErrorFormattingMixin, viewsets.ModelViewSet):
    queryset = (
        AccountingJournalEntry.objects.select_related("academic_year", "reversal_of")
        .prefetch_related("lines__ledger_account", "lines__currency")
        .annotate(
            total_debit_amount=Coalesce(
                Sum("lines__debit_amount"),
                Value(0),
                output_field=DecimalField(max_digits=18, decimal_places=2),
            ),
            total_credit_amount=Coalesce(
                Sum("lines__credit_amount"),
                Value(0),
                output_field=DecimalField(max_digits=18, decimal_places=2),
            ),
        )
        .order_by("-posting_date", "-created_at")
    )
    serializer_class = AccountingJournalEntrySerializer
    permission_classes = [AccountingFinanceAccessPolicy]
    pagination_class = None

    def get_serializer_class(self):
        if self.action == "list":
            return AccountingJournalEntryListSerializer
        if self.action == "retrieve":
            return AccountingJournalEntryDetailSerializer
        return AccountingJournalEntrySerializer

    def get_queryset(self):
        queryset = super().get_queryset()
        status_param = self.request.query_params.get("status")
        source = self.request.query_params.get("source")
        academic_year = self.request.query_params.get("academic_year")
        start_date = self.request.query_params.get("start_date")
        end_date = self.request.query_params.get("end_date")

        if status_param:
            queryset = queryset.filter(status=status_param)
        if source:
            queryset = queryset.filter(source=source)
        if academic_year:
            queryset = queryset.filter(academic_year_id=academic_year)
        if start_date:
            queryset = queryset.filter(posting_date__gte=start_date)
        if end_date:
            queryset = queryset.filter(posting_date__lte=end_date)

        return queryset

    def _validate_mutable(self, journal_entry):
        immutable_statuses = {
            AccountingJournalEntry.EntryStatus.POSTED,
            AccountingJournalEntry.EntryStatus.REVERSED,
        }
        if journal_entry.status in immutable_statuses:
            return Response(
                {
                    "detail": (
                        "Posted or reversed journal entries are immutable. "
                        "Create a reversing/correcting entry instead."
                    )
                },
                status=status.HTTP_400_BAD_REQUEST,
            )
        return None

    def update(self, request, *args, **kwargs):
        instance = self.get_object()
        error_response = self._validate_mutable(instance)
        if error_response:
            return error_response
        return super().update(request, *args, **kwargs)

    def partial_update(self, request, *args, **kwargs):
        instance = self.get_object()
        error_response = self._validate_mutable(instance)
        if error_response:
            return error_response
        return super().partial_update(request, *args, **kwargs)

    def destroy(self, request, *args, **kwargs):
        instance = self.get_object()
        error_response = self._validate_mutable(instance)
        if error_response:
            return error_response
        return super().destroy(request, *args, **kwargs)

    @action(detail=False, methods=["post"], url_path="bulk-upload", parser_classes=[MultiPartParser, FormParser])
    def bulk_upload(self, request):
        from accounting.services.bulk_upload import bulk_upload_journal_entries

        uploaded_file = request.FILES.get("file")
        if not uploaded_file:
            return Response({"detail": "No file provided."}, status=status.HTTP_400_BAD_REQUEST)

        replace_existing = str(request.data.get("replace_existing", "false")).lower() in ("true", "1")

        try:
            result = bulk_upload_journal_entries(uploaded_file, replace_existing=replace_existing)
            return Response(result, status=status.HTTP_200_OK)
        except ValueError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        except Exception as exc:
            return Response({"detail": f"Upload failed: {str(exc)}"}, status=status.HTTP_400_BAD_REQUEST)


class AccountingJournalLineViewSet(AccountingErrorFormattingMixin, viewsets.ModelViewSet):
    queryset = AccountingJournalLine.objects.select_related("journal_entry", "ledger_account", "currency").order_by("journal_entry", "line_sequence")
    serializer_class = AccountingJournalLineSerializer
    permission_classes = [AccountingFinanceAccessPolicy]

    def _validate_parent_entry_mutable(self, journal_line):
        parent_status = journal_line.journal_entry.status
        immutable_statuses = {
            AccountingJournalEntry.EntryStatus.POSTED,
            AccountingJournalEntry.EntryStatus.REVERSED,
        }
        if parent_status in immutable_statuses:
            return Response(
                {
                    "detail": (
                        "Journal lines cannot be changed when the parent journal entry is posted or reversed."
                    )
                },
                status=status.HTTP_400_BAD_REQUEST,
            )
        return None

    def update(self, request, *args, **kwargs):
        instance = self.get_object()
        error_response = self._validate_parent_entry_mutable(instance)
        if error_response:
            return error_response
        return super().update(request, *args, **kwargs)

    def partial_update(self, request, *args, **kwargs):
        instance = self.get_object()
        error_response = self._validate_parent_entry_mutable(instance)
        if error_response:
            return error_response
        return super().partial_update(request, *args, **kwargs)

    def destroy(self, request, *args, **kwargs):
        instance = self.get_object()
        error_response = self._validate_parent_entry_mutable(instance)
        if error_response:
            return error_response
        return super().destroy(request, *args, **kwargs)
