"""
URL Configuration for Settings API
"""

from django.urls import path
from settings import views

app_name = 'settings'

urlpatterns = [
    # School Grading Settings
    path(
        'grading/',
        views.GradingSettingsView.as_view(),
        name='school-grading-settings'
    ),
    path(
        'grading-style/',
        views.SchoolGradingStyleView.as_view(),
        name='school-grading-style'
    ),
    # Grading Fixtures Initialization
    path(
        'grading/init/',
        views.GradingFixturesView.as_view(),
        name='grading-fixtures'
    ),
    # Gradebook Regeneration
    path(
        'grading/regenerate/',
        views.GradebookRegenerateView.as_view(),
        name='gradebook-regenerate'
    ),
    # Grading Task Status (for async operations)
    path(
        'grading/tasks/<str:task_id>/',
        views.GradingTaskStatusView.as_view(),
        name='grading-task-status'
    ),
]
