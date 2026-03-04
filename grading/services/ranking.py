from collections import defaultdict
from decimal import Decimal, ROUND_HALF_UP
from typing import Dict, List, Optional

from django.core.cache import cache
from django.db.models import F, Q
from django.db.models.expressions import Window
from django.db.models.functions import DenseRank

from grading.models import Grade, Assessment, GradeBook
from students.models import Enrollment


class RankingService:
    """
    Service to handle student ranking calculations with optimization and caching.
    Supports ranking by:
    - Assessment
    - Subject (Marking Period or Final Average)
    - Overall (Marking Period or Final Average)

    Scopes:
    - Section
    - Grade Level
    - School
    """

    CACHE_TIMEOUT = 60 * 15  # 15 minutes

    @classmethod
    def get_assessment_rankings(
        cls, assessment_id: str, scope_type: str = "section", scope_id: str = None
    ) -> List[Dict]:
        """
        Rank students based on a specific assessment score.

        Args:
            assessment_id: ID of the assessment
            scope_type: 'section', 'grade_level', 'school' (derived from assessment typically,
                       but allows ranking across multiple sections if assessment is common)
        """
        try:
            assessment = Assessment.objects.select_related(
                "gradebook__section", "gradebook__section__grade_level"
            ).get(id=assessment_id)
        except Assessment.DoesNotExist:
            return []

        # Base query for grades
        # We want grades for this assessment (or equivalent assessments if ranking across sections?)
        # Usually assessment ranking is within the specific assessment instance (which belongs to one gradebook/section).
        # If we want to rank across sections, we need to find "equivalent" assessments (e.g. same name/type in other gradebooks).
        # For now, let's assume specific assessment ranking is usually within its gradebook (section).
        # But the user asked for "by class section, grade level...".
        # If ranking by grade level for "Quiz 1", we imply "Quiz 1" exists in all sections.

        if scope_type == "section":
            # Simple case: rank within the assessment's gradebook
            grades = (
                Grade.objects.filter(assessment_id=assessment_id, score__isnull=False)
                .select_related("student")
                .annotate(
                    rank=Window(expression=DenseRank(), order_by=F("score").desc())
                )
                .order_by("rank")
            )

            return cls._format_rank_results(grades, score_field="score")

        elif scope_type == "grade_level":
            # Complex case: Find equivalent assessments in same grade level
            # Assumption: Equivalent assessments share the same name and assessment_type
            grade_level = assessment.gradebook.section.grade_level

            equivalent_assessments = Assessment.objects.filter(
                gradebook__section__grade_level=grade_level,
                gradebook__subject=assessment.gradebook.subject,  # Same subject
                name=assessment.name,  # Same name
                assessment_type=assessment.assessment_type,  # Same type
            )

            grades = (
                Grade.objects.filter(
                    assessment__in=equivalent_assessments, score__isnull=False
                )
                .select_related("student", "assessment__gradebook__section")
                .annotate(
                    rank=Window(expression=DenseRank(), order_by=F("score").desc())
                )
                .order_by("rank")
            )

            return cls._format_rank_results(grades, score_field="score")

        return []

    @classmethod
    def get_subject_rankings(
        cls,
        subject_id: str,
        academic_year_id: str,
        scope_type: str = "grade_level",  # section, grade_level
        scope_id: str = None,  # ID of section or grade_level
        marking_period_id: str = None,  # If None, use Final Average
    ) -> List[Dict]:
        """
        Rank students in a specific subject.
        """
        cache_key = f"rank_subj:{subject_id}:{academic_year_id}:{scope_type}:{scope_id}:{marking_period_id}"
        cached = cache.get(cache_key)
        if cached:
            return cached

        # 1. Identify GradeBooks involved
        gb_filter = Q(
            subject_id=subject_id, academic_year_id=academic_year_id, active=True
        )

        if scope_type == "section":
            gb_filter &= Q(section_id=scope_id)
        elif scope_type == "grade_level":
            gb_filter &= Q(section__grade_level_id=scope_id)

        gradebooks = GradeBook.objects.filter(gb_filter).select_related("section")

        if not gradebooks.exists():
            return []

        # 2. Calculate averages for all students in these gradebooks
        # We'll do this in memory to handle complex calculation methods (weighted, etc)

        student_scores = []  # (student, score)

        # Pre-fetch grades for efficiency
        # Filter grades by these gradebooks
        # If marking_period_id is set, filter assessments by that MP

        grade_filter = Q(
            assessment__gradebook__in=gradebooks,
            status=Grade.Status.APPROVED,
            assessment__is_calculated=True,
        )

        if marking_period_id:
            grade_filter &= Q(assessment__marking_period_id=marking_period_id)

        grades = Grade.objects.filter(grade_filter).select_related(
            "student", "assessment", "assessment__gradebook", "enrollment__section"
        )

        # Group by student -> gradebook
        # Actually we just need Student -> Score for this subject
        # Since a student usually has 1 gradebook for a subject in a year,
        # we can calculate the score for that gradebook.

        grades_by_student_gb = defaultdict(list)
        students_map = {}  # id -> Student obj
        sections_map = {}  # student_id -> Section name

        for grade in grades:
            k = (grade.student_id, grade.assessment.gradebook_id)
            grades_by_student_gb[k].append(grade)
            students_map[grade.student_id] = grade.student
            sections_map[grade.student_id] = grade.enrollment.section.name

        # Calculate score for each student
        results = []

        for (student_id, gb_id), student_grades in grades_by_student_gb.items():
            if not student_grades:
                continue

            gb = student_grades[0].assessment.gradebook

            # Calculate percentage based on GB method
            score = cls._calculate_grades_average(student_grades, gb.calculation_method)

            if score is not None:
                results.append(
                    {
                        "student": students_map[student_id],
                        "score": score,
                        "section_name": sections_map.get(student_id, ""),
                        "gradebook_id": gb_id,
                    }
                )

        # 3. Rank
        ranked_results = cls._assign_ranks(results)

        cache.set(cache_key, ranked_results, cls.CACHE_TIMEOUT)
        return ranked_results

    @classmethod
    def get_overall_rankings(
        cls,
        academic_year_id: str,
        scope_type: str = "grade_level",
        scope_id: str = None,
        marking_period_id: str = None,
        semester_id: str = None,
    ) -> List[Dict]:
        """
        Rank students by overall average across all subjects.
        Can filter by marking_period_id OR semester_id.
        """
        cache_key = f"rank_overall:{academic_year_id}:{scope_type}:{scope_id}:{marking_period_id}:{semester_id}"
        cached = cache.get(cache_key)
        if cached:
            return cached

        # 1. Get Enrollments for scope
        enroll_filter = Q(academic_year_id=academic_year_id, active=True)
        if scope_type == "section":
            enroll_filter &= Q(section_id=scope_id)
        elif scope_type == "grade_level":
            enroll_filter &= Q(section__grade_level_id=scope_id)
        elif scope_type == "school":
            enroll_filter &= Q(student__school_id=scope_id)

        enrollments = Enrollment.objects.filter(enroll_filter).select_related(
            "student", "section"
        )

        if not enrollments.exists():
            return []

        student_ids = [e.student_id for e in enrollments]
        students_map = {e.student_id: e.student for e in enrollments}
        sections_map = {e.student_id: e.section.name for e in enrollments}

        # 2. Fetch ALL approved grades for these students
        grade_filter = Q(
            student_id__in=student_ids,
            status=Grade.Status.APPROVED,
            assessment__is_calculated=True,
            assessment__gradebook__academic_year_id=academic_year_id,
        )

        if marking_period_id:
            grade_filter &= Q(assessment__marking_period_id=marking_period_id)
        elif semester_id:
            grade_filter &= Q(assessment__marking_period__semester_id=semester_id)

        grades = Grade.objects.filter(grade_filter).select_related(
            "assessment", "assessment__gradebook"
        )

        # 3. Group by Student -> GradeBook -> Grades
        grades_by_student = defaultdict(lambda: defaultdict(list))

        for grade in grades:
            grades_by_student[grade.student_id][grade.assessment.gradebook].append(
                grade
            )

        # 4. Calculate Average for each student
        results = []

        for student_id, gb_map in grades_by_student.items():
            gb_averages = []

            for gb, student_grades in gb_map.items():
                avg = cls._calculate_grades_average(
                    student_grades, gb.calculation_method
                )
                if avg is not None:
                    gb_averages.append(avg)

            if gb_averages:
                # Overall Average = Average of Subject Averages
                overall_avg = sum(gb_averages) / len(gb_averages)
                # Round to 2 decimal places
                overall_avg = float(
                    Decimal(str(overall_avg)).quantize(
                        Decimal("0.01"), rounding=ROUND_HALF_UP
                    )
                )

                results.append(
                    {
                        "student": students_map[student_id],
                        "score": overall_avg,
                        "section_name": sections_map.get(student_id, ""),
                    }
                )

        # 5. Rank
        ranked_results = cls._assign_ranks(results)

        cache.set(cache_key, ranked_results, cls.CACHE_TIMEOUT)
        return ranked_results

    @staticmethod
    def _calculate_grades_average(grades: List[Grade], method: str) -> Optional[float]:
        """Helper to calculate average based on GB method"""
        if not grades:
            return None

        if method == GradeBook.CalculationMethod.CUMULATIVE:
            total_earned = sum(
                Decimal(str(g.score)) for g in grades if g.score is not None
            )
            total_possible = sum(
                Decimal(str(g.assessment.max_score))
                for g in grades
                if g.assessment.max_score
            )
            if total_possible > 0:
                return float((total_earned / total_possible * Decimal("100")))
            return None

        elif method == GradeBook.CalculationMethod.WEIGHTED:
            total_weighted_score = Decimal("0")
            total_weight = Decimal("0")

            for g in grades:
                if (
                    g.score is not None
                    and g.assessment.max_score
                    and g.assessment.weight
                ):
                    pct = (
                        Decimal(str(g.score)) / Decimal(str(g.assessment.max_score))
                    ) * Decimal("100")
                    weight = Decimal(str(g.assessment.weight))
                    total_weighted_score += pct * weight
                    total_weight += weight

            if total_weight > 0:
                return float(total_weighted_score / total_weight)
            return None

        else:  # AVERAGE
            percentages = []
            for g in grades:
                if g.score is not None and g.assessment.max_score:
                    pct = (
                        Decimal(str(g.score)) / Decimal(str(g.assessment.max_score))
                    ) * Decimal("100")
                    percentages.append(pct)

            if percentages:
                return float(sum(percentages) / len(percentages))
            return None

    @staticmethod
    def _assign_ranks(results: List[Dict]) -> List[Dict]:
        """
        Assign ranks to a list of results with 'score' key.
        Handles ties using "1224" strategy (Dense Rank logic is "1223").
        Standard competition ranking ("1224") is usually preferred for schools.
        """
        # Sort by score descending
        results.sort(key=lambda x: x["score"], reverse=True)

        ranked = []
        current_rank = 1
        current_score = None
        count_at_rank = 0

        for i, item in enumerate(results):
            if i == 0:
                item["rank"] = 1
                current_score = item["score"]
                count_at_rank = 1
            elif item["score"] == current_score:
                item["rank"] = current_rank
                count_at_rank += 1
            else:
                current_rank += count_at_rank
                item["rank"] = current_rank
                current_score = item["score"]
                count_at_rank = 1

            # Add formatted score
            item["formatted_score"] = f"{item['score']:.2f}"
            ranked.append(item)

        return ranked

    @staticmethod
    def _format_rank_results(queryset, score_field="score"):
        """Format queryset results into list of dicts"""
        results = []
        for item in queryset:
            results.append(
                {
                    "student": item.student,
                    "score": getattr(item, score_field),
                    "rank": item.rank,
                    "section_name": (
                        item.assessment.gradebook.section.name
                        if hasattr(item, "assessment")
                        else ""
                    ),
                }
            )
        return results

    @classmethod
    def get_student_overall_rank(
        cls,
        student_id: str,
        academic_year_id: str,
        scope_type: str = "section",
        scope_id: str = None,
        marking_period_id: str = None,
        semester_id: str = None,
    ) -> Optional[Dict]:
        """
        Get specific student's overall rank.
        Efficiently retrieves cached full rankings and extracts just this student.

        Args:
            student_id: ID of student
            academic_year_id: ID of academic year
            scope_type: 'section', 'grade_level', or 'school'
            scope_id: ID of the scope (section_id, grade_level_id, etc)

        Returns:
            Dict with keys: 'rank', 'total_students', 'score', 'percentile'
            or None if not found/ranked.
        """
        # Fetch full rankings (cached)
        rankings = cls.get_overall_rankings(
            academic_year_id=academic_year_id,
            scope_type=scope_type,
            scope_id=scope_id,
            marking_period_id=marking_period_id,
            semester_id=semester_id,
        )

        if not rankings:
            return None

        total_students = len(rankings)

        # Find student in rankings
        # Compare string IDs to be safe
        student_rank_data = next(
            (r for r in rankings if str(r["student"].id) == str(student_id)), None
        )

        if student_rank_data:
            rank = student_rank_data["rank"]
            # Calculate percentile (higher is better)
            # Formula: percentage of scores below this score
            # Simple inverse rank percentile: (total - rank) / total * 100
            percentile = (
                round(((total_students - rank) / total_students) * 100, 1)
                if total_students > 1
                else 100.0
            )

            return {
                "rank": rank,
                "total_students": total_students,
                "score": student_rank_data["score"],
                "formatted_score": student_rank_data.get("formatted_score"),
                "percentile": percentile,
                "scope_type": scope_type,
                "label": f"{rank}/{total_students}",
            }

        return None

    @classmethod
    def get_student_subject_rank(
        cls,
        student_id: str,
        subject_id: str,
        academic_year_id: str,
        scope_type: str = "section",
        scope_id: str = None,
        marking_period_id: str = None,
    ) -> Optional[Dict]:
        """
        Get specific student's rank in a subject.
        """
        rankings = cls.get_subject_rankings(
            subject_id=subject_id,
            academic_year_id=academic_year_id,
            scope_type=scope_type,
            scope_id=scope_id,
            marking_period_id=marking_period_id,
        )

        if not rankings:
            return None

        total_students = len(rankings)
        student_rank_data = next(
            (r for r in rankings if str(r["student"].id) == str(student_id)), None
        )

        if student_rank_data:
            rank = student_rank_data["rank"]
            percentile = (
                round(((total_students - rank) / total_students) * 100, 1)
                if total_students > 1
                else 100.0
            )

            return {
                "rank": rank,
                "total_students": total_students,
                "score": student_rank_data["score"],
                "formatted_score": student_rank_data.get("formatted_score"),
                "percentile": percentile,
                "scope_type": scope_type,
                "label": f"{rank}/{total_students}",
            }

        return None

    @classmethod
    def get_report_card_rankings(
        cls, student_id: str, academic_year_id: str, section_id: str
    ) -> Dict[str, Dict]:
        """
        Optimized method to get all rankings needed for a report card in a single pass.
        Returns a dict keyed by context ('final', 'semester_{id}', 'mp_{id}').
        """
        cache_key = f"report_card_ranks:{section_id}:{academic_year_id}"
        # We cache the ENTIRE section's rankings structure
        section_rankings = cache.get(cache_key)

        if not section_rankings:
            # Fetch all approved grades for the section/year
            grades = Grade.objects.filter(
                enrollment__section_id=section_id,
                enrollment__academic_year_id=academic_year_id,
                status=Grade.Status.APPROVED,
                assessment__is_calculated=True,
                assessment__gradebook__academic_year_id=academic_year_id,
            ).select_related(
                "student",
                "assessment__marking_period",
                "assessment__marking_period__semester",
                "assessment__gradebook",
            )

            # Group grades by student -> context -> list of grades
            # Contexts: 'final', 'sem_{id}', 'mp_{id}'
            grades_by_context = defaultdict(lambda: defaultdict(list))

            for grade in grades:
                sid = str(grade.student_id)

                # Add to Final context
                grades_by_context["final"][sid].append(grade)

                if grade.assessment.marking_period:
                    mp = grade.assessment.marking_period
                    # Add to MP context
                    grades_by_context[f"mp_{mp.id}"][sid].append(grade)
                    # Add to Semester context
                    if mp.semester:
                        grades_by_context[f"semester_{mp.semester.id}"][sid].append(
                            grade
                        )

            # Calculate averages and ranks for each context
            section_rankings = {}  # context -> { student_id -> rank_info }

            for context, student_grades_map in grades_by_context.items():
                # Calculate average for each student in this context
                student_averages = []

                for sid, grades_list in student_grades_map.items():
                    # Group by gradebook to calculate subject averages first
                    gb_grades = defaultdict(list)
                    for g in grades_list:
                        gb_grades[g.assessment.gradebook_id].append(g)

                    # Calculate subject averages
                    subject_avgs = []
                    for gb_id, g_list in gb_grades.items():
                        # We need calculation method. It's on gradebook.
                        # Since all grades in g_list belong to same gb, take first
                        gb = g_list[0].assessment.gradebook
                        avg = cls._calculate_grades_average(
                            g_list, gb.calculation_method
                        )
                        if avg is not None:
                            subject_avgs.append(avg)

                    if subject_avgs:
                        overall_avg = sum(subject_avgs) / len(subject_avgs)
                        # Round
                        overall_avg = float(
                            Decimal(str(overall_avg)).quantize(
                                Decimal("0.01"), rounding=ROUND_HALF_UP
                            )
                        )

                        student_averages.append(
                            {"student_id": sid, "score": overall_avg}
                        )

                # Rank students for this context
                # Sort descending
                student_averages.sort(key=lambda x: x["score"], reverse=True)

                ranked_map = {}
                total = len(student_averages)

                current_rank = 1
                current_score = None
                count_at_rank = 0

                for i, item in enumerate(student_averages):
                    if i == 0:
                        rank = 1
                        current_score = item["score"]
                        count_at_rank = 1
                    elif item["score"] == current_score:
                        rank = current_rank
                        count_at_rank += 1
                    else:
                        current_rank += count_at_rank
                        rank = current_rank
                        current_score = item["score"]
                        count_at_rank = 1

                    ranked_map[item["student_id"]] = {
                        "rank": rank,
                        "total": total,
                        "label": f"{rank}/{total}",
                    }

                section_rankings[context] = ranked_map

            cache.set(cache_key, section_rankings, cls.CACHE_TIMEOUT)

        # Extract rankings for the specific student
        student_rankings = {}
        sid = str(student_id)

        for context, ranks_map in section_rankings.items():
            if sid in ranks_map:
                student_rankings[context] = ranks_map[sid]

        return student_rankings
