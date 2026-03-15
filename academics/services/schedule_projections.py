from __future__ import annotations

from dataclasses import dataclass

from django.db import transaction

from academics.models import (
    GradeBookScheduleProjection,
    SectionSchedule,
    StudentScheduleProjection,
)
from grading.models import GradeBook
from staff.models import TeacherSchedule, TeacherSubject
from students.models import Enrollment

INACTIVE_ENROLLMENT_STATUSES = {"withdrawn", "canceled"}


@dataclass
class TimeWindow:
    day_of_week: int
    start_time: object
    end_time: object


def _resolve_time_window(class_schedule: SectionSchedule) -> TimeWindow | None:
    if class_schedule.section_time_slot:
        return TimeWindow(
            day_of_week=class_schedule.section_time_slot.day_of_week,
            start_time=class_schedule.section_time_slot.start_time,
            end_time=class_schedule.section_time_slot.end_time,
        )

    if class_schedule.period_time:
        return TimeWindow(
            day_of_week=class_schedule.period_time.day_of_week,
            start_time=class_schedule.period_time.start_time,
            end_time=class_schedule.period_time.end_time,
        )

    return None


def _is_class_subject_schedule(class_schedule: SectionSchedule) -> bool:
    return (
        class_schedule.active
        and class_schedule.subject_id is not None
        and class_schedule.period.period_type == class_schedule.period.PeriodType.CLASS
    )


def _sync_teacher_schedules(class_schedule: SectionSchedule):
    existing_qs = TeacherSchedule.objects.filter(class_schedule=class_schedule)

    if not _is_class_subject_schedule(class_schedule):
        existing_qs.delete()
        return

    desired_teacher_ids = set(
        TeacherSubject.objects.filter(
            section_subject=class_schedule.subject,
            active=True,
        ).values_list("teacher_id", flat=True)
    )

    if not desired_teacher_ids:
        existing_qs.delete()
        return

    existing_teacher_ids = set(existing_qs.values_list("teacher_id", flat=True))

    existing_qs.exclude(teacher_id__in=desired_teacher_ids).delete()

    missing_teacher_ids = desired_teacher_ids - existing_teacher_ids
    if missing_teacher_ids:
        TeacherSchedule.objects.bulk_create(
            [
                TeacherSchedule(
                    class_schedule=class_schedule,
                    teacher_id=teacher_id,
                )
                for teacher_id in missing_teacher_ids
            ],
            ignore_conflicts=True,
        )


def _ensure_gradebooks(class_schedule: SectionSchedule):
    if class_schedule.subject_id is None:
        return GradeBook.objects.none()

    section_subject = class_schedule.subject
    section = class_schedule.section
    subject = section_subject.subject

    year_ids = list(
        Enrollment.objects.filter(section=section, active=True)
        .exclude(status__in=INACTIVE_ENROLLMENT_STATUSES)
        .values_list("academic_year_id", flat=True)
        .distinct()
    )

    if not year_ids:
        return GradeBook.objects.filter(section_subject=section_subject, active=True)

    existing_gradebooks = GradeBook.objects.filter(
        section_subject=section_subject,
        academic_year_id__in=year_ids,
    )
    existing_by_year = {gradebook.academic_year_id: gradebook for gradebook in existing_gradebooks}

    missing_year_ids = [year_id for year_id in year_ids if year_id not in existing_by_year]
    for year_id in missing_year_ids:
        GradeBook.objects.create(
            section_subject=section_subject,
            section=section,
            subject=subject,
            academic_year_id=year_id,
            name=f"{subject.name} - {section.name}",
        )

    return GradeBook.objects.filter(section_subject=section_subject, active=True)


def _sync_gradebook_schedules(class_schedule: SectionSchedule, time_window: TimeWindow | None):
    existing_qs = GradeBookScheduleProjection.objects.filter(class_schedule=class_schedule)

    if not _is_class_subject_schedule(class_schedule) or time_window is None:
        existing_qs.delete()
        return

    gradebooks = list(_ensure_gradebooks(class_schedule))
    if not gradebooks:
        existing_qs.delete()
        return

    desired_gradebook_ids = {gradebook.id for gradebook in gradebooks}
    existing_qs.exclude(gradebook_id__in=desired_gradebook_ids).delete()

    existing_by_gradebook = {
        projection.gradebook_id: projection
        for projection in GradeBookScheduleProjection.objects.filter(
            class_schedule=class_schedule,
            gradebook_id__in=desired_gradebook_ids,
        )
    }

    for gradebook in gradebooks:
        defaults = {
            "section": class_schedule.section,
            "section_subject": class_schedule.subject,
            "subject": class_schedule.subject.subject,
            "period": class_schedule.period,
            "day_of_week": time_window.day_of_week,
            "start_time": time_window.start_time,
            "end_time": time_window.end_time,
        }

        existing = existing_by_gradebook.get(gradebook.id)
        if existing:
            GradeBookScheduleProjection.objects.filter(id=existing.id).update(**defaults)
            continue

        GradeBookScheduleProjection.objects.create(
            class_schedule=class_schedule,
            gradebook=gradebook,
            **defaults,
        )


def _sync_student_schedules(class_schedule: SectionSchedule, time_window: TimeWindow | None):
    existing_qs = StudentScheduleProjection.objects.filter(class_schedule=class_schedule)

    if not _is_class_subject_schedule(class_schedule) or time_window is None:
        existing_qs.delete()
        return

    enrollments = list(
        Enrollment.objects.filter(section=class_schedule.section, active=True)
        .exclude(status__in=INACTIVE_ENROLLMENT_STATUSES)
        .select_related("student")
    )

    if not enrollments:
        existing_qs.delete()
        return

    desired_enrollment_ids = {enrollment.id for enrollment in enrollments}
    existing_qs.exclude(enrollment_id__in=desired_enrollment_ids).delete()

    existing_by_enrollment = {
        projection.enrollment_id: projection
        for projection in StudentScheduleProjection.objects.filter(
            class_schedule=class_schedule,
            enrollment_id__in=desired_enrollment_ids,
        )
    }

    for enrollment in enrollments:
        defaults = {
            "student": enrollment.student,
            "section": class_schedule.section,
            "section_subject": class_schedule.subject,
            "subject": class_schedule.subject.subject,
            "period": class_schedule.period,
            "day_of_week": time_window.day_of_week,
            "start_time": time_window.start_time,
            "end_time": time_window.end_time,
        }

        existing = existing_by_enrollment.get(enrollment.id)
        if existing:
            StudentScheduleProjection.objects.filter(id=existing.id).update(**defaults)
            continue

        StudentScheduleProjection.objects.create(
            class_schedule=class_schedule,
            enrollment=enrollment,
            **defaults,
        )


@transaction.atomic
def sync_schedule_projections_for_class_schedule(class_schedule: SectionSchedule):
    time_window = _resolve_time_window(class_schedule)

    _sync_teacher_schedules(class_schedule)
    _sync_gradebook_schedules(class_schedule, time_window)
    _sync_student_schedules(class_schedule, time_window)


@transaction.atomic
def purge_schedule_projections_for_class_schedule(class_schedule_id: str):
    TeacherSchedule.objects.filter(class_schedule_id=class_schedule_id).delete()
    GradeBookScheduleProjection.objects.filter(class_schedule_id=class_schedule_id).delete()
    StudentScheduleProjection.objects.filter(class_schedule_id=class_schedule_id).delete()
