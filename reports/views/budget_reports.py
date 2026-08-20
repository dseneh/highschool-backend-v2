from uuid import UUID

from rest_framework.response import Response
from rest_framework.views import APIView

from budgeting.access_policies import BudgetAccessPolicy
from budgeting.models import Budget
from budgeting.services import build_budget_report
from reports.utils.budget_export import export_comprehensive_budget_report
from reports.utils.export_helpers import export_tabular_report, parse_date_param


class BudgetReportView(APIView):
    permission_classes = [BudgetAccessPolicy]
    report_type = None

    def _error(self, detail, status=400):
        return Response({"detail": detail}, status=status)

    def get(self, request):
        budget_id = request.query_params.get("budget_id")
        if not budget_id:
            return self._error("budget_id is required.")
        try:
            UUID(str(budget_id))
        except (TypeError, ValueError, AttributeError):
            return self._error("budget_id must be a valid UUID.")
        try:
            budget = Budget.objects.select_related(
                "academic_year", "base_currency", "submitted_by", "approved_by",
                "activated_by", "closed_by",
            ).prefetch_related(
                "sections__lines__periods", "sections__lines__gl_account",
                "enrollment_assumptions__grade_level",
                "revisions__approved_by", "revisions__line_deltas__budget_line__section",
                "lifecycle_events__actor",
            ).get(pk=budget_id)
        except Budget.DoesNotExist:
            return self._error("Budget not found.", 404)

        export_format = request.query_params.get("export")
        if export_format and export_format not in {"pdf", "xlsx"}:
            return self._error("export must be pdf or xlsx.")
        raw_start = request.query_params.get("start_date")
        raw_end = request.query_params.get("end_date")
        start_date = parse_date_param(raw_start)
        end_date = parse_date_param(raw_end)
        if raw_start and not start_date:
            return self._error("start_date must use YYYY-MM-DD format.")
        if raw_end and not end_date:
            return self._error("end_date must use YYYY-MM-DD format.")
        start_date = start_date or budget.academic_year.start_date
        end_date = end_date or budget.academic_year.end_date
        if start_date > end_date:
            return self._error("start_date must be on or before end_date.")
        if start_date < budget.academic_year.start_date or end_date > budget.academic_year.end_date:
            return self._error("Report dates must fall within the budget academic year.")

        payload = build_budget_report(budget, self.report_type, start_date, end_date)
        if export_format:
            if self.report_type == "budget-summary":
                return export_comprehensive_budget_report(
                    request,
                    payload,
                    filename_base=f"{self.report_type}-{budget.id}",
                )
            headers = [column[0] for column in payload["columns"]]
            rows = [[row.get(column[1]) for column in payload["columns"]] for row in payload["results"]]
            response = export_tabular_report(
                request,
                filename_base=f"{self.report_type}-{budget.id}",
                title=self.report_type.replace("-", " ").title(),
                subtitle=f"{payload['context'].get('academic_year', budget.academic_year)} | {start_date} to {end_date}",
                summary_rows=list(payload["summary"].items()),
                headers=headers,
                rows=rows,
            )
            if response:
                return response
        return Response(payload)
