from rest_framework import status
from rest_framework.exceptions import NotFound
from rest_framework.response import Response
from rest_framework.views import APIView
from ..access_policies import AcademicsAccessPolicy
import logging

from common.utils import create_model_data, update_model_fields
from common.cache_service import DataCache

from ..serializers import SectionSubjectSerializer
from business.core.services import validate_section_subject_assignment, process_section_subject_assignments
from business.core.adapters import get_section_by_id_or_name, get_section_subjects, bulk_create_section_subjects, get_assigned_subject_ids
from grading.gradebook_initializer import create_gradebook_for_section_subject
from academics.models import AcademicYear
from django.db import transaction

logger = logging.getLogger(__name__)

class SectionSubjectListView(APIView):
    permission_classes = [AcademicsAccessPolicy]
    # permission_classes = [AllowAny]
    def get_section_object(self, id):
        section = get_section_by_id_or_name(id)
        if not section:
            raise NotFound("Section does not exist with this id")
        return section

    def get(self, request, section_id):
        section = self.get_section_object(section_id)

        subjects = get_section_subjects(section)
        serializer = SectionSubjectSerializer(
            subjects, many=True, context={"request": request}
        )

        return Response(serializer.data, status=status.HTTP_200_OK)

    def _sync_gradebooks_and_assessments(
        self,
        source_section,
        target_section,
        source_to_target_ss,
        user,
    ):
        """
        Sync gradebooks and assessments from source -> target section subjects.
        Creates missing gradebooks and missing assessments, skips existing matches.
        """
        from grading.models import GradeBook, Assessment

        if not source_to_target_ss:
            return {
                "gradebooks_created": 0,
                "assessments_created": 0,
                "assessments_skipped": 0,
            }

        source_gradebooks = (
            GradeBook.objects
            .filter(section_subject_id__in=source_to_target_ss.keys(), active=True)
            .prefetch_related("assessments")
            .select_related("academic_year", "section_subject")
        )

        gradebooks_created = 0
        assessments_created = 0
        assessments_skipped = 0

        for src_gb in source_gradebooks:
            target_ss = source_to_target_ss.get(str(src_gb.section_subject_id))
            if target_ss is None:
                continue

            gb_name = (
                src_gb.name.replace(source_section.name, target_section.name, 1)
                if source_section.name in src_gb.name
                else src_gb.name
            )

            target_gb, gb_created = GradeBook.objects.get_or_create(
                section_subject=target_ss,
                academic_year=src_gb.academic_year,
                name=gb_name,
                defaults={
                    "section": target_section,
                    "subject": target_ss.subject,
                    "calculation_method": src_gb.calculation_method,
                    "created_by": user,
                    "updated_by": user,
                },
            )
            if gb_created:
                gradebooks_created += 1

            for src_asmt in src_gb.assessments.filter(active=True):
                exists = Assessment.objects.filter(
                    gradebook=target_gb,
                    name=src_asmt.name,
                    assessment_type=src_asmt.assessment_type,
                    marking_period=src_asmt.marking_period,
                    max_score=src_asmt.max_score,
                    weight=src_asmt.weight,
                    due_date=src_asmt.due_date,
                    is_calculated=src_asmt.is_calculated,
                    active=True,
                ).exists()

                if exists:
                    assessments_skipped += 1
                    continue

                Assessment.objects.create(
                    gradebook=target_gb,
                    name=src_asmt.name,
                    assessment_type=src_asmt.assessment_type,
                    marking_period=src_asmt.marking_period,
                    max_score=src_asmt.max_score,
                    weight=src_asmt.weight,
                    due_date=src_asmt.due_date,
                    is_calculated=src_asmt.is_calculated,
                    created_by=user,
                    updated_by=user,
                )
                assessments_created += 1

        return {
            "gradebooks_created": gradebooks_created,
            "assessments_created": assessments_created,
            "assessments_skipped": assessments_skipped,
        }

    @transaction.atomic
    def post(self, request, section_id):
        section = self.get_section_object(section_id)
        req_data: dict = request.data

        source_section_id = req_data.get("source_section_id")
        if source_section_id:
            source_section = self.get_section_object(source_section_id)

            source_section_subjects = list(
                source_section.section_subjects.filter(active=True).select_related("subject")
            )
            if not source_section_subjects:
                return Response(
                    {"detail": "Source section has no active subjects to import."},
                    status=status.HTTP_200_OK,
                )

            existing_target_subjects = {
                str(ss.subject_id): ss
                for ss in section.section_subjects.filter(active=True).select_related("subject")
            }

            created_section_subjects = []
            existing_subject_count = 0
            source_to_target_ss = {}

            from academics.models import SectionSubject

            for src_ss in source_section_subjects:
                target_ss = existing_target_subjects.get(str(src_ss.subject_id))
                if target_ss is None:
                    target_ss = SectionSubject.objects.create(
                        section=section,
                        subject=src_ss.subject,
                        created_by=request.user,
                        updated_by=request.user,
                    )
                    created_section_subjects.append(target_ss)
                    existing_target_subjects[str(src_ss.subject_id)] = target_ss
                else:
                    existing_subject_count += 1

                source_to_target_ss[str(src_ss.id)] = target_ss

            sync_summary = self._sync_gradebooks_and_assessments(
                source_section=source_section,
                target_section=section,
                source_to_target_ss=source_to_target_ss,
                user=request.user,
            )

            self._invalidate_cache()

            serializer = SectionSubjectSerializer(
                created_section_subjects,
                many=True,
                context={"request": request},
            )

            created_count = len(created_section_subjects)
            response_data = {
                "created": serializer.data,
                "created_count": created_count,
                "existing_count": existing_subject_count,
                "message": (
                    f"Imported {created_count} new subject(s); "
                    f"synced assessments for {existing_subject_count} existing subject(s)."
                ),
                "gradebooks": {
                    "created": sync_summary["gradebooks_created"],
                    "assessments_created": sync_summary["assessments_created"],
                    "assessments_skipped": sync_summary["assessments_skipped"],
                },
            }

            return Response(
                response_data,
                status=status.HTTP_201_CREATED if created_count > 0 else status.HTTP_200_OK,
            )

        subject_ids = req_data.get("subjects", [])

        # Validate subject assignment
        is_valid, error = validate_section_subject_assignment(subject_ids)
        if not is_valid:
            return Response({"detail": error}, status=400)

        # Get existing subject IDs
        existing_subject_ids = get_assigned_subject_ids(section)

        # Process subject assignments
        result = process_section_subject_assignments(subject_ids, existing_subject_ids)
        new_subjects = result.get('new', [])
        existing_subjects = result.get('existing', [])

        # Create section subjects in bulk for new subjects only
        if new_subjects:
            section_subjects = bulk_create_section_subjects(section, new_subjects, request.user)
            
            # Automatically create gradebooks, assessments, and grades for new section subjects
            gradebook_results = []
            # Use multiple_entry as default grading style
            # TODO: Get this from school/system settings when available
            grading_style = 'multiple_entry'
            
            # Get current academic year
            try:
                current_academic_year = AcademicYear.objects.filter(is_current=True).first()
                if current_academic_year:
                    for section_subject in section_subjects:
                        try:
                            result = create_gradebook_for_section_subject(
                                section_subject=section_subject,
                                academic_year=current_academic_year,
                                grading_style=grading_style,
                                created_by=request.user
                            )
                            gradebook_results.append({
                                'subject': section_subject.subject.name,
                                'gradebook_created': result['gradebook_created'],
                                'assessments_created': result['assessments_created'],
                                'grades_created': result['grades_created'],
                                'errors': result.get('errors', [])
                            })
                            
                            if result['success']:
                                logger.info(
                                    f"Auto-created gradebook for {section_subject.subject.name} "
                                    f"in {section.name}: {result['assessments_created']} assessments, "
                                    f"{result['grades_created']} grades"
                                )
                        except Exception as e:
                            logger.error(
                                f"Error auto-creating gradebook for {section_subject.subject.name}: {str(e)}"
                            )
                            gradebook_results.append({
                                'subject': section_subject.subject.name,
                                'gradebook_created': False,
                                'errors': [str(e)]
                            })
                else:
                    logger.warning("No current academic year set - skipping gradebook auto-creation")
            except Exception as e:
                logger.error(f"Error getting current academic year for gradebook creation: {str(e)}")
            
            # Invalidate sections cache after creating section subjects
            self._invalidate_cache()
            
            serializer = SectionSubjectSerializer(section_subjects, many=True)
            response_data = {
                "created": serializer.data,
                "created_count": len(section_subjects),
                "message": "Subjects assigned successfully",
            }
            
            # Add gradebook creation results if any were processed
            if gradebook_results:
                total_gradebooks = sum(1 for r in gradebook_results if r['gradebook_created'])
                total_assessments = sum(r['assessments_created'] for r in gradebook_results)
                total_grades = sum(r['grades_created'] for r in gradebook_results)
                
                response_data["gradebooks"] = {
                    "created": total_gradebooks,
                    "assessments_created": total_assessments,
                    "grades_created": total_grades,
                    "details": gradebook_results
                }
            
            if existing_subjects:
                response_data["existing_count"] = len(existing_subjects)
                response_data["message"] = f"{len(section_subjects)} new subjects assigned, {len(existing_subjects)} already existed"
            
            return Response(response_data, status=status.HTTP_201_CREATED)
        else:
            return Response(
                {
                    "detail": "No new subjects were assigned (all subjects already exist in this section)",
                    "existing_count": len(existing_subjects)
                },
                status=200,
            )
    
    def _invalidate_cache(self):
        """Invalidate section caches after modifications"""
        DataCache.invalidate_sections()
        logger.debug(f"Invalidated section cache after section subject creation")

from business.core.adapters import get_section_subject_by_id, section_subject_has_grades, deactivate_section_subject, delete_section_subject_from_db

class SectionSubjectDetailView(APIView):
    permission_classes = [AcademicsAccessPolicy]
    # permission_classes = [IsAuthenticatedOrReadOnly, IsAdminOrSystemAdmin]
    def get_object(self, id):
        section_subject = get_section_subject_by_id(id)
        if not section_subject:
            raise NotFound("SectionSubject does not exist with this id")
        return section_subject

    def get(self, request, id):
        subject = self.get_object(id)
        serializer = SectionSubjectSerializer(subject, context={"request": request})
        return Response(serializer.data, status=status.HTTP_200_OK)

    def put(self, request, id):
        subject = self.get_object(id)

        allowed_fields = [
            "active",
        ]

        serializer = update_model_fields(
            request, subject, allowed_fields, SectionSubjectSerializer
        )
        
        # Invalidate sections cache after update
        self._invalidate_cache()
        
        return Response(serializer.data, status=status.HTTP_200_OK)

    def delete(self, request, id):
        section_subject = self.get_object(id)
        
        # Check if subject has any grades entered
        has_grades = section_subject_has_grades(section_subject)
        
        if has_grades:
            # If grades exist, deactivate instead of delete
            deactivate_section_subject(section_subject)
            self._invalidate_cache()
            
            return Response(
                {
                    "message": "Subject has been deactivated instead of deleted because it has grades entered.",
                    "deactivated": True
                },
                status=status.HTTP_200_OK,
            )
        
        # No grades exist, safe to delete
        deleted = delete_section_subject_from_db(section_subject)
        
        if deleted:
            # Successfully deleted
            self._invalidate_cache()
            return Response(
                {
                    "message": "Subject deleted successfully",
                    "deleted": True
                },
                status=status.HTTP_200_OK
            )
        else:
            # Delete failed (protected by foreign key or other constraint)
            # Deactivate as fallback
            deactivate_section_subject(section_subject)
            self._invalidate_cache()
            
            return Response(
                {
                    "message": "Subject has been deactivated instead of deleted due to database constraints.",
                    "deactivated": True
                },
                status=status.HTTP_200_OK,
            )
    
    def _invalidate_cache(self, request=None):
        """Invalidate section caches after modifications"""
        DataCache.invalidate_sections(request)
        logger.debug(f"Invalidated section cache after section subject modification")