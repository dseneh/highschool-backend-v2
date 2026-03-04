## Academic Year Data Initialization

### Tables to be populated automatically

- Semesters
  - Each semester must be created when an academic year is created
  - In most cases, will be copied from the previous academic year
- Marking Periods
  - Since the marking periods depend on the semesters, they will also be created upon the semester creation
  - In most cases, will be copied from the previous academic year
- Grade Books
  - Grade book must be created for each subject for the academic year
    - Each gradebook will create assessments based on grade_style value provided (from wizard) and for each marking period
    - each assessment will create grade for each student
- 