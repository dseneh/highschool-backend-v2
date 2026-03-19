"""
Bulk Grade Upload Views

Handles uploading student grades from Excel files.
"""

from django.db import transaction
from django.shortcuts import get_object_or_404
from rest_framework.views import APIView
from ..access_policies import GradebookAccessPolicy
from rest_framework.response import Response
from rest_framework.parsers import MultiPartParser, FormParser
from rest_framework import status as http_status
from decimal import Decimal, InvalidOperation

from academics.models import Section, AcademicYear, MarkingPeriod
from common.utils import get_object_by_uuid_or_fields
from students.models import Student
from grading.models import Assessment, Grade

class BulkGradeUploadView(APIView):
    """
    POST /sections/<section_id>/grades/upload/
    
    Upload student grades from Excel file.
    
    Query Parameters:
    - override_grades: Boolean (optional, default=false) - if true, updates grades regardless of status; 
                       if false, only updates grades with 'draft' or null status
    
    Excel Format (Metadata in first rows, then student data):
    
    Row 1: Grade Level: | <grade_level_name>
    Row 2: Section: | <section_name>
    Row 3: Subject: | <subject_name>
    Row 4: Academic Year: | <academic_year>
    Row 5: Marking Period: | <marking_period_name>
    Row 6: (blank)
    Row 7: Instructions: Do NOT modify...
    Row 8: (blank)
    Row 9: Student ID | Student Name | <Assessment1> | <Assessment2> | ...
    Row 10+: Student data rows
    
    Example:
    Grade Level:	Nursery 1
    Section:	General
    Subject:	Art
    Academic Year:	2025-2026
    Marking Period:	Marking Period 6
    
    Instructions: Do NOT modify the metadata above or student information columns below. Only enter scores in the assessment columns.
    
    Student ID	Student Name	Assignment	Attendance	Participation	Quiz	Test
    0121774	Michael Ashley Blair	5	5	5	20	40
    0121781	Brian Andrea Diaz	3	5	5	20	40
    """
    
    parser_classes = (MultiPartParser, FormParser)

    @staticmethod
    def _parse_bool(value, default=False):
        if value is None:
            return default
        if isinstance(value, bool):
            return value
        return str(value).strip().lower() in {"1", "true", "yes", "on"}
    
    @transaction.atomic
    def post(self, request, section_id):
        # Read override flag from query params first, then form body for robustness.
        override_raw = request.query_params.get('override_grades')
        if override_raw is None:
            override_raw = request.data.get('override_grades')
        override_grades = self._parse_bool(override_raw, default=False)
        
        # Verify section exists
        section = get_object_or_404(Section, pk=section_id)
        
        # Get uploaded file
        if 'file' not in request.FILES:
            return Response({
                'detail': 'No file uploaded. Please provide an Excel file.'
            }, status=http_status.HTTP_400_BAD_REQUEST)
        
        uploaded_file = request.FILES['file']
        
        # Validate file type
        if not uploaded_file.name.endswith(('.xlsx', '.xls')):
            return Response({
                'detail': 'Invalid file type. Please upload an Excel file (.xlsx or .xls).'
            }, status=http_status.HTTP_400_BAD_REQUEST)
        
        # Validate file size (max 10MB)
        max_file_size = 10 * 1024 * 1024  # 10MB in bytes
        if uploaded_file.size > max_file_size:
            return Response({
                'detail': f'File size exceeds maximum allowed size of 10MB. Your file is {uploaded_file.size / (1024 * 1024):.2f}MB.'
            }, status=http_status.HTTP_400_BAD_REQUEST)
        
        try:
            # Process the Excel file
            result = self._process_excel_file(
                uploaded_file, 
                section, 
                override_grades,
                request.user
            )
            
            return Response(result, status=http_status.HTTP_200_OK)
            
        except Exception as e:
            return Response({
                'detail': f'Error processing file: {str(e)}'
            }, status=http_status.HTTP_400_BAD_REQUEST)
    
    def _process_excel_file(self, file, section, override_grades, user):
        """Process the uploaded Excel file and create/update grades"""
        import pandas as pd
        from academics.models import Subject, GradeLevel

        def _normalize_excel_text(value):
            """
            Normalize Excel cell values to trimmed strings without introducing
            numeric coercion artifacts (e.g. 20025.0).
            """
            if value is None:
                return ''

            if isinstance(value, str):
                return value.strip()

            try:
                if pd.isna(value):
                    return ''
            except Exception:
                pass

            if isinstance(value, float):
                # Excel often loads numeric IDs as float; strip only trailing .0.
                if value.is_integer():
                    return str(int(value))
                return format(value, 'f').rstrip('0').rstrip('.')

            if isinstance(value, int):
                return str(value)

            return str(value).strip()
        
        # ========================================================================
        # STEP 1: Read Excel file and extract metadata from first rows
        # ========================================================================
        try:
            # Read the entire Excel file without headers first
            df_raw = pd.read_excel(file, header=None)
        except Exception as e:
            raise ValueError(f"Failed to read Excel file: {str(e)}")
        
        if df_raw.empty:
            raise ValueError("Excel file is empty. Please provide data to upload.")
        
        # Extract metadata from first 5 rows
        metadata = {}
        try:
            # Find the row with "Grade Level:" - could be row 0, 1, or 2
            grade_level_row = None
            for i in range(min(5, len(df_raw))):
                if len(df_raw.columns) > 0:
                    first_col = str(df_raw.iloc[i, 0]).strip().lower()
                    if 'grade level' in first_col:
                        grade_level_row = i
                        break
            
            if grade_level_row is None:
                raise ValueError("Could not find 'Grade Level:' in the first 5 rows")
            
            # Extract metadata starting from grade_level_row
            metadata['grade_level'] = str(df_raw.iloc[grade_level_row, 1]).strip() if len(df_raw.columns) > 1 else None
            metadata['section'] = str(df_raw.iloc[grade_level_row + 1, 1]).strip() if len(df_raw) > grade_level_row + 1 and len(df_raw.columns) > 1 else None
            metadata['subject'] = str(df_raw.iloc[grade_level_row + 2, 1]).strip() if len(df_raw) > grade_level_row + 2 and len(df_raw.columns) > 1 else None
            metadata['academic_year'] = str(df_raw.iloc[grade_level_row + 3, 1]).strip() if len(df_raw) > grade_level_row + 3 and len(df_raw.columns) > 1 else None
            metadata['marking_period'] = str(df_raw.iloc[grade_level_row + 4, 1]).strip() if len(df_raw) > grade_level_row + 4 and len(df_raw.columns) > 1 else None
            
            # Store the header row index for later (it's after metadata + blank line + instructions + blank line)
            # Typically: metadata ends at grade_level_row + 4, then blank, instructions, blank, headers
            metadata['header_row'] = grade_level_row + 8
            
        except Exception as e:
            raise ValueError(f"Failed to extract metadata from Excel file. Ensure metadata format is correct. Error: {str(e)}")
        
        # Validate metadata
        if not metadata.get('grade_level') or metadata['grade_level'] == 'nan':
            raise ValueError("Grade Level is missing in row 1. Format: 'Grade Level:' in column A, value in column B")
        
        if not metadata.get('section') or metadata['section'] == 'nan':
            raise ValueError("Section is missing in row 2. Format: 'Section:' in column A, value in column B")
        
        if not metadata.get('subject') or metadata['subject'] == 'nan':
            raise ValueError("Subject is missing in row 3. Format: 'Subject:' in column A, value in column B")
        
        if not metadata.get('academic_year') or metadata['academic_year'] == 'nan':
            raise ValueError("Academic Year is missing in row 4. Format: 'Academic Year:' in column A, value in column B")
        
        if not metadata.get('marking_period') or metadata['marking_period'] == 'nan':
            raise ValueError("Marking Period is missing in row 5. Format: 'Marking Period:' in column A, value in column B")
        
        # ========================================================================
        # STEP 2: Validate metadata against database
        # ========================================================================
        
        # Validate Grade Level
        try:
            grade_level = GradeLevel.objects.get(name=metadata['grade_level'])
        except GradeLevel.DoesNotExist:
            raise ValueError(f"Grade Level '{metadata['grade_level']}' not found in the system")
        
        # Validate Section
        if section.name != metadata['section']:
            raise ValueError(f"Section mismatch. Expected '{section.name}' but file has '{metadata['section']}'")
        
        # Validate Academic Year
        try:
            academic_year = AcademicYear.objects.get(name=metadata['academic_year'])
        except AcademicYear.DoesNotExist:
            raise ValueError(f"Academic Year '{metadata['academic_year']}' not found in the system")
        
        # Validate Marking Period
        try:
            marking_period = MarkingPeriod.objects.get(
                name=metadata['marking_period'],
                semester__academic_year=academic_year
            )
        except MarkingPeriod.DoesNotExist:
            raise ValueError(f"Marking Period '{metadata['marking_period']}' not found for academic year '{metadata['academic_year']}'")
        
        # ========================================================================
        # STEP 3: Read student data (headers row is dynamic based on metadata position)
        # ========================================================================
        try:
            # Use the header_row we calculated earlier
            header_row_index = metadata.get('header_row', 8)
            df = pd.read_excel(file, header=header_row_index, dtype=object)
            
            # Rename columns to standardize (handle possible column name variations)
            column_mapping = {}
            for col in df.columns:
                col_lower = str(col).strip().lower()
                if col_lower in ['student id', 'id', 'id_number', 'student_id']:
                    column_mapping[col] = 'student_id'
                elif col_lower in ['student name', 'name', 'full_name', 'student_name']:
                    column_mapping[col] = 'student_name'
            
            df.rename(columns=column_mapping, inplace=True)

            # Treat IDs and names strictly as text to preserve leading zeros and
            # avoid float artifacts from Excel numeric cells.
            if 'student_id' in df.columns:
                df['student_id'] = df['student_id'].apply(_normalize_excel_text)
            if 'student_name' in df.columns:
                df['student_name'] = df['student_name'].apply(_normalize_excel_text)
            
        except Exception as e:
            raise ValueError(f"Failed to read student data from Excel file (header at row {header_row_index + 1}): {str(e)}")
        
        # Validate file is not empty
        if df.empty:
            raise ValueError(f"No student data found in Excel file. Student data should start from row {header_row_index + 2}.")
        
        # Validate required columns
        if 'student_id' not in df.columns:
            raise ValueError(f"'Student ID' or 'id_number' column not found in row {header_row_index + 1}. Ensure the header row has one of these columns.")
        
        if 'student_name' not in df.columns:
            raise ValueError(f"'Student Name' column not found in row {header_row_index + 1}. Ensure the header row has 'Student Name' or 'student_name' column.")
        
        # Get assessment columns (all columns except student_id and student_name)
        assessment_columns = [col for col in df.columns if col not in ['student_id', 'student_name']]
        
        if not assessment_columns:
            raise ValueError("No assessment columns found. Please add at least one assessment column after 'Student Name'.")

        # Validate Subject using the current upload context instead of a global name lookup.
        subject_candidates = Subject.objects.filter(
            name=metadata['subject'],
            gradebooks__section=section,
            gradebooks__academic_year=academic_year,
            gradebooks__assessments__marking_period=marking_period,
            gradebooks__assessments__name__in=assessment_columns,
            gradebooks__assessments__active=True,
        ).distinct()

        subject_count = subject_candidates.count()
        if subject_count == 0:
            raise ValueError(
                f"Subject '{metadata['subject']}' was not found for section '{section.name}' in academic year '{academic_year.name}'."
            )
        if subject_count > 1:
            raise ValueError(
                f"Subject '{metadata['subject']}' is ambiguous for this upload context. Please ensure the section, marking period, and assessment columns match a single gradebook."
            )

        subject = subject_candidates.first()
        
        # Statistics
        stats = {
            'total_rows': len(df),
            'students_processed': 0,
            'grades_created': 0,
            'grades_updated': 0,
            'grades_skipped': 0,
            'grades_locked': 0,
            'errors': [],
            'warnings': [],
            'metadata': metadata
        }
        
        # ========================================================================
        # STEP 4: Pre-fetch all needed data to reduce database queries
        # ========================================================================
        
        # Extract unique student IDs
        student_ids = df['student_id'].dropna().astype(str).str.strip().unique()
        
        # Pre-fetch students with the shared UUID-or-field resolver so id_number values
        # do not get sent through UUID filters and trigger validation errors.
        students_map = {}
        for student_lookup in student_ids:
            try:
                student = get_object_by_uuid_or_fields(
                    Student,
                    student_lookup,
                    fields=['id_number', 'prev_id_number'],
                )
            except Student.DoesNotExist:
                continue

            students_map[str(student_lookup)] = student
            students_map[str(student.id_number)] = student
            students_map[str(student.id)] = student

            prev_id_number = getattr(student, 'prev_id_number', None)
            if prev_id_number:
                students_map[str(prev_id_number)] = student
        
        # Pre-fetch assessments for this section, academic year, subject, and marking period
        assessments_cache = {}
        assessments_qs = Assessment.objects.filter(
            gradebook__section=section,
            gradebook__academic_year=academic_year,
            gradebook__section_subject__subject=subject,
            marking_period=marking_period,
            active=True
        ).select_related(
            'marking_period',
            'assessment_type',
            'gradebook',
            'gradebook__section_subject',
            'gradebook__section_subject__subject'
        )
        
        for assessment in assessments_qs:
            # Cache by assessment name for easy lookup
            assessments_cache[assessment.name] = assessment
        
        # Pre-fetch enrollments
        from students.models import Enrollment
        enrollments_cache = {}
        for enrollment in Enrollment.objects.filter(
            academic_year=academic_year,
            section=section,
            student__in=students_map.values()
        ).select_related('student'):
            enrollments_cache[enrollment.student.id] = enrollment.id
        
        # Pre-fetch existing grades
        existing_grades_cache = {}
        for grade in Grade.objects.filter(
            section=section,
            academic_year=academic_year,
            subject=subject,
            student__in=students_map.values(),
            assessment__marking_period=marking_period
        ).select_related('assessment', 'student'):
            key = (grade.assessment.id, grade.student.id)
            existing_grades_cache[key] = grade
        
        # ========================================================================
        # STEP 5: Process student rows
        # ========================================================================
        
        grades_to_create = []
        grades_to_update = []
        processed_students = set()
        
        # Get header row index for accurate row number reporting
        header_row_index = metadata.get('header_row', 8)
        
        for index, row in df.iterrows():
            # Excel row number (accounting for header row position + 1 for data rows)
            # Add 2: +1 for 0-indexed to 1-indexed, +1 because data starts after header
            row_number = header_row_index + index + 2
            
            try:
                # Get student ID
                student_id = str(row['student_id']).strip()
                if pd.isna(student_id) or not student_id:
                    stats['errors'].append({
                        'row': row_number,
                        'error': 'Student ID is missing'
                    })
                    continue
                
                # Lookup student
                student = students_map.get(student_id)
                if not student:
                    stats['errors'].append({
                        'row': row_number,
                        'student_id': student_id,
                        'error': f'Student not found with ID: {student_id}'
                    })
                    continue
                
                # Verify student name (optional warning)
                student_name_in_file = str(row['student_name']).strip() if not pd.isna(row['student_name']) else ''
                if student_name_in_file and student.get_full_name().lower() != student_name_in_file.lower():
                    stats['warnings'].append({
                        'row': row_number,
                        'student_id': student_id,
                        'warning': f"Name mismatch. Expected: '{student.get_full_name()}', Found: '{student_name_in_file}'"
                    })
                
                # Get enrollment
                enrollment_id = enrollments_cache.get(student.id)
                if not enrollment_id:
                    stats['errors'].append({
                        'row': row_number,
                        'student_id': student_id,
                        'error': f'Student is not enrolled in {section.name} for {academic_year.name}'
                    })
                    continue
                
                # Process each assessment column
                student_processed = False
                
                for assessment_col in assessment_columns:
                    score_value = row[assessment_col]
                    
                    # Skip if no score provided
                    if pd.isna(score_value) or str(score_value).strip() == '':
                        continue
                    
                    # Lookup assessment
                    assessment = assessments_cache.get(assessment_col)
                    
                    if not assessment:
                        stats['errors'].append({
                            'row': row_number,
                            'student_id': student_id,
                            'assessment': assessment_col,
                            'error': f"Assessment '{assessment_col}' not found for {metadata['marking_period']}"
                        })
                        continue
                    
                    # Validate and convert score
                    try:
                        score = Decimal(str(score_value).strip())
                        
                        if score < 0:
                            stats['errors'].append({
                                'row': row_number,
                                'student_id': student_id,
                                'assessment': assessment_col,
                                'error': f'Score cannot be negative: {score}'
                            })
                            continue
                        
                        if assessment.max_score and score > assessment.max_score:
                            stats['errors'].append({
                                'row': row_number,
                                'student_id': student_id,
                                'assessment': assessment_col,
                                'error': f'Score {score} exceeds maximum score of {assessment.max_score}'
                            })
                            continue
                        
                        if score.as_tuple().exponent < -2:
                            stats['errors'].append({
                                'row': row_number,
                                'student_id': student_id,
                                'assessment': assessment_col,
                                'error': f'Score {score} has too many decimal places. Maximum 2 allowed.'
                            })
                            continue
                            
                    except (InvalidOperation, ValueError, AttributeError):
                        stats['errors'].append({
                            'row': row_number,
                            'student_id': student_id,
                            'assessment': assessment_col,
                            'error': f'Invalid score value: {score_value}. Must be a number.'
                        })
                        continue
                    
                    # Check if grade exists
                    grade_key = (assessment.id, student.id)
                    existing_grade = existing_grades_cache.get(grade_key)
                    
                    if existing_grade:
                        # Check if we can update
                        can_update = override_grades or existing_grade.status in [Grade.Status.DRAFT, None]
                        
                        if can_update:
                            existing_grade.score = score
                            existing_grade.status = Grade.Status.DRAFT
                            existing_grade.updated_by = user
                            grades_to_update.append(existing_grade)
                            stats['grades_updated'] += 1
                        else:
                            stats['grades_locked'] += 1
                            stats['warnings'].append({
                                'row': row_number,
                                'student_id': student_id,
                                'assessment': assessment_col,
                                'warning': f'Grade is {existing_grade.get_status_display()}. Use override_grades=true to update.'
                            })
                    else:
                        # Create new grade
                        new_grade = Grade(
                            assessment=assessment,
                            student=student,
                            score=score,
                            status=Grade.Status.DRAFT,
                            enrollment_id=enrollment_id,
                            academic_year=academic_year,
                            section=section,
                            subject=subject,
                            created_by=user,
                            updated_by=user
                        )
                        grades_to_create.append(new_grade)
                        # Update cache to prevent duplicates
                        existing_grades_cache[grade_key] = new_grade
                        stats['grades_created'] += 1
                    
                    student_processed = True
                
                if student_processed:
                    processed_students.add(student.id)
                    
            except Exception as e:
                stats['errors'].append({
                    'row': row_number,
                    'error': f'Unexpected error: {str(e)}'
                })
                continue
        
        # ========================================================================
        # STEP 6: Bulk create/update grades
        # ========================================================================
        
        if grades_to_create:
            Grade.objects.bulk_create(grades_to_create, batch_size=500)
        
        if grades_to_update:
            Grade.objects.bulk_update(
                grades_to_update, 
                ['score', 'status', 'updated_by', 'updated_at'],
                batch_size=500
            )
        
        stats['students_processed'] = len(processed_students)
        
        # Build response message
        message = f"Successfully processed {stats['students_processed']} students for {metadata['subject']} - {metadata['marking_period']}. "
        message += f"Created {stats['grades_created']} new grades, updated {stats['grades_updated']} existing grades."
        
        if stats['grades_locked'] > 0:
            message += f" {stats['grades_locked']} grades were locked (use override_grades=true to update)."
        
        if stats['warnings']:
            message += f" {len(stats['warnings'])} warnings occurred."
        
        if stats['errors']:
            message += f" {len(stats['errors'])} errors occurred."
        
        return {
            'detail': message,
            'metadata': metadata,
            'statistics': {
                'total_rows': stats['total_rows'],
                'students_processed': stats['students_processed'],
                'grades_created': stats['grades_created'],
                'grades_updated': stats['grades_updated'],
                'grades_locked': stats['grades_locked'],
                'warning_count': len(stats['warnings']),
                'error_count': len(stats['errors'])
            },
            'warnings': stats['warnings'][:50],
            'errors': stats['errors'][:50]
        }
