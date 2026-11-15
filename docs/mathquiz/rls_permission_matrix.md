# MathQuiz – Row Level Security & Role Permission Matrix
**Document Code:** MQ-SEC-001  
**Project:** MathQuiz Mathematics Examination & Assessment Management System  
**Version:** 1.0  
**Date:** 15 November 2026  

---

## 1. Overview & Security Principles
In compliance with Section 8.4 and Section 9 of the Technical Blueprint, client browsers are prohibited from holding privileged database credentials or calling raw SQL queries directly. All examination mutations and scorecard lookups are intermediated by secure server functions.

### Core Security Invariants:
1. **Zero Client-Side Service Keys:** The Supabase `service_role` key is strictly kept in secure server-side environment variables.
2. **Result Isolation Gate:** Students can only read their own examination scores after an authorized administrator sets `is_published = true`.
3. **Answer Key Protection:** Correct answer keys (`is_correct = true`) and session token hashes are never sent in student-facing payloads.
4. **Authoritative Expiry:** Expiration timers are checked transactionally on the server; the client-side countdown is display-only.
5. **Admin Retake Exclusivity:** Faculty can view and evaluate all quizzes, but only Administrators can authorize student retakes and publish final results.

---

## 2. Role-Based Access Control (RBAC) Matrix

| Entity / Action | Admin | Faculty | Student (Authenticated Session) | Anonymous / Public |
| :--- | :---: | :---: | :---: | :---: |
| **Quizzes: View List & Metadata** | Full | Full | Eligible Quizzes Only | Denied |
| **Quizzes: Create / Configure / Edit**| Full | Full | Denied | Denied |
| **Quizzes: Publish Official Results** | **Authorized** | Denied | Denied | Denied |
| **Question Bank: View & Manage** | Full | Full | Denied | Denied |
| **Question Options: View Answer Key**| Full | Full | **DENIED (Always Hidden)** | Denied |
| **Student Roster: Upload & Map** | Full | Full | Denied | Denied |
| **Exam Paper: Retrieve Assigned Paper**| View | View | **Own Paper Only (Keys Masked)**| Denied |
| **Exam Answers: Immediate Autosave** | Denied | Denied | **Own Active Attempt Only** | Denied |
| **Violations: Record Browser Strikes**| Review | Review | **Log to Own Attempt** | Denied |
| **Violations: Review & Reset** | Full | Full | Denied | Denied |
| **Evaluation: Auto-Marking ($S = C$)**| System/Trigger | System/Trigger | Denied | Denied |
| **Marks: Manual Adjustments + Audit** | Authorized | Authorized | Denied | Denied |
| **Retake: Authorize with Reason** | **Authorized** | Denied | Denied | Denied |
| **Results: View Scorecard** | Full | Full | **Own Published Result Only** | Denied |
| **Excel 7-Sheet Consolidated Export** | Authorized | Authorized | Denied | Denied |

---

## 3. Table-Level RLS Policy Definition (PostgreSQL 15)

```sql
-- Enable RLS on all MathQuiz tables
ALTER TABLE public.mq_quizzes ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.mq_quiz_students ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.mq_question_banks ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.mq_questions ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.mq_question_options ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.mq_attempts ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.mq_student_assignments ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.mq_answers ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.mq_violations ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.mq_question_marks ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.mq_results ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.mq_attendance ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.mq_activity_logs ENABLE ROW LEVEL SECURITY;

-- Deny all direct anonymous / public access by default
CREATE POLICY deny_all_anonymous_quizzes ON public.mq_quizzes FOR ALL USING (false);
CREATE POLICY deny_all_anonymous_questions ON public.mq_questions FOR ALL USING (false);
CREATE POLICY deny_all_anonymous_options ON public.mq_question_options FOR ALL USING (false);
CREATE POLICY deny_all_anonymous_attempts ON public.mq_attempts FOR ALL USING (false);
CREATE POLICY deny_all_anonymous_answers ON public.mq_answers FOR ALL USING (false);
CREATE POLICY deny_all_anonymous_results ON public.mq_results FOR ALL USING (false);

-- Administrative & Faculty Access via server-authenticated context
CREATE POLICY admin_faculty_all_quizzes ON public.mq_quizzes
    FOR ALL TO authenticated
    USING (EXISTS (SELECT 1 FROM public.users WHERE users.id = auth.uid() AND users.role IN ('admin', 'faculty')));

CREATE POLICY admin_faculty_all_results ON public.mq_results
    FOR ALL TO authenticated
    USING (EXISTS (SELECT 1 FROM public.users WHERE users.id = auth.uid() AND users.role IN ('admin', 'faculty')));

-- Student Result Publication Policy (Own records + Published only)
CREATE POLICY student_view_published_results ON public.mq_results
    FOR SELECT TO authenticated
    USING (
        is_published = true 
        AND sap_id = (SELECT register_number FROM public.students WHERE students.id = auth.uid())
    );
```

---

## 4. Student Session Security Model

1. **Verification Handshake (`POST /api/mq/verify-student`):**
   - Candidate provides `student_name`, `sap_id`, `email`, and `quiz_code`.
   - Validated against active `mq_quiz_students` roster.
   - Prevents enumeration via generic failure messages.
2. **Session Token Generation:**
   - 256-bit cryptographically secure random token (`secrets.token_hex(32)`).
   - Server stores SHA-256 hash (`session_token_hash`).
   - Token is exchanged in memory or via HttpOnly cookies.
3. **Idempotency & Replay Prevention:**
   - Every answer save carries an `idempotency_key`. Duplicate requests with identical keys are acknowledged without duplicate DB revisions.
4. **Authoritative Expiry & Locking:**
   - On submission or server expiry (`now >= expires_at`), attempt status transitions to `submitted` or `auto_submitted`.
   - Further calls to `save-answer` or `get-paper` fail with `HTTP 400 Attempt locked`.
