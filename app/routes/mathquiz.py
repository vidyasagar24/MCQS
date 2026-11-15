import os
import uuid
from datetime import datetime
from flask import Blueprint, render_template, request, jsonify, send_file, current_app, redirect, url_for, flash
from flask_login import login_required, current_user
from app.models import db, User, Student, Subject, MQQuiz, MQQuestion, MQQuestionOption, MQAttempt, MQResult
from app.services import mathquiz_service
from app.utils.decorators import admin_required

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
    subjects = Subject.query.filter_by(status='Active').all()
    total_students = Student.query.count()
    total_questions = MQQuestion.query.count()
    return render_template(
        'mathquiz/admin.html',
        quizzes=quizzes,
        subjects=subjects,
        total_students=total_students,
        total_questions=total_questions
    )


# ============================================================================
# STUDENT REST APIs
# ============================================================================

@mathquiz_bp.route('/api/mq/verify-student', methods=['POST'])
def api_verify_student():
    data = request.get_json(silent=True) or {}
    name = data.get('student_name')
    sap = data.get('sap_id')
    email = data.get('email')
    quiz_code = data.get('quiz_code')

    success, payload, err = mathquiz_service.verify_student(name, sap, email, quiz_code)
    if not success:
        return jsonify({"success": False, "error": err}), 400

    return jsonify({"success": True, "data": payload}), 200


@mathquiz_bp.route('/api/mq/start-attempt', methods=['POST'])
def api_start_attempt():
    data = request.get_json(silent=True) or {}
    quiz_id = data.get('quiz_id')
    student_id = data.get('student_id')
    client_ip = request.headers.get('X-Forwarded-For', request.remote_addr)

    success, payload, err = mathquiz_service.start_or_resume_attempt(quiz_id, student_id, client_ip=client_ip)
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
        return jsonify({"success": False, "error": msg}), 400

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
    dist = data.get('distribution_type', 'random_pool')
    rr_mode = data.get('round_robin_mode')
    subj_id = data.get('subject_id')
    neg_enabled = bool(data.get('negative_marking_enabled', False))
    neg_marks = float(data.get('negative_marks', 0.0))
    max_strikes = int(data.get('max_violations_allowed', 3))

    if not code:
        return jsonify({"success": False, "error": "Quiz code is required."}), 400

    if MQQuiz.query.filter_by(quiz_code=code).first():
        return jsonify({"success": False, "error": "Quiz code already exists."}), 400

    quiz = MQQuiz(
        title=title,
        quiz_code=code,
        subject_id=subj_id,
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

    content = file.read()
    success, result, err = mathquiz_service.parse_and_import_questions(
        content,
        file.filename,
        quiz_id=quiz_id,
        bank_id=bank_id,
        user_id=current_user.id
    )
    if not success:
        return jsonify({"success": False, "error": err, "data": result}), 400

    return jsonify({"success": True, "data": result}), 200


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


@mathquiz_bp.route('/mathquiz/templates/download/<category>/<format_ext>')
def download_template(category, format_ext):
    """Serves the 15 downloadable distribution templates."""
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
