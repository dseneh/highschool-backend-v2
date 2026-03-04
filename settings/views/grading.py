"""
Views for Settings API.

Handles grading settings management for schools.
"""

from rest_framework import status
from rest_framework.views import APIView
from ..access_policies import SettingsAccessPolicy
from rest_framework.response import Response
from django.db import transaction

from common.utils import update_model_fields
from academics.models import AcademicYear
from settings.models import GradingSettings
from settings.serializers import (
    GradingSettingsOut,
)
from grading.gradebook_initializer import initialize_gradebooks_for_academic_year
from grading.response import GradingResponse


class GradingSettingsView(APIView):
    permission_classes = [SettingsAccessPolicy]
    """
    Manage grading settings.

    GET /api/v1/settings/grading/
    PATCH /api/v1/settings/grading/
    """

    def get(self, request):
        """Get grading settings for current tenant.
        Creates default settings if none exist."""
        # Get or create settings (tenant-filtered automatically)
        settings, created = GradingSettings.objects.get_or_create(
            defaults={
                "created_by": request.user,
                "updated_by": request.user,
            },
        )

        if not created:
            settings.updated_by = request.user

        serializer = GradingSettingsOut(settings)

        return GradingResponse.success(
            data=serializer.data,
            message=(
                "Grading settings retrieved successfully"
                if not created
                else "Default grading settings created"
            ),
            is_new=created,
        )

    @transaction.atomic()
    def patch(self, request):
        """
        Update grading settings for current tenant.

        If grading_style changes and 'force' is True, reinitializes all gradebooks
        for active academic years with the new grading style.

        Parameters:
            - force (bool): If True and grading_style changed, reinitialize gradebooks (DESTRUCTIVE)
            - grading_style: 'single_entry' or 'multiple_entry'
            - ... other grading settings fields
        """
        allowed_fields = [
            "grading_style",
            "single_entry_assessment_name",
            "use_default_templates",
            "auto_calculate_final_grade",
            "default_calculation_method",
            "require_grade_approval",
            "require_grade_review",
            "display_assessment_on_single_entry",
            "allow_assessment_delete",
            "allow_assessment_create",
            "display_grade_status",
            "allow_assessment_edit",
            "use_letter_grades",
            "allow_teacher_override",
            "lock_grades_after_semester",
            "cumulative_average_calculation",
        ]

        # Get or create settings (handle case where settings don't exist yet, tenant-filtered)
        settings, created = GradingSettings.objects.get_or_create(
            defaults={
                "created_by": request.user,
                "updated_by": request.user,
            },
        )
        existing_grading_style = settings.grading_style

        # Get force parameter
        force = request.data.get("force", False)
        force = str(force).lower() in ["true", "1", "yes"]

        grading_style = request.data.get("grading_style", existing_grading_style)
        if grading_style not in ["single_entry", "multiple_entry"]:
            return GradingResponse.validation_error(
                message="Invalid grading_style value",
                field_errors={
                    "grading_style": ['Must be "single_entry" or "multiple_entry"']
                },
            )

        # Check if grading style is changing
        grading_style_changed = grading_style != existing_grading_style

        if grading_style_changed and not force:
            # Warn user that force is required to reinitialize
            return GradingResponse.warning(
                message=f"Grading style change detected ({existing_grading_style} → {grading_style}). This requires reinitializing all gradebooks.",
                warnings=[
                    "This operation will DELETE all existing gradebooks, assessments, and grades!",
                    'Pass "force": true to confirm and proceed with reinitialization',
                ],
                requires_confirmation=True,
                confirmation_param="force",
                current_grading_style=existing_grading_style,
                new_grading_style=grading_style,
            )

        # If grading style changed and force is True, reinitialize gradebooks FIRST
        if grading_style_changed and force:
            from grading.tasks import GradingTaskManager, MockTaskProcessor
            from academics.models import Section

            # Get current academic year (tenant-filtered)
            academic_year = AcademicYear.objects.filter(active=True).first()

            if not academic_year:
                return GradingResponse.error(
                    message="No active academic year found",
                    errors=[
                        "Cannot reinitialize gradebooks without an active academic year"
                    ],
                    error_code="NO_ACTIVE_ACADEMIC_YEAR",
                )

            # Check if we should use background processing
            section_count = Section.objects.filter(active=True).count()

            should_use_background = GradingTaskManager.should_use_background(
                section_count
            )

            # For large schools, use background task
            if should_use_background:
                task_id = GradingTaskManager.create_task(
                    task_type="gradebook_initialization",
                    academic_year_id=str(academic_year.id),
                    user_id=str(request.user.id),
                    params={
                        "grading_style": grading_style,
                        "regenerate": force,
                        "old_grading_style": existing_grading_style,
                    },
                )

                # Start background processing (mock for now, will be Celery in production)
                MockTaskProcessor.process_gradebook_initialization(task_id)

                # Build full absolute URL for status endpoint
                status_path = f"/api/v1/settings/grading/tasks/{task_id}/"
                status_url = request.build_absolute_uri(status_path)

                # Return immediately with task ID
                return GradingResponse.async_task(
                    task_id=task_id,
                    status_url=status_url,
                    message="Gradebook initialization started in background",
                    estimated_time_seconds=section_count * 2,
                    section_count=section_count,
                    grading_style_change={
                        "old": existing_grading_style,
                        "new": grading_style,
                    },
                    note="Settings will be updated automatically after successful initialization. Check status_url for progress.",
                )

            # STEP 3: For small/medium schools, process synchronously
            # Reinitialize gradebooks for each active academic year
            reinitialization_results = []
            total_gradebooks_created = 0
            total_assessments_created = 0
            total_grades_created = 0
            errors = []
            all_succeeded = True

            # for academic_year in active_academic_years:
            try:
                result = initialize_gradebooks_for_academic_year(
                    academic_year=academic_year,
                    grading_style=grading_style,
                    created_by=request.user,
                    regenerate=force,  # DESTRUCTIVE: Delete existing gradebooks
                    skip_assessment_types=False,  # Populate assessment types from fixtures
                    skip_grade_letters=False,  # Populate grade letters from fixtures
                    skip_templates=False,  # Populate templates from fixtures (for multiple_entry)
                )

                reinitialization_results.append(
                    {
                        "academic_year": {
                            "id": str(academic_year.id),
                            "name": academic_year.name,
                        },
                        "success": result["success"],
                        "message": result["message"],
                        "stats": result["stats"],
                    }
                )

                if result["success"]:
                    total_gradebooks_created += result["stats"]["gradebooks_created"]
                    total_assessments_created += result["stats"]["assessments_created"]
                    total_grades_created += result["stats"]["grades_created"]
                else:
                    all_succeeded = False

                if result.get("errors"):
                    errors.extend(result["errors"])

            except Exception as e:
                all_succeeded = False
                error_msg = f"Error reinitializing {academic_year.name}: {str(e)}"
                reinitialization_results.append(
                    {
                        "academic_year": {
                            "id": str(academic_year.id),
                            "name": academic_year.name,
                        },
                        "success": False,
                        "message": error_msg,
                        "stats": {},
                    }
                )
                errors.append(error_msg)

            # Only update settings if ALL reinitializations succeeded
            if not all_succeeded:
                # Rollback transaction - settings won't be updated
                transaction.set_rollback(True)
                return GradingResponse.error(
                    message="Gradebook reinitialization failed. Settings were NOT updated.",
                    errors=errors,
                    error_code="REINITIALIZATION_FAILED",
                    status=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    grading_style_changed=False,
                    old_grading_style=existing_grading_style,
                    attempted_grading_style=grading_style,
                    reinitialization={
                        "performed": True,
                        "all_succeeded": False,
                        "academic_year": {
                            "id": str(academic_year.id),
                            "name": academic_year.name,
                        },
                        "total_gradebooks_created": total_gradebooks_created,
                        "total_assessments_created": total_assessments_created,
                        "total_grades_created": total_grades_created,
                        "results": reinitialization_results,
                    },
                )

            # All reinitializations succeeded - NOW update settings
            response_data = update_model_fields(
                request, settings, allowed_fields, GradingSettingsOut
            )

            return GradingResponse.success(
                data=(
                    response_data.data
                    if hasattr(response_data, "data")
                    else response_data
                ),
                message=f"Grading settings updated and gradebooks reinitialized with {grading_style} mode.",
                grading_style_changed=True,
                old_grading_style=existing_grading_style,
                new_grading_style=grading_style,
                reinitialization={
                    "performed": True,
                    "all_succeeded": True,
                    "academic_year": {
                        "id": str(academic_year.id),
                        "name": academic_year.name,
                    },
                    "total_gradebooks_created": total_gradebooks_created,
                    "total_assessments_created": total_assessments_created,
                    "total_grades_created": total_grades_created,
                    "results": reinitialization_results,
                    "errors": errors if errors else None,
                },
            )

        # Normal update without grading style change
        # Handle transitional grade states when workflow settings change
        old_require_approval = settings.require_grade_approval
        old_require_review = settings.require_grade_review
        new_require_approval = request.data.get("require_grade_approval", old_require_approval)
        new_require_review = request.data.get("require_grade_review", old_require_review)
        
        # Track migrations for response
        grade_migrations = {
            "performed": False,
            "approval_disabled": False,
            "review_disabled": False,
            "grades_migrated": 0,
        }
        
        # If approval requirement is being disabled, auto-approve submitted grades
        if old_require_approval and not new_require_approval:
            from grading.models import Grade
            
            submitted_grades = Grade.objects.filter(status=Grade.Status.SUBMITTED)
            submitted_count = submitted_grades.count()
            
            if submitted_count > 0:
                # Transition all submitted grades to approved
                submitted_grades.update(
                    status=Grade.Status.APPROVED,
                    updated_by=request.user
                )
                grade_migrations["performed"] = True
                grade_migrations["approval_disabled"] = True
                grade_migrations["grades_migrated"] += submitted_count
                grade_migrations["approval_migration"] = {
                    "grades_auto_approved": submitted_count,
                    "reason": "Approval requirement disabled - submitted grades automatically approved"
                }
        
        # If review requirement is being disabled, auto-submit pending/reviewed grades
        if old_require_review and not new_require_review:
            from grading.models import Grade
            
            # Handle pending and reviewed grades
            transitional_grades = Grade.objects.filter(
                status__in=[Grade.Status.PENDING, Grade.Status.REVIEWED]
            )
            transitional_count = transitional_grades.count()
            
            if transitional_count > 0:
                # If approval is still required, move to submitted
                # If approval is also disabled, move directly to approved
                target_status = Grade.Status.APPROVED if not new_require_approval else Grade.Status.SUBMITTED
                
                transitional_grades.update(
                    status=target_status,
                    updated_by=request.user
                )
                grade_migrations["performed"] = True
                grade_migrations["review_disabled"] = True
                grade_migrations["grades_migrated"] += transitional_count
                grade_migrations["review_migration"] = {
                    "grades_auto_transitioned": transitional_count,
                    "target_status": target_status,
                    "reason": f"Review requirement disabled - transitional grades moved to {target_status}"
                }
        
        # Now update the settings
        response_data = update_model_fields(
            request, settings, allowed_fields, GradingSettingsOut
        )
        
        # Enhancement response with migration info if migrations occurred
        if grade_migrations["performed"]:
            if hasattr(response_data, 'data'):
                response_dict = response_data.data
            else:
                response_dict = response_data
            
            return GradingResponse.success(
                data=response_dict,
                message="Settings updated successfully with automatic grade state migration",
                grade_migrations=grade_migrations,
            )
        
        return response_data


class SchoolGradingStyleView(APIView):
    """
    Quick check for tenant's grading style.

    GET /api/v1/settings/grading-style/
    """

    def get(self, request):
        """Get grading style for current tenant. Returns single_entry or multiple_entry mode."""
        settings = GradingSettings.objects.first()
        
        if settings:
            grading_style = settings.grading_style
            is_single_entry = settings.is_single_entry_mode()
        else:
            # Default to multiple entry if no settings
            grading_style = "multiple_entry"
            is_single_entry = False

        return GradingResponse.success(
            data={
                "grading_style": grading_style,
                "is_single_entry": is_single_entry,
                "is_multiple_entry": not is_single_entry,
            },
            message="Grading style retrieved successfully",
        )


class GradingFixturesView(APIView):
    """
    Initialize or check grading fixtures (assessment types, grade letters, templates).

    GET /api/v1/settings/grading/fixtures/
    POST /api/v1/settings/grading/fixtures/
    """

    def get(self, request):
        """Initialize grading fixtures for current tenant."""
        from grading.gradebook_initializer import (
            _ensure_assessment_types,
            _ensure_grade_letters,
            _ensure_default_templates,
        )
        from grading.models import (
            AssessmentType,
            GradeLetter,
            DefaultAssessmentTemplate,
        )

        # Get grading settings (tenant-filtered)
        settings = GradingSettings.objects.first()
        
        if settings:
            grading_style = settings.grading_style
        else:
            # Create default settings first
            settings, _ = GradingSettings.objects.get_or_create(
                defaults={
                    "created_by": request.user,
                    "updated_by": request.user,
                },
            )
            grading_style = settings.grading_style

        fixtures_initialized = {}
        errors = []

        # Initialize assessment types
        result = _ensure_assessment_types(
            grading_style=grading_style, created_by=request.user
        )
        fixtures_initialized["assessment_types"] = {
            "created": result["created"],
            "updated": result["updated"],
        }
        if result.get("errors"):
            errors.extend(result["errors"])

        # Initialize grade letters
        result = _ensure_grade_letters(created_by=request.user)
        fixtures_initialized["grade_letters"] = {
            "created": result["created"],
            "updated": result["updated"],
        }
        if result.get("errors"):
            errors.extend(result["errors"])

        # Initialize default templates
        result = _ensure_default_templates(created_by=request.user)
        fixtures_initialized["default_templates"] = {
            "created": result["created"],
            "updated": result["updated"],
        }
        if result.get("errors"):
            errors.extend(result["errors"])

        total_created = sum(f["created"] for f in fixtures_initialized.values())
        total_updated = sum(f["updated"] for f in fixtures_initialized.values())

        return GradingResponse.success(
            data={
                "grading_style": grading_style,
                "fixtures_initialized": fixtures_initialized,
                "summary": {
                    "total_created": total_created,
                    "total_updated": total_updated,
                    "total_fixtures": total_created + total_updated,
                },
            },
            message=f"Fixtures initialized successfully: {total_created} created, {total_updated} updated",
            errors=errors if errors else None,
        )


class GradebookRegenerateView(APIView):
    """
    Regenerate gradebooks for current tenant's academic year.

    POST /api/v1/settings/grading/regenerate/
    """

    @transaction.atomic()
    def post(self, request):
        """
        Regenerate gradebooks for a specific academic year.

        Body Parameters:
            - academic_year_id (optional): Academic year to regenerate gradebooks for (defaults to current)
            - grading_style (optional): Override grading style (defaults to settings)
            - force (required): Must be true to confirm regeneration (DESTRUCTIVE operation)
        """
        from academics.models import Section
        from grading.tasks import GradingTaskManager, MockTaskProcessor

        # Get required parameters
        academic_year_id = request.data.get("academic_year_id")
        if not academic_year_id:
            current_year = AcademicYear.objects.filter(active=True).first()
            academic_year_id = current_year.id if current_year else None
        if not academic_year_id:
            return GradingResponse.validation_error(
                message="academic_year_id is required",
                field_errors={"academic_year_id": ["This field is required"]},
            )

        # Get force parameter
        force = request.data.get("force", False)
        force = str(force).lower() in ["true", "1", "yes"]

        if not force:
            return GradingResponse.warning(
                message="Gradebook regeneration requires confirmation",
                warnings=[
                    "This operation will DELETE all existing gradebooks, assessments, and grades!",
                    'Pass "force": true to confirm and proceed with regeneration',
                ],
                requires_confirmation=True,
                confirmation_param="force",
            )

        # Get academic year
        try:
            academic_year = AcademicYear.objects.get(id=academic_year_id)
        except AcademicYear.DoesNotExist:
            return GradingResponse.not_found(
                message="Academic year not found",
                resource_type="academic_year",
                resource_id=academic_year_id,
            )

        # Get grading style (from request or settings)
        grading_style = request.data.get("grading_style")
        if grading_style:
            if grading_style not in ["single_entry", "multiple_entry"]:
                return GradingResponse.validation_error(
                    message="Invalid grading_style value",
                    field_errors={
                        "grading_style": ['Must be "single_entry" or "multiple_entry"']
                    },
                )
        else:
            # Get from settings (tenant-filtered)
            settings = GradingSettings.objects.first()
            if settings:
                grading_style = settings.grading_style
            else:
                # Create default settings
                settings, _ = GradingSettings.objects.get_or_create(
                    defaults={
                        "created_by": request.user,
                        "updated_by": request.user,
                    },
                )
                grading_style = settings.grading_style

        # Check if we should use background processing
        section_count = Section.objects.filter(active=True).count()

        should_use_background = GradingTaskManager.should_use_background(section_count)

        # For large schools, use background task
        if should_use_background:
            task_id = GradingTaskManager.create_task(
                task_type="gradebook_initialization",
                academic_year_id=str(academic_year.id),
                user_id=str(request.user.id),
                params={
                    "grading_style": grading_style,
                    "regenerate": True,
                },
            )

            # Start background processing
            MockTaskProcessor.process_gradebook_initialization(task_id)

            # Build full absolute URL for status endpoint
            status_path = f"/api/v1/settings/grading/tasks/{task_id}/"
            status_url = request.build_absolute_uri(status_path)

            return GradingResponse.async_task(
                task_id=task_id,
                status_url=status_url,
                message="Gradebook regeneration started in background",
                estimated_time_seconds=section_count * 2,
                section_count=section_count,
                grading_style=grading_style,
                note="Check status_url for progress.",
            )

        # For small/medium schools, process synchronously
        try:
            result = initialize_gradebooks_for_academic_year(
                academic_year=academic_year,
                grading_style=grading_style,
                created_by=request.user,
                regenerate=True,  # DESTRUCTIVE: Delete existing gradebooks
                skip_assessment_types=False,  # Ensure assessment types exist
                skip_grade_letters=False,  # Ensure grade letters exist
                skip_templates=False,  # Ensure templates exist
            )

            if not result["success"]:
                transaction.set_rollback(True)
                return GradingResponse.error(
                    message="Gradebook regeneration failed",
                    errors=result.get("errors", []),
                    error_code="REGENERATION_FAILED",
                    status=status.HTTP_500_INTERNAL_SERVER_ERROR,
                )

            return GradingResponse.success(
                data={
                    "grading_style": grading_style,
                    "academic_year": {
                        "id": str(academic_year.id),
                        "name": academic_year.name,
                    },
                    "stats": result["stats"],
                },
                message=f"Gradebooks regenerated successfully for {academic_year.name}",
                errors=result.get("errors") if result.get("errors") else None,
            )

        except Exception as e:
            transaction.set_rollback(True)
            return GradingResponse.error(
                message="Gradebook regeneration failed",
                errors=[str(e)],
                error_code="REGENERATION_EXCEPTION",
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )


class GradingTaskStatusView(APIView):
    """
    Check status of async gradebook initialization tasks.

    GET /api/v1/settings/grading/tasks/{task_id}/
    """

    def get(self, request, task_id):
        """Get the status of a background gradebook initialization task."""
        from grading.tasks import GradingTaskManager

        task = GradingTaskManager.get_task(task_id)

        if not task:
            return Response(
                {"success": False, "error": "Task not found"},
                status=status.HTTP_404_NOT_FOUND,
            )

        response_data = {
            "success": True,
            "task_id": task["id"],
            "status": task["status"],
            "progress": task["progress"],
            "created_at": task["created_at"],
            "updated_at": task["updated_at"],
        }

        if task["status"] == "pending":
            response_data["message"] = "Task is queued and waiting to start"
        elif task["status"] == "processing":
            response_data["message"] = "Task is currently processing"
        elif task["status"] == "completed":
            response_data["message"] = "Task completed successfully"
            response_data["result"] = task.get("result")

            # If task completed successfully, update the grading settings
            if task.get("result", {}).get("success"):
                params = task.get("params", {})
                new_style = params.get("grading_style")

                if new_style:
                    # Update settings now that initialization is complete
                    settings = GradingSettings.objects.first()
                    if settings:
                        settings.grading_style = new_style
                        settings.save(update_fields=["grading_style"])

                        response_data["settings_updated"] = True
                        response_data["new_grading_style"] = new_style
        elif task["status"] == "failed":
            response_data["message"] = "Task failed"
            response_data["error"] = task.get("error")

        return GradingResponse.task_status(
            task_id=task["id"],
            status=task["status"],
            progress=task["progress"],
            message=response_data.get("message", ""),
            created_at=task["created_at"],
            updated_at=task["updated_at"],
            result=task.get("result"),
            error=task.get("error"),
            settings_updated=response_data.get("settings_updated", False),
            new_grading_style=response_data.get("new_grading_style"),
        )

    def delete(self, request, task_id):
        """Cancel a running task."""
        from grading.tasks import GradingTaskManager

        task = GradingTaskManager.get_task(task_id)

        if not task:
            return GradingResponse.not_found(
                message="Task not found", resource_type="task", resource_id=task_id
            )

        # Can only cancel pending or processing tasks
        if task["status"] in ["pending", "processing"]:
            GradingTaskManager.update_task(task_id, status="cancelled")

            return GradingResponse.success(
                message="Task cancelled successfully",
                data={"task_id": task_id, "status": "cancelled"},
            )
        else:
            return GradingResponse.error(
                message=f'Cannot cancel task with status: {task["status"]}',
                error_code="CANNOT_CANCEL_TASK",
                current_status=task["status"],
            )
