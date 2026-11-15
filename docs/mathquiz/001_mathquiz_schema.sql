-- ============================================================================
-- MathQuiz Additive Schema Migration Script
-- Version: 1.0
-- Target Database: Supabase PostgreSQL 15
-- Principle: 100% Additive. No existing tables are modified or dropped.
-- ============================================================================

CREATE EXTENSION IF NOT EXISTS pgcrypto;

-- 1. Quizzes Master Configuration
CREATE TABLE IF NOT EXISTS public.mq_quizzes (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    title TEXT NOT NULL,
    quiz_code VARCHAR(30) NOT NULL UNIQUE,
    subject_id INTEGER REFERENCES public.subjects(id) ON DELETE SET NULL,
    mapping_id INTEGER REFERENCES public.faculty_subject_mapping(id) ON DELETE SET NULL,
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
    status VARCHAR(20) NOT NULL DEFAULT 'draft' CHECK (status IN ('draft', 'scheduled', 'active', 'deactive', 'inactive', 'completed', 'archived')),
    created_by INTEGER NOT NULL REFERENCES public.users(id),
    starts_at TIMESTAMPTZ,
    ends_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- 2. Quiz Student Eligibility & Roster
CREATE TABLE IF NOT EXISTS public.mq_quiz_students (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    quiz_id UUID NOT NULL REFERENCES public.mq_quizzes(id) ON DELETE CASCADE,
    student_id INTEGER NOT NULL REFERENCES public.students(id) ON DELETE RESTRICT,
    sap_id VARCHAR(50) NOT NULL,
    registered_at TIMESTAMPTZ DEFAULT NOW(),
    is_eligible BOOLEAN DEFAULT TRUE,
    UNIQUE (quiz_id, student_id),
    UNIQUE (quiz_id, sap_id)
);

-- 3. Question Bank & Categorization
CREATE TABLE IF NOT EXISTS public.mq_question_banks (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name VARCHAR(150) NOT NULL,
    subject_id INTEGER REFERENCES public.subjects(id) ON DELETE SET NULL,
    description TEXT,
    created_by INTEGER NOT NULL REFERENCES public.users(id),
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- 4. Questions
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

-- 5. Question MCQ Options
CREATE TABLE IF NOT EXISTS public.mq_question_options (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    question_id UUID NOT NULL REFERENCES public.mq_questions(id) ON DELETE CASCADE,
    option_key CHAR(1) NOT NULL CHECK (option_key IN ('A', 'B', 'C', 'D', 'E')),
    latex_source TEXT NOT NULL,
    is_correct BOOLEAN NOT NULL DEFAULT FALSE,
    display_order INTEGER NOT NULL DEFAULT 1,
    UNIQUE (question_id, option_key)
);

-- 6. Question Pools (Random Distribution)
CREATE TABLE IF NOT EXISTS public.mq_question_pools (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    quiz_id UUID NOT NULL REFERENCES public.mq_quizzes(id) ON DELETE CASCADE,
    pool_name VARCHAR(100) NOT NULL,
    required_count INTEGER NOT NULL CHECK (required_count > 0),
    marks_per_question NUMERIC(10,2) NOT NULL DEFAULT 1.0,
    UNIQUE (quiz_id, pool_name)
);

-- 7. Pool-Question Junction
CREATE TABLE IF NOT EXISTS public.mq_pool_questions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    pool_id UUID NOT NULL REFERENCES public.mq_question_pools(id) ON DELETE CASCADE,
    question_id UUID NOT NULL REFERENCES public.mq_questions(id) ON DELETE CASCADE,
    UNIQUE (pool_id, question_id)
);

-- 8. Question Sets (Round-Robin Distribution)
CREATE TABLE IF NOT EXISTS public.mq_question_sets (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    quiz_id UUID NOT NULL REFERENCES public.mq_quizzes(id) ON DELETE CASCADE,
    set_name VARCHAR(20) NOT NULL,
    sequence INTEGER NOT NULL,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE (quiz_id, set_name)
);

-- 9. Question Set Items
CREATE TABLE IF NOT EXISTS public.mq_question_set_items (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    set_id UUID NOT NULL REFERENCES public.mq_question_sets(id) ON DELETE CASCADE,
    question_id UUID NOT NULL REFERENCES public.mq_questions(id) ON DELETE CASCADE,
    position INTEGER NOT NULL,
    UNIQUE (set_id, position),
    UNIQUE (set_id, question_id)
);

-- 10. Student Examination Attempts
CREATE TABLE IF NOT EXISTS public.mq_attempts (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    quiz_id UUID NOT NULL REFERENCES public.mq_quizzes(id) ON DELETE RESTRICT,
    student_id INTEGER NOT NULL REFERENCES public.students(id) ON DELETE RESTRICT,
    sap_id VARCHAR(50) NOT NULL,
    session_token_hash VARCHAR(64) NOT NULL,
    assigned_set_id UUID REFERENCES public.mq_question_sets(id) ON DELETE SET NULL,
    attempt_number INTEGER NOT NULL DEFAULT 1,
    started_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    expires_at TIMESTAMPTZ NOT NULL,
    submitted_at TIMESTAMPTZ,
    status VARCHAR(30) NOT NULL DEFAULT 'in_progress' CHECK (status IN ('in_progress', 'submitted', 'auto_submitted', 'disqualified')),
    total_marks NUMERIC(10,2),
    submission_reason TEXT,
    client_ip VARCHAR(50),
    system_fingerprint VARCHAR(100),
    created_at TIMESTAMPTZ DEFAULT NOW(),
    CONSTRAINT uq_mq_attempt_quiz_student_attempt_number UNIQUE (quiz_id, student_id, attempt_number)
);

-- 11. Student Paper Question Assignments
CREATE TABLE IF NOT EXISTS public.mq_student_assignments (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    attempt_id UUID NOT NULL REFERENCES public.mq_attempts(id) ON DELETE CASCADE,
    question_id UUID NOT NULL REFERENCES public.mq_questions(id) ON DELETE RESTRICT,
    position INTEGER NOT NULL,
    options_permutation JSONB,
    assigned_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE (attempt_id, question_id),
    UNIQUE (attempt_id, position)
);

-- 12. Student Answers
CREATE TABLE IF NOT EXISTS public.mq_answers (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    attempt_id UUID NOT NULL REFERENCES public.mq_attempts(id) ON DELETE CASCADE,
    question_id UUID NOT NULL REFERENCES public.mq_questions(id) ON DELETE RESTRICT,
    selected_option CHAR(1),
    selected_options JSONB DEFAULT '[]'::jsonb,
    answered_at TIMESTAMPTZ DEFAULT NOW(),
    idempotency_key VARCHAR(64),
    revision_number INTEGER DEFAULT 1,
    UNIQUE (attempt_id, question_id)
);

-- 13. Proctoring & Browser Violations
CREATE TABLE IF NOT EXISTS public.mq_violations (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    attempt_id UUID NOT NULL REFERENCES public.mq_attempts(id) ON DELETE CASCADE,
    violation_type VARCHAR(100) NOT NULL,
    event_time TIMESTAMPTZ DEFAULT NOW(),
    strike_number INTEGER NOT NULL DEFAULT 1,
    metadata JSONB DEFAULT '{}'::jsonb
);

-- 14. Question Marks Evaluation
CREATE TABLE IF NOT EXISTS public.mq_question_marks (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    attempt_id UUID NOT NULL REFERENCES public.mq_attempts(id) ON DELETE CASCADE,
    question_id UUID NOT NULL REFERENCES public.mq_questions(id) ON DELETE RESTRICT,
    maximum_marks NUMERIC(10,2) NOT NULL DEFAULT 1.0,
    awarded_marks NUMERIC(10,2) NOT NULL DEFAULT 0.0,
    is_correct BOOLEAN NOT NULL DEFAULT FALSE,
    evaluated_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE (attempt_id, question_id)
);

-- 15. Consolidated Examination Results
CREATE TABLE IF NOT EXISTS public.mq_results (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    attempt_id UUID NOT NULL REFERENCES public.mq_attempts(id) ON DELETE CASCADE UNIQUE,
    quiz_id UUID NOT NULL REFERENCES public.mq_quizzes(id) ON DELETE CASCADE,
    student_id INTEGER NOT NULL REFERENCES public.students(id) ON DELETE RESTRICT,
    sap_id VARCHAR(50) NOT NULL,
    attendance_status VARCHAR(20) NOT NULL DEFAULT 'Present',
    raw_score NUMERIC(10,2) NOT NULL DEFAULT 0.0,
    grace_marks NUMERIC(10,2) DEFAULT 0.0,
    adjustment_marks NUMERIC(10,2) DEFAULT 0.0,
    final_score NUMERIC(10,2) NOT NULL DEFAULT 0.0,
    maximum_marks NUMERIC(10,2) NOT NULL DEFAULT 0.0,
    percentage NUMERIC(7,2) NOT NULL DEFAULT 0.0,
    result_status VARCHAR(30) NOT NULL DEFAULT 'EVALUATED' CHECK (result_status IN ('EVALUATED', 'UNDER_REVIEW', 'FINALIZED', 'PUBLISHED')),
    evaluated_at TIMESTAMPTZ DEFAULT NOW(),
    is_published BOOLEAN DEFAULT FALSE,
    published_at TIMESTAMPTZ,
    published_by INTEGER REFERENCES public.users(id),
    UNIQUE (quiz_id, student_id)
);

-- 16. Attendance Tracking
CREATE TABLE IF NOT EXISTS public.mq_attendance (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    quiz_id UUID NOT NULL REFERENCES public.mq_quizzes(id) ON DELETE CASCADE,
    student_id INTEGER NOT NULL REFERENCES public.students(id) ON DELETE RESTRICT,
    sap_id VARCHAR(50) NOT NULL,
    attendance_status VARCHAR(20) NOT NULL DEFAULT 'Absent',
    marked_by INTEGER REFERENCES public.users(id),
    marked_at TIMESTAMPTZ DEFAULT NOW(),
    reason TEXT,
    UNIQUE (quiz_id, student_id)
);

-- 17. Activity & Audit Logs
CREATE TABLE IF NOT EXISTS public.mq_activity_logs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    actor_user_id INTEGER REFERENCES public.users(id),
    actor_role VARCHAR(30),
    action VARCHAR(100) NOT NULL,
    entity_type VARCHAR(50) NOT NULL,
    entity_id VARCHAR(100),
    details JSONB,
    ip_address VARCHAR(50),
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- 18. Manual Mark Adjustments
CREATE TABLE IF NOT EXISTS public.mq_mark_adjustments (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    result_id UUID NOT NULL REFERENCES public.mq_results(id) ON DELETE CASCADE,
    student_id INTEGER REFERENCES public.students(id),
    original_marks NUMERIC(10,2) NOT NULL,
    revised_marks NUMERIC(10,2) NOT NULL,
    reason TEXT NOT NULL,
    adjusted_by INTEGER NOT NULL REFERENCES public.users(id),
    adjusted_at TIMESTAMPTZ DEFAULT NOW()
);

-- 19. Bulk Import Jobs & Errors
CREATE TABLE IF NOT EXISTS public.mq_import_jobs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    file_name TEXT NOT NULL,
    format VARCHAR(20) NOT NULL,
    total_records INTEGER DEFAULT 0,
    successful_records INTEGER DEFAULT 0,
    failed_records INTEGER DEFAULT 0,
    status VARCHAR(30) DEFAULT 'completed',
    created_by INTEGER REFERENCES public.users(id),
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS public.mq_import_errors (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    job_id UUID NOT NULL REFERENCES public.mq_import_jobs(id) ON DELETE CASCADE,
    row_number INTEGER NOT NULL,
    error_message TEXT NOT NULL,
    raw_data JSONB
);

-- ============================================================================
-- PERFORMANCE & HIGH-CONCURRENCY INDEXES
-- ============================================================================
CREATE INDEX IF NOT EXISTS idx_mq_quizzes_code ON public.mq_quizzes(quiz_code);
CREATE INDEX IF NOT EXISTS idx_mq_quizzes_status ON public.mq_quizzes(status);
CREATE INDEX IF NOT EXISTS idx_mq_quiz_students_sap ON public.mq_quiz_students(sap_id);
CREATE INDEX IF NOT EXISTS idx_mq_quiz_students_quiz_eligible ON public.mq_quiz_students(quiz_id, is_eligible);
CREATE INDEX IF NOT EXISTS idx_mq_questions_quiz ON public.mq_questions(quiz_id);
CREATE INDEX IF NOT EXISTS idx_mq_questions_subject ON public.mq_questions(subject_id);
CREATE INDEX IF NOT EXISTS idx_mq_attempts_token ON public.mq_attempts(session_token_hash);
CREATE INDEX IF NOT EXISTS idx_mq_attempts_quiz_status ON public.mq_attempts(quiz_id, status);
CREATE INDEX IF NOT EXISTS idx_mq_attempts_expiry ON public.mq_attempts(expires_at) WHERE status = 'in_progress';
CREATE INDEX IF NOT EXISTS idx_mq_answers_attempt ON public.mq_answers(attempt_id);
CREATE INDEX IF NOT EXISTS idx_mq_results_quiz ON public.mq_results(quiz_id, result_status);
CREATE INDEX IF NOT EXISTS idx_mq_attendance_quiz ON public.mq_attendance(quiz_id, attendance_status);
CREATE INDEX IF NOT EXISTS idx_mq_violations_attempt_time ON public.mq_violations(attempt_id, event_time);
CREATE INDEX IF NOT EXISTS idx_mq_activity_logs_actor ON public.mq_activity_logs(actor_user_id, created_at);
