-- ============================================================================
-- STANDALONE DATABASE SCHEMA & SEED FOR MCQS
-- Target Database: Dedicated Supabase PostgreSQL Database (Separate from ICA_Marks)
-- Version: 1.0 (Completely Independent & Isolated)
-- ============================================================================

CREATE EXTENSION IF NOT EXISTS pgcrypto;

-- 1. USERS TABLE
CREATE TABLE IF NOT EXISTS public.users (
    id SERIAL PRIMARY KEY,
    username VARCHAR(60) NOT NULL UNIQUE,
    password_hash VARCHAR(255) NOT NULL,
    role VARCHAR(20) NOT NULL DEFAULT 'faculty',
    faculty_id INTEGER NULL,
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- 2. SUBJECTS TABLE
CREATE TABLE IF NOT EXISTS public.subjects (
    id SERIAL PRIMARY KEY,
    subject_code VARCHAR(30) NOT NULL,
    subject_name VARCHAR(150) NOT NULL,
    programme_id INTEGER NOT NULL DEFAULT 1,
    semester_id INTEGER NOT NULL DEFAULT 1,
    credits INTEGER NOT NULL DEFAULT 4,
    ica_max NUMERIC(10,2) NOT NULL DEFAULT 50.0,
    tee_max NUMERIC(10,2) NOT NULL DEFAULT 100.0,
    status VARCHAR(20) NOT NULL DEFAULT 'Active',
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- 3. STUDENTS TABLE
CREATE TABLE IF NOT EXISTS public.students (
    id SERIAL PRIMARY KEY,
    student_id_code VARCHAR(50),
    register_number VARCHAR(50) NOT NULL UNIQUE,
    student_name VARCHAR(120) NOT NULL,
    programme_id INTEGER NOT NULL DEFAULT 1,
    academic_year_id INTEGER NOT NULL DEFAULT 3,
    current_semester_id INTEGER NOT NULL DEFAULT 2,
    section_id INTEGER NOT NULL DEFAULT 1,
    email VARCHAR(120),
    status VARCHAR(20) NOT NULL DEFAULT 'Active',
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- 4. QUIZZES MASTER
CREATE TABLE IF NOT EXISTS public.mq_quizzes (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    title TEXT NOT NULL,
    quiz_code VARCHAR(30) NOT NULL UNIQUE,
    subject_id INTEGER REFERENCES public.subjects(id) ON DELETE SET NULL,
    duration_minutes INTEGER NOT NULL CHECK (duration_minutes > 0),
    total_questions INTEGER NOT NULL DEFAULT 10,
    total_marks NUMERIC(10,2) NOT NULL DEFAULT 10.0,
    passing_marks NUMERIC(10,2) DEFAULT 4.0,
    distribution_type VARCHAR(30) NOT NULL CHECK (distribution_type IN ('random_pool', 'round_robin', 'all_questions')),
    round_robin_mode VARCHAR(30) CHECK (round_robin_mode IN ('question_sets', 'individual_questions')),
    negative_marking_enabled BOOLEAN DEFAULT FALSE,
    negative_marks NUMERIC(10,2) DEFAULT 0.0,
    shuffle_questions BOOLEAN DEFAULT TRUE,
    shuffle_options BOOLEAN DEFAULT TRUE,
    max_violations_allowed INTEGER DEFAULT 3,
    result_release_status VARCHAR(20) NOT NULL DEFAULT 'hidden' CHECK (result_release_status IN ('hidden', 'published')),
    status VARCHAR(20) NOT NULL DEFAULT 'active' CHECK (status IN ('draft', 'scheduled', 'active', 'deactive', 'inactive', 'completed', 'archived')),
    created_by INTEGER NOT NULL REFERENCES public.users(id),
    starts_at TIMESTAMPTZ,
    ends_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- 5. QUIZ STUDENT ROSTER
CREATE TABLE IF NOT EXISTS public.mq_quiz_students (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    quiz_id UUID NOT NULL REFERENCES public.mq_quizzes(id) ON DELETE CASCADE,
    student_id INTEGER NOT NULL REFERENCES public.students(id) ON DELETE CASCADE,
    sap_id VARCHAR(50) NOT NULL,
    registered_at TIMESTAMPTZ DEFAULT NOW(),
    is_eligible BOOLEAN DEFAULT TRUE,
    UNIQUE (quiz_id, student_id),
    UNIQUE (quiz_id, sap_id)
);

-- 6. QUESTION BANKS
CREATE TABLE IF NOT EXISTS public.mq_question_banks (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name VARCHAR(150) NOT NULL,
    subject_id INTEGER REFERENCES public.subjects(id) ON DELETE SET NULL,
    description TEXT,
    created_by INTEGER NOT NULL REFERENCES public.users(id),
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- 7. QUESTIONS
CREATE TABLE IF NOT EXISTS public.mq_questions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    quiz_id UUID REFERENCES public.mq_quizzes(id) ON DELETE CASCADE,
    question_bank_id UUID REFERENCES public.mq_question_banks(id) ON DELETE SET NULL,
    subject_id INTEGER REFERENCES public.subjects(id) ON DELETE SET NULL,
    batch_name VARCHAR(100) DEFAULT 'Batch 1',
    topic VARCHAR(150),
    subtopic VARCHAR(150),
    question_type VARCHAR(20) DEFAULT 'single' CHECK (question_type IN ('single', 'multiple')),
    difficulty VARCHAR(20) DEFAULT 'Medium' CHECK (difficulty IN ('Easy', 'Medium', 'Hard')),
    latex_source TEXT NOT NULL,
    marks NUMERIC(10,2) NOT NULL DEFAULT 1.0,
    negative_marks NUMERIC(10,2) DEFAULT 0.0,
    explanation TEXT,
    image_path TEXT,
    is_active BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- 8. QUESTION OPTIONS
CREATE TABLE IF NOT EXISTS public.mq_question_options (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    question_id UUID NOT NULL REFERENCES public.mq_questions(id) ON DELETE CASCADE,
    option_key CHAR(1) NOT NULL CHECK (option_key IN ('A', 'B', 'C', 'D', 'E')),
    latex_source TEXT NOT NULL,
    is_correct BOOLEAN NOT NULL DEFAULT FALSE,
    display_order INTEGER NOT NULL DEFAULT 1,
    UNIQUE (question_id, option_key)
);

-- 9. QUESTION POOLS
CREATE TABLE IF NOT EXISTS public.mq_question_pools (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    quiz_id UUID NOT NULL REFERENCES public.mq_quizzes(id) ON DELETE CASCADE,
    pool_name VARCHAR(100) NOT NULL,
    required_count INTEGER NOT NULL CHECK (required_count > 0),
    marks_per_question NUMERIC(10,2) NOT NULL DEFAULT 1.0,
    UNIQUE (quiz_id, pool_name)
);

-- 10. POOL QUESTIONS JUNCTION
CREATE TABLE IF NOT EXISTS public.mq_pool_questions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    pool_id UUID NOT NULL REFERENCES public.mq_question_pools(id) ON DELETE CASCADE,
    question_id UUID NOT NULL REFERENCES public.mq_questions(id) ON DELETE CASCADE,
    UNIQUE (pool_id, question_id)
);

-- 11. QUESTION SETS
CREATE TABLE IF NOT EXISTS public.mq_question_sets (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    quiz_id UUID NOT NULL REFERENCES public.mq_quizzes(id) ON DELETE CASCADE,
    set_name VARCHAR(50) NOT NULL,
    UNIQUE (quiz_id, set_name)
);

-- 12. QUESTION SET ITEMS
CREATE TABLE IF NOT EXISTS public.mq_question_set_items (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    set_id UUID NOT NULL REFERENCES public.mq_question_sets(id) ON DELETE CASCADE,
    question_id UUID NOT NULL REFERENCES public.mq_questions(id) ON DELETE CASCADE,
    sequence_order INTEGER NOT NULL DEFAULT 1,
    UNIQUE (set_id, question_id)
);

-- 13. STUDENT ASSIGNMENTS
CREATE TABLE IF NOT EXISTS public.mq_student_assignments (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    quiz_id UUID NOT NULL REFERENCES public.mq_quizzes(id) ON DELETE CASCADE,
    student_id INTEGER NOT NULL REFERENCES public.students(id) ON DELETE CASCADE,
    set_id UUID REFERENCES public.mq_question_sets(id) ON DELETE SET NULL,
    assigned_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE (quiz_id, student_id)
);

-- 14. EXAM ATTEMPTS
CREATE TABLE IF NOT EXISTS public.mq_attempts (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    quiz_id UUID NOT NULL REFERENCES public.mq_quizzes(id) ON DELETE CASCADE,
    student_id INTEGER NOT NULL REFERENCES public.students(id) ON DELETE CASCADE,
    session_token VARCHAR(255) NOT NULL UNIQUE,
    status VARCHAR(30) NOT NULL DEFAULT 'in_progress' CHECK (status IN ('in_progress', 'submitted', 'auto_submitted', 'disqualified', 'timed_out')),
    score NUMERIC(10,2),
    total_marks NUMERIC(10,2),
    percentage NUMERIC(5,2),
    is_passed BOOLEAN,
    violations_count INTEGER DEFAULT 0,
    is_locked BOOLEAN DEFAULT FALSE,
    lock_reason TEXT,
    started_at TIMESTAMPTZ DEFAULT NOW(),
    submitted_at TIMESTAMPTZ,
    auto_submitted_at TIMESTAMPTZ,
    expires_at TIMESTAMPTZ NOT NULL,
    ip_address VARCHAR(50),
    system_fingerprint TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- 15. STUDENT ANSWERS
CREATE TABLE IF NOT EXISTS public.mq_answers (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    attempt_id UUID NOT NULL REFERENCES public.mq_attempts(id) ON DELETE CASCADE,
    question_id UUID NOT NULL REFERENCES public.mq_questions(id) ON DELETE CASCADE,
    selected_option_key CHAR(1),
    is_marked_for_review BOOLEAN DEFAULT FALSE,
    is_answered BOOLEAN DEFAULT FALSE,
    is_correct BOOLEAN,
    marks_awarded NUMERIC(10,2) DEFAULT 0.0,
    answered_at TIMESTAMPTZ,
    time_spent_seconds INTEGER DEFAULT 0,
    UNIQUE (attempt_id, question_id)
);

-- 16. PROCTORING VIOLATIONS
CREATE TABLE IF NOT EXISTS public.mq_violations (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    attempt_id UUID NOT NULL REFERENCES public.mq_attempts(id) ON DELETE CASCADE,
    violation_type VARCHAR(50) NOT NULL,
    details TEXT,
    client_timestamp TIMESTAMPTZ,
    strike_number INTEGER NOT NULL DEFAULT 1,
    recorded_at TIMESTAMPTZ DEFAULT NOW()
);

-- 17. QUESTION MARKS AUDIT
CREATE TABLE IF NOT EXISTS public.mq_question_marks (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    attempt_id UUID NOT NULL REFERENCES public.mq_attempts(id) ON DELETE CASCADE,
    question_id UUID NOT NULL REFERENCES public.mq_questions(id) ON DELETE CASCADE,
    score NUMERIC(10,2) NOT NULL DEFAULT 0.0,
    awarded_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE (attempt_id, question_id)
);

-- 18. FINAL RESULTS
CREATE TABLE IF NOT EXISTS public.mq_results (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    quiz_id UUID NOT NULL REFERENCES public.mq_quizzes(id) ON DELETE CASCADE,
    student_id INTEGER NOT NULL REFERENCES public.students(id) ON DELETE CASCADE,
    attempt_id UUID NOT NULL REFERENCES public.mq_attempts(id) ON DELETE CASCADE UNIQUE,
    score NUMERIC(10,2) NOT NULL,
    total_marks NUMERIC(10,2) NOT NULL,
    percentage NUMERIC(5,2) NOT NULL,
    is_passed BOOLEAN NOT NULL,
    correct_count INTEGER DEFAULT 0,
    incorrect_count INTEGER DEFAULT 0,
    unanswered_count INTEGER DEFAULT 0,
    violations_count INTEGER DEFAULT 0,
    calculated_at TIMESTAMPTZ DEFAULT NOW()
);

-- 19. IMPORT JOBS
CREATE TABLE IF NOT EXISTS public.mq_import_jobs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    quiz_id UUID REFERENCES public.mq_quizzes(id) ON DELETE CASCADE,
    file_name VARCHAR(255) NOT NULL,
    file_type VARCHAR(20) NOT NULL,
    status VARCHAR(30) NOT NULL DEFAULT 'processing',
    total_rows INTEGER DEFAULT 0,
    imported_count INTEGER DEFAULT 0,
    failed_count INTEGER DEFAULT 0,
    created_by INTEGER REFERENCES public.users(id),
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- 20. IMPORT ERRORS
CREATE TABLE IF NOT EXISTS public.mq_import_errors (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    job_id UUID NOT NULL REFERENCES public.mq_import_jobs(id) ON DELETE CASCADE,
    row_number INTEGER NOT NULL,
    field_name VARCHAR(100),
    error_message TEXT NOT NULL,
    raw_data TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- 21. MARK ADJUSTMENTS
CREATE TABLE IF NOT EXISTS public.mq_mark_adjustments (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    attempt_id UUID NOT NULL REFERENCES public.mq_attempts(id) ON DELETE CASCADE,
    original_score NUMERIC(10,2) NOT NULL,
    adjusted_score NUMERIC(10,2) NOT NULL,
    reason TEXT NOT NULL,
    adjusted_by INTEGER NOT NULL REFERENCES public.users(id),
    adjusted_at TIMESTAMPTZ DEFAULT NOW()
);

-- 22. ATTENDANCE
CREATE TABLE IF NOT EXISTS public.mq_attendance (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    quiz_id UUID NOT NULL REFERENCES public.mq_quizzes(id) ON DELETE CASCADE,
    student_id INTEGER NOT NULL REFERENCES public.students(id) ON DELETE CASCADE,
    status VARCHAR(20) NOT NULL DEFAULT 'absent',
    marked_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE (quiz_id, student_id)
);

-- 23. ACTIVITY LOGS
CREATE TABLE IF NOT EXISTS public.mq_activity_logs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id INTEGER REFERENCES public.users(id),
    action VARCHAR(100) NOT NULL,
    entity_type VARCHAR(50),
    entity_id VARCHAR(100),
    details TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- ============================================================================
-- INITIAL SEED DATA
-- ============================================================================

-- Seed Administrator: admin / Admin@123
INSERT INTO public.users (id, username, password_hash, role, is_active)
VALUES (1, 'admin', 'scrypt:32768:8:1$MLvZqFRxEnXRq44a$4686b9e35ba59c60e096d8c845e44d715b16de9bfc17c75b9bbcdef1f45ec8f9d5f91650d43f4da07ced91038a843f5584c9b330803cd83e619cd35ced69b365', 'admin', TRUE)
ON CONFLICT (username) DO NOTHING;

-- Seed Faculty: vvs / Faculty@123
INSERT INTO public.users (id, username, password_hash, role, is_active)
VALUES (2, 'vvs', 'scrypt:32768:8:1$qq2jKww7EsJ7THPw$ca830654141693f76af947a026456b9e30aadee16fdb7f3e1061f3313bbdd211d1ab180e1546c94582aefb96c021fb3e32f2cc16c3bc5b64508219cd79058a4e', 'faculty', TRUE)
ON CONFLICT (username) DO NOTHING;

SELECT setval('users_id_seq', (SELECT MAX(id) FROM public.users));

-- Seed Subjects
INSERT INTO public.subjects (id, subject_code, subject_name, programme_id, semester_id, credits, ica_max, tee_max, status)
VALUES
(1, 'MATH101', 'Applied Mathematics II', 1, 2, 4, 50.0, 100.0, 'Active'),
(2, 'CS101', 'Python Programming & Algorithms', 1, 2, 4, 50.0, 100.0, 'Active')
ON CONFLICT (id) DO NOTHING;

SELECT setval('subjects_id_seq', (SELECT MAX(id) FROM public.subjects));

-- Seed Students
INSERT INTO public.students (id, register_number, student_name, email, programme_id, academic_year_id, current_semester_id, section_id, status)
VALUES
(1, '2026CE001', 'Meera Nair', 'meera.nair@univ.edu', 1, 3, 2, 1, 'Active'),
(2, '2026CE002', 'Arjun Rao', 'arjun.rao@univ.edu', 1, 3, 2, 1, 'Active'),
(3, '2026CE003', 'Rohan Sharma', 'rohan.sharma@univ.edu', 1, 3, 2, 1, 'Active'),
(4, '2026CE004', 'Priya Patel', 'priya.patel@univ.edu', 1, 3, 2, 1, 'Active'),
(5, '2026CE005', 'Siddharth Verma', 'siddharth.verma@univ.edu', 1, 3, 2, 1, 'Active'),
(6, '2026CE006', 'Ananya Gupta', 'ananya.gupta@univ.edu', 1, 3, 2, 1, 'Active'),
(7, '2026CE007', 'Kavya Iyer', 'kavya.iyer@univ.edu', 1, 3, 2, 1, 'Active'),
(8, '2026CE008', 'Vikram Singh', 'vikram.singh@univ.edu', 1, 3, 2, 1, 'Active'),
(9, '2026CE009', 'Aditya Kumar', 'aditya.kumar@univ.edu', 1, 3, 2, 1, 'Active'),
(10, '2026CE010', 'Sneha Reddy', 'sneha.reddy@univ.edu', 1, 3, 2, 1, 'Active')
ON CONFLICT (register_number) DO NOTHING;

SELECT setval('students_id_seq', (SELECT MAX(id) FROM public.students));

-- Seed Active Quizzes
INSERT INTO public.mq_quizzes (
    id, title, quiz_code, subject_id, duration_minutes, total_questions, total_marks, passing_marks,
    distribution_type, negative_marking_enabled, negative_marks, shuffle_questions, shuffle_options,
    max_violations_allowed, result_release_status, status, created_by
)
VALUES
('f0c996fa-8857-4e30-a428-e0b20030dfef', 'Python Programming Examination', 'PYTHON26', 2, 15, 10, 10.0, 4.0, 'all_questions', FALSE, 0.0, TRUE, TRUE, 3, 'published', 'active', 1),
('f51fff02-0e31-44d0-b1c5-4b1abe7ba0c5', 'python_test', 'PYTHON2627', 2, 15, 10, 10.0, 4.0, 'all_questions', FALSE, 0.0, TRUE, TRUE, 3, 'published', 'active', 1),
('4b3a5d45-06fd-4a49-99e6-eee844a32689', 'Mid-Semester Examination: Applied Mathematics II', 'MATH2026', 1, 15, 10, 10.0, 4.0, 'all_questions', FALSE, 0.0, TRUE, TRUE, 3, 'published', 'active', 1)
ON CONFLICT (quiz_code) DO NOTHING;

-- Enroll Students into all quizzes
INSERT INTO public.mq_quiz_students (quiz_id, student_id, sap_id, is_eligible)
SELECT q.id, s.id, s.register_number, TRUE
FROM public.mq_quizzes q
CROSS JOIN public.students s
ON CONFLICT (quiz_id, student_id) DO NOTHING;
