import os
import uuid
import re
import csv
import json
import hashlib
import secrets
from datetime import datetime, timedelta
from io import BytesIO, StringIO
import openpyxl
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
from docx import Document
from sqlalchemy import func, or_
from app.models import (
    db, Student, User, Subject,
    MQQuiz, MQQuizStudent, MQQuestionBank, MQQuestion, MQQuestionOption,
    MQQuestionPool, MQPoolQuestion, MQQuestionSet, MQQuestionSetItem, MQAttempt,
    MQStudentAssignment, MQAnswer, MQViolation, MQQuestionMark, MQResult,
    MQMarkAdjustment, MQImportJob, MQImportError, MQAttendance, MQActivityLog
)

def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode('utf-8')).hexdigest()

def generate_session_token() -> str:
    return secrets.token_hex(32)

# ============================================================================
# 1. VERIFICATION & AUTHENTICATION (MQ-01)
# ============================================================================
def verify_student(student_name: str, sap_id: str, email: str, quiz_code: str, system_fingerprint: str = None):
    """
    Validates SAP ID, Student Name, Email, and Quiz Code against registered institutional records.
    Enforces strict 1:1 system lock: Only one SAP ID is allowed to write an exam per system.
    Returns (success: bool, data: dict, error_message: str)
    """
    clean_sap = (sap_id or '').strip()
    clean_email = (email or '').strip().lower()
    clean_code = (quiz_code or '').strip().upper()
    clean_name = (student_name or '').strip()

    if not clean_sap or not clean_email or not clean_code or not clean_name:
        return False, None, "Candidate Name, SAP ID, registered Email, and Examination Quiz Code are all required."

    quiz = MQQuiz.query.filter(func.upper(MQQuiz.quiz_code) == clean_code).first()
    if not quiz:
        return False, None, "Invalid examination quiz code. Please verify and try again."

    if quiz.status != 'active':
        return False, None, f"Examination '{quiz.title}' ({quiz.quiz_code}) is currently deactivated. It cannot be conducted for students at this time."

    # 1. Verify student identity exists in database
    student = Student.query.filter(
        func.lower(Student.register_number) == clean_sap.lower()
    ).first()

    if not student:
        return False, None, f"Student record not found for SAP ID '{clean_sap}'. Please contact the examination administrator."

    # 2. Strict Match: Student Name must match institutional records
    if student.student_name:
        c_name = " ".join(clean_name.lower().split())
        s_name = " ".join(student.student_name.lower().split())
        c_parts = set(c_name.split())
        s_parts = set(s_name.split())
        if c_name != s_name and not (s_parts.issubset(c_parts) or c_parts.issubset(s_parts)):
            return False, None, f"Candidate name '{clean_name}' does not match institutional records for SAP ID '{clean_sap}'."

    # 3. Strict Match: Email must match registered institutional email
    if student.email and student.email.strip().lower() != clean_email:
        return False, None, f"Email address '{clean_email}' does not match the registered record for SAP ID '{clean_sap}'."

    # 4. Strict 1:1 Workstation Lock: Only one SAP ID is allowed per system
    if system_fingerprint:
        conflict_att = MQAttempt.query.filter(
            MQAttempt.quiz_id == quiz.id,
            MQAttempt.system_fingerprint == system_fingerprint,
            MQAttempt.student_id != student.id
        ).first()
        if conflict_att:
            return False, None, f"Access Denied: This system/workstation is already locked to SAP ID '{conflict_att.sap_id}' for this examination. Only one student is permitted per system."

        existing_att = MQAttempt.query.filter_by(quiz_id=quiz.id, student_id=student.id).order_by(MQAttempt.attempt_number.desc()).first()
        if existing_att and existing_att.system_fingerprint and existing_att.system_fingerprint != system_fingerprint:
            if existing_att.status == 'in_progress':
                return False, None, "Security Violation: Your active examination session is locked to another workstation. Device switching is strictly prohibited."

    # Check quiz registration
    reg = MQQuizStudent.query.filter_by(quiz_id=quiz.id, student_id=student.id).first()
    if not reg or not reg.is_eligible:
        # If registration table has no records for this quiz, allow student by default
        total_registered = MQQuizStudent.query.filter_by(quiz_id=quiz.id).count()
        if total_registered > 0:
            return False, None, "You are not registered for this examination. Contact your faculty."

    # Check existing attempt
    existing_attempt = MQAttempt.query.filter_by(quiz_id=quiz.id, student_id=student.id).order_by(MQAttempt.attempt_number.desc()).first()
    attempt_status = existing_attempt.status if existing_attempt else 'not_started'

    return True, {
        "student_id": student.id,
        "student_name": student.student_name,
        "sap_id": student.register_number,
        "email": student.email,
        "quiz_id": str(quiz.id),
        "quiz_title": quiz.title,
        "quiz_code": quiz.quiz_code,
        "duration_minutes": quiz.duration_minutes,
        "total_questions": quiz.total_questions,
        "total_marks": float(quiz.total_marks),
        "attempt_status": attempt_status,
        "max_violations_allowed": quiz.max_violations_allowed
    }, None


# ============================================================================
# 2. ATTEMPT INITIALIZATION & QUESTION DISTRIBUTION (MQ-08, MQ-09)
# ============================================================================
def start_or_resume_attempt(quiz_id_str: str, student_id: int, client_ip: str = None, system_fingerprint: str = None):
    """
    Starts a new examination attempt or resumes an active in-progress attempt.
    Generates question assignments permanently on initial start.
    Enforces 1:1 workstation device lock: Only one SAP ID per system.
    """
    quiz = MQQuiz.query.get(uuid.UUID(quiz_id_str))
    if not quiz:
        return False, None, "Quiz not found."

    if quiz.status != 'active':
        return False, None, f"Examination '{quiz.title}' is currently deactivated. Access is not permitted."

    student = Student.query.get(student_id)
    if not student:
        return False, None, "Student not found."

    # Check device lock: ensure no other student has taken this quiz on this system
    if system_fingerprint:
        conflict_attempt = MQAttempt.query.filter(
            MQAttempt.quiz_id == quiz.id,
            MQAttempt.system_fingerprint == system_fingerprint,
            MQAttempt.student_id != student.id
        ).first()
        if conflict_attempt:
            return False, None, f"Access Denied: This system/workstation is already locked to SAP ID '{conflict_attempt.sap_id}' for this examination. Only one student is permitted per system."

    now = datetime.utcnow()
    existing_attempt = MQAttempt.query.filter_by(quiz_id=quiz.id, student_id=student.id).order_by(MQAttempt.attempt_number.desc()).first()
    next_attempt_num = 1

    if existing_attempt:
        if existing_attempt.status in ('submitted', 'auto_submitted', 'disqualified'):
            # Check if an authorized retake activity log exists after submission
            retake_log = MQActivityLog.query.filter(
                MQActivityLog.action == 'AUTHORIZE_RETAKE',
                MQActivityLog.entity_type == 'mq_attempts',
                MQActivityLog.created_at > (existing_attempt.submitted_at or existing_attempt.started_at)
            ).order_by(MQActivityLog.created_at.desc()).first()

            is_auth = False
            if retake_log and isinstance(retake_log.details, dict):
                if retake_log.details.get('quiz_id') == str(quiz.id) and retake_log.details.get('student_id') == student.id:
                    is_auth = True

            if not is_auth:
                return False, {
                    "attempt_id": str(existing_attempt.id),
                    "status": existing_attempt.status,
                    "submitted_at": existing_attempt.submitted_at.isoformat() if existing_attempt.submitted_at else None
                }, "This examination attempt has already been finalized. Admin authorization is required for a retake."
            else:
                next_attempt_num = (existing_attempt.attempt_number or 1) + 1
                existing_attempt = None

        if existing_attempt:
            # Check workstation lock for resumption
            if existing_attempt.system_fingerprint and system_fingerprint and existing_attempt.system_fingerprint != system_fingerprint:
                return False, None, "Access Denied: Your examination attempt is bound to another workstation. Device switching is strictly prohibited."

            # Bind system fingerprint if not yet bound
            if not existing_attempt.system_fingerprint and system_fingerprint:
                existing_attempt.system_fingerprint = system_fingerprint

            # Check if expired while away
            if now >= existing_attempt.expires_at.replace(tzinfo=None):
                submit_attempt_by_id(existing_attempt.id, auto=True, reason="Examination timer expired.")
                return False, {
                    "attempt_id": str(existing_attempt.id),
                    "status": "auto_submitted",
                    "submitted_at": now.isoformat()
                }, "Your previous examination session has expired and was automatically submitted. Admin authorization is required for a retake."

            # Active session: issue fresh resumption token
            token = generate_session_token()
            existing_attempt.session_token_hash = hash_token(token)
            db.session.commit()

            remaining_seconds = max(0, int((existing_attempt.expires_at.replace(tzinfo=None) - now).total_seconds()))
            return True, {
                "attempt_id": str(existing_attempt.id),
                "session_token": token,
                "status": existing_attempt.status,
                "started_at": existing_attempt.started_at.isoformat(),
                "expires_at": existing_attempt.expires_at.isoformat(),
                "remaining_seconds": remaining_seconds,
                "max_violations": quiz.max_violations_allowed
            }, None

    # Brand new attempt: Generate paper assignment
    questions = _generate_paper_questions(quiz, student)
    if not questions:
        return False, None, "Insufficient questions in question bank for paper generation."

    token = generate_session_token()
    token_h = hash_token(token)
    expires_at = now + timedelta(minutes=quiz.duration_minutes)

    attempt = MQAttempt(
        quiz_id=quiz.id,
        student_id=student.id,
        sap_id=student.register_number,
        session_token_hash=token_h,
        attempt_number=next_attempt_num,
        started_at=now,
        expires_at=expires_at,
        status='in_progress',
        client_ip=client_ip,
        system_fingerprint=system_fingerprint
    )
    db.session.add(attempt)
    db.session.flush()

    # Track attendance status: In-Progress
    att = MQAttendance.query.filter_by(quiz_id=quiz.id, student_id=student.id).first()
    if not att:
        att = MQAttendance(
            quiz_id=quiz.id,
            student_id=student.id,
            sap_id=student.register_number,
            attendance_status='In-Progress'
        )
        db.session.add(att)
    else:
        att.attendance_status = 'In-Progress'

    # Save immutable question assignments
    for pos, q in enumerate(questions, 1):
        perm = ['A', 'B', 'C', 'D']
        if quiz.shuffle_options:
            secrets.SystemRandom().shuffle(perm)

        assign = MQStudentAssignment(
            attempt_id=attempt.id,
            question_id=q.id,
            position=pos,
            options_permutation=perm
        )
        db.session.add(assign)

    db.session.commit()

    remaining_seconds = quiz.duration_minutes * 60
    return True, {
        "attempt_id": str(attempt.id),
        "session_token": token,
        "status": "in_progress",
        "started_at": now.isoformat(),
        "expires_at": expires_at.isoformat(),
        "remaining_seconds": remaining_seconds,
        "max_violations": quiz.max_violations_allowed
    }, None


def _get_eligible_questions_for_quiz(quiz: MQQuiz):
    """
    Returns candidate question pool for a quiz.
    Prioritizes:
    1. Questions explicitly assigned to this quiz (quiz_id == quiz.id).
    2. Questions in Question Bank matching quiz.subject_id.
    3. Fallback: if insufficient, general questions where quiz_id is null and subject_id is null or active.
    """
    # 1. Questions assigned directly to quiz
    direct_qs = MQQuestion.query.filter_by(quiz_id=quiz.id, is_active=True).all()
    if direct_qs and len(direct_qs) >= (quiz.total_questions or 1):
        return direct_qs

    # 2. Questions for quiz subject
    if quiz.subject_id:
        subject_qs = MQQuestion.query.filter(
            MQQuestion.is_active == True,
            (MQQuestion.quiz_id == quiz.id) | (MQQuestion.subject_id == quiz.subject_id)
        ).order_by(MQQuestion.created_at.asc()).all()
        if subject_qs:
            return subject_qs

    # 3. Direct questions if any, otherwise all active
    if direct_qs:
        return direct_qs
    return MQQuestion.query.filter_by(is_active=True).order_by(MQQuestion.created_at.asc()).all()


def _generate_paper_questions(quiz: MQQuiz, student: Student):
    """Executes the approved distribution algorithms."""
    sr = secrets.SystemRandom()

    # Mode 1: Random Pool
    if quiz.distribution_type == 'random_pool':
        pools = MQQuestionPool.query.filter_by(quiz_id=quiz.id).all()
        selected = []
        if pools:
            for p in pools:
                pool_qs = MQQuestion.query.join(
                    MQPoolQuestion, MQPoolQuestion.question_id == MQQuestion.id
                ).filter(
                    MQPoolQuestion.pool_id == p.id,
                    MQQuestion.is_active == True
                ).all()
                if not pool_qs:
                    pool_qs = _get_eligible_questions_for_quiz(quiz)
                sr.shuffle(pool_qs)
                selected.extend(pool_qs[:p.required_count])
        else:
            all_qs = _get_eligible_questions_for_quiz(quiz)
            sr.shuffle(all_qs)
            selected = all_qs[:quiz.total_questions]
        
        if quiz.shuffle_questions:
            sr.shuffle(selected)
        return selected

    # Mode 2: Round Robin - Question Sets
    elif quiz.distribution_type == 'round_robin' and quiz.round_robin_mode == 'question_sets':
        sets = MQQuestionSet.query.filter_by(quiz_id=quiz.id).order_by(MQQuestionSet.sequence.asc()).all()
        if not sets:
            all_qs = _get_eligible_questions_for_quiz(quiz)
            if not all_qs:
                return []
            k = min(quiz.total_questions, len(all_qs))
            num_sets = 4
            set_idx = (student.id - 1) % num_sets
            step = max(1, len(all_qs) // num_sets)
            start_offset = (set_idx * step) % len(all_qs)
            selected = [all_qs[(start_offset + i) % len(all_qs)] for i in range(k)]
            if quiz.shuffle_questions:
                sr.shuffle(selected)
            return selected

        # Student cyclic position Si = ((student_id - 1) mod K)
        set_idx = (student.id - 1) % len(sets)
        assigned_set = sets[set_idx]
        items = MQQuestionSetItem.query.filter_by(set_id=assigned_set.id).order_by(MQQuestionSetItem.position.asc()).all()
        qs = [item.question for item in items if item.question.is_active]
        return qs

    # Mode 3: Round Robin - Individual Questions
    elif quiz.distribution_type == 'round_robin' and quiz.round_robin_mode == 'individual_questions':
        all_qs = _get_eligible_questions_for_quiz(quiz)
        if not all_qs:
            return []
        
        n = len(all_qs)
        k = min(quiz.total_questions, n)
        start = (student.id - 1) % n
        selected = [all_qs[(start + i) % n] for i in range(k)]
        return selected

    # Mode 4: All Questions
    else:
        all_qs = _get_eligible_questions_for_quiz(quiz)
        if quiz.shuffle_questions:
            sr.shuffle(all_qs)
        return all_qs[:quiz.total_questions] if quiz.total_questions else all_qs


# ============================================================================
# 3. EXAMINATION PAPER RETRIEVAL (MQ-09)
# ============================================================================
def get_paper(session_token: str):
    """
    Retrieves the assigned question paper for an active session.
    Never exposes correct answers.
    """
    token_h = hash_token(session_token)
    attempt = MQAttempt.query.filter_by(session_token_hash=token_h).first()
    if not attempt:
        return False, None, "Invalid or expired examination session."

    if attempt.status != 'in_progress':
        return False, None, f"Attempt is {attempt.status}. Paper is locked."

    if attempt.quiz.status != 'active':
        return False, None, f"Examination '{attempt.quiz.title}' is currently deactivated. Paper is locked."

    now = datetime.utcnow()
    if now >= attempt.expires_at.replace(tzinfo=None):
        submit_attempt_by_id(attempt.id, auto=True, reason="Time limit expired.")
        return False, None, "Examination time expired. Your attempt has been auto-submitted."

    assignments = MQStudentAssignment.query.filter_by(attempt_id=attempt.id).order_by(MQStudentAssignment.position.asc()).all()
    ans_by_qid = {a.question_id: a for a in attempt.answers}

    paper_questions = []
    for assign in assignments:
        q = assign.question
        opts_query = MQQuestionOption.query.filter_by(question_id=q.id).order_by(MQQuestionOption.display_order.asc()).all()
        
        # Build options according to assignment permutation
        options_map = {o.option_key: o.latex_source for o in opts_query}
        ordered_options = []
        perm = assign.options_permutation or ['A', 'B', 'C', 'D']
        for key in perm:
            if key in options_map:
                ordered_options.append({
                    "key": key,
                    "latex": options_map[key]
                })

        ans_obj = ans_by_qid.get(q.id)
        s_opt = ans_obj.selected_option if ans_obj else None
        s_opts = ans_obj.selected_options if (ans_obj and ans_obj.selected_options) else ([s_opt] if s_opt else [])

        paper_questions.append({
            "position": assign.position,
            "question_id": str(q.id),
            "latex_source": q.latex_source,
            "question_type": getattr(q, 'question_type', 'single') or 'single',
            "topic": q.topic,
            "difficulty": q.difficulty,
            "marks": float(q.marks),
            "options": ordered_options,
            "saved_answer": s_opt,
            "saved_options": s_opts
        })

    remaining_seconds = max(0, int((attempt.expires_at.replace(tzinfo=None) - now).total_seconds()))
    current_strikes_count = MQViolation.query.filter_by(attempt_id=attempt.id).count()

    return True, {
        "attempt_id": str(attempt.id),
        "student_name": attempt.student.student_name,
        "sap_id": attempt.sap_id,
        "quiz_title": attempt.quiz.title,
        "remaining_seconds": remaining_seconds,
        "total_questions": len(paper_questions),
        "max_violations": attempt.quiz.max_violations_allowed or 3,
        "current_strikes": current_strikes_count,
        "status": attempt.status,
        "questions": paper_questions
    }, None


# ============================================================================
# 4. ANSWER PERSISTENCE (MQ-09)
# ============================================================================
def save_student_answer(session_token: str, question_id_str: str, selected_option: str = None, selected_options: list = None, idempotency_key: str = None):
    """
    Saves student answer with idempotency and server timestamping.
    Supports both single-answer and multiple-answer MCQs.
    """
    token_h = hash_token(session_token)
    attempt = MQAttempt.query.filter_by(session_token_hash=token_h).first()
    if not attempt or attempt.status != 'in_progress':
        return False, "Cannot save answer: Examination attempt is not active."

    now = datetime.utcnow()
    if now >= attempt.expires_at.replace(tzinfo=None):
        submit_attempt_by_id(attempt.id, auto=True, reason="Time expired during answer submission.")
        return False, "Examination timer has expired."

    q_uuid = uuid.UUID(question_id_str)
    # Verify question is assigned to this attempt
    assign = MQStudentAssignment.query.filter_by(attempt_id=attempt.id, question_id=q_uuid).first()
    if not assign:
        return False, "Question is not assigned to this student attempt."

    # Normalize option values
    if selected_options is not None:
        opts_list = [str(x).strip().upper() for x in selected_options if str(x).strip()]
        s_single = opts_list[0] if opts_list else None
    else:
        s_single = str(selected_option).strip().upper() if selected_option else None
        opts_list = [s_single] if s_single else []

    ans = MQAnswer.query.filter_by(attempt_id=attempt.id, question_id=q_uuid).first()
    if ans:
        ans.selected_option = s_single
        ans.selected_options = opts_list
        ans.answered_at = now
        ans.idempotency_key = idempotency_key
        ans.revision_number = (ans.revision_number or 1) + 1
    else:
        ans = MQAnswer(
            attempt_id=attempt.id,
            question_id=q_uuid,
            selected_option=s_single,
            selected_options=opts_list,
            answered_at=now,
            idempotency_key=idempotency_key,
            revision_number=1
        )
        db.session.add(ans)

    db.session.commit()
    return True, "Answer saved."


# ============================================================================
# 5. SECURITY & PROCTORING VIOLATION RECORDING (MQ-10)
# ============================================================================
def record_student_violation(session_token: str, violation_type: str, metadata: dict = None):
    """
    Logs browser security events and automatically submits if threshold reached.
    """
    token_h = hash_token(session_token)
    attempt = MQAttempt.query.filter_by(session_token_hash=token_h).first()
    if not attempt:
        return False, "Attempt not found."

    max_strikes = attempt.quiz.max_violations_allowed or 3

    # If attempt is already terminated/submitted, return auto_submitted status directly
    if attempt.status in ('submitted', 'auto_submitted', 'disqualified'):
        return True, {
            "auto_submitted": True,
            "already_submitted": True,
            "status": attempt.status,
            "strike_number": MQViolation.query.filter_by(attempt_id=attempt.id).count(),
            "max_strikes": max_strikes,
            "reason": attempt.submission_reason or "Examination attempt has already been finalized."
        }

    current_count = MQViolation.query.filter_by(attempt_id=attempt.id).count()
    strike_number = current_count + 1

    viol = MQViolation(
        attempt_id=attempt.id,
        violation_type=violation_type,
        strike_number=strike_number,
        event_metadata=metadata or {}
    )
    db.session.add(viol)
    db.session.commit()

    if strike_number >= max_strikes:
        submit_attempt_by_id(
            attempt.id,
            auto=True,
            reason=f"Auto-submitted: Reached maximum permitted strikes ({strike_number}/{max_strikes}). Last violation: {violation_type}"
        )
        return True, {
            "auto_submitted": True,
            "strike_number": strike_number,
            "max_strikes": max_strikes,
            "reason": f"Maximum permitted strikes reached ({strike_number}/{max_strikes}). Last violation: {violation_type}"
        }

    return True, {
        "auto_submitted": False,
        "strike_number": strike_number,
        "max_strikes": max_strikes
    }


# ============================================================================
# 6. SUBMISSION & AUTOMATIC EVALUATION (MQ-11, MQ-12, MQ-13)
# ============================================================================
def submit_attempt_by_token(session_token: str, auto: bool = False, reason: str = None):
    token_h = hash_token(session_token)
    attempt = MQAttempt.query.filter_by(session_token_hash=token_h).first()
    if not attempt:
        return False, None, "Attempt not found."
    return submit_attempt_by_id(attempt.id, auto=auto, reason=reason)


def submit_attempt_by_id(attempt_id: uuid.UUID, auto: bool = False, reason: str = None):
    attempt = MQAttempt.query.get(attempt_id)
    if not attempt:
        return False, None, "Attempt not found."

    if attempt.status in ('submitted', 'auto_submitted', 'disqualified'):
        return True, {
            "status": attempt.status,
            "submitted_at": attempt.submitted_at.isoformat() if attempt.submitted_at else None,
            "result_status": "hidden"
        }, None

    now = datetime.utcnow()
    attempt.status = 'auto_submitted' if auto else 'submitted'
    attempt.submitted_at = now
    attempt.submission_reason = reason or ("Auto-submitted by system" if auto else "Submitted by student")

    # Evaluate attempt
    quiz = attempt.quiz
    assignments = MQStudentAssignment.query.filter_by(attempt_id=attempt.id).all()
    ans_by_qid = {a.question_id: a for a in attempt.answers}

    total_awarded = 0.0
    total_max = 0.0

    for assign in assignments:
        q = assign.question
        # Correct option set C
        correct_opts = MQQuestionOption.query.filter_by(question_id=q.id, is_correct=True).all()
        correct_set = set(o.option_key for o in correct_opts)

        ans_obj = ans_by_qid.get(q.id)
        if ans_obj:
            if ans_obj.selected_options:
                student_set = set(ans_obj.selected_options)
            elif ans_obj.selected_option:
                student_set = {ans_obj.selected_option}
            else:
                student_set = set()
        else:
            student_set = set()

        q_max = float(q.marks)
        total_max += q_max

        # Exact-match scoring: S == C
        if not student_set:
            awarded = 0.0
            is_corr = False
        elif student_set == correct_set:
            awarded = q_max
            is_corr = True
        else:
            is_corr = False
            if quiz.negative_marking_enabled:
                neg = float(quiz.negative_marks if quiz.negative_marks is not None else (q.negative_marks or 0.0))
                awarded = -neg
            else:
                awarded = 0.0

        total_awarded += awarded

        # Record question-wise marks
        qm = MQQuestionMark(
            attempt_id=attempt.id,
            question_id=q.id,
            maximum_marks=q_max,
            awarded_marks=awarded,
            is_correct=is_corr
        )
        db.session.add(qm)

    total_awarded = max(0.0, total_awarded)  # Floor score at 0 if negative exceeds total
    attempt.total_marks = total_awarded

    percentage = round((total_awarded / total_max * 100), 2) if total_max > 0 else 0.0

    # Update attendance
    att = MQAttendance.query.filter_by(quiz_id=quiz.id, student_id=attempt.student_id).first()
    if att:
        att.attendance_status = 'Present'

    # Save or update consolidated result record
    result = MQResult.query.filter_by(quiz_id=quiz.id, student_id=attempt.student_id).first()
    if not result:
        result = MQResult(
            attempt_id=attempt.id,
            quiz_id=quiz.id,
            student_id=attempt.student_id,
            sap_id=attempt.sap_id,
            attendance_status='Present',
            raw_score=total_awarded,
            final_score=total_awarded,
            maximum_marks=total_max,
            percentage=percentage,
            result_status='EVALUATED',
            is_published=(quiz.result_release_status == 'published')
        )
        db.session.add(result)
    else:
        result.attempt_id = attempt.id
        result.attendance_status = 'Present'
        result.raw_score = total_awarded
        result.final_score = total_awarded
        result.maximum_marks = total_max
        result.percentage = percentage
        result.result_status = 'EVALUATED'
        result.evaluated_at = now

    db.session.commit()

    return True, {
        "status": attempt.status,
        "submitted_at": now.isoformat(),
        "total_attempted": len([a for a in ans_by_qid.values() if (a.selected_option or a.selected_options)]),
        "total_questions": len(assignments),
        "result_status": "hidden"
    }, None


# ============================================================================
# 7. ADMIN RESULT PUBLICATION & STUDENT LOOKUP (MQ-13)
# ============================================================================
def set_result_publication(quiz_id_str: str, publish: bool, admin_user_id: int):
    """Admin toggles result publication status."""
    quiz = MQQuiz.query.get(uuid.UUID(quiz_id_str))
    if not quiz:
        return False, "Quiz not found."

    now = datetime.utcnow()
    quiz.result_release_status = 'published' if publish else 'hidden'

    results = MQResult.query.filter_by(quiz_id=quiz.id).all()
    for r in results:
        r.is_published = publish
        r.published_at = now if publish else None
        r.published_by = admin_user_id if publish else None
        r.result_status = 'PUBLISHED' if publish else 'FINALIZED'

    db.session.commit()
    return True, f"Results {'published' if publish else 'hidden'} successfully."


def set_quiz_status(quiz_id_str: str, status: str, admin_user_id: int = None):
    """
    Admin toggles quiz active / deactive state for conducting examinations.
    'active': Quiz can be conducted for students.
    'deactive': Quiz cannot be conducted for students.
    """
    try:
        q_uuid = uuid.UUID(quiz_id_str)
    except Exception:
        return False, "Invalid Quiz ID format."

    quiz = MQQuiz.query.get(q_uuid)
    if not quiz:
        return False, "Quiz not found."

    clean_status = 'active' if str(status).strip().lower() in ('active', 'activate', '1', 'true') else 'deactive'
    quiz.status = clean_status
    db.session.commit()

    if clean_status == 'active':
        msg = f"Examination '{quiz.title}' ({quiz.quiz_code}) is now ACTIVE. Students can now verify credentials and write this exam."
    else:
        msg = f"Examination '{quiz.title}' ({quiz.quiz_code}) has been DEACTIVATED. Students cannot conduct this exam."

    return True, msg


def admin_authorize_retake(quiz_id_str: str, student_id: int, reason: str, admin_user_id: int):
    """
    Admin authorizes an examination retake with mandatory audit logging.
    Preserves all previous attempts, answers, and results.
    """
    if not reason or not reason.strip():
        return False, "A mandatory reason must be provided to authorize a retake."

    quiz = MQQuiz.query.get(uuid.UUID(quiz_id_str))
    if not quiz:
        return False, "Quiz not found."

    student = Student.query.get(student_id)
    if not student:
        return False, "Student not found."

    prev_attempt = MQAttempt.query.filter_by(quiz_id=quiz.id, student_id=student.id).order_by(MQAttempt.attempt_number.desc()).first()
    if not prev_attempt or prev_attempt.status not in ('submitted', 'auto_submitted', 'disqualified'):
        return False, "Student does not have a completed or disqualified attempt eligible for retake."

    next_num = (prev_attempt.attempt_number or 1) + 1

    log = MQActivityLog(
        actor_user_id=admin_user_id,
        actor_role='admin',
        action='AUTHORIZE_RETAKE',
        entity_type='mq_attempts',
        entity_id=str(prev_attempt.id),
        details={
            "quiz_id": str(quiz.id),
            "quiz_code": quiz.quiz_code,
            "student_id": student.id,
            "sap_id": student.register_number,
            "previous_attempt_number": prev_attempt.attempt_number,
            "new_attempt_number": next_num,
            "reason": reason.strip(),
            "authorized_at": datetime.utcnow().isoformat()
        }
    )
    db.session.add(log)
    db.session.commit()

    return True, f"Retake authorized for student {student.register_number} (Attempt #{next_num})."


def lookup_student_result(sap_id: str, email: str, quiz_code: str = None):
    """Student result lookup respecting Admin publication release gate."""
    clean_sap = (sap_id or '').strip()
    clean_email = (email or '').strip().lower()

    student = Student.query.filter(
        func.lower(Student.register_number) == clean_sap.lower()
    ).first()
    if not student:
        return False, None, "Student record not found."

    if student.email and student.email.strip().lower() != clean_email:
        return False, None, "Email does not match registered record."

    query = MQResult.query.filter_by(student_id=student.id)
    if quiz_code:
        quiz = MQQuiz.query.filter(func.upper(MQQuiz.quiz_code) == quiz_code.strip().upper()).first()
        if quiz:
            query = query.filter_by(quiz_id=quiz.id)

    results = query.order_by(MQResult.evaluated_at.desc()).all()
    if not results:
        # Check if attempt exists but not evaluated
        attempt = MQAttempt.query.filter_by(student_id=student.id).order_by(MQAttempt.started_at.desc()).first()
        if attempt:
            return True, [{
                "quiz_title": attempt.quiz.title,
                "quiz_code": attempt.quiz.quiz_code,
                "submitted": True,
                "status": attempt.status,
                "is_published": False,
                "message": "Examination submitted successfully. Results have not yet been published by faculty."
            }], None
        return False, None, "No examination attempts found for this student."

    output = []
    for r in results:
        q = r.quiz
        if not r.is_published:
            output.append({
                "quiz_title": q.title,
                "quiz_code": q.quiz_code,
                "submitted_at": r.attempt.submitted_at.isoformat() if r.attempt.submitted_at else None,
                "is_published": False,
                "message": "Your submission is verified. Marks are awaiting faculty release."
            })
        else:
            # Published: include detailed scorecard
            items = []
            for assign in r.attempt.assignments:
                question = assign.question
                qm = MQQuestionMark.query.filter_by(attempt_id=r.attempt_id, question_id=question.id).first()
                ans = MQAnswer.query.filter_by(attempt_id=r.attempt_id, question_id=question.id).first()
                correct_opt = MQQuestionOption.query.filter_by(question_id=question.id, is_correct=True).first()

                items.append({
                    "position": assign.position,
                    "question_text": question.latex_source,
                    "student_choice": ans.selected_option if ans else None,
                    "correct_choice": correct_opt.option_key if correct_opt else None,
                    "is_correct": qm.is_correct if qm else False,
                    "awarded_marks": float(qm.awarded_marks) if qm else 0.0,
                    "max_marks": float(qm.maximum_marks) if qm else float(question.marks),
                    "explanation": question.explanation
                })

            output.append({
                "quiz_title": q.title,
                "quiz_code": q.quiz_code,
                "is_published": True,
                "raw_score": float(r.raw_score),
                "final_score": float(r.final_score),
                "maximum_marks": float(r.maximum_marks),
                "percentage": float(r.percentage),
                "attendance": r.attendance_status,
                "items": items
            })

    return True, output, None


# ============================================================================
# 8. 7-SHEET CONSOLIDATED EXCEL WORKBOOK GENERATOR (MQ-15)
# ============================================================================
def generate_consolidated_excel(quiz_id_str: str) -> BytesIO:
    """
    Generates a 7-sheet consolidated workbook:
    1. Student Summary (includes registered absentees marked AB)
    2. Question-wise Marks
    3. Attendance Sheet
    4. Question Analysis
    5. Distribution Assignment
    6. Violations Report
    7. Mark Adjustments
    """
    quiz = MQQuiz.query.get(uuid.UUID(quiz_id_str))
    if not quiz:
        raise ValueError("Quiz not found")

    wb = openpyxl.Workbook()
    wb.remove(wb.active)  # Remove default sheet

    header_font = Font(name="Calibri", size=11, bold=True, color="FFFFFF")
    header_fill = PatternFill(start_color="1E3A8A", end_color="1E3A8A", fill_type="solid")
    border = Border(
        left=Side(style='thin', color='CBD5E1'), right=Side(style='thin', color='CBD5E1'),
        top=Side(style='thin', color='CBD5E1'), bottom=Side(style='thin', color='CBD5E1')
    )
    center = Alignment(horizontal="center", vertical="center")
    left = Alignment(horizontal="left", vertical="center")

    def style_header(ws, headers):
        ws.row_dimensions[1].height = 28
        ws.views.sheetView[0].showGridLines = True
        for col, h in enumerate(headers, 1):
            cell = ws.cell(row=1, column=col, value=h)
            cell.font = header_font
            cell.fill = header_fill
            cell.alignment = center
            cell.border = border

    # Get student roster (eligible or registered)
    registered_students = Student.query.join(MQQuizStudent, MQQuizStudent.student_id == Student.id).filter(
        MQQuizStudent.quiz_id == quiz.id
    ).all()
    if not registered_students:
        registered_students = Student.query.all()  # Institutional fallback

    attempts_map = {a.student_id: a for a in MQAttempt.query.filter_by(quiz_id=quiz.id).all()}
    results_map = {r.student_id: r for r in MQResult.query.filter_by(quiz_id=quiz.id).all()}

    # Sheet 1: Student Summary
    ws1 = wb.create_sheet("Student Summary")
    s1_headers = ["SAP ID", "Student Name", "Email ID", "Section", "Attendance", "Final Marks", "Max Marks", "Percentage", "Result Status"]
    style_header(ws1, s1_headers)
    for r_idx, s in enumerate(registered_students, 2):
        ws1.row_dimensions[r_idx].height = 22
        res = results_map.get(s.id)
        att = attempts_map.get(s.id)

        status_text = res.attendance_status if res else ("Present" if att else "Absent")
        final_marks = float(res.final_score) if res else "AB"
        max_marks = float(res.maximum_marks) if res else float(quiz.total_marks)
        pct = f"{float(res.percentage):.1f}%" if res else "AB"
        res_status = res.result_status if res else "ABSENT"

        section_val = s.section.name if hasattr(s, 'section') and s.section else ""
        vals = [s.register_number, s.student_name, s.email or "", section_val, status_text, final_marks, max_marks, pct, res_status]
        for c_idx, val in enumerate(vals, 1):
            c = ws1.cell(row=r_idx, column=c_idx, value=val)
            c.border = border
            c.alignment = center if c_idx in (1, 4, 5, 8, 9) else left

    # Sheet 2: Question-wise Marks
    ws2 = wb.create_sheet("Question-wise Marks")
    max_q = quiz.total_questions or 10
    s2_headers = ["SAP ID", "Student Name"] + [f"Q{i}" for i in range(1, max_q + 1)] + ["Total Marks"]
    style_header(ws2, s2_headers)
    for r_idx, s in enumerate(registered_students, 2):
        ws2.row_dimensions[r_idx].height = 22
        att = attempts_map.get(s.id)
        res = results_map.get(s.id)
        row_vals = [s.register_number, s.student_name]

        if att:
            q_marks_map = {qm.question_id: float(qm.awarded_marks) for qm in MQQuestionMark.query.filter_by(attempt_id=att.id).all()}
            for assign in att.assignments[:max_q]:
                row_vals.append(q_marks_map.get(assign.question_id, 0.0))
            while len(row_vals) < len(s2_headers) - 1:
                row_vals.append("")
            row_vals.append(float(res.final_score) if res else 0.0)
        else:
            row_vals += ["AB"] * max_q + ["AB"]

        for c_idx, val in enumerate(row_vals, 1):
            c = ws2.cell(row=r_idx, column=c_idx, value=val)
            c.border = border
            c.alignment = center if c_idx != 2 else left

    # Sheet 3: Attendance
    ws3 = wb.create_sheet("Attendance")
    s3_headers = ["SAP ID", "Student Name", "Status", "Start Time", "Submission Time", "Strikes", "Client IP"]
    style_header(ws3, s3_headers)
    for r_idx, s in enumerate(registered_students, 2):
        ws3.row_dimensions[r_idx].height = 22
        att = attempts_map.get(s.id)
        strikes = len(att.violations) if att else 0
        vals = [
            s.register_number,
            s.student_name,
            att.status if att else "Absent",
            att.started_at.strftime("%Y-%m-%d %H:%M:%S") if att and att.started_at else "-",
            att.submitted_at.strftime("%Y-%m-%d %H:%M:%S") if att and att.submitted_at else "-",
            strikes if att else 0,
            att.client_ip if att and att.client_ip else "-"
        ]
        for c_idx, val in enumerate(vals, 1):
            c = ws3.cell(row=r_idx, column=c_idx, value=val)
            c.border = border
            c.alignment = center if c_idx in (1, 3, 6, 7) else left

    # Sheet 4: Question Analysis
    ws4 = wb.create_sheet("Question Analysis")
    s4_headers = ["Question ID", "Topic", "Difficulty", "Total Assigned", "Correct Answers", "Incorrect Answers", "Unanswered", "Accuracy %"]
    style_header(ws4, s4_headers)
    questions = MQQuestion.query.filter_by(quiz_id=quiz.id).all()
    for r_idx, q in enumerate(questions, 2):
        ws4.row_dimensions[r_idx].height = 22
        marks_rows = MQQuestionMark.query.filter_by(question_id=q.id).all()
        corr = sum(1 for m in marks_rows if m.is_correct)
        total_eval = len(marks_rows)
        inc = sum(1 for m in marks_rows if not m.is_correct and float(m.awarded_marks) < 0)
        unans = sum(1 for m in marks_rows if not m.is_correct and float(m.awarded_marks) == 0)
        acc = f"{(corr / total_eval * 100):.1f}%" if total_eval > 0 else "0.0%"

        vals = [str(q.id)[:8], q.topic or "-", q.difficulty, total_eval, corr, inc, unans, acc]
        for c_idx, val in enumerate(vals, 1):
            c = ws4.cell(row=r_idx, column=c_idx, value=val)
            c.border = border
            c.alignment = center

    # Sheet 5: Distribution Blueprint
    ws5 = wb.create_sheet("Distribution")
    s5_headers = ["SAP ID", "Student Name", "Assigned Set / Mode", "Assigned Question Count", "Question Sequence"]
    style_header(ws5, s5_headers)
    for r_idx, s in enumerate(registered_students, 2):
        ws5.row_dimensions[r_idx].height = 22
        att = attempts_map.get(s.id)
        if att:
            seq = ", ".join(f"Q{a.position}" for a in att.assignments)
            vals = [s.register_number, s.student_name, quiz.distribution_type, len(att.assignments), seq]
        else:
            vals = [s.register_number, s.student_name, "Not Attempted", 0, "-"]
        for c_idx, val in enumerate(vals, 1):
            c = ws5.cell(row=r_idx, column=c_idx, value=val)
            c.border = border
            c.alignment = center if c_idx in (1, 3, 4) else left

    # Sheet 6: Security Violations
    ws6 = wb.create_sheet("Violations")
    s6_headers = ["SAP ID", "Student Name", "Violation Type", "Strike #", "Timestamp"]
    style_header(ws6, s6_headers)
    v_rows = MQViolation.query.join(MQAttempt).filter(MQAttempt.quiz_id == quiz.id).order_by(MQViolation.event_time.asc()).all()
    if not v_rows:
        ws6.append(["-", "No violations recorded", "-", "-", "-"])
    for r_idx, v in enumerate(v_rows, 2):
        ws6.row_dimensions[r_idx].height = 22
        att = v.attempt
        vals = [att.sap_id, att.student.student_name, v.violation_type, v.strike_number, v.event_time.strftime("%Y-%m-%d %H:%M:%S")]
        for c_idx, val in enumerate(vals, 1):
            c = ws6.cell(row=r_idx, column=c_idx, value=val)
            c.border = border
            c.alignment = center if c_idx in (1, 4, 5) else left

    # Sheet 7: Mark Adjustments
    ws7 = wb.create_sheet("Mark Adjustments")
    s7_headers = ["SAP ID", "Student Name", "Original Marks", "Revised Marks", "Difference", "Reason", "Adjusted By", "Timestamp"]
    style_header(ws7, s7_headers)
    adj_rows = MQMarkAdjustment.query.join(MQResult).filter(MQResult.quiz_id == quiz.id).all()
    if not adj_rows:
        ws7.append(["-", "No manual adjustments", "-", "-", "-", "-", "-", "-"])
    for r_idx, adj in enumerate(adj_rows, 2):
        ws7.row_dimensions[r_idx].height = 22
        diff = float(adj.revised_marks) - float(adj.original_marks)
        vals = [
            adj.student.register_number if adj.student else "-",
            adj.student.student_name if adj.student else "-",
            float(adj.original_marks),
            float(adj.revised_marks),
            f"{diff:+.2f}",
            adj.reason,
            adj.adjusted_by,
            adj.adjusted_at.strftime("%Y-%m-%d %H:%M:%S")
        ]
        for c_idx, val in enumerate(vals, 1):
            c = ws7.cell(row=r_idx, column=c_idx, value=val)
            c.border = border
            c.alignment = center if c_idx in (1, 3, 4, 5, 7, 8) else left

    # Autofit columns across all sheets
    for ws in wb.worksheets:
        for col in ws.columns:
            max_len = max(len(str(cell.value or '')) for cell in col)
            col_letter = openpyxl.utils.get_column_letter(col[0].column)
            ws.column_dimensions[col_letter].width = max(max_len + 3, 12)

    output = BytesIO()
    wb.save(output)
    output.seek(0)
    return output


# ============================================================================
# 8. BULK QUESTION IMPORT ENGINE (MQ-05)
# ============================================================================

def _parse_csv(content_bytes: bytes):
    text = content_bytes.decode('utf-8-sig', errors='replace')
    reader = csv.DictReader(StringIO(text))
    rows = []
    for idx, r in enumerate(reader, 1):
        rows.append((idx, r))
    return rows

def _parse_excel(content_bytes: bytes):
    wb = openpyxl.load_workbook(BytesIO(content_bytes), data_only=True)
    ws = wb.active
    rows = []
    headers = [str(cell.value or '').strip() for cell in ws[1]]
    for row_idx, row in enumerate(ws.iter_rows(min_row=2, values_only=True), start=2):
        if not any(row):
            continue
        row_dict = {}
        for h, val in zip(headers, row):
            if h:
                row_dict[h] = str(val).strip() if val is not None else ""
        rows.append((row_idx, row_dict))
    return rows

def _parse_json(content_bytes: bytes):
    data = json.loads(content_bytes.decode('utf-8', errors='replace'))
    questions = data.get('questions', [])
    root_subject_code = data.get('subject_code')
    root_subject_name = data.get('subject_name')
    rows = []
    for idx, q in enumerate(questions, 1):
        if isinstance(q, dict):
            if root_subject_code and not q.get('subject_code'):
                q['subject_code'] = root_subject_code
            if root_subject_name and not q.get('subject_name'):
                q['subject_name'] = root_subject_name
        rows.append((idx, q))
    return rows

def _parse_tex(content_bytes: bytes):
    text = content_bytes.decode('utf-8', errors='replace')
    doc_subj = ""
    for line in text.splitlines()[:25]:
        if line.startswith('% SUBJECT:') or line.startswith('% SUBJECT_CODE:'):
            doc_subj = re.sub(r'^%\s*SUBJECT(_CODE)?:\s*', '', line).strip()
            break
            
    pattern = re.compile(r'\\begin\{question\}(?:\[(.*?)\])?(.*?)\\end\{question\}', re.DOTALL)
    matches = pattern.findall(text)
    rows = []
    opt_letters = ['A', 'B', 'C', 'D']
    for idx, (batch, body) in enumerate(matches, 1):
        lines = [line.strip() for line in body.split('\n') if line.strip()]
        topic = ""
        subj_code = doc_subj
        marks = 1.0
        neg_marks = 0.0
        explanation = ""
        question_lines = []
        options = {}
        opt_idx = 0
        correct_answer = None

        for line in lines:
            if line.startswith('% TOPIC:'):
                topic = line.replace('% TOPIC:', '').strip()
            elif line.startswith('% SUBJECT:') or line.startswith('% SUBJECT_CODE:'):
                subj_code = re.sub(r'^%\s*SUBJECT(_CODE)?:\s*', '', line).strip()
            elif line.startswith('% MARKS:'):
                m = re.search(r'MARKS:\s*([\d\.]+)', line)
                if m: marks = float(m.group(1))
                nm = re.search(r'NEGATIVE:\s*([\d\.]+)', line)
                if nm: neg_marks = float(nm.group(1))
            elif line.startswith('% EXPLANATION:'):
                explanation = line.replace('% EXPLANATION:', '').strip()
            elif line.startswith(r'\CorrectChoice') or line.startswith(r'\choice'):
                is_correct = line.startswith(r'\CorrectChoice')
                opt_text = re.sub(r'^\\(CorrectChoice|choice)\s*', '', line).strip()
                if opt_idx < len(opt_letters):
                    let = opt_letters[opt_idx]
                    options[f'option_{let.lower()}'] = opt_text
                    if is_correct:
                        correct_answer = let
                    opt_idx += 1
            else:
                if opt_idx == 0 and not line.startswith('%'):
                    question_lines.append(line)

        rows.append((idx, {
            "question": "\n".join(question_lines),
            "option_a": options.get('option_a', ''),
            "option_b": options.get('option_b', ''),
            "option_c": options.get('option_c', ''),
            "option_d": options.get('option_d', ''),
            "correct_answer": correct_answer or 'A',
            "marks": marks,
            "negative_marks": neg_marks,
            "topic": topic,
            "subject_code": subj_code,
            "batch": batch,
            "explanation": explanation
        }))
    return rows

def _parse_docx(content_bytes: bytes):
    doc = Document(BytesIO(content_bytes))
    paragraphs = [p.text.strip() for p in doc.paragraphs if p.text.strip()]
    doc_subj = ""
    for p in paragraphs[:10]:
        if p.startswith('Subject:'):
            doc_subj = p.replace('Subject:', '').strip()
            if '-' in doc_subj:
                doc_subj = doc_subj.split('-')[0].strip()
            break

    rows = []
    current_q = None
    row_idx = 0

    for p in paragraphs:
        if p.startswith('Question ') and '[' in p:
            if current_q:
                row_idx += 1
                rows.append((row_idx, current_q))
            m = re.search(r'Question\s+\d+\s+\[(.*?)\]', p)
            batch = m.group(1) if m else ""
            current_q = {
                "batch": batch,
                "question": "",
                "subject_code": doc_subj,
                "option_a": "",
                "option_b": "",
                "option_c": "",
                "option_d": "",
                "correct_answer": "A",
                "marks": 1.0,
                "negative_marks": 0.0,
                "topic": "",
                "difficulty": "Medium",
                "explanation": ""
            }
        elif current_q is not None:
            if not current_q["question"]:
                current_q["question"] = p
            elif p.startswith("A) "):
                current_q["option_a"] = p[3:].strip()
            elif p.startswith("B) "):
                current_q["option_b"] = p[3:].strip()
            elif p.startswith("C) "):
                current_q["option_c"] = p[3:].strip()
            elif p.startswith("D) "):
                current_q["option_d"] = p[3:].strip()
            elif p.startswith("Subject:"):
                s_val = p.replace("Subject:", "").strip()
                if '-' in s_val:
                    s_val = s_val.split('-')[0].strip()
                current_q["subject_code"] = s_val
            elif p.startswith("Correct Answer:"):
                ans_match = re.search(r'Correct Answer:\s*([A-D])', p)
                if ans_match: current_q["correct_answer"] = ans_match.group(1)
                marks_match = re.search(r'Marks:\s*([\d\.]+)', p)
                if marks_match: current_q["marks"] = float(marks_match.group(1))
                neg_match = re.search(r'Negative:\s*([\d\.]+)', p)
                if neg_match: current_q["negative_marks"] = float(neg_match.group(1))
            elif p.startswith("Topic:"):
                t_match = re.search(r'Topic:\s*(.*?)(?:\||$)', p)
                if t_match: current_q["topic"] = t_match.group(1).strip()
                diff_match = re.search(r'Difficulty:\s*(.*?)$', p)
                if diff_match: current_q["difficulty"] = diff_match.group(1).strip()
            elif p.startswith("Explanation:"):
                current_q["explanation"] = p.replace("Explanation:", "").strip()

    if current_q:
        row_idx += 1
        rows.append((row_idx, current_q))

    return rows

def parse_and_import_questions(file_bytes: bytes, filename: str, quiz_id=None, bank_id=None, subject_id=None, user_id=None):
    """
    Parses and ingests question documents (.xlsx, .csv, .json, .tex, .docx).
    Validates required fields, creates MQQuestion & MQQuestionOption records,
    and logs errors into MQImportJob & MQImportError.
    """
    ext = filename.rsplit('.', 1)[-1].lower() if '.' in filename else ''
    valid_exts = {'xlsx', 'csv', 'json', 'tex', 'docx'}
    if ext not in valid_exts:
        return False, None, f"Unsupported file format: '.{ext}'. Supported formats are: XLSX, CSV, JSON, TEX, DOCX."

    job = MQImportJob(
        file_name=filename,
        format=ext,
        created_by=user_id,
        status='processing'
    )
    db.session.add(job)
    db.session.commit()

    try:
        if ext == 'csv':
            raw_rows = _parse_csv(file_bytes)
        elif ext == 'xlsx':
            raw_rows = _parse_excel(file_bytes)
        elif ext == 'json':
            raw_rows = _parse_json(file_bytes)
        elif ext == 'tex':
            raw_rows = _parse_tex(file_bytes)
        elif ext == 'docx':
            raw_rows = _parse_docx(file_bytes)
    except Exception as e:
        job.status = 'failed'
        job.failed_records = 0
        err = MQImportError(
            job_id=job.id,
            row_number=0,
            error_message=f"File parse error: {str(e)}",
            raw_data={"filename": filename}
        )
        db.session.add(err)
        db.session.commit()
        return False, {"job_id": str(job.id), "errors": [str(e)]}, f"Failed to parse file: {str(e)}"

    total_records = len(raw_rows)
    success_count = 0
    failed_count = 0
    errors_list = []

    quiz_uuid = uuid.UUID(str(quiz_id)) if quiz_id else None
    bank_uuid = uuid.UUID(str(bank_id)) if bank_id else None

    # Resolve default subject_id (from parameter or from target quiz)
    default_subject_id = None
    if subject_id:
        try:
            default_subject_id = int(subject_id)
        except (ValueError, TypeError):
            default_subject_id = None
    elif quiz_uuid:
        target_quiz = MQQuiz.query.get(quiz_uuid)
        if target_quiz and target_quiz.subject_id:
            default_subject_id = target_quiz.subject_id

    for row_num, item in raw_rows:
        q_text = str(item.get('question') or item.get('question_text') or '').strip()
        opt_a = str(item.get('option_a') or '').strip()
        opt_b = str(item.get('option_b') or '').strip()
        opt_c = str(item.get('option_c') or '').strip()
        opt_d = str(item.get('option_d') or '').strip()
        corr = str(item.get('correct_answer') or item.get('correct_choice') or '').strip().upper()

        val_errors = []
        if not q_text:
            val_errors.append("Question text is empty.")
        if not opt_a or not opt_b or not opt_c or not opt_d:
            val_errors.append("All four options (option_a, option_b, option_c, option_d) must be non-empty.")
        if corr not in ('A', 'B', 'C', 'D'):
            val_errors.append(f"Invalid correct_answer '{corr}'; must be 'A', 'B', 'C', or 'D'.")

        if val_errors:
            failed_count += 1
            err_msg = " | ".join(val_errors)
            errors_list.append({"row": row_num, "error": err_msg})
            import_err = MQImportError(
                job_id=job.id,
                row_number=row_num,
                error_message=err_msg,
                raw_data={k: str(v) for k, v in item.items()} if isinstance(item, dict) else {"raw": str(item)}
            )
            db.session.add(import_err)
            continue

        try:
            marks = float(item.get('marks', 1.0))
        except (ValueError, TypeError):
            marks = 1.0

        try:
            neg_marks = float(item.get('negative_marks', 0.0))
        except (ValueError, TypeError):
            neg_marks = 0.0

        topic = str(item.get('topic') or 'General Mathematics').strip()
        diff = str(item.get('difficulty') or 'Medium').strip().capitalize()
        if diff not in ('Easy', 'Medium', 'Hard'):
            diff = 'Medium'
        explanation = str(item.get('explanation') or '').strip()
        batch_or_pool = str(item.get('pool_id') or item.get('set_id') or item.get('batch') or 'Batch 1').strip()

        # Row-specific subject code, name, or id override
        row_subject_id = default_subject_id
        if item.get('subject_code'):
            sc = str(item['subject_code']).strip().upper()
            s_match = Subject.query.filter(
                (db.func.lower(Subject.subject_code) == sc.lower()) |
                (db.func.lower(Subject.subject_name) == sc.lower())
            ).first()
            if s_match:
                row_subject_id = s_match.id
            else:
                # Dynamically register new subject if not existing
                sn = str(item.get('subject_name') or item.get('subject') or sc).strip()
                try:
                    new_sub = Subject(
                        subject_code=sc,
                        subject_name=sn,
                        programme_id=1,
                        semester_id=1,
                        credits=4,
                        ica_max=50.0,
                        tee_max=100.0,
                        status='Active'
                    )
                    db.session.add(new_sub)
                    db.session.flush()
                    row_subject_id = new_sub.id
                except Exception:
                    pass
        elif item.get('subject_name') or item.get('subject'):
            sn = str(item.get('subject_name') or item.get('subject')).strip()
            s_match = Subject.query.filter(
                (db.func.lower(Subject.subject_name) == sn.lower()) |
                (db.func.lower(Subject.subject_code) == sn.lower())
            ).first()
            if s_match:
                row_subject_id = s_match.id
            else:
                words = [w for w in sn.split() if w]
                sc = "".join([w[0] for w in words]).upper()[:6] if words else sn[:6].upper()
                try:
                    new_sub = Subject(
                        subject_code=sc,
                        subject_name=sn,
                        programme_id=1,
                        semester_id=1,
                        credits=4,
                        ica_max=50.0,
                        tee_max=100.0,
                        status='Active'
                    )
                    db.session.add(new_sub)
                    db.session.flush()
                    row_subject_id = new_sub.id
                except Exception:
                    pass
        elif item.get('subject_id'):
            try:
                row_subject_id = int(item['subject_id'])
            except (ValueError, TypeError):
                pass

        q = MQQuestion(
            quiz_id=quiz_uuid,
            question_bank_id=bank_uuid,
            subject_id=row_subject_id,
            batch_name=batch_or_pool,
            topic=topic,
            difficulty=diff,
            latex_source=q_text,
            marks=marks,
            negative_marks=neg_marks,
            explanation=explanation if explanation else None,
            is_active=True
        )
        db.session.add(q)
        db.session.flush()

        options_data = [
            ('A', opt_a, corr == 'A', 1),
            ('B', opt_b, corr == 'B', 2),
            ('C', opt_c, corr == 'C', 3),
            ('D', opt_d, corr == 'D', 4)
        ]
        for opt_key, opt_text, is_c, disp_order in options_data:
            opt = MQQuestionOption(
                question_id=q.id,
                option_key=opt_key,
                latex_source=opt_text,
                is_correct=is_c,
                display_order=disp_order
            )
            db.session.add(opt)

        pool_id_val = item.get('pool_id')
        if pool_id_val and quiz_uuid:
            p_name = str(pool_id_val).strip()
            pool = MQQuestionPool.query.filter_by(quiz_id=quiz_uuid, pool_name=p_name).first()
            if not pool:
                pool = MQQuestionPool(
                    quiz_id=quiz_uuid,
                    pool_name=p_name,
                    required_count=1,
                    marks_per_question=marks
                )
                db.session.add(pool)
                db.session.flush()
            pool_q = MQPoolQuestion(pool_id=pool.id, question_id=q.id)
            db.session.add(pool_q)

        set_id_val = item.get('set_id')
        if set_id_val and quiz_uuid:
            s_name = str(set_id_val).strip()
            q_set = MQQuestionSet.query.filter_by(quiz_id=quiz_uuid, set_name=s_name).first()
            if not q_set:
                curr_sets = MQQuestionSet.query.filter_by(quiz_id=quiz_uuid).count()
                q_set = MQQuestionSet(
                    quiz_id=quiz_uuid,
                    set_name=s_name,
                    sequence=curr_sets + 1
                )
                db.session.add(q_set)
                db.session.flush()
            next_pos = MQQuestionSetItem.query.filter_by(set_id=q_set.id).count() + 1
            item_pos = item.get('sequence_number')
            try:
                item_pos = int(item_pos) if item_pos else next_pos
            except (ValueError, TypeError):
                item_pos = next_pos
            s_item = MQQuestionSetItem(
                set_id=q_set.id,
                question_id=q.id,
                position=item_pos
            )
            db.session.add(s_item)

        success_count += 1

    job.total_records = total_records
    job.successful_records = success_count
    job.failed_records = failed_count
    job.status = 'completed' if failed_count == 0 else ('partial' if success_count > 0 else 'failed')
    db.session.commit()

    return True, {
        "job_id": str(job.id),
        "total_records": total_records,
        "successful_records": success_count,
        "failed_records": failed_count,
        "status": job.status,
        "errors": errors_list[:20]
    }, None


# ============================================================================
# 10. STUDENT REGISTRATION & ROSTER IMPORT ENGINE (MQ-02)
# ============================================================================

def get_students_list(search_query: str = None, quiz_id_str: str = None, limit: int = 100):
    """
    Returns list of students with optional search and quiz enrollment status.
    """
    query = Student.query
    if search_query:
        sq = f"%{search_query.strip().lower()}%"
        query = query.filter(
            or_(
                func.lower(Student.register_number).ilike(sq),
                func.lower(Student.student_name).ilike(sq),
                func.lower(Student.email).ilike(sq)
            )
        )

    students = query.order_by(Student.register_number.asc()).limit(limit).all()

    enrolled_student_ids = set()
    if quiz_id_str:
        try:
            q_id = uuid.UUID(quiz_id_str)
            enrolled = MQQuizStudent.query.filter_by(quiz_id=q_id, is_eligible=True).all()
            enrolled_student_ids = {e.student_id for e in enrolled}
        except Exception:
            pass

    results = []
    for s in students:
        results.append({
            "id": s.id,
            "sap_id": s.register_number,
            "student_name": s.student_name,
            "email": s.email or "",
            "status": s.status,
            "is_enrolled": (s.id in enrolled_student_ids) if quiz_id_str else None
        })
    return results


def register_student(sap_id: str, student_name: str, email: str = None, quiz_id_str: str = None):
    """
    Registers or updates an individual student record.
    Optionally enrolls the candidate in the specified examination.
    """
    clean_sap = (sap_id or '').strip()
    clean_name = (student_name or '').strip()
    clean_email = (email or '').strip().lower() if email else None

    if not clean_sap or not clean_name:
        return False, None, "SAP ID and Student Name are mandatory."

    student = Student.query.filter(func.lower(Student.register_number) == clean_sap.lower()).first()
    is_new = False
    if not student:
        is_new = True
        student = Student(
            student_id_code=clean_sap,
            register_number=clean_sap,
            student_name=clean_name,
            email=clean_email,
            programme_id=1,
            academic_year_id=3,
            current_semester_id=2,
            section_id=1,
            status='Active'
        )
        db.session.add(student)
        db.session.flush()
    else:
        student.student_name = clean_name
        if clean_email:
            student.email = clean_email
        student.status = 'Active'

    # If quiz_id provided, enroll in quiz
    if quiz_id_str:
        try:
            q_id = uuid.UUID(quiz_id_str)
            reg = MQQuizStudent.query.filter_by(quiz_id=q_id, student_id=student.id).first()
            if not reg:
                reg = MQQuizStudent(
                    quiz_id=q_id,
                    student_id=student.id,
                    sap_id=clean_sap,
                    is_eligible=True
                )
                db.session.add(reg)
            else:
                reg.is_eligible = True
        except Exception:
            pass

    db.session.commit()
    return True, {
        "id": student.id,
        "sap_id": student.register_number,
        "student_name": student.student_name,
        "email": student.email,
        "is_new": is_new
    }, None


def import_students_from_file(file_storage, quiz_id_str: str = None):
    """
    Parses XLSX or CSV student roster and registers students in bulk.
    Expected headers: sap_id (or register_number), student_name (or name), email.
    """
    filename = (file_storage.filename or '').lower()
    content = file_storage.read()

    rows = []
    if filename.endswith('.xlsx'):
        wb = openpyxl.load_workbook(BytesIO(content), data_only=True)
        ws = wb.active
        raw_rows = list(ws.iter_rows(values_only=True))
        if not raw_rows:
            return False, None, "The uploaded Excel file is empty."
        headers = [str(h or '').strip().lower() for h in raw_rows[0]]
        for r in raw_rows[1:]:
            if not any(r):
                continue
            row_dict = {headers[i]: r[i] for i in range(min(len(headers), len(r)))}
            rows.append(row_dict)
    elif filename.endswith('.csv'):
        text_data = content.decode('utf-8', errors='ignore')
        reader = csv.DictReader(StringIO(text_data))
        for r in reader:
            if not any(r.values()):
                continue
            rows.append({k.strip().lower(): v for k, v in r.items() if k})
    else:
        return False, None, "Unsupported file format. Please upload an .xlsx or .csv student roster."

    added_count = 0
    updated_count = 0
    enrolled_count = 0
    errors = []

    quiz_uuid = None
    if quiz_id_str:
        try:
            quiz_uuid = uuid.UUID(quiz_id_str)
        except Exception:
            pass

    for idx, r in enumerate(rows, start=2):
        sap = (
            r.get('sap_id') or r.get('register_number') or r.get('roll_number') or 
            r.get('sap') or r.get('roll_no') or r.get('sapid') or r.get('student_id')
        )
        name = r.get('student_name') or r.get('name') or r.get('full_name') or r.get('candidate_name')
        email = r.get('email') or r.get('email_id') or r.get('mail')

        if not sap or not name:
            errors.append(f"Row {idx}: Missing SAP ID or Student Name.")
            continue

        clean_sap = str(sap).strip()
        clean_name = str(name).strip()
        clean_email = str(email).strip().lower() if email else None

        student = Student.query.filter(func.lower(Student.register_number) == clean_sap.lower()).first()
        if not student:
            student = Student(
                student_id_code=clean_sap,
                register_number=clean_sap,
                student_name=clean_name,
                email=clean_email,
                programme_id=1,
                academic_year_id=3,
                current_semester_id=2,
                section_id=1,
                status='Active'
            )
            db.session.add(student)
            db.session.flush()
            added_count += 1
        else:
            student.student_name = clean_name
            if clean_email:
                student.email = clean_email
            student.status = 'Active'
            updated_count += 1

        if quiz_uuid:
            reg = MQQuizStudent.query.filter_by(quiz_id=quiz_uuid, student_id=student.id).first()
            if not reg:
                reg = MQQuizStudent(
                    quiz_id=quiz_uuid,
                    student_id=student.id,
                    sap_id=clean_sap,
                    is_eligible=True
                )
                db.session.add(reg)
                enrolled_count += 1
            else:
                reg.is_eligible = True

    db.session.commit()
    return True, {
        "total_rows": len(rows),
        "added": added_count,
        "updated": updated_count,
        "enrolled": enrolled_count,
        "errors": errors[:5]
    }, None


# ============================================================================
# 11. DYNAMIC DISTRIBUTION TEMPLATE GENERATOR WITH SUBJECT CATEGORIZATION
# ============================================================================

def generate_distribution_template(category: str, format_ext: str, subject_code: str = None, subject_id: int = None, subject_name: str = None):
    """
    Dynamically generates official distribution templates (.xlsx, .csv, .json, .tex, .docx)
    customized with the selected Academic Subject (subject_code & subject_name).
    When questions are filled and uploaded using these templates, they are automatically
    stored under that Subject's category in the Question Bank.
    """
    subject = None
    if subject_id:
        try:
            subject = Subject.query.get(int(subject_id))
        except (ValueError, TypeError):
            pass
    if not subject and subject_code:
        subject = Subject.query.filter(
            (db.func.lower(Subject.subject_code) == str(subject_code).strip().lower()) |
            (db.func.lower(Subject.subject_name) == str(subject_code).strip().lower())
        ).first()

    if subject:
        code = subject.subject_code
        name = subject.subject_name
    elif subject_code:
        code = str(subject_code).strip().upper()
        name = str(subject_name).strip() if subject_name else f"{code} Course"
    else:
        fallback = Subject.query.filter_by(status='Active').first() or Subject.query.first()
        code = fallback.subject_code if fallback else "GEN101"
        name = fallback.subject_name if fallback else "General Academic Course"

    cat = category.lower().replace('_', '-')
    ext = format_ext.lower().replace('.', '')

    # Special Case: Student Cohort Roster Template
    if cat == 'general':
        wb = openpyxl.Workbook()
        ws = wb.active
        ws.title = "Student Roster"
        header_fill = PatternFill(start_color="312E81", end_color="312E81", fill_type="solid")
        header_font = Font(name="Calibri", size=11, bold=True, color="FFFFFF")
        r_headers = ["sap_id", "student_name", "email", "section_name", "subject_code", "academic_year"]
        ws.append(r_headers)
        for col_num in range(1, len(r_headers) + 1):
            cell = ws.cell(row=1, column=col_num)
            cell.fill = header_fill
            cell.font = header_font
            cell.alignment = Alignment(horizontal="center", vertical="center")
        sample_students = [
            ["2026CE001", "Aarav Sharma", "aarav.sharma@institution.edu", "Section A", code, "2025-2026"],
            ["2026CE002", "Priya Patel", "priya.patel@institution.edu", "Section A", code, "2025-2026"],
            ["2026CE003", "Rohan Gupta", "rohan.gupta@institution.edu", "Section B", code, "2025-2026"]
        ]
        for row in sample_students:
            ws.append(row)
        for col in ws.columns:
            ws.column_dimensions[openpyxl.utils.get_column_letter(col[0].column)].width = 24
        buf = BytesIO()
        wb.save(buf)
        return buf.getvalue(), f"template_student_roster_{code.lower()}.xlsx", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"

    # Distribution Templates: Random Pool, Round Robin, or All Questions
    if cat == 'random-pool':
        headers = [
            "subject_code", "subject_name", "pool_id", "question_id", "question",
            "option_a", "option_b", "option_c", "option_d", "correct_answer",
            "marks", "negative_marks", "topic", "difficulty", "explanation"
        ]
        rows = [
            [
                code, name, "Pool_Foundations", f"Q-{code}-001",
                f"What is the foundational definition or rule in {name}?",
                "Definition A", "Definition B (Standard Canonical)", "Definition C", "Definition D",
                "B", 2.0, 0.5, "Foundations", "Easy", f"Primary principle of {name}."
            ],
            [
                code, name, "Pool_Core", f"Q-{code}-002",
                f"Evaluate the core relationship $\\mathcal{{F}}(x)$ under standard conditions in {name}.",
                "State 1", "State 2", "State 3", "State 4",
                "A", 2.0, 0.5, "Core Methodology", "Medium", "Derived from foundational principles."
            ],
            [
                code, name, "Pool_Advanced", f"Q-{code}-003",
                f"Determine the analytical bound $\\lim_{{n \\to \\infty}} S_n$ in {name}.",
                "$O(n)$", "$O(\\log n)$", "$O(n^2)$", "$O(1)$",
                "B", 3.0, 0.75, "Advanced Analysis", "Hard", "Proven via bounding theorems."
            ]
        ]
    elif cat == 'round-robin':
        headers = [
            "subject_code", "subject_name", "set_id", "sequence_number", "question_id", "question",
            "option_a", "option_b", "option_c", "option_d", "correct_answer",
            "marks", "negative_marks", "topic", "difficulty", "explanation"
        ]
        rows = [
            [
                code, name, "Set_A", 1, f"Q-{code}-A01",
                f"Set A - Question 1: Fundamental formulation in {name}.",
                "Choice 1", "Choice 2", "Choice 3", "Choice 4",
                "A", 2.0, 0.5, "Unit 1", "Medium", "Unit 1 formulation."
            ],
            [
                code, name, "Set_B", 1, f"Q-{code}-B01",
                f"Set B - Question 1: Equivalent variant of formulation in {name}.",
                "Variant 1", "Variant 2", "Variant 3", "Variant 4",
                "B", 2.0, 0.5, "Unit 1", "Medium", "Unit 1 variant."
            ],
            [
                code, name, "Set_C", 1, f"Q-{code}-C01",
                f"Set C - Question 1: Analytical variant in {name}.",
                "Alpha", "Beta", "Gamma", "Delta",
                "C", 2.0, 0.5, "Unit 1", "Medium", "Unit 1 analytical."
            ],
            [
                code, name, "Set_D", 1, f"Q-{code}-D01",
                f"Set D - Question 1: Discrete variant in {name}.",
                "Option 1", "Option 2", "Option 3", "Option 4",
                "D", 2.0, 0.5, "Unit 1", "Medium", "Unit 1 discrete."
            ]
        ]
    else:  # all-questions
        headers = [
            "subject_code", "subject_name", "sequence_number", "question_id", "question",
            "option_a", "option_b", "option_c", "option_d", "correct_answer",
            "marks", "negative_marks", "topic", "difficulty", "explanation"
        ]
        rows = [
            [
                code, name, 1, f"Q-{code}-001",
                f"Question 1: Foundational assessment problem in {name}.",
                "1/2", "1/3", "1/4", "1/5",
                "B", 2.0, 0.5, "Foundations", "Easy", "Standard result."
            ],
            [
                code, name, 2, f"Q-{code}-002",
                f"Question 2: Intermediate diagnostic evaluation in {name}.",
                "True", "False", "Indeterminate", "Non-convergent",
                "A", 2.0, 0.5, "Analysis", "Medium", "Canonical rule."
            ],
            [
                code, name, 3, f"Q-{code}-003",
                f"Question 3: Comprehensive derivation problem in {name}.",
                "Result X", "Result Y", "Result Z", "Result W",
                "C", 3.0, 0.75, "Applied", "Hard", "Derived via theorem."
            ]
        ]

    filename_base = f"template_{cat.replace('-', '_')}_{code.lower()}"

    if ext == 'csv':
        buf = StringIO()
        writer = csv.writer(buf, lineterminator='\n')
        writer.writerow(headers)
        for r in rows:
            writer.writerow(r)
        content = ('\ufeff' + buf.getvalue()).encode('utf-8')
        return content, f"{filename_base}.csv", "text/csv; charset=utf-8"

    elif ext == 'xlsx':
        wb = openpyxl.Workbook()
        ws = wb.active
        ws.title = f"{code} Template"
        header_fill = PatternFill(start_color="312E81", end_color="312E81", fill_type="solid")
        header_font = Font(name="Calibri", size=11, bold=True, color="FFFFFF")
        thin_border = Border(
            left=Side(style='thin', color='CBD5E1'),
            right=Side(style='thin', color='CBD5E1'),
            top=Side(style='thin', color='CBD5E1'),
            bottom=Side(style='thin', color='CBD5E1')
        )
        ws.append(headers)
        for col_num in range(1, len(headers) + 1):
            cell = ws.cell(row=1, column=col_num)
            cell.fill = header_fill
            cell.font = header_font
            cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
            cell.border = thin_border

        for row_idx, r in enumerate(rows, start=2):
            ws.append(r)
            for col_num in range(1, len(r) + 1):
                cell = ws.cell(row=row_idx, column=col_num)
                cell.font = Font(name="Calibri", size=10)
                cell.border = thin_border
                cell.alignment = Alignment(vertical="center")

        for col in ws.columns:
            max_len = max(len(str(cell.value or '')) for cell in col)
            col_letter = openpyxl.utils.get_column_letter(col[0].column)
            ws.column_dimensions[col_letter].width = min(max(max_len + 3, 12), 45)

        buf = BytesIO()
        wb.save(buf)
        return buf.getvalue(), f"{filename_base}.xlsx", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"

    elif ext == 'json':
        q_list = []
        for r in rows:
            q_list.append(dict(zip(headers, r)))
        data = {
            "subject_code": code,
            "subject_name": name,
            "distribution_type": cat,
            "template_version": "1.0",
            "instructions": f"Upload this JSON to automatically store questions under subject category '{code} - {name}' in the Question Bank.",
            "questions": q_list
        }
        return json.dumps(data, indent=2).encode('utf-8'), f"{filename_base}.json", "application/json"

    elif ext == 'tex':
        lines = [
            f"% ============================================================================",
            f"% MathQuiz LaTeX Ingestion Template",
            f"% SUBJECT_CODE: {code}",
            f"% SUBJECT_NAME: {name}",
            f"% DISTRIBUTION: {cat}",
            f"% Instructions: Uploading this file stores questions under subject category '{code}'.",
            f"% ============================================================================\n",
            r"\documentclass{article}",
            r"\usepackage{amsmath,amssymb}",
            r"\begin{document}"
        ]
        for r in rows:
            r_dict = dict(zip(headers, r))
            pool_or_set = r_dict.get('pool_id') or r_dict.get('set_id') or 'Batch 1'
            lines.append(f"\\begin{{question}}[{pool_or_set}]")
            lines.append(f"% SUBJECT: {code}")
            lines.append(f"% TOPIC: {r_dict.get('topic', 'General')}")
            lines.append(f"% MARKS: {r_dict.get('marks', 2.0)}")
            lines.append(f"% NEGATIVE: {r_dict.get('negative_marks', 0.5)}")
            if r_dict.get('explanation'):
                lines.append(f"% EXPLANATION: {r_dict.get('explanation')}")
            lines.append(r_dict['question'])

            corr = r_dict['correct_answer']
            for opt_key in ('A', 'B', 'C', 'D'):
                prefix = r"\CorrectChoice" if corr == opt_key else r"\choice"
                lines.append(f"{prefix} {r_dict[f'option_{opt_key.lower()}']}")
            lines.append(r"\end{question}" + "\n")

        lines.append(r"\end{document}")
        return "\n".join(lines).encode('utf-8'), f"{filename_base}.tex", "application/x-tex"

    elif ext == 'docx':
        doc = Document()
        doc.add_heading(f"MathQuiz Question Template - [{code}] {name}", level=1)
        doc.add_paragraph(f"Subject: {code} - {name}")
        doc.add_paragraph(f"Distribution: {cat.replace('-', ' ').title()}")
        doc.add_paragraph(f"Note: Questions uploaded with this document are automatically saved under '{code} - {name}' in the Question Bank.")

        for idx, r in enumerate(rows, 1):
            r_dict = dict(zip(headers, r))
            batch = r_dict.get('pool_id') or r_dict.get('set_id') or f"Batch {idx}"
            doc.add_heading(f"Question {idx} [{batch}]", level=2)
            doc.add_paragraph(r_dict['question'])

            corr = r_dict['correct_answer']
            for opt_key in ('A', 'B', 'C', 'D'):
                val = r_dict[f'option_{opt_key.lower()}']
                marker = "*" if corr == opt_key else ""
                doc.add_paragraph(f"{marker}{opt_key}) {val}")

            doc.add_paragraph(f"Subject: {code}")
            doc.add_paragraph(f"Topic: {r_dict.get('topic', 'General')} | Difficulty: {r_dict.get('difficulty', 'Medium')} | Marks: {r_dict.get('marks', 1.0)} | Negative: {r_dict.get('negative_marks', 0.0)}")
            if r_dict.get('explanation'):
                doc.add_paragraph(f"Explanation: {r_dict.get('explanation')}")
            doc.add_paragraph("---")

        buf = BytesIO()
        doc.save(buf)
        return buf.getvalue(), f"{filename_base}.docx", "application/vnd.openxmlformats-officedocument.wordprocessingml.document"

    return b"", "template.dat", "application/octet-stream"

