from django.core.exceptions import ValidationError
from django.db.models import DecimalField, Sum, Value
from django.db.models.functions import Coalesce
from django.db import transaction
from datetime import date
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.parsers import MultiPartParser, FormParser
from rest_framework.response import Response

from accounting.access_policies import AccountingFinanceAccessPolicy
from accounting.models import (
    AccountingBankAccount,
    AccountingCurrency,
    AccountingExchangeRate,
    AccountingJournalEntry,
    AccountingJournalLine,
    AccountingLedgerAccount,
    AccountingTransactionType,
)
from accounting.services import sync_transaction_type_for_ledger_account
from accounting.services.journal_list_filters import apply_journal_entry_list_filters
from accounting.services.journal_summary import build_journal_entry_list_summary
from accounting.serializers import (
    AccountingCurrencySerializer,
    AccountingExchangeRateSerializer,
    AccountingJournalEntryDetailSerializer,
    AccountingJournalEntryListSerializer,
    AccountingJournalEntrySerializer,
    AccountingJournalLineSerializer,
    AccountingLedgerAccountSerializer,
    AccountingTransactionTypeSerializer,
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

    @action(detail=False, methods=["get"], url_path="lookup")
    def lookup(self, request):
        from accounting.services.currency_totals import (
            get_tenant_base_currency,
            resolve_exchange_rate_for_entry,
        )

        from_currency_id = request.query_params.get("from_currency")
        to_currency_id = request.query_params.get("to_currency")
        as_of_raw = request.query_params.get("as_of")
        bank_account_id = request.query_params.get("bank_account_id")

        if not from_currency_id:
            return Response(
                {"detail": "from_currency is required."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        from_currency = AccountingCurrency.objects.filter(pk=from_currency_id).first()
        if from_currency is None:
            return Response(
                {"detail": "from_currency not found."},
                status=status.HTTP_404_NOT_FOUND,
            )

        to_currency = None
        if to_currency_id:
            to_currency = AccountingCurrency.objects.filter(pk=to_currency_id).first()
            if to_currency is None:
                return Response(
                    {"detail": "to_currency not found."},
                    status=status.HTTP_404_NOT_FOUND,
                )
        else:
            to_currency = get_tenant_base_currency()

        as_of = None
        if as_of_raw:
            try:
                as_of = date.fromisoformat(str(as_of_raw).strip())
            except ValueError:
                return Response(
                    {"detail": "as_of must be a valid ISO date (YYYY-MM-DD)."},
                    status=status.HTTP_400_BAD_REQUEST,
                )

        payload = resolve_exchange_rate_for_entry(
            from_currency=from_currency,
            to_currency=to_currency,
            as_of=as_of,
            bank_account_id=bank_account_id or None,
        )
        return Response(payload)


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

    @action(detail=True, methods=["post"], url_path="sync-transaction-type")
    def sync_transaction_type(self, request, pk=None):
        account = self.get_object()
        try:
            result = sync_transaction_type_for_ledger_account(
                account,
                transaction_type_code=request.data.get("code"),
                transaction_type_name=request.data.get("name"),
                transaction_category=request.data.get("transaction_category"),
            )
        except ValidationError as exc:
            payload = exc.message_dict if hasattr(exc, "message_dict") else {"detail": exc.messages}
            return Response(payload, status=status.HTTP_400_BAD_REQUEST)

        transaction_type = None
        if result.transaction_type_id is not None:
            transaction_type = AccountingTransactionType.objects.filter(
                pk=result.transaction_type_id
            ).first()

        serialized = (
            AccountingTransactionTypeSerializer(transaction_type).data
            if transaction_type is not None
            else None
        )
        return Response(
            {
                "result": result.to_dict(),
                "transaction_type": serialized,
            },
            status=status.HTTP_200_OK,
        )


def _build_bank_by_ledger_map():
    return {
        str(row["ledger_account_id"]): row["account_name"]
        for row in AccountingBankAccount.objects.filter(ledger_account_id__isnull=False).values(
            "ledger_account_id", "account_name"
        )
    }


def _entry_bank_accounts(entry, bank_by_ledger):
    ledger_ids = {line.ledger_account_id for line in entry.lines.all()}
    names = sorted(
        {
            bank_by_ledger[str(ledger_id)]
            for ledger_id in ledger_ids
            if str(ledger_id) in bank_by_ledger
        }
    )
    return ", ".join(names)


def _entry_total_base_debit(entry):
    total = 0
    for line in entry.lines.all():
        if line.debit_amount:
            total += float(line.base_amount or 0)
    return total


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
        .order_by("-updated_at", "-created_at")
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

    def _serializer_context_with_bank_map(self):
        context = self.get_serializer_context()
        if "bank_by_ledger" not in context:
            context = {**context, "bank_by_ledger": _build_bank_by_ledger_map()}
        return context

    def list(self, request, *args, **kwargs):
        queryset = self.filter_queryset(self.get_queryset())
        summary = build_journal_entry_list_summary(queryset, request.query_params)
        serializer_context = self._serializer_context_with_bank_map()

        page = self.paginate_queryset(queryset)
        if page is not None:
            serializer = self.get_serializer(page, many=True, context=serializer_context)
            paginated = self.get_paginated_response(serializer.data)
            paginated.data["summary"] = summary
            return paginated

        serializer = self.get_serializer(queryset, many=True, context=serializer_context)
        return Response({"results": serializer.data, "count": queryset.count(), "summary": summary})

    def get_queryset(self):
        queryset = super().get_queryset()
        return apply_journal_entry_list_filters(queryset, self.request.query_params)

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

    _JOURNAL_SOURCE_LABELS = dict(AccountingJournalEntry._meta.get_field("source").choices)
    _JOURNAL_STATUS_LABELS = dict(AccountingJournalEntry._meta.get_field("status").choices)

    _EXPORT_COLUMNS = {
        "posting_date": ("Date", lambda e, _: str(e.posting_date) if e.posting_date else ""),
        "reference_number": ("Reference", lambda e, _: e.reference_number or ""),
        "description": ("Description", lambda e, _: e.description or ""),
        "source": (
            "Source",
            lambda e, ctx: ctx["source_labels"].get(e.source, e.source or ""),
        ),
        "source_reference": ("Source Reference", lambda e, _: e.source_reference or ""),
        "bank_account": ("Bank Account", lambda e, ctx: _entry_bank_accounts(e, ctx["bank_by_ledger"])),
        "total_debit": (
            "Total Debit",
            lambda e, _: float(getattr(e, "total_debit_amount", 0) or 0),
        ),
        "total_credit": (
            "Total Credit",
            lambda e, _: float(getattr(e, "total_credit_amount", 0) or 0),
        ),
        "total_base_amount": ("Total Base Amount", lambda e, _: _entry_total_base_debit(e)),
        "status": (
            "Status",
            lambda e, ctx: ctx["status_labels"].get(e.status, e.status or ""),
        ),
        "academic_year": (
            "Academic Year",
            lambda e, _: e.academic_year.name if e.academic_year else "",
        ),
        "posted_by": ("Posted By", lambda e, _: e.posted_by or ""),
        "posted_at": (
            "Posted At",
            lambda e, _: e.posted_at.strftime("%Y-%m-%d %H:%M") if e.posted_at else "",
        ),
        "reversal_of": (
            "Reversal Of",
            lambda e, _: e.reversal_of.reference_number if e.reversal_of else "",
        ),
        "created_at": (
            "Created At",
            lambda e, _: e.created_at.strftime("%Y-%m-%d %H:%M") if e.created_at else "",
        ),
        "updated_at": (
            "Updated At",
            lambda e, _: e.updated_at.strftime("%Y-%m-%d %H:%M") if e.updated_at else "",
        ),
    }

    _DEFAULT_EXPORT_COLUMNS = [
        "posting_date",
        "reference_number",
        "description",
        "source",
        "source_reference",
        "bank_account",
        "total_debit",
        "total_credit",
        "status",
    ]

    @action(detail=False, methods=["get"], url_path="export")
    def export_entries(self, request):
        from common.file_generators import FileGenerator, FileGeneratorConfig

        file_format = request.query_params.get("file_format", "csv")
        if file_format not in ("csv", "excel"):
            return Response(
                {"detail": "file_format must be 'csv' or 'excel'"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        columns_param = request.query_params.get("columns")
        if columns_param:
            col_keys = [column for column in columns_param.split(",") if column in self._EXPORT_COLUMNS]
        else:
            col_keys = self._DEFAULT_EXPORT_COLUMNS

        if not col_keys:
            return Response(
                {"detail": "No valid columns specified"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        queryset = self.get_queryset()
        bank_by_ledger = _build_bank_by_ledger_map()
        export_context = {
            "bank_by_ledger": bank_by_ledger,
            "source_labels": self._JOURNAL_SOURCE_LABELS,
            "status_labels": self._JOURNAL_STATUS_LABELS,
        }

        headers = [self._EXPORT_COLUMNS[key][0] for key in col_keys]
        extractors = [self._EXPORT_COLUMNS[key][1] for key in col_keys]

        data = []
        iterator_kwargs = (
            {"chunk_size": 2000}
            if getattr(queryset, "_prefetch_related_lookups", None)
            else {}
        )
        for entry in queryset.iterator(**iterator_kwargs):
            row = {}
            for key, extractor in zip(col_keys, extractors):
                row[key] = extractor(entry, export_context)
            data.append(row)

        metadata = {}
        start_date = request.query_params.get("start_date")
        end_date = request.query_params.get("end_date")
        if start_date:
            metadata["From"] = start_date
        if end_date:
            metadata["To"] = end_date
        status_param = request.query_params.get("status")
        if status_param:
            metadata["Status"] = status_param
        source_param = request.query_params.get("source")
        if source_param:
            metadata["Source"] = source_param

        config = FileGeneratorConfig(
            title="Journal Entries",
            filename_prefix="journal_entries",
            headers=headers,
            metadata=metadata,
        )

        return FileGenerator.generate_file(
            data=data,
            config=config,
            file_format=file_format,
        )

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
