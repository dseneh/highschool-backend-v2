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

from core.models import Tenant, TenantCreationJob
from core.services.tenant_deletion import hard_delete_tenant_workspace

logger = logging.getLogger(__name__)


AUDIT_FIELDS = {"created_at", "updated_at", "created_by", "updated_by"}
SHARED_REFERENCE_MODELS = {"core.Division"}


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
    def __init__(self, source_schema: str, destination_schema: str, modules: list[CloneModule]):
        self.source_schema = source_schema
        self.destination_schema = destination_schema
        self.modules = modules
        self.id_map: dict[tuple[str, str], object] = {}
        self.pending_relations: list[tuple[str, object, str, tuple[str, str]]] = []

    @property
    def model_labels(self) -> list[str]:
        return [label for module in self.modules for label in module.model_labels]

    def snapshot_source(self) -> CloneSnapshot:
        snapshot = CloneSnapshot()
        selected_models = set(self.model_labels)
        with schema_context(self.source_schema):
            for label in self.model_labels:
                model = _model(label)
                rows = []
                for obj in model.objects.all().iterator():
                    values = {}
                    relations = {}
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
                            relations[model_field.name] = (target_label, str(source_id)) if source_id is not None else None
                        else:
                            values[model_field.name] = getattr(obj, model_field.name)
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


def run_clone_job(job_id: str) -> None:
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

        modules = resolve_modules(job.selected_modules)
        source = Tenant.objects.get(pk=job.source_tenant_id, active=True)
        clone_service = TenantCloneService(source.schema_name, job.destination_schema, modules)
        snapshot = clone_service.snapshot_source()

        from core.serializers import CreateTenantSerializer
        from users.models import User

        actor = User.objects.get(pk=job.requested_by_id)
        request = type("JobRequest", (), {"user": actor})()
        serializer = CreateTenantSerializer(
            data=job.request_payload,
            context={"request": request, "skip_default_divisions": True},
        )
        serializer.is_valid(raise_exception=True)
        _update_job(job.pk, "Creating Schema", 15)
        tenant = serializer.save()
        TenantCreationJob.objects.filter(pk=job.pk).update(destination_tenant=tenant)
        tenant.provisioning_status = "in_progress"
        tenant.provisioning_step = "Applying Base Setup"
        tenant.provisioning_progress = 25
        tenant.provisioning_payload = {"source_schema": source.schema_name, "modules": job.selected_modules}
        tenant.save(update_fields=["provisioning_status", "provisioning_step", "provisioning_progress", "provisioning_payload"])

        _update_job(job.pk, "Applying Base Setup", 25)
        _update_job(job.pk, "Cloning Selected Modules", 40)
        counts = clone_service.clone(snapshot)
        _update_job(job.pk, "Validating Clone", 85)

        tenant.provisioning_status = "completed"
        tenant.provisioning_step = "Completed"
        tenant.provisioning_progress = 100
        tenant.provisioning_error = ""
        tenant.save(update_fields=["provisioning_status", "provisioning_step", "provisioning_progress", "provisioning_error"])
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
        logger.exception("Tenant clone job %s failed", job_id)
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
                logger.exception("Failed to clean up tenant clone destination %s", tenant.schema_name)
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


def start_clone_job(job: TenantCreationJob) -> None:
    threading.Thread(
        target=run_clone_job,
        args=(str(job.pk),),
        daemon=True,
        name=f"tenant-clone-{job.pk}",
    ).start()
