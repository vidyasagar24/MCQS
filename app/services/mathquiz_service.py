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
from sqlalchemy import func
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
def verify_student(student_name: str, sap_id: str, email: str, quiz_code: str):
    """
    Validates SAP ID, Email, and Quiz Code against registered institutional records.
    Returns (success: bool, data: dict, error_message: str)
    """
    clean_sap = (sap_id or '').strip()
    clean_email = (email or '').strip().lower()
    clean_code = (quiz_code or '').strip().upper()
    clean_name = (student_name or '').strip()

    if not clean_sap or not clean_email or not clean_code:
        return False, None, "SAP ID, registered email, and examination quiz code are required."

    quiz = MQQuiz.query.filter(func.upper(MQQuiz.quiz_code) == clean_code).first()
    if not quiz:
        return False, None, "Invalid examination quiz code. Please verify and try again."

    if quiz.status not in ('scheduled', 'active'):
        return False, None, f"Examination is currently {quiz.status}. Access is not permitted."

    # Verify student identity
    student = Student.query.filter(
        func.lower(Student.register_number) == clean_sap.lower()
    ).first()

    if not student:
        return False, None, "Student record not found for the provided SAP ID."

    if student.email and student.email.strip().lower() != clean_email:
        return False, None, "Email address does not match the registered record for this SAP ID."

    # Check quiz registration
    reg = MQQuizStudent.query.filter_by(quiz_id=quiz.id, student_id=student.id).first()
    if not reg or not reg.is_eligible:
        # If registration table has no records for this quiz, allow student by default
        total_registered = MQQuizStudent.query.filter_by(quiz_id=quiz.id).count()
        if total_registered > 0:
            return False, None, "You are not registered for this examination. Contact your faculty."

    # Check existing attempt
    existing_attempt = MQAttempt.query.filter_by(quiz_id=quiz.id, student_id=student.id).first()
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
def start_or_resume_attempt(quiz_id_str: str, student_id: int, client_ip: str = None):
    """
    Starts a new examination attempt or resumes an active in-progress attempt.
    Generates question assignments permanently on initial start.
    """
    quiz = MQQuiz.query.get(uuid.UUID(quiz_id_str))
    if not quiz:
        return False, None, "Quiz not found."

    student = Student.query.get(student_id)
    if not student:
        return False, None, "Student not found."

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
        client_ip=client_ip
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
                    pool_qs = MQQuestion.query.filter_by(quiz_id=quiz.id, is_active=True).all()
                sr.shuffle(pool_qs)
                selected.extend(pool_qs[:p.required_count])
        else:
            all_qs = MQQuestion.query.filter_by(quiz_id=quiz.id, is_active=True).all()
            sr.shuffle(all_qs)
            selected = all_qs[:quiz.total_questions]
        
        if quiz.shuffle_questions:
            sr.shuffle(selected)
        return selected

    # Mode 2: Round Robin - Question Sets
    elif quiz.distribution_type == 'round_robin' and quiz.round_robin_mode == 'question_sets':
        sets = MQQuestionSet.query.filter_by(quiz_id=quiz.id).order_by(MQQuestionSet.sequence.asc()).all()
        if not sets:
            all_qs = MQQuestion.query.filter_by(quiz_id=quiz.id, is_active=True).all()
            return all_qs[:quiz.total_questions]

        # Student cyclic position Si = ((student_id - 1) mod K)
        set_idx = (student.id - 1) % len(sets)
        assigned_set = sets[set_idx]
        items = MQQuestionSetItem.query.filter_by(set_id=assigned_set.id).order_by(MQQuestionSetItem.position.asc()).all()
        qs = [item.question for item in items if item.question.is_active]
        return qs

    # Mode 3: Round Robin - Individual Questions
    elif quiz.distribution_type == 'round_robin' and quiz.round_robin_mode == 'individual_questions':
        all_qs = MQQuestion.query.filter_by(quiz_id=quiz.id, is_active=True).order_by(MQQuestion.created_at.asc()).all()
        if not all_qs:
            return []
        
        n = len(all_qs)
        k = min(quiz.total_questions, n)
        start = (student.id - 1) % n
        selected = [all_qs[(start + i) % n] for i in range(k)]
        return selected

    # Mode 4: All Questions
    else:
        all_qs = MQQuestion.query.filter_by(quiz_id=quiz.id, is_active=True).all()
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

    return True, {
        "attempt_id": str(attempt.id),
        "student_name": attempt.student.student_name,
        "sap_id": attempt.sap_id,
        "quiz_title": attempt.quiz.title,
        "remaining_seconds": remaining_seconds,
        "total_questions": len(paper_questions),
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
    if not attempt or attempt.status != 'in_progress':
        return False, "Attempt not active."

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

    max_strikes = attempt.quiz.max_violations_allowed or 3
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
            "reason": f"Maximum strikes reached ({strike_number}/{max_strikes})"
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
            return True, {
                "submitted": True,
                "status": attempt.status,
                "is_published": False,
                "message": "Examination submitted successfully. Results have not yet been published by faculty."
            }, None
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
    rows = []
    for idx, q in enumerate(questions, 1):
        rows.append((idx, q))
    return rows

def _parse_tex(content_bytes: bytes):
    text = content_bytes.decode('utf-8', errors='replace')
    pattern = re.compile(r'\\begin\{question\}(?:\[(.*?)\])?(.*?)\\end\{question\}', re.DOTALL)
    matches = pattern.findall(text)
    rows = []
    opt_letters = ['A', 'B', 'C', 'D']
    for idx, (batch, body) in enumerate(matches, 1):
        lines = [line.strip() for line in body.split('\n') if line.strip()]
        topic = ""
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
            "batch": batch,
            "explanation": explanation
        }))
    return rows

def _parse_docx(content_bytes: bytes):
    doc = Document(BytesIO(content_bytes))
    paragraphs = [p.text.strip() for p in doc.paragraphs if p.text.strip()]
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

def parse_and_import_questions(file_bytes: bytes, filename: str, quiz_id=None, bank_id=None, user_id=None):
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

        q = MQQuestion(
            quiz_id=quiz_uuid,
            question_bank_id=bank_uuid,
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
