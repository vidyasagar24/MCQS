import os
import uuid
from io import BytesIO
from datetime import datetime
from flask import Blueprint, render_template, request, jsonify, send_file, current_app, redirect, url_for, flash
from flask_login import login_required, current_user
from sqlalchemy import func
from app.models import db, User, Student, Subject, MQQuiz, MQQuestion, MQQuestionOption, MQAttempt, MQResult
from app.services import mathquiz_service
from app.utils.decorators import admin_required, faculty_required

mathquiz_bp = Blueprint('mathquiz', __name__)

# ============================================================================
# STUDENT PORTAL VIEWS (HTML5 / Vanilla JS)
# ============================================================================

@mathquiz_bp.route('/mathquiz')
@mathquiz_bp.route('/mathquiz/student')
def student_portal():
    """Student entrance: verification and login."""
    return render_template('mathquiz/student_login.html')

@mathquiz_bp.route('/mathquiz/exam')
def exam_portal():
    """Proctored examination room with MathJax 3 & Security Monitor."""
    return render_template('mathquiz/exam.html')

@mathquiz_bp.route('/mathquiz/result')
def result_portal():
    """Student result scorecard lookup."""
    return render_template('mathquiz/result.html')


# ============================================================================
# ADMIN & FACULTY DASHBOARD VIEWS
# ============================================================================

@mathquiz_bp.route('/mathquiz/admin')
@login_required
def admin_portal():
    """Integrated MathQuiz Admin & Faculty Examination Console."""
    quizzes = MQQuiz.query.order_by(MQQuiz.created_at.desc()).all()
    active_quizzes_count = sum(1 for q in quizzes if q.status == 'active')
    subjects = Subject.query.filter_by(status='Active').all()
    total_students = Student.query.count()
    students = Student.query.order_by(Student.register_number.asc()).limit(200).all()
    questions = MQQuestion.query.order_by(MQQuestion.created_at.desc()).all()
    total_questions = len(questions)
    topics = sorted(list(set(q.topic for q in questions if q.topic)))
    return render_template(
        'mathquiz/admin.html',
        quizzes=quizzes,
        active_quizzes_count=active_quizzes_count,
        subjects=subjects,
        total_students=total_students,
        students=students,
        questions=questions,
        topics=topics,
        total_questions=total_questions
    )


# ============================================================================
# STUDENT REST APIs
# ============================================================================

@mathquiz_bp.route('/api/mq/student-info/<sap_id>', methods=['GET'])
def api_get_student_info(sap_id):
    """
    Public lookup: Returns candidate name and email for a valid SAP ID.
    Used by student examination login to auto-display name & email upon SAP ID entry.
    """
    clean_sap = (sap_id or '').strip()
    if not clean_sap:
        return jsonify({"success": False, "error": "SAP ID is required."}), 400

    student = Student.query.filter(
        func.lower(Student.register_number) == clean_sap.lower()
    ).first()

    if not student:
        return jsonify({
            "success": False,
            "error": f"No registered student record found for SAP ID '{clean_sap}'. Please verify your roll number."
        }), 404

    return jsonify({
        "success": True,
        "data": {
            "student_id": student.id,
            "sap_id": student.register_number,
            "student_name": student.student_name,
            "email": student.email or ""
        }
    }), 200


@mathquiz_bp.route('/api/mq/verify-student', methods=['POST'])
def api_verify_student():
    data = request.get_json(silent=True) or {}
    name = data.get('student_name')
    sap = data.get('sap_id')
    email = data.get('email')
    quiz_code = data.get('quiz_code')
    sys_fp = data.get('system_fingerprint')

    success, payload, err = mathquiz_service.verify_student(name, sap, email, quiz_code, system_fingerprint=sys_fp)
    if not success:
        return jsonify({"success": False, "error": err}), 400

    return jsonify({"success": True, "data": payload}), 200


@mathquiz_bp.route('/api/mq/start-attempt', methods=['POST'])
def api_start_attempt():
    data = request.get_json(silent=True) or {}
    quiz_id = data.get('quiz_id')
    student_id = data.get('student_id')
    sys_fp = data.get('system_fingerprint')
    client_ip = request.headers.get('X-Forwarded-For', request.remote_addr)

    success, payload, err = mathquiz_service.start_or_resume_attempt(quiz_id, student_id, client_ip=client_ip, system_fingerprint=sys_fp)
    if not success:
        return jsonify({"success": False, "error": err, "data": payload}), 400

    return jsonify({"success": True, "data": payload}), 200


@mathquiz_bp.route('/api/mq/get-paper', methods=['POST'])
def api_get_paper():
    data = request.get_json(silent=True) or {}
    token = data.get('session_token')
    if not token:
        return jsonify({"success": False, "error": "Session token required"}), 401

    success, paper, err = mathquiz_service.get_paper(token)
    if not success:
        return jsonify({"success": False, "error": err}), 400

    return jsonify({"success": True, "paper": paper}), 200


@mathquiz_bp.route('/api/mq/save-answer', methods=['POST'])
def api_save_answer():
    data = request.get_json(silent=True) or {}
    token = data.get('session_token')
    q_id = data.get('question_id')
    opt = data.get('selected_option')
    opts = data.get('selected_options')
    idem = data.get('idempotency_key')

    if not token or not q_id:
        return jsonify({"success": False, "error": "Missing parameters"}), 400

    success, msg = mathquiz_service.save_student_answer(token, q_id, selected_option=opt, selected_options=opts, idempotency_key=idem)
    if not success:
        attempt_inactive = bool("not active" in msg or "expired" in msg or "locked" in msg)
        return jsonify({"success": False, "error": msg, "attempt_inactive": attempt_inactive}), 400

    return jsonify({"success": True, "message": msg}), 200


@mathquiz_bp.route('/api/mq/record-violation', methods=['POST'])
def api_record_violation():
    data = request.get_json(silent=True) or {}
    token = data.get('session_token')
    v_type = data.get('violation_type', 'Unspecified violation')
    metadata = data.get('metadata', {})

    if not token:
        return jsonify({"success": False, "error": "Session token required"}), 401

    success, result = mathquiz_service.record_student_violation(token, v_type, metadata)
    if not success:
        return jsonify({"success": False, "error": result}), 400

    return jsonify({"success": True, "data": result}), 200


@mathquiz_bp.route('/api/mq/submit-attempt', methods=['POST'])
def api_submit_attempt():
    data = request.get_json(silent=True) or {}
    token = data.get('session_token')
    auto = bool(data.get('auto', False))
    reason = data.get('reason')

    if not token:
        return jsonify({"success": False, "error": "Session token required"}), 401

    success, summary, err = mathquiz_service.submit_attempt_by_token(token, auto=auto, reason=reason)
    if not success:
        return jsonify({"success": False, "error": err}), 400

    return jsonify({"success": True, "summary": summary}), 200


@mathquiz_bp.route('/api/mq/check-result', methods=['POST'])
def api_check_result():
    data = request.get_json(silent=True) or {}
    sap = data.get('sap_id')
    email = data.get('email')
    quiz_code = data.get('quiz_code')

    success, results, err = mathquiz_service.lookup_student_result(sap, email, quiz_code)
    if not success:
        return jsonify({"success": False, "error": err}), 400

    return jsonify({"success": True, "results": results}), 200


# ============================================================================
# ADMIN & FACULTY REST APIs
# ============================================================================

@mathquiz_bp.route('/api/mq/create-quiz', methods=['POST'])
@login_required
def api_create_quiz():
    data = request.get_json(silent=True) or {}
    title = data.get('title', 'Engineering Mathematics Examination')
    code = data.get('quiz_code', '').strip().upper()
    dur = int(data.get('duration_minutes', 60))
    raw_dist = str(data.get('distribution_type', 'random_pool')).strip()
    subj_id = data.get('subject_id')
    neg_enabled = bool(data.get('negative_marking_enabled', False))
    neg_marks = float(data.get('negative_marks', 0.0))
    max_strikes = int(data.get('max_violations_allowed', 3))

    # Normalize distribution type and round-robin mode for database constraints
    if raw_dist == 'round_robin_set':
        dist = 'round_robin'
        rr_mode = 'question_sets'
    elif raw_dist == 'round_robin_individual':
        dist = 'round_robin'
        rr_mode = 'individual_questions'
    elif raw_dist in ('random_pool', 'round_robin', 'all_questions'):
        dist = raw_dist
        rr_mode = data.get('round_robin_mode') or ('question_sets' if dist == 'round_robin' else None)
    else:
        dist = 'random_pool'
        rr_mode = None

    if not code:
        return jsonify({"success": False, "error": "Quiz code is required."}), 400

    if MQQuiz.query.filter_by(quiz_code=code).first():
        return jsonify({"success": False, "error": "Quiz code already exists."}), 400

    try:
        quiz = MQQuiz(
            title=title,
            quiz_code=code,
            subject_id=int(subj_id) if subj_id else None,
            duration_minutes=dur,
            total_questions=int(data.get('total_questions', 10)),
            total_marks=float(data.get('total_marks', 20.0)),
            distribution_type=dist,
            round_robin_mode=rr_mode,
            negative_marking_enabled=neg_enabled,
            negative_marks=neg_marks,
            max_violations_allowed=max_strikes,
            status='active',
            created_by=current_user.id
        )
        db.session.add(quiz)
        db.session.commit()
        return jsonify({"success": True, "quiz_id": str(quiz.id), "message": "Quiz created successfully."}), 201
    except Exception as e:
        db.session.rollback()
        return jsonify({"success": False, "error": f"Failed to create examination: {str(e)}"}), 500


@mathquiz_bp.route('/api/mq/publish-results', methods=['POST'])
@login_required
def api_publish_results():
    data = request.get_json(silent=True) or {}
    quiz_id = data.get('quiz_id')
    publish = bool(data.get('publish', True))

    if not quiz_id:
        return jsonify({"success": False, "error": "Quiz ID is required."}), 400

    success, msg = mathquiz_service.set_result_publication(quiz_id, publish, current_user.id)
    if not success:
        return jsonify({"success": False, "error": msg}), 400

    return jsonify({"success": True, "message": msg}), 200


@mathquiz_bp.route('/api/mq/toggle-quiz-status', methods=['POST'])
@login_required
def api_toggle_quiz_status():
    """Admin toggles active / deactive state of an examination for student conduction."""
    data = request.get_json(silent=True) or {}
    quiz_id = data.get('quiz_id')
    status = str(data.get('status', 'active')).strip().lower()

    if not quiz_id:
        return jsonify({"success": False, "error": "Quiz ID is required."}), 400

    success, msg = mathquiz_service.set_quiz_status(quiz_id, status, current_user.id)
    if not success:
        return jsonify({"success": False, "error": msg}), 400

    return jsonify({"success": True, "message": msg}), 200


@mathquiz_bp.route('/api/mq/upload-questions', methods=['POST'])
@login_required
def api_upload_questions():
    """Bulk import questions via TEX, XLSX, CSV, DOCX, JSON."""
    if 'file' not in request.files:
        return jsonify({"success": False, "error": "No file uploaded."}), 400
    file = request.files['file']
    if not file.filename:
        return jsonify({"success": False, "error": "No file selected."}), 400

    quiz_id = request.form.get('quiz_id')
    bank_id = request.form.get('bank_id')
    subject_id = request.form.get('subject_id')

    content = file.read()
    success, result, err = mathquiz_service.parse_and_import_questions(
        content,
        file.filename,
        quiz_id=quiz_id,
        bank_id=bank_id,
        subject_id=subject_id,
        user_id=current_user.id
    )
    if not success:
        return jsonify({"success": False, "error": err, "data": result}), 400

    return jsonify({"success": True, "data": result}), 200


@mathquiz_bp.route('/api/mq/create-question', methods=['POST'])
@login_required
def api_create_question():
    """Authors and saves a single question with LaTeX and MCQ options."""
    data = request.get_json(silent=True) or {}
    q_text = (data.get('latex_source') or '').strip()
    if not q_text:
        return jsonify({"success": False, "error": "Question expression is required."}), 400

    options = data.get('options', [])
    if len(options) < 2:
        return jsonify({"success": False, "error": "At least 2 options are required."}), 400

    subj_id = data.get('subject_id')
    quiz_id = data.get('quiz_id')
    topic = (data.get('topic') or 'General').strip()
    diff = (data.get('difficulty') or 'Medium').strip().capitalize()
    marks = float(data.get('marks', 1.0))
    neg_marks = float(data.get('negative_marks', 0.0))
    expl = (data.get('explanation') or '').strip()

    try:
        q = MQQuestion(
            latex_source=q_text,
            subject_id=int(subj_id) if subj_id else None,
            quiz_id=uuid.UUID(str(quiz_id)) if quiz_id else None,
            topic=topic,
            difficulty=diff if diff in ('Easy', 'Medium', 'Hard') else 'Medium',
            marks=marks,
            negative_marks=neg_marks,
            explanation=expl if expl else None,
            is_active=True
        )
        db.session.add(q)
        db.session.flush()

        for idx, opt in enumerate(options):
            o = MQQuestionOption(
                question_id=q.id,
                option_key=opt.get('key', chr(65 + idx)),
                latex_source=opt.get('text', ''),
                is_correct=bool(opt.get('is_correct', False)),
                display_order=idx + 1
            )
            db.session.add(o)

        db.session.commit()
        return jsonify({"success": True, "question_id": str(q.id), "message": "Question saved successfully to question bank."}), 201
    except Exception as e:
        db.session.rollback()
        return jsonify({"success": False, "error": f"Failed to save question: {str(e)}"}), 500


@mathquiz_bp.route('/api/mq/admin-reset-attempt', methods=['POST'])
@login_required
def api_admin_reset_attempt():
    """Admin authorizes a retake for a student."""
    if not getattr(current_user, 'is_admin', False):
        return jsonify({"success": False, "error": "Only Administrators can authorize examination retakes."}), 403

    data = request.get_json(silent=True) or {}
    quiz_id = data.get('quiz_id')
    student_id = data.get('student_id')
    reason = data.get('reason')

    if not quiz_id or not student_id:
        return jsonify({"success": False, "error": "quiz_id and student_id are required."}), 400

    success, msg = mathquiz_service.admin_authorize_retake(quiz_id, student_id, reason, current_user.id)
    if not success:
        return jsonify({"success": False, "error": msg}), 400

    return jsonify({"success": True, "message": msg}), 200


@mathquiz_bp.route('/api/mq/export-results/<quiz_id>')
@login_required
def api_export_results(quiz_id):
    """Downloads 7-sheet consolidated results workbook."""
    try:
        quiz = MQQuiz.query.get(uuid.UUID(quiz_id))
        if not quiz:
            return jsonify({"error": "Quiz not found"}), 404

        excel_stream = mathquiz_service.generate_consolidated_excel(quiz_id)
        filename = f"MATHQUIZ_{quiz.quiz_code}_RESULTS_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}.xlsx"
        return send_file(
            excel_stream,
            as_attachment=True,
            download_name=filename,
            mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
        )
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ============================================================================
# STUDENT MANAGEMENT REST APIs (Admin / Faculty)
# ============================================================================

@mathquiz_bp.route('/api/mq/students', methods=['GET'])
@login_required
@faculty_required
def api_list_students():
    q = request.args.get('q')
    quiz_id = request.args.get('quiz_id')
    students = mathquiz_service.get_students_list(search_query=q, quiz_id_str=quiz_id)
    return jsonify({"success": True, "students": students}), 200


@mathquiz_bp.route('/api/mq/students/register', methods=['POST'])
@login_required
@faculty_required
def api_register_single_student():
    data = request.get_json(silent=True) or {}
    sap = data.get('sap_id')
    name = data.get('student_name')
    email = data.get('email')
    quiz_id = data.get('quiz_id')

    success, student_data, err = mathquiz_service.register_student(
        sap_id=sap,
        student_name=name,
        email=email,
        quiz_id_str=quiz_id
    )
    if not success:
        return jsonify({"success": False, "error": err}), 400

    return jsonify({"success": True, "data": student_data}), 200


@mathquiz_bp.route('/api/mq/students/import', methods=['POST'])
@login_required
@faculty_required
def api_import_students():
    if 'file' not in request.files:
        return jsonify({"success": False, "error": "No file uploaded."}), 400

    file = request.files['file']
    if not file or file.filename == '':
        return jsonify({"success": False, "error": "Empty filename."}), 400

    quiz_id = request.form.get('quiz_id')
    success, summary, err = mathquiz_service.import_students_from_file(file, quiz_id_str=quiz_id)
    if not success:
        return jsonify({"success": False, "error": err}), 400

    return jsonify({"success": True, "data": summary}), 200


@mathquiz_bp.route('/api/mq/subjects', methods=['GET'])
@login_required
@faculty_required
def api_list_subjects():
    """Lists all active academic subjects registered in the institution database."""
    subjects = Subject.query.filter_by(status='Active').order_by(Subject.subject_code).all()
    return jsonify({
        "success": True,
        "subjects": [
            {"id": s.id, "subject_code": s.subject_code, "subject_name": s.subject_name}
            for s in subjects
        ]
    }), 200


@mathquiz_bp.route('/api/mq/subjects/create', methods=['POST'])
@login_required
@faculty_required
def api_create_subject():
    """
    Registers a new academic subject for question banking, template authoring, and examinations.
    """
    data = request.get_json(silent=True) or {}
    code = str(data.get('subject_code', '')).strip().upper()
    name = str(data.get('subject_name', '')).strip()

    if not code:
        return jsonify({"success": False, "error": "Subject code is required (e.g., CS502, MFCS301)."}), 400
    if not name:
        return jsonify({"success": False, "error": "Subject name is required."}), 400

    # Check for existing subject (case-insensitive by code or name)
    existing = Subject.query.filter(
        (func.lower(Subject.subject_code) == code.lower()) |
        (func.lower(Subject.subject_name) == name.lower())
    ).first()

    if existing:
        return jsonify({
            "success": True,
            "already_existed": True,
            "subject": {
                "id": existing.id,
                "subject_code": existing.subject_code,
                "subject_name": existing.subject_name
            },
            "message": f"Subject '{existing.subject_code} - {existing.subject_name}' is already active and ready to use."
        }), 200

    try:
        new_subject = Subject(
            subject_code=code,
            subject_name=name,
            programme_id=1,
            semester_id=1,
            credits=4,
            ica_max=50.0,
            tee_max=100.0,
            status='Active'
        )
        db.session.add(new_subject)
        db.session.commit()
        return jsonify({
            "success": True,
            "already_existed": False,
            "subject": {
                "id": new_subject.id,
                "subject_code": new_subject.subject_code,
                "subject_name": new_subject.subject_name
            },
            "message": f"Subject '{new_subject.subject_code} - {new_subject.subject_name}' created successfully!"
        }), 201
    except Exception as e:
        db.session.rollback()
        return jsonify({"success": False, "error": f"Failed to create subject: {str(e)}"}), 500


@mathquiz_bp.route('/mathquiz/templates/download/<category>/<format_ext>')
def download_template(category, format_ext):
    """
    Serves the 15 downloadable distribution templates dynamically configured with
    the selected academic subject. Questions authored in this template are automatically
    routed to that subject's category in the Question Bank upon bulk upload.
    """
    subject_code = request.args.get('subject_code')
    subject_id = request.args.get('subject_id')
    subject_name = request.args.get('subject_name')

    try:
        content_bytes, filename, mimetype = mathquiz_service.generate_distribution_template(
            category, format_ext, subject_code=subject_code, subject_id=subject_id, subject_name=subject_name
        )
        if content_bytes and len(content_bytes) > 0:
            return send_file(
                BytesIO(content_bytes),
                as_attachment=True,
                download_name=filename,
                mimetype=mimetype
            )
    except Exception as e:
        current_app.logger.warning(f"Dynamic template generation fallback: {e}")

    # Fallback to pre-packaged static templates if generator encounters an exception
    base_dir = os.path.join(current_app.root_path, 'static', 'templates')
    file_map = {
        ("random-pool", "xlsx"): ("random-pool", "template_random_pool.xlsx"),
        ("random-pool", "csv"): ("random-pool", "template_random_pool.csv"),
        ("random-pool", "docx"): ("random-pool", "template_random_pool.docx"),
        ("random-pool", "json"): ("random-pool", "template_random_pool.json"),
        ("random-pool", "tex"): ("random-pool", "template_random_pool.tex"),
        ("round-robin", "xlsx"): ("round-robin", "template_round_robin.xlsx"),
        ("round-robin", "csv"): ("round-robin", "template_round_robin.csv"),
        ("round-robin", "docx"): ("round-robin", "template_round_robin.docx"),
        ("round-robin", "json"): ("round-robin", "template_round_robin.json"),
        ("round-robin", "tex"): ("round-robin", "template_round_robin.tex"),
        ("all-questions", "xlsx"): ("all-questions", "template_all_questions.xlsx"),
        ("all-questions", "csv"): ("all-questions", "template_all_questions.csv"),
        ("all-questions", "docx"): ("all-questions", "template_all_questions.docx"),
        ("all-questions", "json"): ("all-questions", "template_all_questions.json"),
        ("all-questions", "tex"): ("all-questions", "template_all_questions.tex"),
        ("general", "xlsx"): ("general", "template_student_roster.xlsx"),
    }

    key = (category.lower(), format_ext.lower())
    if key not in file_map:
        return "Template not found", 404

    subfolder, filename = file_map[key]
    filepath = os.path.join(base_dir, subfolder, filename)
    if not os.path.exists(filepath):
        return "File not found", 404

    return send_file(filepath, as_attachment=True, download_name=filename)
