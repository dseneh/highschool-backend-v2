"""Student report download endpoints."""

import csv
import json
from datetime import datetime
from io import BytesIO

from django.db.models import Case, DecimalField, ExpressionWrapper, F, FloatField, OuterRef, Q, Subquery, Sum, Value, When
from django.db.models.functions import Coalesce
from django.http import HttpResponse
from openpyxl import Workbook
from openpyxl.styles import Font
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView

from academics.models import AcademicYear
from business.students.services import student_service
from common.filter import get_student_queryparams
from common.utils import get_enrollment_bill_summary
from finance.models import Transaction
from grading.services.ranking import RankingService
from students.models import Enrollment, Student, StudentEnrollmentBill
from students.serializers import StudentDetailSerializer, StudentSerializer

from ..access_policies import ReportsAccessPolicy
from ..settings import get_reports_setting
from ..tasks import TaskManager, MockTaskProcessor


def _to_bool(value, default=False):
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in ("true", "1", "yes", "on")


def _resolve_student(student_id: str):
    lookup = Q(id=student_id) | Q(id_number=student_id) | Q(prev_id_number=student_id)
    return Student.objects.filter(lookup).first()


def _resolve_academic_year(academic_year_id: str | None):
    if academic_year_id:
        return AcademicYear.objects.filter(id=academic_year_id).first()
    return AcademicYear.objects.filter(current=True).first()


def _build_export_headers(include_billing=False, show_rank=False, show_grade_average=False):
    headers = [
        "ID Number",
        "Full Name",
        "Gender",
        "Status",
        "Grade Level",
        "Section",
        "Email",
        "Phone",
        "Balance",
        "Entry Date",
    ]

    if show_grade_average:
        headers.append("Grade Average")
    if show_rank:
        headers.append("Rank")
    if include_billing:
        headers.extend(
            [
                "Tuition",
                "Total Fees",
                "Concession",
                "Total Bill",
                "Amount Paid",
                "Billing Balance",
            ]
        )

    return headers


def _build_list_export_rows(
    rows,
    include_billing=False,
    show_rank=False,
    show_grade_average=False,
):
    export_rows = []
    for row in rows:
        current_enrollment = row.get("current_enrollment") or {}
        section_data = current_enrollment.get("section") or {}
        grade_data = row.get("current_grade_level") or row.get("grade_level") or {}
        billing_summary = current_enrollment.get("billing_summary") or {}
        export_row = [
            row.get("id_number", ""),
            row.get("full_name", ""),
            row.get("gender", ""),
            row.get("status", ""),
            grade_data.get("name", ""),
            section_data.get("name", ""),
            row.get("email", ""),
            row.get("phone_number", ""),
            row.get("balance", ""),
            row.get("entry_date", ""),
        ]

        if show_grade_average:
            export_row.append(row.get("grade_average", ""))
        if show_rank:
            export_row.append(row.get("rank", ""))
        if include_billing:
            export_row.extend(
                [
                    billing_summary.get("tuition", ""),
                    billing_summary.get("total_fees", ""),
                    billing_summary.get("total_concession", ""),
                    billing_summary.get("total_bill", ""),
                    billing_summary.get("paid", ""),
                    billing_summary.get("balance", ""),
                ]
            )

        export_rows.append(export_row)

    return export_rows


def _build_ranking_lookup(request, students, academic_year):
    if not academic_year:
        return {}

    section_param = (request.query_params.get("section") or "").strip()
    grade_param = (request.query_params.get("grade_level") or "").strip()

    section_values = [value.strip() for value in section_param.split(",") if value.strip()]
    grade_values = [value.strip() for value in grade_param.split(",") if value.strip()]

    scope_type = None
    scope_id = None

    if len(section_values) == 1:
        scope_type = "section"
        scope_id = section_values[0]
    elif len(grade_values) == 1:
        scope_type = "grade_level"
        scope_id = grade_values[0]

    if scope_type and scope_id:
        try:
            ranking_rows = RankingService.get_overall_rankings(
                academic_year_id=str(academic_year.id),
                scope_type=scope_type,
                scope_id=scope_id,
            )
            return {
                str(row["student"].id): {
                    "score": row.get("score"),
                    "rank": row.get("rank"),
                }
                for row in ranking_rows
                if row.get("student") is not None
            }
        except Exception:
            return {}

    ranking_lookup = {}
    try:
        for student in students:
            current_enrollment = next(
                (
                    enrollment
                    for enrollment in student.enrollments.all()
                    if enrollment.academic_year_id == academic_year.id
                ),
                None,
            )

            if not current_enrollment or not current_enrollment.section_id:
                continue

            rank_data = RankingService.get_student_overall_rank(
                student_id=str(student.id),
                academic_year_id=str(academic_year.id),
                scope_type="section",
                scope_id=str(current_enrollment.section_id),
            )
            if rank_data:
                ranking_lookup[str(student.id)] = {
                    "score": rank_data.get("score"),
                    "rank": rank_data.get("rank"),
                }
    except Exception:
        return {}

    return ranking_lookup


def _build_xlsx_response(headers, rows, filename_prefix):
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "Students"
    sheet.append(headers)

    for cell in sheet[1]:
        cell.font = Font(bold=True)

    for row in rows:
        sheet.append(row)

    sheet.freeze_panes = "A2"

    for column_cells in sheet.columns:
        max_length = 0
        column_letter = column_cells[0].column_letter
        for cell in column_cells:
            value = "" if cell.value is None else str(cell.value)
            if len(value) > max_length:
                max_length = len(value)
        sheet.column_dimensions[column_letter].width = min(max(max_length + 2, 12), 40)

    buffer = BytesIO()
    workbook.save(buffer)
    buffer.seek(0)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    response = HttpResponse(
        buffer.getvalue(),
        content_type=(
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        ),
    )
    response["Content-Disposition"] = (
        f'attachment; filename="{filename_prefix}_{timestamp}.xlsx"'
    )
    return response


def _build_students_queryset(request, academic_year=None):
    students = Student.objects.select_related("grade_level").prefetch_related(
        "enrollments__academic_year",
        "enrollments__grade_level",
        "enrollments__section",
        "enrollments__student_bills",
    )

    selected_year_filter = {"enrollment__academic_year": academic_year} if academic_year else {
        "enrollment__academic_year__current": True
    }
    selected_year_student_filter = {"academic_year": academic_year} if academic_year else {
        "academic_year__current": True
    }

    filter_fields = [
        "first_name",
        "last_name",
        "middle_name",
        "gender",
        "grade_level",
        "section",
    ]

    status_filter = request.query_params.get("status", "")
    query_params = request.query_params.copy()
    enrollment_statuses, other_statuses = student_service.parse_enrollment_status_filter(
        status_filter
    )
    query_params.pop("status", None)

    query = get_student_queryparams(query_params, filter_fields)
    if query:
        students = students.filter(query)

    billed_subquery = (
        StudentEnrollmentBill.objects.filter(
            enrollment__student=OuterRef("pk"),
            **selected_year_filter,
        )
        .values("enrollment__student")
        .annotate(total=Sum("amount"))
        .values("total")[:1]
    )
    paid_subquery = (
        Transaction.objects.filter(
            student=OuterRef("pk"),
            status="approved",
            **selected_year_student_filter,
        )
        .values("student")
        .annotate(total=Sum("amount"))
        .values("total")[:1]
    )

    students = students.annotate(
        billed_total=Coalesce(
            Subquery(billed_subquery),
            Value(0),
            output_field=DecimalField(max_digits=12, decimal_places=2),
        ),
        paid_total=Coalesce(
            Subquery(paid_subquery),
            Value(0),
            output_field=DecimalField(max_digits=12, decimal_places=2),
        ),
    ).annotate(balance_total=F("billed_total") - F("paid_total"))

    balance_owed = str(query_params.get("balance_owed", "")).strip().lower()
    balance_condition = str(query_params.get("balance_condition", "")).strip().lower()
    balance_min = query_params.get("balance_min")
    balance_max = query_params.get("balance_max")

    if balance_owed == "owed":
        students = students.filter(balance_total__gt=0)
    elif balance_owed == "clear":
        students = students.filter(balance_total__lte=0)

    try:
        min_value = None if balance_min in [None, ""] else float(balance_min)
    except (TypeError, ValueError):
        min_value = None

    try:
        max_value = None if balance_max in [None, ""] else float(balance_max)
    except (TypeError, ValueError):
        max_value = None

    is_pct = balance_condition.startswith("pct-")
    actual_condition = balance_condition[4:] if is_pct else balance_condition

    if is_pct:
        students = students.annotate(
            balance_pct=Case(
                When(billed_total=0, then=Value(0.0)),
                default=ExpressionWrapper(
                    F("balance_total") * Value(100.0) / F("billed_total"),
                    output_field=FloatField(),
                ),
                output_field=FloatField(),
            )
        )

    filter_field = "balance_pct" if is_pct else "balance_total"

    if actual_condition == "is-equal-to" and min_value is not None:
        students = students.filter(**{filter_field: min_value})
    elif actual_condition == "is-greater-than" and min_value is not None:
        students = students.filter(**{f"{filter_field}__gt": min_value})
    elif actual_condition == "is-less-than" and min_value is not None:
        students = students.filter(**{f"{filter_field}__lt": min_value})
    else:
        if min_value is not None:
            students = students.filter(**{f"{filter_field}__gte": min_value})
        if max_value is not None:
            students = students.filter(**{f"{filter_field}__lte": max_value})

    if enrollment_statuses or other_statuses:
        status_qs = None
        if other_statuses:
            status_qs = students.filter(status__in=other_statuses).distinct()

        enrollment_qs = None
        if enrollment_statuses:
            enrolled_qs = None
            not_enrolled_qs = None

            if "enrolled" in enrollment_statuses:
                enrolled_qs = students.filter(
                    **({"enrollments__academic_year": academic_year} if academic_year else {"enrollments__academic_year__current": True})
                ).distinct()
            if "not_enrolled" in enrollment_statuses:
                not_enrolled_qs = students.exclude(
                    **({"enrollments__academic_year": academic_year} if academic_year else {"enrollments__academic_year__current": True})
                ).distinct()

            if enrolled_qs is not None and not_enrolled_qs is not None:
                enrollment_qs = (enrolled_qs | not_enrolled_qs).distinct()
            elif enrolled_qs is not None:
                enrollment_qs = enrolled_qs
            elif not_enrolled_qs is not None:
                enrollment_qs = not_enrolled_qs

        if status_qs is not None and enrollment_qs is not None:
            students = (status_qs | enrollment_qs).distinct()
        elif status_qs is not None:
            students = status_qs
        elif enrollment_qs is not None:
            students = enrollment_qs

    ordering = request.query_params.get("ordering", "id_number")
    sort_fields, is_descending = student_service.get_sorting_fields(ordering)
    if is_descending:
        sort_fields = [f"-{field}" for field in sort_fields]
        students = students.order_by(*sort_fields)
    else:
        students = students.order_by(ordering)

    return students


class StudentReportView(APIView):
    """List-level student reports based on existing student filters."""

    permission_classes = [ReportsAccessPolicy]

    def get(self, request):
        report_format = (
            request.query_params.get("file_format")
            or request.query_params.get("format")
            or "xlsx"
        ).lower()
        limit_raw = request.query_params.get("limit")
        limit = None
        if limit_raw not in [None, ""]:
            try:
                limit = max(int(limit_raw), 1)
            except (TypeError, ValueError):
                limit = None

        include_billing = _to_bool(request.query_params.get("include_billing"), default=True)
        show_rank = _to_bool(request.query_params.get("show_rank"), default=False)
        show_grade_average = _to_bool(
            request.query_params.get("show_grade_average"), default=False
        )
        academic_year = _resolve_academic_year(request.query_params.get("academic_year_id"))
        use_background = _to_bool(request.query_params.get("background"), default=False)
        force_sync = _to_bool(request.query_params.get("force_sync"), default=False)
        max_sync_records = int(get_reports_setting("MAX_SYNC_RECORDS", 5000) or 5000)

        queryset = _build_students_queryset(request, academic_year=academic_year)

        total_count = queryset.count()

        if (
            total_count > max_sync_records
            and not force_sync
            and report_format in {"xlsx", "csv", "json"}
        ):
            if use_background:
                task_params = {
                    "query_params": dict(request.query_params),
                    "report_format": report_format,
                    "cache_key": TaskManager.generate_cache_key(
                        {
                            "type": "student_report",
                            **dict(request.query_params),
                        }
                    ),
                }
                task_id = TaskManager.create_task(
                    task_type="student_report",
                    query_params=task_params,
                    user_id=getattr(request.user, "id", 0) or 0,
                    estimated_count=total_count,
                )
                MockTaskProcessor.process_student_report(task_id)

                return Response(
                    {
                        "task_id": task_id,
                        "status": "pending",
                        "processing_mode": "background",
                        "message": (
                            "Large report detected. Processing in background. "
                            "Poll export status endpoint for completion."
                        ),
                        "estimated_records": total_count,
                        "check_status_url": f"/api/v1/reports/export-status/{task_id}/",
                    },
                    status=status.HTTP_202_ACCEPTED,
                )

            return Response(
                {
                    "detail": (
                        f"Report is too large for synchronous export ({total_count} records). "
                        f"Use limit<= {max_sync_records}, pass background=true, or force_sync=true."
                    ),
                    "record_count": total_count,
                    "max_sync_records": max_sync_records,
                },
                status=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            )

        if limit is not None:
            queryset = queryset[:limit]

        ranking_lookup = {}
        if show_rank or show_grade_average:
            ranking_lookup = _build_ranking_lookup(request, queryset, academic_year)

        serializer = StudentSerializer(
            queryset,
            many=True,
            context={
                "request": request,
                "include_billing": include_billing,
                "include_payment_plan": include_billing,
                "include_payment_status": include_billing,
                "show_rank": show_rank,
                "show_grade_average": show_grade_average,
                "show_balance": True,
                "ranking_lookup": ranking_lookup,
                "academic_year": academic_year,
                "academic_year_id": str(academic_year.id) if academic_year else None,
            },
        )
        rows = serializer.data
        export_rows = _build_list_export_rows(
            rows,
            include_billing=include_billing,
            show_rank=show_rank,
            show_grade_average=show_grade_average,
        )
        headers = _build_export_headers(
            include_billing=include_billing,
            show_rank=show_rank,
            show_grade_average=show_grade_average,
        )

        if report_format == "json":
            return Response(
                {
                    "count": total_count if limit is None else len(rows),
                    "limit": limit,
                    "generated_at": datetime.now().isoformat(),
                    "results": rows,
                }
            )

        if report_format == "xlsx":
            return _build_xlsx_response(headers, export_rows, "students_report")

        if report_format != "csv":
            return Response(
                {"detail": "Unsupported format. Use xlsx, csv, or json."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"students_report_{timestamp}.csv"
        response = HttpResponse(content_type="text/csv")
        response["Content-Disposition"] = f'attachment; filename="{filename}"'

        writer = csv.writer(response)
        writer.writerow(headers)

        for export_row in export_rows:
            writer.writerow(export_row)

        return response


class StudentIndividualReportView(APIView):
    """Individual student report downloads: bio, financial, or full."""

    permission_classes = [ReportsAccessPolicy]

    def get(self, request, student_id):
        student = _resolve_student(student_id)
        if not student:
            return Response(
                {"detail": "Student does not exist."},
                status=status.HTTP_404_NOT_FOUND,
            )

        report_type = (request.query_params.get("report_type") or "full").lower()
        report_format = (
            request.query_params.get("file_format")
            or request.query_params.get("format")
            or "json"
        ).lower()
        academic_year_id = request.query_params.get("academic_year_id")

        if report_type not in {"bio", "financial", "full"}:
            return Response(
                {"detail": "Unsupported report_type. Use bio, financial, or full."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        academic_year = _resolve_academic_year(academic_year_id)
        enrollment = None
        if academic_year:
            enrollment = Enrollment.objects.filter(
                student=student,
                academic_year=academic_year,
            ).first()

        bio_data = None
        if report_type in {"bio", "full"}:
            bio_data = StudentDetailSerializer(student, context={"request": request}).data

        financial_data = None
        if report_type in {"financial", "full"}:
            billing_summary = (
                get_enrollment_bill_summary(enrollment, include_payment_plan=True)
                if enrollment
                else None
            )

            bills_queryset = StudentEnrollmentBill.objects.none()
            if enrollment:
                bills_queryset = StudentEnrollmentBill.objects.filter(
                    enrollment=enrollment
                ).order_by("name")

            transactions_queryset = Transaction.objects.filter(student=student).select_related(
                "type", "payment_method", "academic_year"
            )
            if academic_year:
                transactions_queryset = transactions_queryset.filter(academic_year=academic_year)
            transactions_queryset = transactions_queryset.order_by("-date", "-created_at")[:1000]

            financial_data = {
                "academic_year": {
                    "id": str(academic_year.id),
                    "name": academic_year.name,
                }
                if academic_year
                else None,
                "enrollment_id": str(enrollment.id) if enrollment else None,
                "billing_summary": billing_summary,
                "bills": [
                    {
                        "id": str(bill.id),
                        "name": bill.name,
                        "amount": float(bill.amount),
                        "type": bill.type,
                        "notes": bill.notes,
                    }
                    for bill in bills_queryset
                ],
                "transactions": [
                    {
                        "id": str(tx.id),
                        "transaction_id": tx.transaction_id,
                        "date": tx.date.isoformat() if tx.date else None,
                        "description": tx.description,
                        "amount": float(tx.amount),
                        "status": tx.status,
                        "type": tx.type.name if tx.type else None,
                        "payment_method": tx.payment_method.name if tx.payment_method else None,
                    }
                    for tx in transactions_queryset
                ],
            }

        payload = {
            "report_type": report_type,
            "generated_at": datetime.now().isoformat(),
            "student": {
                "id": str(student.id),
                "id_number": student.id_number,
                "full_name": student.get_full_name(),
            },
        }

        if bio_data is not None:
            payload["bio"] = bio_data
        if financial_data is not None:
            payload["financial"] = financial_data

        if academic_year:
            payload["download_links"] = {
                "report_card_pdf": f"/api/v1/grading/students/{student.id}/final-grades/academic-years/{academic_year.id}/report-card/",
                "billing_pdf": f"/api/v1/students/{student.id}/bills/download-pdf/",
            }

        if report_format == "json":
            json_response = HttpResponse(
                json.dumps(payload, ensure_ascii=True, default=str, indent=2),
                content_type="application/json",
            )
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            json_response["Content-Disposition"] = (
                f'attachment; filename="student_{student.id_number}_{report_type}_{timestamp}.json"'
            )
            return json_response

        if report_format != "csv":
            return Response(
                {"detail": "Unsupported format. Use json or csv."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"student_{student.id_number}_{report_type}_{timestamp}.csv"
        response = HttpResponse(content_type="text/csv")
        response["Content-Disposition"] = f'attachment; filename="{filename}"'

        writer = csv.writer(response)

        if report_type == "bio":
            writer.writerow(
                [
                    "ID Number",
                    "Full Name",
                    "Date of Birth",
                    "Gender",
                    "Email",
                    "Phone",
                    "Address",
                    "City",
                    "State",
                    "Country",
                    "Status",
                ]
            )
            writer.writerow(
                [
                    student.id_number,
                    student.get_full_name(),
                    student.date_of_birth.isoformat() if student.date_of_birth else "",
                    student.gender or "",
                    student.email or "",
                    student.phone_number or "",
                    student.address or "",
                    student.city or "",
                    student.state or "",
                    student.country or "",
                    student.status,
                ]
            )
            return response

        # For financial/full CSV, output transaction ledger rows.
        writer.writerow(
            [
                "Student ID",
                "Student Name",
                "Academic Year",
                "Transaction ID",
                "Date",
                "Description",
                "Type",
                "Payment Method",
                "Status",
                "Amount",
            ]
        )

        tx_rows = (payload.get("financial") or {}).get("transactions") or []
        for tx in tx_rows:
            writer.writerow(
                [
                    student.id_number,
                    student.get_full_name(),
                    (payload.get("financial") or {}).get("academic_year", {}).get("name", ""),
                    tx.get("transaction_id", ""),
                    tx.get("date", ""),
                    tx.get("description", ""),
                    tx.get("type", ""),
                    tx.get("payment_method", ""),
                    tx.get("status", ""),
                    tx.get("amount", ""),
                ]
            )

        return response
