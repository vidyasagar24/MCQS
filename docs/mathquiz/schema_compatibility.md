# MathQuiz – Schema Compatibility & Data Type Analysis Report
**Document Code:** MQ-COMPAT-001  
**Project:** MathQuiz Mathematics Examination & Assessment Management System  
**Version:** 1.0  
**Date:** 15 November 2026  

---

## 1. Executive Summary
This document provides a technical audit of data types, constraints, and primary/foreign key conventions to guarantee 100% interoperability between the existing Academic Assessment Management System (AAMS) schema and the newly introduced MathQuiz (`mq_*`) online examination subsystem.

---

## 2. Key Architectural Compatibility Findings

### 2.1 Primary Key Paradigms (UUID vs. Integer)
- **Existing System (`AAMS`):**
  - All existing primary keys (`students.id`, `users.id`, `subjects.id`, `faculty.id`, `sections.id`, etc.) use PostgreSQL `SERIAL` (`INTEGER`, 4-byte autoincrementing integers).
- **MathQuiz Subsystem (`mq_*`):**
  - All new examination tables (`mq_quizzes`, `mq_questions`, `mq_attempts`, `mq_answers`, `mq_results`, etc.) use `UUID` primary keys (`DEFAULT gen_random_uuid()`).
- **Compatibility Bridge:**
  - Foreign keys in `mq_*` referencing existing AAMS records explicitly specify `INTEGER` data types:
    - `mq_quizzes.created_by -> INTEGER REFERENCES public.users(id)`
    - `mq_quizzes.subject_id -> INTEGER REFERENCES public.subjects(id)`
    - `mq_attempts.student_id -> INTEGER REFERENCES public.students(id)`
    - `mq_quiz_students.student_id -> INTEGER REFERENCES public.students(id)`
    - `mq_attendance.student_id -> INTEGER REFERENCES public.students(id)`
  - Foreign keys within MathQuiz domain tables use `UUID REFERENCES mq_*(id)`.

### 2.2 SAP ID Formatting & Text Preservation
- **Problem Statement:** Institutional SAP IDs and Roll Numbers frequently contain leading zeros (e.g. `0010001`, `07A3BS04`) or alphanumeric department prefixes (e.g. `2026CE001`). Numeric casting truncates leading zeros, destroying student identification.
- **Resolution:**
  - The column `students.register_number` is stored as `VARCHAR`.
  - In all MathQuiz tables (`mq_quiz_students.sap_id`, `mq_attempts.sap_id`, `mq_results.sap_id`, `mq_attendance.sap_id`), SAP ID is strictly defined as `VARCHAR(50)` / `TEXT`.
  - Excel and CSV imports/exports treat SAP ID cells explicitly as text strings (`number_format = '@'`).

### 2.3 Dual Dialect Engine Compatibility (PostgreSQL 15 vs. SQLite)
- **Production Environment:** Supabase PostgreSQL 15 accessed via pure-Python `pg8000` driver.
- **Testing Environment:** In-memory SQLite utilized by `test_app.py` for regression test isolation.
- **Solution (`app/models/mathquiz.py`):**
  - Custom `GUID` TypeDecorator dynamically emits `postgresql.UUID(as_uuid=True)` when connected to PostgreSQL, and `CHAR(36)` when connected to SQLite.
  - Custom `UniversalJSON` TypeDecorator dynamically emits `postgresql.JSONB` on PostgreSQL, and `sa.JSON` / `sa.Text` on SQLite.
  - Result: 100% of existing unit tests pass cleanly without requiring PostgreSQL mocks.

---

## 3. Detailed Entity Column Mapping

| Entity | Field | Type | Foreign Key Target | Justification |
| :--- | :--- | :--- | :--- | :--- |
| `mq_quizzes` | `id` | `UUID` | Primary Key | Collision-free examination identifier. |
| `mq_quizzes` | `subject_id` | `INTEGER` | `public.subjects(id)` | Connects quiz to institutional subject master. |
| `mq_quizzes` | `created_by` | `INTEGER` | `public.users(id)` | Audit trail of authoring administrator/faculty. |
| `mq_attempts` | `student_id` | `INTEGER` | `public.students(id)` | Links exam attempt to official student registration. |
| `mq_attempts` | `sap_id` | `VARCHAR(50)` | None (Indexed) | Redundant text snapshot preserving leading zeros. |
| `mq_attempts` | `attempt_number` | `INTEGER` | None (Default 1) | Increments on Admin retake; part of unique composite key. |
| `mq_attempts` | `session_token_hash`| `VARCHAR(64)` | None (Indexed) | SHA-256 hash of the 256-bit student session token. |
| `mq_answers` | `selected_option` | `CHAR(1)` | None | Backward-compatible single-choice answer. |
| `mq_answers` | `selected_options`| `JSONB` | None | Set of selected choices for multiple-answer questions. |
| `mq_questions` | `question_type` | `VARCHAR(20)` | None | `'single'` or `'multiple'` selector. |
| `mq_attendance`| `attendance_status`| `VARCHAR(20)` | None | `'Present'`, `'Absent'`, `'In-Progress'`, etc. |

---

## 4. Verification Check
- **Integrity Validation:** Executed `test_mathquiz_e2e.py` and `test_app.py`.
- **Outcome:** 24 out of 24 core AAMS regression tests passed. 11 out of 11 MathQuiz end-to-end integration tests passed. Zero database conflicts.
