"""Migrate v1 single-school data into one existing v2 tenant schema.

This command is intentionally scoped and idempotent for safer execution.
It currently supports the first production batch for academics core tables:
- core_division -> {schema}.division
- core_gradelevel -> {schema}.grade_level
- core_section -> {schema}.section
- core_subject -> {schema}.subject
- core_sectionsubject -> {schema}.section_subject

And a second non-schedule academics batch:
- core_academicyear -> {schema}.academic_year
- core_semester -> {schema}.semester
- core_markingperiod -> {schema}.marking_period
- core_gradeleveltuitionfee -> {schema}.grade_level_tuition_fee
"""

from __future__ import annotations

from typing import Iterable

import psycopg2
from psycopg2.extras import execute_values

from django.core.management.base import BaseCommand, CommandError


class Command(BaseCommand):
    help = "Migrate v1 data to one v2 tenant schema (single-tenant mode)."

    def add_arguments(self, parser):
        parser.add_argument("--src-db", required=True, type=str, help="v1 PostgreSQL URL")
        parser.add_argument("--dst-db", required=True, type=str, help="v2 PostgreSQL URL")
        parser.add_argument("--schema", required=True, type=str, help="Target v2 tenant schema")
        parser.add_argument(
            "--batch",
            required=True,
            choices=[
                "academics_core",
                "academics_non_schedule",
                "students_core",
                "staff_core",
                "finance_core",
                "grading_core",
            ],
            help="Batch to run",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Preview counts and SQL flow without writing to destination",
        )

    def handle(self, *args, **options):
        src_db = options["src_db"]
        dst_db = options["dst_db"]
        schema = options["schema"].strip()
        batch = options["batch"]
        dry_run = bool(options["dry_run"])

        if not schema:
            raise CommandError("--schema cannot be empty")

        self.stdout.write(self.style.SUCCESS(f"Starting batch={batch}, schema={schema}, dry_run={dry_run}"))

        src_conn = psycopg2.connect(src_db)
        dst_conn = psycopg2.connect(dst_db)

        try:
            src_conn.autocommit = False
            dst_conn.autocommit = False

            with src_conn.cursor() as src_cur, dst_conn.cursor() as dst_cur:
                school_id = self._get_source_school_id(src_cur)
                self.stdout.write(f"Source school_id: {school_id}")

                if batch == "academics_core":
                    summary = self._migrate_academics_core(
                        src_cur=src_cur,
                        dst_cur=dst_cur,
                        school_id=school_id,
                        schema=schema,
                        dry_run=dry_run,
                    )
                elif batch == "academics_non_schedule":
                    summary = self._migrate_academics_non_schedule(
                        src_cur=src_cur,
                        dst_cur=dst_cur,
                        school_id=school_id,
                        schema=schema,
                        dry_run=dry_run,
                    )
                elif batch == "students_core":
                    summary = self._migrate_students_core(
                        src_cur=src_cur,
                        dst_cur=dst_cur,
                        school_id=school_id,
                        schema=schema,
                        dry_run=dry_run,
                    )
                elif batch == "staff_core":
                    summary = self._migrate_staff_core(
                        src_cur=src_cur,
                        dst_cur=dst_cur,
                        school_id=school_id,
                        schema=schema,
                        dry_run=dry_run,
                    )
                elif batch == "finance_core":
                    summary = self._migrate_finance_core(
                        src_cur=src_cur,
                        dst_cur=dst_cur,
                        school_id=school_id,
                        schema=schema,
                        dry_run=dry_run,
                    )
                elif batch == "grading_core":
                    summary = self._migrate_grading_core(
                        src_cur=src_cur,
                        dst_cur=dst_cur,
                        school_id=school_id,
                        schema=schema,
                        dry_run=dry_run,
                    )
                else:
                    raise CommandError(f"Unsupported batch: {batch}")

                if dry_run:
                    dst_conn.rollback()
                    self.stdout.write(self.style.WARNING("Dry-run complete. Destination transaction rolled back."))
                else:
                    dst_conn.commit()
                    self.stdout.write(self.style.SUCCESS("Migration batch committed."))

                src_conn.commit()

                self.stdout.write(self.style.SUCCESS("Batch summary:"))
                for key, value in summary.items():
                    self.stdout.write(f"- {key}: {value}")

        except Exception as exc:
            dst_conn.rollback()
            src_conn.rollback()
            raise CommandError(f"Migration failed and rolled back: {exc}") from exc
        finally:
            src_conn.close()
            dst_conn.close()

    def _get_source_school_id(self, src_cur) -> str:
        src_cur.execute(
            """
            SELECT id
            FROM core_school
            ORDER BY active DESC, created_at ASC
            LIMIT 1
            """
        )
        row = src_cur.fetchone()
        if not row:
            raise CommandError("No school rows found in v1 core_school")
        return str(row[0])

    def _migrate_academics_core(self, src_cur, dst_cur, school_id: str, schema: str, dry_run: bool) -> dict:
        summary = {}

        divisions = self._fetch_rows(
            src_cur,
            """
            SELECT id, active, created_at, updated_at, name, description
            FROM core_division
            WHERE school_id = %s
            ORDER BY name
            """,
            (school_id,),
        )
        summary["src.core_division"] = len(divisions)
        self._insert_rows(
            dst_cur,
            schema,
            "division",
            ["id", "active", "created_at", "updated_at", "name", "description", "created_by_id", "updated_by_id"],
            [
                (
                    str(r[0]),
                    r[1],
                    r[2],
                    r[3],
                    r[4],
                    r[5],
                    None,
                    None,
                )
                for r in divisions
            ],
            dry_run,
        )

        grade_levels = self._fetch_rows(
            src_cur,
            """
            SELECT id, active, created_at, updated_at, level, name, description, division_id, max_class_capacity, short_name
            FROM core_gradelevel
            WHERE school_id = %s
            ORDER BY level, name
            """,
            (school_id,),
        )
        summary["src.core_gradelevel"] = len(grade_levels)
        self._insert_rows(
            dst_cur,
            schema,
            "grade_level",
            [
                "id",
                "active",
                "created_at",
                "updated_at",
                "level",
                "name",
                "description",
                "division_id",
                "max_class_capacity",
                "short_name",
                "created_by_id",
                "updated_by_id",
            ],
            [
                (
                    str(r[0]),
                    r[1],
                    r[2],
                    r[3],
                    r[4],
                    r[5],
                    r[6],
                    str(r[7]) if r[7] else None,
                    r[8],
                    r[9],
                    None,
                    None,
                )
                for r in grade_levels
            ],
            dry_run,
        )

        sections = self._fetch_rows(
            src_cur,
            """
            SELECT id, active, created_at, updated_at, name, description, grade_level_id, max_capacity, tuition_fee
            FROM core_section
            WHERE grade_level_id IN (
                SELECT id FROM core_gradelevel WHERE school_id = %s
            )
            ORDER BY name
            """,
            (school_id,),
        )
        summary["src.core_section"] = len(sections)
        self._insert_rows(
            dst_cur,
            schema,
            "section",
            [
                "id",
                "active",
                "created_at",
                "updated_at",
                "name",
                "description",
                "grade_level_id",
                "max_capacity",
                "tuition_fee",
                "room_number",
                "created_by_id",
                "updated_by_id",
            ],
            [
                (
                    str(r[0]),
                    r[1],
                    r[2],
                    r[3],
                    r[4],
                    r[5],
                    str(r[6]) if r[6] else None,
                    r[7],
                    r[8],
                    None,
                    None,
                    None,
                )
                for r in sections
            ],
            dry_run,
        )

        subjects = self._fetch_rows(
            src_cur,
            """
            SELECT id, active, created_at, updated_at, name, description
            FROM core_subject
            WHERE school_id = %s
            ORDER BY name
            """,
            (school_id,),
        )
        summary["src.core_subject"] = len(subjects)
        self._insert_rows(
            dst_cur,
            schema,
            "subject",
            ["id", "active", "created_at", "updated_at", "name", "description", "created_by_id", "updated_by_id"],
            [
                (
                    str(r[0]),
                    r[1],
                    r[2],
                    r[3],
                    r[4],
                    r[5],
                    None,
                    None,
                )
                for r in subjects
            ],
            dry_run,
        )

        section_subjects = self._fetch_rows(
            src_cur,
            """
            SELECT ss.id, ss.active, ss.created_at, ss.updated_at, ss.section_id, ss.subject_id
            FROM core_sectionsubject ss
            JOIN core_section s ON s.id = ss.section_id
            JOIN core_gradelevel gl ON gl.id = s.grade_level_id
            WHERE gl.school_id = %s
            ORDER BY ss.subject_id
            """,
            (school_id,),
        )
        summary["src.core_sectionsubject"] = len(section_subjects)
        self._insert_rows(
            dst_cur,
            schema,
            "section_subject",
            ["id", "active", "created_at", "updated_at", "section_id", "subject_id", "created_by_id", "updated_by_id"],
            [
                (
                    str(r[0]),
                    r[1],
                    r[2],
                    r[3],
                    str(r[4]) if r[4] else None,
                    str(r[5]) if r[5] else None,
                    None,
                    None,
                )
                for r in section_subjects
            ],
            dry_run,
        )

        for table in ["division", "grade_level", "section", "subject", "section_subject"]:
            dst_cur.execute(f"SELECT COUNT(*) FROM {schema}.{table}")
            summary[f"dst.{table}"] = dst_cur.fetchone()[0]

        return summary

    def _migrate_academics_non_schedule(self, src_cur, dst_cur, school_id: str, schema: str, dry_run: bool) -> dict:
        """Migrate non-schedule academics data.

        This batch intentionally skips period/period_time/section_schedule tables.
        """
        summary = {}

        academic_years = self._fetch_rows(
            src_cur,
            """
            SELECT id, active, created_at, updated_at, start_date, end_date, name, current, status
            FROM core_academicyear
            WHERE school_id = %s
            ORDER BY start_date DESC
            """,
            (school_id,),
        )
        summary["src.core_academicyear"] = len(academic_years)
        self._insert_rows(
            dst_cur,
            schema,
            "academic_year",
            [
                "id",
                "active",
                "created_at",
                "updated_at",
                "start_date",
                "end_date",
                "name",
                "current",
                "status",
                "created_by_id",
                "updated_by_id",
            ],
            [
                (
                    str(r[0]),
                    r[1],
                    r[2],
                    r[3],
                    r[4],
                    r[5],
                    r[6],
                    r[7],
                    r[8],
                    None,
                    None,
                )
                for r in academic_years
            ],
            dry_run,
        )

        semesters = self._fetch_rows(
            src_cur,
            """
            SELECT id, active, created_at, updated_at, academic_year_id, name, start_date, end_date
            FROM core_semester
            WHERE school_id = %s
            ORDER BY start_date, name
            """,
            (school_id,),
        )
        summary["src.core_semester"] = len(semesters)
        self._insert_rows(
            dst_cur,
            schema,
            "semester",
            [
                "id",
                "active",
                "created_at",
                "updated_at",
                "academic_year_id",
                "name",
                "start_date",
                "end_date",
                "created_by_id",
                "updated_by_id",
            ],
            [
                (
                    str(r[0]),
                    r[1],
                    r[2],
                    r[3],
                    str(r[4]) if r[4] else None,
                    r[5],
                    r[6],
                    r[7],
                    None,
                    None,
                )
                for r in semesters
            ],
            dry_run,
        )

        marking_periods = self._fetch_rows(
            src_cur,
            """
            SELECT id, active, created_at, updated_at, semester_id, name, short_name, description, start_date, end_date
            FROM core_markingperiod
            WHERE semester_id IN (
                SELECT id FROM core_semester WHERE school_id = %s
            )
            ORDER BY start_date, name
            """,
            (school_id,),
        )
        summary["src.core_markingperiod"] = len(marking_periods)
        self._insert_rows(
            dst_cur,
            schema,
            "marking_period",
            [
                "id",
                "active",
                "created_at",
                "updated_at",
                "semester_id",
                "name",
                "short_name",
                "description",
                "start_date",
                "end_date",
                "created_by_id",
                "updated_by_id",
            ],
            [
                (
                    str(r[0]),
                    r[1],
                    r[2],
                    r[3],
                    str(r[4]) if r[4] else None,
                    r[5],
                    r[6],
                    r[7],
                    r[8],
                    r[9],
                    None,
                    None,
                )
                for r in marking_periods
            ],
            dry_run,
        )

        tuition_fees = self._fetch_rows(
            src_cur,
            """
            SELECT id, active, created_at, updated_at, grade_level_id, targeted_student_type, amount
            FROM core_gradeleveltuitionfee
            WHERE grade_level_id IN (
                SELECT id FROM core_gradelevel WHERE school_id = %s
            )
            ORDER BY grade_level_id
            """,
            (school_id,),
        )
        summary["src.core_gradeleveltuitionfee"] = len(tuition_fees)
        self._insert_rows(
            dst_cur,
            schema,
            "grade_level_tuition_fee",
            [
                "id",
                "active",
                "created_at",
                "updated_at",
                "grade_level_id",
                "targeted_student_type",
                "amount",
                "created_by_id",
                "updated_by_id",
            ],
            [
                (
                    str(r[0]),
                    r[1],
                    r[2],
                    r[3],
                    str(r[4]) if r[4] else None,
                    r[5],
                    r[6],
                    None,
                    None,
                )
                for r in tuition_fees
            ],
            dry_run,
        )

        for table in ["academic_year", "semester", "marking_period", "grade_level_tuition_fee"]:
            dst_cur.execute(f"SELECT COUNT(*) FROM {schema}.{table}")
            summary[f"dst.{table}"] = dst_cur.fetchone()[0]

        return summary

    def _migrate_students_core(self, src_cur, dst_cur, school_id: str, schema: str, dry_run: bool) -> dict:
        """Migrate students core data without legacy gradebook transformations."""
        summary = {}

        # Keep student sequence aligned for future inserts in v2.
        src_cur.execute(
            """
            SELECT COALESCE(MAX(student_seq), 0)
            FROM students_student
            WHERE school_id = %s
            """,
            (school_id,),
        )
        max_seq = src_cur.fetchone()[0] or 0
        summary["src.students_student.max_seq"] = int(max_seq)

        if dry_run:
            self.stdout.write(f"[dry-run] would upsert {schema}.student_sequence(id=1,last_seq={max_seq})")
        else:
            dst_cur.execute(
                f"""
                INSERT INTO {schema}.student_sequence (id, last_seq)
                VALUES (1, %s)
                ON CONFLICT (id)
                DO UPDATE SET last_seq = EXCLUDED.last_seq
                """,
                (int(max_seq),),
            )

        students = self._fetch_rows(
            src_cur,
            """
            SELECT
                s.id,
                s.active,
                s.created_at,
                s.updated_at,
                s.first_name,
                s.middle_name,
                s.last_name,
                s.date_of_birth,
                s.gender,
                s.email,
                s.phone_number,
                s.address,
                s.city,
                s.state,
                s.postal_code,
                s.country,
                s.place_of_birth,
                s.status,
                s.photo,
                s.prev_id_number,
                s.date_of_graduation,
                s.entry_date,
                s.grade_level_id,
                s.entry_as,
                s.school_code,
                s.student_seq,
                s.id_number,
                u.id_number AS user_account_id_number,
                NULL::date AS withdrawal_date,
                NULL::text AS withdrawal_reason
            FROM students_student s
            LEFT JOIN users_customuser u ON u.id = s.user_account_id
            WHERE s.school_id = %s
            ORDER BY s.last_name, s.first_name
            """,
            (school_id,),
        )
        summary["src.students_student"] = len(students)

        self._insert_rows(
            dst_cur,
            schema,
            "student",
            [
                "id",
                "active",
                "created_at",
                "updated_at",
                "first_name",
                "middle_name",
                "last_name",
                "date_of_birth",
                "gender",
                "email",
                "phone_number",
                "address",
                "city",
                "state",
                "postal_code",
                "country",
                "place_of_birth",
                "status",
                "photo",
                "prev_id_number",
                "date_of_graduation",
                "entry_date",
                "grade_level_id",
                "entry_as",
                "school_code",
                "student_seq",
                "id_number",
                "user_account_id_number",
                "withdrawal_date",
                "withdrawal_reason",
                "created_by_id",
                "updated_by_id",
            ],
            [
                (
                    str(r[0]),
                    r[1],
                    r[2],
                    r[3],
                    r[4],
                    r[5],
                    r[6],
                    r[7],
                    r[8],
                    r[9],
                    r[10],
                    r[11],
                    r[12],
                    r[13],
                    r[14],
                    r[15],
                    r[16],
                    r[17],
                    r[18],
                    r[19],
                    r[20],
                    r[21],
                    str(r[22]) if r[22] else None,
                    r[23],
                    r[24],
                    r[25],
                    r[26],
                    r[27],
                    r[28],
                    r[29],
                    None,
                    None,
                )
                for r in students
            ],
            dry_run,
        )

        enrollments = self._fetch_rows(
            src_cur,
            """
            SELECT
                e.id,
                e.active,
                e.created_at,
                e.updated_at,
                e.student_id,
                e.academic_year_id,
                e.grade_level_id,
                e.next_grade_level_id,
                e.section_id,
                e.date_enrolled,
                e.notes,
                e.status,
                e.enrolled_as
            FROM students_enrollment e
            JOIN students_student s ON s.id = e.student_id
            WHERE s.school_id = %s
            ORDER BY e.date_enrolled, e.created_at
            """,
            (school_id,),
        )
        summary["src.students_enrollment"] = len(enrollments)

        self._insert_rows(
            dst_cur,
            schema,
            "enrollment",
            [
                "id",
                "active",
                "created_at",
                "updated_at",
                "student_id",
                "academic_year_id",
                "grade_level_id",
                "next_grade_level_id",
                "section_id",
                "date_enrolled",
                "notes",
                "status",
                "enrolled_as",
                "created_by_id",
                "updated_by_id",
            ],
            [
                (
                    str(r[0]),
                    r[1],
                    r[2],
                    r[3],
                    str(r[4]) if r[4] else None,
                    str(r[5]) if r[5] else None,
                    str(r[6]) if r[6] else None,
                    str(r[7]) if r[7] else None,
                    str(r[8]) if r[8] else None,
                    r[9],
                    r[10],
                    r[11],
                    r[12],
                    None,
                    None,
                )
                for r in enrollments
            ],
            dry_run,
        )

        attendance_rows = self._fetch_rows(
            src_cur,
            """
            SELECT
                a.id,
                a.active,
                a.created_at,
                a.updated_at,
                a.enrollment_id,
                a.date,
                a.status,
                a.notes
            FROM students_attendance a
            JOIN students_enrollment e ON e.id = a.enrollment_id
            JOIN students_student s ON s.id = e.student_id
            WHERE s.school_id = %s
            ORDER BY a.date, a.created_at
            """,
            (school_id,),
        )
        summary["src.students_attendance"] = len(attendance_rows)

        self._insert_rows(
            dst_cur,
            schema,
            "attendance",
            [
                "id",
                "active",
                "created_at",
                "updated_at",
                "enrollment_id",
                "date",
                "status",
                "notes",
                "created_by_id",
                "updated_by_id",
            ],
            [
                (
                    str(r[0]),
                    r[1],
                    r[2],
                    r[3],
                    str(r[4]) if r[4] else None,
                    r[5],
                    r[6],
                    r[7],
                    None,
                    None,
                )
                for r in attendance_rows
            ],
            dry_run,
        )

        bills = self._fetch_rows(
            src_cur,
            """
            SELECT
                b.id,
                b.active,
                b.created_at,
                b.updated_at,
                b.enrollment_id,
                b.name,
                b.amount,
                b.type,
                b.notes
            FROM students_studentenrollmentbill b
            JOIN students_enrollment e ON e.id = b.enrollment_id
            JOIN students_student s ON s.id = e.student_id
            WHERE s.school_id = %s
            ORDER BY b.created_at
            """,
            (school_id,),
        )
        summary["src.students_studentenrollmentbill"] = len(bills)

        self._insert_rows(
            dst_cur,
            schema,
            "enrollment_bill",
            [
                "id",
                "active",
                "created_at",
                "updated_at",
                "enrollment_id",
                "name",
                "amount",
                "type",
                "notes",
                "created_by_id",
                "updated_by_id",
            ],
            [
                (
                    str(r[0]),
                    r[1],
                    r[2],
                    r[3],
                    str(r[4]) if r[4] else None,
                    r[5],
                    r[6],
                    r[7],
                    r[8],
                    None,
                    None,
                )
                for r in bills
            ],
            dry_run,
        )

        for table in ["student_sequence", "student", "enrollment", "attendance", "enrollment_bill"]:
            dst_cur.execute(f"SELECT COUNT(*) FROM {schema}.{table}")
            summary[f"dst.{table}"] = dst_cur.fetchone()[0]

        return summary

    def _migrate_staff_core(self, src_cur, dst_cur, school_id: str, schema: str, dry_run: bool) -> dict:
        """Migrate staff core data (excluding teacher_subject and teacher_schedule)."""
        summary = {}

        departments = self._fetch_rows(
            src_cur,
            """
            SELECT id, active, created_at, updated_at, name, code, description
            FROM staff_department
            WHERE school_id = %s
            ORDER BY name
            """,
            (school_id,),
        )
        summary["src.staff_department"] = len(departments)
        self._insert_rows(
            dst_cur,
            schema,
            "department",
            ["id", "active", "created_at", "updated_at", "name", "code", "description", "created_by_id", "updated_by_id"],
            [
                (
                    str(r[0]),
                    r[1],
                    r[2],
                    r[3],
                    r[4],
                    r[5],
                    r[6],
                    None,
                    None,
                )
                for r in departments
            ],
            dry_run,
        )

        categories = self._fetch_rows(
            src_cur,
            """
            SELECT id, active, created_at, updated_at, name, description
            FROM staff_positioncategory
            WHERE school_id = %s
            ORDER BY name
            """,
            (school_id,),
        )
        summary["src.staff_positioncategory"] = len(categories)
        self._insert_rows(
            dst_cur,
            schema,
            "position_category",
            ["id", "active", "created_at", "updated_at", "name", "description", "created_by_id", "updated_by_id"],
            [
                (
                    str(r[0]),
                    r[1],
                    r[2],
                    r[3],
                    r[4],
                    r[5],
                    None,
                    None,
                )
                for r in categories
            ],
            dry_run,
        )

        positions = self._fetch_rows(
            src_cur,
            """
            SELECT
                id,
                active,
                created_at,
                updated_at,
                category_id,
                department_id,
                title,
                code,
                description,
                level,
                employment_type,
                compensation_type,
                salary_min,
                salary_max,
                teaching_role,
                can_delete
            FROM staff_position
            WHERE school_id = %s
            ORDER BY level, title
            """,
            (school_id,),
        )
        summary["src.staff_position"] = len(positions)
        self._insert_rows(
            dst_cur,
            schema,
            "position",
            [
                "id",
                "active",
                "created_at",
                "updated_at",
                "category_id",
                "department_id",
                "title",
                "code",
                "description",
                "level",
                "employment_type",
                "compensation_type",
                "salary_min",
                "salary_max",
                "teaching_role",
                "can_delete",
                "created_by_id",
                "updated_by_id",
            ],
            [
                (
                    str(r[0]),
                    r[1],
                    r[2],
                    r[3],
                    str(r[4]) if r[4] else None,
                    str(r[5]) if r[5] else None,
                    r[6],
                    r[7],
                    r[8],
                    r[9],
                    r[10],
                    r[11],
                    r[12],
                    r[13],
                    r[14],
                    r[15],
                    None,
                    None,
                )
                for r in positions
            ],
            dry_run,
        )

        staff_rows = self._fetch_rows(
            src_cur,
            """
            SELECT
                st.id,
                st.active,
                st.created_at,
                st.updated_at,
                st.first_name,
                st.middle_name,
                st.last_name,
                st.date_of_birth,
                st.gender,
                st.email,
                st.phone_number,
                st.address,
                st.city,
                st.state,
                st.postal_code,
                st.country,
                st.place_of_birth,
                st.hire_date,
                st.status,
                st.photo,
                st.primary_department_id,
                st.id_number,
                st.is_teacher,
                st.position_id,
                u.id_number AS user_account_id_number,
                NULL::date AS suspension_date,
                NULL::text AS suspension_reason,
                NULL::date AS termination_date,
                NULL::text AS termination_reason,
                NULL::uuid AS manager_id
            FROM staff_staff st
            LEFT JOIN users_customuser u ON u.id = st.user_account_id
            WHERE st.school_id = %s
            ORDER BY st.last_name, st.first_name
            """,
            (school_id,),
        )
        summary["src.staff_staff"] = len(staff_rows)
        self._insert_rows(
            dst_cur,
            schema,
            "staff",
            [
                "id",
                "active",
                "created_at",
                "updated_at",
                "first_name",
                "middle_name",
                "last_name",
                "date_of_birth",
                "gender",
                "email",
                "phone_number",
                "address",
                "city",
                "state",
                "postal_code",
                "country",
                "place_of_birth",
                "hire_date",
                "status",
                "photo",
                "primary_department_id",
                "id_number",
                "is_teacher",
                "position_id",
                "user_account_id_number",
                "suspension_date",
                "suspension_reason",
                "termination_date",
                "termination_reason",
                "manager_id",
                "created_by_id",
                "updated_by_id",
            ],
            [
                (
                    str(r[0]),
                    r[1],
                    r[2],
                    r[3],
                    r[4],
                    r[5],
                    r[6],
                    r[7],
                    r[8],
                    r[9],
                    r[10],
                    r[11],
                    r[12],
                    r[13],
                    r[14],
                    r[15],
                    r[16],
                    r[17],
                    r[18],
                    r[19],
                    str(r[20]) if r[20] else None,
                    r[21],
                    r[22],
                    str(r[23]) if r[23] else None,
                    r[24],
                    r[25],
                    r[26],
                    r[27],
                    r[28],
                    str(r[29]) if r[29] else None,
                    None,
                    None,
                )
                for r in staff_rows
            ],
            dry_run,
        )

        teacher_sections = self._fetch_rows(
            src_cur,
            """
            SELECT ts.id, ts.active, ts.created_at, ts.updated_at, ts.teacher_id, ts.section_id
            FROM staff_teachersection ts
            JOIN staff_staff st ON st.id = ts.teacher_id
            WHERE st.school_id = %s
            ORDER BY ts.created_at
            """,
            (school_id,),
        )
        summary["src.staff_teachersection"] = len(teacher_sections)
        self._insert_rows(
            dst_cur,
            schema,
            "teacher_section",
            ["id", "active", "created_at", "updated_at", "teacher_id", "section_id", "created_by_id", "updated_by_id"],
            [
                (
                    str(r[0]),
                    r[1],
                    r[2],
                    r[3],
                    str(r[4]) if r[4] else None,
                    str(r[5]) if r[5] else None,
                    None,
                    None,
                )
                for r in teacher_sections
            ],
            dry_run,
        )

        for table in ["department", "position_category", "position", "staff", "teacher_section"]:
            dst_cur.execute(f"SELECT COUNT(*) FROM {schema}.{table}")
            summary[f"dst.{table}"] = dst_cur.fetchone()[0]

        return summary

    def _migrate_finance_core(self, src_cur, dst_cur, school_id: str, schema: str, dry_run: bool) -> dict:
        """Migrate finance tables including transactions and installments."""
        summary = {}

        bank_accounts = self._fetch_rows(
            src_cur,
            """
            SELECT id, active, created_at, updated_at, number, bank_number, name, description
            FROM finance_bankaccount
            WHERE school_id = %s
            ORDER BY name
            """,
            (school_id,),
        )
        summary["src.finance_bankaccount"] = len(bank_accounts)
        self._insert_rows(
            dst_cur,
            schema,
            "bank_account",
            ["id", "active", "created_at", "updated_at", "number", "bank_number", "name", "description", "created_by_id", "updated_by_id"],
            [
                (
                    str(r[0]),
                    r[1],
                    r[2],
                    r[3],
                    r[4],
                    r[5],
                    r[6],
                    r[7],
                    None,
                    None,
                )
                for r in bank_accounts
            ],
            dry_run,
        )

        payment_methods = self._fetch_rows(
            src_cur,
            """
            SELECT id, active, created_at, updated_at, name, description, is_editable
            FROM finance_paymentmethod
            WHERE school_id = %s
            ORDER BY name
            """,
            (school_id,),
        )
        summary["src.finance_paymentmethod"] = len(payment_methods)
        self._insert_rows(
            dst_cur,
            schema,
            "payment_method",
            ["id", "active", "created_at", "updated_at", "name", "description", "is_editable", "created_by_id", "updated_by_id"],
            [
                (
                    str(r[0]),
                    r[1],
                    r[2],
                    r[3],
                    r[4],
                    r[5],
                    r[6],
                    None,
                    None,
                )
                for r in payment_methods
            ],
            dry_run,
        )

        currencies = self._fetch_rows(
            src_cur,
            """
            SELECT id, active, created_at, updated_at, name, symbol, code
            FROM finance_currency
            WHERE school_id = %s
            ORDER BY name
            """,
            (school_id,),
        )
        summary["src.finance_currency"] = len(currencies)
        self._insert_rows(
            dst_cur,
            schema,
            "currency",
            ["id", "active", "created_at", "updated_at", "name", "symbol", "code", "created_by_id", "updated_by_id"],
            [
                (
                    str(r[0]),
                    r[1],
                    r[2],
                    r[3],
                    r[4],
                    r[5],
                    r[6],
                    None,
                    None,
                )
                for r in currencies
            ],
            dry_run,
        )

        general_fees = self._fetch_rows(
            src_cur,
            """
            SELECT id, active, created_at, updated_at, name, description, amount, student_target
            FROM finance_generalfeelist
            WHERE school_id = %s
            ORDER BY name
            """,
            (school_id,),
        )
        summary["src.finance_generalfeelist"] = len(general_fees)
        self._insert_rows(
            dst_cur,
            schema,
            "general_fee_list",
            ["id", "active", "created_at", "updated_at", "name", "description", "amount", "student_target", "created_by_id", "updated_by_id"],
            [
                (
                    str(r[0]),
                    r[1],
                    r[2],
                    r[3],
                    r[4],
                    r[5],
                    r[6],
                    r[7],
                    None,
                    None,
                )
                for r in general_fees
            ],
            dry_run,
        )

        section_fees = self._fetch_rows(
            src_cur,
            """
            SELECT sf.id, sf.active, sf.created_at, sf.updated_at, sf.section_id, sf.general_fee_id, sf.amount
            FROM finance_sectionfee sf
            JOIN core_section s ON s.id = sf.section_id
            JOIN core_gradelevel gl ON gl.id = s.grade_level_id
            WHERE gl.school_id = %s
            ORDER BY sf.created_at
            """,
            (school_id,),
        )
        summary["src.finance_sectionfee"] = len(section_fees)
        self._insert_rows(
            dst_cur,
            schema,
            "section_fee",
            ["id", "active", "created_at", "updated_at", "section_id", "general_fee_id", "amount", "created_by_id", "updated_by_id"],
            [
                (
                    str(r[0]),
                    r[1],
                    r[2],
                    r[3],
                    str(r[4]) if r[4] else None,
                    str(r[5]) if r[5] else None,
                    r[6],
                    None,
                    None,
                )
                for r in section_fees
            ],
            dry_run,
        )

        txn_types = self._fetch_rows(
            src_cur,
            """
            SELECT id, active, created_at, updated_at, name, description, type_code, type, is_hidden, is_editable
            FROM finance_transactiontype
            WHERE school_id = %s
            ORDER BY name
            """,
            (school_id,),
        )
        summary["src.finance_transactiontype"] = len(txn_types)
        self._insert_rows(
            dst_cur,
            schema,
            "transaction_type",
            ["id", "active", "created_at", "updated_at", "name", "description", "type_code", "type", "is_hidden", "is_editable", "created_by_id", "updated_by_id"],
            [
                (
                    str(r[0]),
                    r[1],
                    r[2],
                    r[3],
                    r[4],
                    r[5],
                    r[6],
                    r[7],
                    r[8],
                    r[9],
                    None,
                    None,
                )
                for r in txn_types
            ],
            dry_run,
        )

        installments = self._fetch_rows(
            src_cur,
            """
            SELECT id, active, created_at, updated_at, academic_year_id, name, description, value, due_date, sequence
            FROM finance_paymentinstallment
            WHERE school_id = %s
            ORDER BY academic_year_id, sequence, due_date
            """,
            (school_id,),
        )
        summary["src.finance_paymentinstallment"] = len(installments)
        self._insert_rows(
            dst_cur,
            schema,
            "payment_installment",
            ["id", "active", "created_at", "updated_at", "academic_year_id", "name", "description", "value", "due_date", "sequence", "created_by_id", "updated_by_id"],
            [
                (
                    str(r[0]),
                    r[1],
                    r[2],
                    r[3],
                    str(r[4]) if r[4] else None,
                    r[5],
                    r[6],
                    r[7],
                    r[8],
                    r[9],
                    None,
                    None,
                )
                for r in installments
            ],
            dry_run,
        )

        transactions = self._fetch_rows(
            src_cur,
            """
            SELECT
                t.id,
                t.active,
                t.created_at,
                t.updated_at,
                t.type_id,
                t.account_id,
                t.transaction_id,
                t.student_id,
                t.academic_year_id,
                t.payment_method_id,
                t.date,
                t.reference,
                t.description,
                t.amount,
                t.notes,
                t.status
            FROM finance_transaction t
            JOIN finance_bankaccount ba ON ba.id = t.account_id
            WHERE ba.school_id = %s
            ORDER BY t.created_at
            """,
            (school_id,),
        )
        summary["src.finance_transaction"] = len(transactions)
        self._insert_rows(
            dst_cur,
            schema,
            "transaction",
            [
                "id",
                "active",
                "created_at",
                "updated_at",
                "type_id",
                "account_id",
                "transaction_id",
                "student_id",
                "academic_year_id",
                "payment_method_id",
                "date",
                "reference",
                "description",
                "amount",
                "notes",
                "status",
                "created_by_id",
                "updated_by_id",
            ],
            [
                (
                    str(r[0]),
                    r[1],
                    r[2],
                    r[3],
                    str(r[4]) if r[4] else None,
                    str(r[5]) if r[5] else None,
                    r[6],
                    str(r[7]) if r[7] else None,
                    str(r[8]) if r[8] else None,
                    str(r[9]) if r[9] else None,
                    r[10],
                    r[11],
                    r[12],
                    r[13],
                    r[14],
                    r[15],
                    None,
                    None,
                )
                for r in transactions
            ],
            dry_run,
        )

        for table in [
            "bank_account",
            "payment_method",
            "currency",
            "general_fee_list",
            "section_fee",
            "transaction_type",
            "payment_installment",
            "transaction",
        ]:
            dst_cur.execute(f"SELECT COUNT(*) FROM {schema}.{table}")
            summary[f"dst.{table}"] = dst_cur.fetchone()[0]

        return summary

    def _migrate_grading_core(self, src_cur, dst_cur, school_id: str, schema: str, dry_run: bool) -> dict:
        """Migrate grading core tables excluding grade_history."""
        summary = {}

        grade_letters = self._fetch_rows(
            src_cur,
            """
            SELECT id, active, created_at, updated_at, letter, min_percentage, max_percentage, "order"
            FROM grading_gradeletter
            WHERE school_id = %s
            ORDER BY "order", letter
            """,
            (school_id,),
        )
        summary["src.grading_gradeletter"] = len(grade_letters)
        self._insert_rows(
            dst_cur,
            schema,
            "grade_letter",
            ["id", "active", "created_at", "updated_at", "letter", "min_percentage", "max_percentage", '"order"', "created_by_id", "updated_by_id"],
            [
                (
                    str(r[0]),
                    r[1],
                    r[2],
                    r[3],
                    r[4],
                    r[5],
                    r[6],
                    r[7],
                    None,
                    None,
                )
                for r in grade_letters
            ],
            dry_run,
        )

        assessment_types = self._fetch_rows(
            src_cur,
            """
            SELECT id, active, created_at, updated_at, name, description, is_single_entry
            FROM grading_assessmenttype
            WHERE school_id = %s
            ORDER BY name
            """,
            (school_id,),
        )
        summary["src.grading_assessmenttype"] = len(assessment_types)
        self._insert_rows(
            dst_cur,
            schema,
            "assessment_type",
            ["id", "active", "created_at", "updated_at", "name", "description", "is_single_entry", "created_by_id", "updated_by_id"],
            [
                (
                    str(r[0]),
                    r[1],
                    r[2],
                    r[3],
                    r[4],
                    r[5],
                    r[6],
                    None,
                    None,
                )
                for r in assessment_types
            ],
            dry_run,
        )

        gradebooks = self._fetch_rows(
            src_cur,
            """
            SELECT id, active, created_at, updated_at, name, calculation_method, academic_year_id, section_id, section_subject_id, subject_id
            FROM grading_gradebook
            ORDER BY created_at, name
            """,
            (),
        )
        summary["src.grading_gradebook"] = len(gradebooks)
        self._insert_rows(
            dst_cur,
            schema,
            "gradebook",
            [
                "id",
                "active",
                "created_at",
                "updated_at",
                "name",
                "calculation_method",
                "academic_year_id",
                "section_id",
                "section_subject_id",
                "subject_id",
                "created_by_id",
                "updated_by_id",
            ],
            [
                (
                    str(r[0]),
                    r[1],
                    r[2],
                    r[3],
                    r[4],
                    r[5],
                    str(r[6]) if r[6] else None,
                    str(r[7]) if r[7] else None,
                    str(r[8]) if r[8] else None,
                    str(r[9]) if r[9] else None,
                    None,
                    None,
                )
                for r in gradebooks
            ],
            dry_run,
        )

        assessments = self._fetch_rows(
            src_cur,
            """
            SELECT
                id,
                active,
                created_at,
                updated_at,
                name,
                max_score,
                weight,
                due_date,
                is_calculated,
                marking_period_id,
                assessment_type_id,
                gradebook_id
            FROM grading_assessment
            ORDER BY created_at, name
            """,
            (),
        )
        summary["src.grading_assessment"] = len(assessments)
        self._insert_rows(
            dst_cur,
            schema,
            "assessment",
            [
                "id",
                "active",
                "created_at",
                "updated_at",
                "name",
                "max_score",
                "weight",
                "due_date",
                "is_calculated",
                "marking_period_id",
                "assessment_type_id",
                "gradebook_id",
                "created_by_id",
                "updated_by_id",
            ],
            [
                (
                    str(r[0]),
                    r[1],
                    r[2],
                    r[3],
                    r[4],
                    r[5],
                    r[6],
                    r[7],
                    r[8],
                    str(r[9]) if r[9] else None,
                    str(r[10]) if r[10] else None,
                    str(r[11]) if r[11] else None,
                    None,
                    None,
                )
                for r in assessments
            ],
            dry_run,
        )

        grades = self._fetch_rows(
            src_cur,
            """
            SELECT
                id,
                active,
                created_at,
                updated_at,
                score,
                status,
                comment,
                academic_year_id,
                assessment_id,
                enrollment_id,
                section_id,
                student_id,
                subject_id
            FROM grading_grade
            ORDER BY created_at
            """,
            (),
        )
        summary["src.grading_grade"] = len(grades)
        self._insert_rows(
            dst_cur,
            schema,
            "grade",
            [
                "id",
                "active",
                "created_at",
                "updated_at",
                "score",
                "status",
                "comment",
                "needs_correction",
                "academic_year_id",
                "assessment_id",
                "enrollment_id",
                "section_id",
                "student_id",
                "subject_id",
                "created_by_id",
                "updated_by_id",
            ],
            [
                (
                    str(r[0]),
                    r[1],
                    r[2],
                    r[3],
                    r[4],
                    r[5],
                    r[6],
                    False,
                    str(r[7]) if r[7] else None,
                    str(r[8]) if r[8] else None,
                    str(r[9]) if r[9] else None,
                    str(r[10]) if r[10] else None,
                    str(r[11]) if r[11] else None,
                    str(r[12]) if r[12] else None,
                    None,
                    None,
                )
                for r in grades
            ],
            dry_run,
        )

        templates = self._fetch_rows(
            src_cur,
            """
            SELECT
                id,
                active,
                created_at,
                updated_at,
                name,
                max_score,
                weight,
                is_calculated,
                "order",
                description,
                is_active,
                target,
                assessment_type_id
            FROM grading_defaultassessmenttemplate
            WHERE school_id = %s
            ORDER BY "order", name
            """,
            (school_id,),
        )
        summary["src.grading_defaultassessmenttemplate"] = len(templates)
        self._insert_rows(
            dst_cur,
            schema,
            "assessment_template",
            [
                "id",
                "active",
                "created_at",
                "updated_at",
                "name",
                "max_score",
                "weight",
                "is_calculated",
                '"order"',
                "description",
                "is_active",
                "target",
                "assessment_type_id",
                "created_by_id",
                "updated_by_id",
            ],
            [
                (
                    str(r[0]),
                    r[1],
                    r[2],
                    r[3],
                    r[4],
                    r[5],
                    r[6],
                    r[7],
                    r[8],
                    r[9],
                    r[10],
                    r[11],
                    str(r[12]) if r[12] else None,
                    None,
                    None,
                )
                for r in templates
            ],
            dry_run,
        )

        for table in ["grade_letter", "assessment_type", "gradebook", "assessment", "grade", "assessment_template"]:
            dst_cur.execute(f"SELECT COUNT(*) FROM {schema}.{table}")
            summary[f"dst.{table}"] = dst_cur.fetchone()[0]

        return summary

    def _fetch_rows(self, cursor, query: str, params: tuple) -> list:
        cursor.execute(query, params)
        return cursor.fetchall()

    def _insert_rows(
        self,
        dst_cur,
        schema: str,
        table: str,
        columns: list[str],
        rows: Iterable[tuple],
        dry_run: bool,
    ) -> None:
        rows = list(rows)
        if not rows:
            return

        if dry_run:
            self.stdout.write(f"[dry-run] would insert into {schema}.{table}: {len(rows)} rows")
            return

        col_sql = ", ".join(columns)
        insert_sql = f"INSERT INTO {schema}.{table} ({col_sql}) VALUES %s ON CONFLICT (id) DO NOTHING"
        execute_values(dst_cur, insert_sql, rows, page_size=500)
