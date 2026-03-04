from rest_framework.views import APIView
from ..access_policies import GradebookAccessPolicy
from rest_framework.response import Response
from rest_framework import serializers
from grading.services.ranking import RankingService

class RankingResultSerializer(serializers.Serializer):
    student = serializers.SerializerMethodField()
    score = serializers.FloatField()
    rank = serializers.IntegerField()
    section_name = serializers.CharField()
    formatted_score = serializers.CharField(required=False)

    def get_student(self, obj):
        student = obj.get("student")
        if not student:
            return None
        return {
            "id": student.id,
            "id_number": student.id_number,
            "full_name": student.get_full_name(),
        }

class RankingView(APIView):
    """
    GET /grading/rankings/

    Query Parameters:
    - type: 'assessment', 'subject', 'overall' (required)
    - scope: 'section', 'grade_level', 'school' (default depends on type)
    - scope_id: ID of the section, grade_level, or school (required if scope is provided)
    - academic_year: ID of academic year (required for subject/overall)
    - subject_id: ID of subject (required for type='subject')
    - assessment_id: ID of assessment (required for type='assessment')
    - marking_period: ID of marking period (optional for subject/overall)
    """

    def get(self, request):
        rank_type = request.query_params.get("type")
        scope_type = request.query_params.get("scope", "section")
        scope_id = request.query_params.get("scope_id")

        if not rank_type:
            return Response({"detail": "type parameter is required"}, status=400)

        results = []

        if rank_type == "assessment":
            assessment_id = request.query_params.get("assessment_id")
            if not assessment_id:
                return Response(
                    {"detail": "assessment_id is required for assessment ranking"},
                    status=400,
                )

            results = RankingService.get_assessment_rankings(
                assessment_id=assessment_id, scope_type=scope_type, scope_id=scope_id
            )

        elif rank_type == "subject":
            subject_id = request.query_params.get("subject_id")
            academic_year_id = request.query_params.get("academic_year")
            marking_period_id = request.query_params.get("marking_period")

            if not subject_id or not academic_year_id:
                return Response(
                    {
                        "detail": "subject_id and academic_year are required for subject ranking"
                    },
                    status=400,
                )

            results = RankingService.get_subject_rankings(
                subject_id=subject_id,
                academic_year_id=academic_year_id,
                scope_type=scope_type,
                scope_id=scope_id,
                marking_period_id=marking_period_id,
            )

        elif rank_type == "overall":
            academic_year_id = request.query_params.get("academic_year")
            marking_period_id = request.query_params.get("marking_period")

            if not academic_year_id:
                return Response(
                    {"detail": "academic_year is required for overall ranking"},
                    status=400,
                )

            results = RankingService.get_overall_rankings(
                academic_year_id=academic_year_id,
                scope_type=scope_type,
                scope_id=scope_id,
                marking_period_id=marking_period_id,
            )

        else:
            return Response(
                {"detail": f"Invalid ranking type: {rank_type}"}, status=400
            )

        serializer = RankingResultSerializer(results, many=True)
        return Response(serializer.data)
