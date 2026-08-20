from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import transaction
from uuid import UUID
from rest_framework import viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import ValidationError
from rest_framework.response import Response

from academics.models import GradeLevel

from .access_policies import BudgetAccessPolicy
from .models import (
    Budget, BudgetEnrollmentAssumption, BudgetLine, BudgetLinePeriod,
    BudgetRevision, BudgetRevisionLineDelta, BudgetSection,
)
from .serializers import (
    BudgetEnrollmentAssumptionSerializer, BudgetLinePeriodSerializer,
    BudgetLineSerializer, BudgetRevisionLineDeltaSerializer,
    BudgetRevisionSerializer, BudgetSectionSerializer, BudgetSerializer,
)
from .services import (
    approve_revision, budget_summary_payload, prior_year_baseline,
    projection_payload, transition_budget,
)


class ActorModelViewSet(viewsets.ModelViewSet):
    permission_classes = [BudgetAccessPolicy]
    pagination_class = None

    def perform_create(self, serializer):
        serializer.save(created_by=self.request.user, updated_by=self.request.user)

    def perform_update(self, serializer):
        serializer.save(updated_by=self.request.user)

    def _budget_for(self, instance):
        if isinstance(instance, Budget):
            return instance
        if isinstance(instance, BudgetSection):
            return instance.budget
        if isinstance(instance, BudgetLine):
            return instance.budget
        if isinstance(instance, BudgetLinePeriod):
            return instance.line.budget
        if isinstance(instance, BudgetEnrollmentAssumption):
            return instance.budget
        if isinstance(instance, BudgetRevision):
            return instance.budget
        if isinstance(instance, BudgetRevisionLineDelta):
            return instance.revision.budget
        return None

    def _ensure_editable(self, instance):
        budget = self._budget_for(instance)
        if isinstance(instance, (BudgetRevision, BudgetRevisionLineDelta)):
            revision = instance if isinstance(instance, BudgetRevision) else instance.revision
            if revision.status != BudgetRevision.Status.DRAFT:
                raise ValidationError("Only draft revisions can be changed.")
            if revision.budget.status not in {Budget.Status.APPROVED, Budget.Status.ACTIVE}:
                raise ValidationError("Revisions are only available for approved or active budgets.")
            return
        if budget and budget.status != Budget.Status.DRAFT:
            raise ValidationError("Approved workflow data is immutable; use a budget revision.")

    def update(self, request, *args, **kwargs):
        self._ensure_editable(self.get_object())
        return super().update(request, *args, **kwargs)

    def destroy(self, request, *args, **kwargs):
        self._ensure_editable(self.get_object())
        return super().destroy(request, *args, **kwargs)

    def handle_exception(self, exc):
        if isinstance(exc, DjangoValidationError):
            exc = ValidationError(exc.messages)
        return super().handle_exception(exc)


class BudgetViewSet(ActorModelViewSet):
    queryset = Budget.objects.select_related("academic_year", "base_currency").prefetch_related(
        "sections__lines__periods", "sections__lines__revision_deltas__revision",
        "enrollment_assumptions", "revisions__line_deltas", "lifecycle_events"
    )
    serializer_class = BudgetSerializer

    def perform_create(self, serializer):
        with transaction.atomic():
            budget = serializer.save(created_by=self.request.user, updated_by=self.request.user)
            BudgetSection.objects.create(
                budget=budget, name="Revenue", section_type=BudgetSection.SectionType.REVENUE,
                sort_order=0, created_by=self.request.user, updated_by=self.request.user,
            )
            BudgetSection.objects.create(
                budget=budget, name="Operating Expenses", section_type=BudgetSection.SectionType.EXPENSE,
                sort_order=1, created_by=self.request.user, updated_by=self.request.user,
            )

    def get_queryset(self):
        queryset = super().get_queryset()
        academic_year_id = self.request.query_params.get("academic_year_id")
        budget_status = self.request.query_params.get("status")
        if academic_year_id:
            queryset = queryset.filter(academic_year_id=academic_year_id)
        if budget_status:
            if budget_status not in Budget.Status.values:
                raise ValidationError({"status": "Invalid budget status."})
            queryset = queryset.filter(status=budget_status)
        return queryset

    def _transition(self, request, target):
        try:
            budget = transition_budget(self.get_object(), target, request.user, request.data.get("reason", ""))
        except DjangoValidationError as exc:
            raise ValidationError(exc.messages)
        return Response(self.get_serializer(budget).data)

    @action(detail=True, methods=["post"])
    def submit(self, request, pk=None):
        return self._transition(request, Budget.Status.SUBMITTED)

    @action(detail=True, methods=["post"])
    def approve(self, request, pk=None):
        return self._transition(request, Budget.Status.APPROVED)

    @action(detail=True, methods=["post"])
    def activate(self, request, pk=None):
        return self._transition(request, Budget.Status.ACTIVE)

    @action(detail=True, methods=["post"])
    def close(self, request, pk=None):
        return self._transition(request, Budget.Status.CLOSED)

    @action(detail=True, methods=["post"])
    def reject(self, request, pk=None):
        return self._transition(request, Budget.Status.DRAFT)

    @action(detail=True, methods=["get"])
    def summary(self, request, pk=None):
        return Response(budget_summary_payload(self.get_object()))

    @action(detail=True, methods=["get"])
    def baseline(self, request, pk=None):
        return Response(prior_year_baseline(self.get_object()))

    @action(detail=True, methods=["get"])
    def projections(self, request, pk=None):
        return Response(projection_payload(self.get_object()))

    @action(detail=True, methods=["post"], url_path="enrollment-assumptions/bulk")
    def bulk_enrollment_assumptions(self, request, pk=None):
        budget = self.get_object()
        self._ensure_editable(budget)
        rows = request.data.get("rows")
        if not isinstance(rows, list):
            raise ValidationError({"rows": "Provide a list of grade-level assumptions."})

        grade_ids = []
        for row in rows:
            if not isinstance(row, dict):
                continue
            try:
                grade_ids.append(UUID(str(row.get("grade_level"))))
            except (TypeError, ValueError, AttributeError):
                continue
        grades = {str(grade.id): grade for grade in GradeLevel.objects.filter(id__in=grade_ids)}
        prepared = []
        seen = set()
        errors = {}
        for index, row in enumerate(rows):
            if not isinstance(row, dict):
                errors[index] = "Each assumption must be an object."
                continue
            grade_id = str(row.get("grade_level") or "")
            if grade_id in seen:
                errors[index] = "Each grade level can appear only once."
                continue
            seen.add(grade_id)
            grade = grades.get(grade_id)
            if grade is None:
                errors[index] = "Select a valid grade level."
                continue
            parsed_values = []
            for field, label in (
                ("estimated_students", "Estimated students"),
                ("prior_actual_students", "Previous-year students"),
            ):
                value = row.get(field, 0)
                if isinstance(value, bool):
                    errors[index] = f"{label} must be a whole number."
                    break
                try:
                    parsed = int(value)
                except (TypeError, ValueError):
                    errors[index] = f"{label} must be a whole number."
                    break
                if parsed < 0 or str(value).strip() != str(parsed):
                    errors[index] = f"{label} must be a non-negative whole number."
                    break
                parsed_values.append(parsed)
            if index in errors:
                continue
            prepared.append((grade, parsed_values[0], parsed_values[1]))
        if errors:
            raise ValidationError({"rows": errors})

        with transaction.atomic():
            for grade, estimated_students, prior_actual_students in prepared:
                values = {
                    "estimated_students": estimated_students,
                    "prior_actual_students": prior_actual_students,
                    "updated_by": request.user,
                }
                BudgetEnrollmentAssumption.objects.update_or_create(
                    budget=budget,
                    grade_level=grade,
                    student_category="",
                    defaults=values,
                    create_defaults={**values, "created_by": request.user},
                )
        assumptions = BudgetEnrollmentAssumption.objects.filter(
            budget=budget, student_category=""
        ).select_related("grade_level")
        return Response(BudgetEnrollmentAssumptionSerializer(assumptions, many=True).data)


class DraftChildViewSet(ActorModelViewSet):
    def perform_create(self, serializer):
        with transaction.atomic():
            instance = serializer.save(created_by=self.request.user, updated_by=self.request.user)
            self._ensure_editable(instance)


class BudgetSectionViewSet(DraftChildViewSet):
    queryset = BudgetSection.objects.select_related("budget").all()
    serializer_class = BudgetSectionSerializer


class BudgetLineViewSet(DraftChildViewSet):
    queryset = BudgetLine.objects.select_related("section__budget", "gl_account").prefetch_related(
        "periods", "revision_deltas__revision"
    )
    serializer_class = BudgetLineSerializer


class BudgetLinePeriodViewSet(DraftChildViewSet):
    queryset = BudgetLinePeriod.objects.select_related("line__section__budget").all()
    serializer_class = BudgetLinePeriodSerializer


class BudgetEnrollmentAssumptionViewSet(DraftChildViewSet):
    queryset = BudgetEnrollmentAssumption.objects.select_related("budget", "grade_level").all()
    serializer_class = BudgetEnrollmentAssumptionSerializer


class BudgetRevisionViewSet(DraftChildViewSet):
    queryset = BudgetRevision.objects.select_related("budget").prefetch_related("line_deltas")
    serializer_class = BudgetRevisionSerializer

    @action(detail=True, methods=["post"])
    def approve(self, request, pk=None):
        try:
            revision = approve_revision(self.get_object(), request.user)
        except DjangoValidationError as exc:
            raise ValidationError(exc.messages)
        return Response(self.get_serializer(revision).data)

    @action(detail=True, methods=["post"])
    def reject(self, request, pk=None):
        revision = self.get_object()
        self._ensure_editable(revision)
        revision.status = BudgetRevision.Status.REJECTED
        revision.updated_by = request.user
        revision.save(update_fields=["status", "updated_by", "updated_at"])
        return Response(self.get_serializer(revision).data)


class BudgetRevisionLineDeltaViewSet(DraftChildViewSet):
    queryset = BudgetRevisionLineDelta.objects.select_related(
        "revision__budget", "budget_line__section__budget"
    )
    serializer_class = BudgetRevisionLineDeltaSerializer
