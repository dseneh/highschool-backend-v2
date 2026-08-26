"""Dependency-aware, tenant-isolated configuration cloning."""

from __future__ import annotations

import logging
import threading
from dataclasses import dataclass, field
from typing import Iterable

from django.db import close_old_connections, models, transaction
from django.utils import timezone
from django_tenants.utils import schema_context
from rest_framework.exceptions import ValidationError

from academics.services.grade_level_range import default_max_level_for_division
from core.models import Tenant, TenantCreationJob
from core.services.tenant_deletion import hard_delete_tenant_workspace

logger = logging.getLogger(__name__)


AUDIT_FIELDS = {"created_at", "updated_at", "created_by", "updated_by"}
SHARED_REFERENCE_MODELS = {"core.Division"}
GRADE_LEVEL_LABEL = "academics.GradeLevel"


@dataclass(frozen=True)
class CloneModule:
    key: str
    label: str
    description: str
    dependencies: tuple[str, ...]
    model_labels: tuple[str, ...]


MODULES = (
    CloneModule(
        "academic_configuration",
        "Academic configuration",
        "Academic years, semesters, marking periods, and calendar settings.",
        (),
        ("academics.AcademicYear", "academics.SchoolCalendarSettings", "academics.Semester", "academics.MarkingPeriod"),
    ),
    CloneModule(
        "grade_levels",
        "Grade levels",
        "Grade levels and grade-level tuition master data.",
        (),
        ("academics.GradeLevel", "academics.GradeLevelTuitionFee"),
    ),
    CloneModule(
        "sections",
        "Sections",
        "Sections and their grade-level relationships.",
        ("grade_levels",),
        ("academics.Section",),
    ),
    CloneModule(
        "subjects",
        "Subjects",
        "Subject catalog and section-subject assignments.",
        ("sections",),
        ("academics.Subject", "academics.SectionSubject"),
    ),
    CloneModule(
        "grading_configuration",
        "Grading configuration",
        "Grading settings, grade bands, assessment types, and reusable templates.",
        (),
        ("settings.GradingSettings", "grading.GradeLetter", "grading.HonorCategory", "grading.AssessmentType", "grading.DefaultAssessmentTemplate"),
    ),
    CloneModule(
        "accounting_configuration",
        "Finance and Chart of Accounts",
        "Currencies, exchange rates, ledger accounts, payment methods, transaction types, and accounting mappings. Balances and transactions are excluded.",
        (),
        ("accounting.AccountingCurrency", "accounting.AccountingExchangeRate", "accounting.AccountingLedgerAccount", "accounting.AccountingPaymentMethod", "accounting.AccountingTransactionType", "accounting.AccountingSettings"),
    ),
    CloneModule(
        "payroll_configuration",
        "Payroll settings",
        "Pay schedules, earning/deduction catalog rules, layouts, and payroll settings. Employees, periods, and runs are excluded.",
        ("accounting_configuration",),
        ("payroll_v2.PaySchedule", "payroll_v2.PayrollCatalogItem", "payroll_v2.PayrollCatalogItemRule", "payroll_v2.PayrollTableView", "payroll_v2.PayrollPayslipTemplate", "payroll_v2.PayrollSettings"),
    ),
    CloneModule(
        "notification_settings",
        "Notification settings",
        "Tenant-level notification delivery settings. Campaigns and user preferences are excluded.",
        (),
        ("notifications.TenantNotificationSettings",),
    ),
)
MODULE_REGISTRY = {module.key: module for module in MODULES}


def module_metadata() -> list[dict]:
    return [
        {
            "key": module.key,
            "label": module.label,
            "description": module.description,
            "dependencies": list(module.dependencies),
            "category": "configuration_master_data",
        }
        for module in MODULES
    ]


def resolve_modules(selected: Iterable[str]) -> list[CloneModule]:
    keys = list(dict.fromkeys(selected))
    unsupported = sorted(set(keys) - set(MODULE_REGISTRY))
    if unsupported:
        raise ValidationError({"clone_modules": f"Unsupported modules: {', '.join(unsupported)}"})
    missing = {
        key: sorted(set(MODULE_REGISTRY[key].dependencies) - set(keys))
        for key in keys
        if set(MODULE_REGISTRY[key].dependencies) - set(keys)
    }
    if missing:
        details = "; ".join(f"{key} requires {', '.join(deps)}" for key, deps in missing.items())
        raise ValidationError({"clone_modules": details})

    ordered: list[CloneModule] = []
    remaining = set(keys)
    while remaining:
        ready = [module for module in MODULES if module.key in remaining and set(module.dependencies).issubset({item.key for item in ordered})]
        if not ready:
            raise ValidationError({"clone_modules": "Module dependencies could not be resolved."})
        ordered.extend(ready)
        remaining -= {module.key for module in ready}
    return ordered


def _model(label: str):
    from django.apps import apps

    return apps.get_model(label)


@dataclass
class CloneSnapshot:
    records: dict[str, list[dict]] = field(default_factory=dict)


class TenantCloneService:
    def __init__(
        self,
        source_schema: str,
        destination_schema: str,
        modules: list[CloneModule],
        destination_division=None,
    ):
        self.source_schema = source_schema
        self.destination_schema = destination_schema
        self.modules = modules
        self.destination_division = destination_division
        self.destination_max_level = (
            default_max_level_for_division(destination_division) if destination_division else None
        )
        self.id_map: dict[tuple[str, str], object] = {}
        self.pending_relations: list[tuple[str, object, str, tuple[str, str]]] = []
        self.skipped_sources: set[tuple[str, str]] = set()

    @property
    def model_labels(self) -> list[str]:
        return [label for module in self.modules for label in module.model_labels]

    def _is_out_of_division_range(self, label: str, obj) -> bool:
        """Grade levels above the destination division's highest level do not belong there."""
        if label != GRADE_LEVEL_LABEL or self.destination_max_level is None:
            return False
        return (getattr(obj, "level", None) or 0) > self.destination_max_level

    def _resolve_relation(self, label: str, field_name: str, target_label: str, source_id: str):
        """Point cloned grade levels at the destination school's shared division."""
        if (
            label == GRADE_LEVEL_LABEL
            and field_name == "division"
            and self.destination_division is not None
        ):
            return (target_label, str(self.destination_division.pk))
        return (target_label, source_id)

    def snapshot_source(self) -> CloneSnapshot:
        snapshot = CloneSnapshot()
        selected_models = set(self.model_labels)
        with schema_context(self.source_schema):
            for label in self.model_labels:
                model = _model(label)
                rows = []
                for obj in model.objects.all().iterator():
                    if self._is_out_of_division_range(label, obj):
                        self.skipped_sources.add((label, str(obj.pk)))
                        continue
                    values = {}
                    relations = {}
                    skip_row = False
                    for model_field in model._meta.concrete_fields:
                        if model_field.primary_key or model_field.name in AUDIT_FIELDS:
                            continue
                        if isinstance(model_field, models.ForeignKey):
                            target_label = model_field.remote_field.model._meta.label
                            source_id = getattr(obj, model_field.attname)
                            if (
                                source_id is not None
                                and target_label not in selected_models
                                and target_label not in SHARED_REFERENCE_MODELS
                            ):
                                if model_field.null:
                                    source_id = None
                                else:
                                    raise ValidationError(
                                        f"{label}.{model_field.name} requires unsupported model {target_label}."
                                    )
                            if source_id is not None and (target_label, str(source_id)) in self.skipped_sources:
                                if not model_field.null:
                                    skip_row = True
                                    break
                                source_id = None
                            relations[model_field.name] = (
                                self._resolve_relation(label, model_field.name, target_label, str(source_id))
                                if source_id is not None
                                else None
                            )
                        else:
                            values[model_field.name] = getattr(obj, model_field.name)
                    if skip_row:
                        self.skipped_sources.add((label, str(obj.pk)))
                        continue
                    rows.append({"source_id": str(obj.pk), "values": values, "relations": relations})
                snapshot.records[label] = rows
        return snapshot

    def clone(self, snapshot: CloneSnapshot) -> dict[str, int]:
        counts = {}
        with schema_context(self.destination_schema), transaction.atomic():
            for label in self.model_labels:
                model = _model(label)
                for row in snapshot.records[label]:
                    values = dict(row["values"])
                    deferred = []
                    for field_name, relation in row["relations"].items():
                        if relation is None:
                            values[f"{field_name}_id"] = None
                            continue
                        target = (relation[0], relation[1])
                        mapped = self.id_map.get(target)
                        model_field = model._meta.get_field(field_name)
                        if mapped is None and relation[0] in SHARED_REFERENCE_MODELS:
                            mapped = relation[1]
                        if mapped is None and not model_field.null:
                            raise ValidationError(f"Missing cloned dependency for {label}.{field_name}.")
                        values[f"{field_name}_id"] = mapped
                        if mapped is None:
                            deferred.append((field_name, target))
                    created = model.objects.create(**values)
                    self.id_map[(label, row["source_id"])] = created.pk
                    self.pending_relations.extend((label, created.pk, name, target) for name, target in deferred)
                counts[label] = len(snapshot.records[label])

            for label, object_id, field_name, target in self.pending_relations:
                mapped = self.id_map.get(target)
                if mapped is None:
                    raise ValidationError(f"Missing cloned dependency for {label}.{field_name}.")
                _model(label).objects.filter(pk=object_id).update(**{f"{field_name}_id": mapped})

            self._validate(snapshot)
        return counts

    def _validate(self, snapshot: CloneSnapshot) -> None:
        source_ids = {source_id for (_, source_id) in self.id_map}
        destination_ids = {str(destination_id) for destination_id in self.id_map.values()}
        if source_ids & destination_ids:
            raise ValidationError("Clone validation found reused source primary keys.")
        for label in self.model_labels:
            expected = len(snapshot.records[label])
            if _model(label).objects.count() != expected:
                raise ValidationError(f"Clone count validation failed for {label}.")


def _update_job(job_id, stage, progress, **updates):
    TenantCreationJob.objects.filter(pk=job_id).update(stage=stage, progress_percent=progress, **updates)


def _set_provisioning(tenant, status, step, progress, **extra):
    for name, value in {"provisioning_status": status, "provisioning_step": step, "provisioning_progress": progress, **extra}.items():
        setattr(tenant, name, value)
    tenant.save(update_fields=["provisioning_status", "provisioning_step", "provisioning_progress", *extra])


def run_tenant_creation_job(job_id: str) -> None:
    """Shared workflow for default and clone tenant creation.

    Only the initialization source differs: default setup seeds nothing extra,
    clone copies the selected modules from the source tenant.
    """
    close_old_connections()
    tenant = None
    try:
        claimed = TenantCreationJob.objects.filter(
            pk=job_id,
            status=TenantCreationJob.Status.PENDING,
        ).update(
            status=TenantCreationJob.Status.IN_PROGRESS,
            stage="Creating Tenant",
            progress_percent=5,
            started_at=timezone.now(),
        )
        if not claimed:
            return
        job = TenantCreationJob.objects.select_related("source_tenant", "requested_by").get(pk=job_id)
        is_clone = job.initialization_source == TenantCreationJob.InitializationSource.CLONE

        source = None
        modules: list[CloneModule] = []
        if is_clone:
            modules = resolve_modules(job.selected_modules)
            source = Tenant.objects.get(pk=job.source_tenant_id, active=True)

        from core.serializers import CreateTenantSerializer
        from users.models import User

        actor = User.objects.filter(pk=job.requested_by_id).first()
        request = type("JobRequest", (), {"user": actor})()
        serializer = CreateTenantSerializer(
            data=job.request_payload,
            context={"request": request},
        )
        serializer.is_valid(raise_exception=True)
        _update_job(job.pk, "Creating Schema", 15)
        tenant = serializer.save()
        TenantCreationJob.objects.filter(pk=job.pk).update(destination_tenant=tenant)
        _set_provisioning(
            tenant,
            "in_progress",
            "Applying Base Setup",
            25,
            provisioning_payload={
                "initialization_source": job.initialization_source,
                "source_schema": source.schema_name if source else "",
                "modules": job.selected_modules,
            },
        )
        _update_job(job.pk, "Applying Base Setup", 25)

        counts: dict[str, int] = {}
        if is_clone:
            _update_job(job.pk, "Cloning Selected Modules", 40)
            clone_service = TenantCloneService(
                source.schema_name,
                tenant.schema_name,
                modules,
                destination_division=tenant.school_division,
            )
            snapshot = clone_service.snapshot_source()
            counts = clone_service.clone(snapshot)
        else:
            _update_job(job.pk, "Preparing Default Setup", 40)
        _update_job(job.pk, "Validating Workspace", 85)

        _set_provisioning(tenant, "completed", "Completed", 100, provisioning_error="")
        _update_job(job.pk, "Finalizing", 95)
        _update_job(
            job.pk,
            "Completed",
            100,
            status=TenantCreationJob.Status.COMPLETED,
            result={"tenant_schema": tenant.schema_name, "cloned_counts": counts},
            completed_at=timezone.now(),
        )
    except Exception as exc:
        logger.exception("Tenant creation job %s failed", job_id)
        cleanup_error = ""
        if tenant is not None:
            try:
                hard_delete_tenant_workspace(tenant)
            except Exception as cleanup_exc:
                cleanup_error = f" Cleanup also failed: {cleanup_exc}"
                Tenant.objects.filter(pk=tenant.pk).update(
                    status=Tenant.STATUS_DELETED,
                    active=False,
                    provisioning_status="failed",
                    provisioning_step="Failed",
                    provisioning_error=str(exc),
                )
                logger.exception("Failed to clean up tenant creation destination %s", tenant.schema_name)
        _update_job(
            job_id,
            "Failed",
            100,
            status=TenantCreationJob.Status.FAILED,
            failure_detail=f"{exc}{cleanup_error}",
            completed_at=timezone.now(),
        )
    finally:
        close_old_connections()


def start_tenant_creation_job(job: TenantCreationJob) -> None:
    threading.Thread(
        target=run_tenant_creation_job,
        args=(str(job.pk),),
        daemon=True,
        name=f"tenant-creation-{job.pk}",
    ).start()
