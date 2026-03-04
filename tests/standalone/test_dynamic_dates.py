#!/usr/bin/env python3
"""
Test script to see what dates would be generated for the current date.
Run this to verify the dynamic date generation logic.
"""
import os
import sys
from datetime import datetime

# Add the project path
sys.path.append("/Users/dewardseneh/workdir/dewx/webapps/highschool/backend")

# Import the data generation functions
from defaults.data.academic_year import get_academic_year
from defaults.data.marking_period import get_marking_periods_dict
from defaults.data.semester import get_semester_list


def test_date_generation():
    print("=" * 60)
    print("DYNAMIC DATE GENERATION TEST")
    print("=" * 60)
    print(f"Current Date: {datetime.now().date()}")
    print()

    # Test academic year
    print("ACADEMIC YEAR:")
    print("-" * 20)
    academic_year = get_academic_year()
    for key, value in academic_year.items():
        print(f"{key}: {value}")
    print()

    # Test semesters
    print("SEMESTERS:")
    print("-" * 20)
    semesters = get_semester_list()
    for i, semester in enumerate(semesters, 1):
        print(f"Semester {i}:")
        for key, value in semester.items():
            print(f"  {key}: {value}")
        print()

    # Test marking periods
    print("MARKING PERIODS:")
    print("-" * 20)
    marking_periods = get_marking_periods_dict()
    for i, period in enumerate(marking_periods, 1):
        print(f"{i}. {period['name']} ({period['short_name']})")
        print(f"   Dates: {period['start_date']} to {period['end_date']}")
        print(f"   Semester: {period['semester'] + 1}")
        print()


if __name__ == "__main__":
    test_date_generation()
