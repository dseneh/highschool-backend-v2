"""
URL configuration for common app (cache and dashboard endpoints).
"""
from django.urls import path
from common import views_cache, views_dashboard

app_name = 'common'

urlpatterns = [
    # Dashboard summary
    path('dashboard/summary/', views_dashboard.get_dashboard_summary, name='dashboard_summary'),
    
    # Reference data endpoints
    path('reference/', views_cache.get_reference_data, name='reference_data'),
    path('reference/divisions/', views_cache.get_divisions, name='divisions'),
    path('reference/grade-levels/', views_cache.get_grade_levels, name='grade_levels'),
    path('reference/sections/', views_cache.get_sections, name='sections'),
    path('reference/academic-years/', views_cache.get_academic_years, name='academic_years'),
    path('reference/current-academic-year/', views_cache.get_current_academic_year, name='current_academic_year'),

    path('cache/invalidate/', views_cache.invalidate_cache, name='invalidate_cache'),
]
