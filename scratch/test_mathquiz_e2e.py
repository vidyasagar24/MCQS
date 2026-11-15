import os
import sys
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
from app import create_app
from app.services import mathquiz_service
from app.models import MQQuiz, Student, MQAttempt, MQResult, MQQuestion, MQQuestionOption

app = create_app()
with app.app_context():
    print("=== TEST 1: STUDENT VERIFICATION ===")
    student = Student.query.filter_by(register_number='2026CE001').first()
    assert student is not None, "Student 2026CE001 must exist"
    
    ok, data, err = mathquiz_service.verify_student(
        student_name=student.student_name,
        sap_id=student.register_number,
        email=student.email,
        quiz_code='MATH2026'
    )
    assert ok, f"Verification failed: {err}"
    print(f"Verified student: {data['student_name']} ({data['sap_id']}) for Quiz: {data['quiz_title']}")

    print("\n=== TEST 2: START ATTEMPT & PAPER GENERATION ===")
    ok, att_data, err = mathquiz_service.start_or_resume_attempt(
        quiz_id_str=data['quiz_id'],
        student_id=data['student_id'],
        client_ip='127.0.0.1'
    )
    if not ok:
        print(f"Notice: Attempt already finalized. Authorizing retake to test...")
        auth_ok, auth_msg = mathquiz_service.admin_authorize_retake(data['quiz_id'], data['student_id'], "Testing Retake flow", 1)
        assert auth_ok, f"Retake authorization failed: {auth_msg}"
        print(f"Admin retake authorized: {auth_msg}")
        ok, att_data, err = mathquiz_service.start_or_resume_attempt(data['quiz_id'], data['student_id'], '127.0.0.1')
    assert ok, f"Start attempt failed: {err}"
    token = att_data['session_token']
    print(f"Attempt started! Attempt ID: {att_data['attempt_id']}, Token generated, Remaining seconds: {att_data['remaining_seconds']}")

    print("\n=== TEST 3: RETRIEVE ASSIGNED QUESTION PAPER ===")
    ok, paper, err = mathquiz_service.get_paper(token)
    assert ok, f"Get paper failed: {err}"
    assert len(paper['questions']) > 0, "Paper must have questions"
    print(f"Paper retrieved successfully! {len(paper['questions'])} assigned questions. First Q: {paper['questions'][0]['latex_source'][:60]}...")
    
    # Verify answers are NOT in the paper
    for q in paper['questions']:
        for opt in q['options']:
            assert 'is_correct' not in opt, "Correctness must not leak to student!"
    print("Security check passed: Correct answer keys NOT exposed.")

    print("\n=== TEST 4: SAVE ANSWERS (SINGLE & MULTI) ===")
    q1 = paper['questions'][0]
    ok, msg = mathquiz_service.save_student_answer(token, q1['question_id'], selected_option='B', idempotency_key='idem_1')
    assert ok, f"Save answer failed: {msg}"
    print("Saved answer for Q1 -> Option B")

    # Multi-answer test on Q2
    if len(paper['questions']) > 1:
        q2 = paper['questions'][1]
        ok, msg = mathquiz_service.save_student_answer(token, q2['question_id'], selected_options=['A', 'C'], idempotency_key='idem_2')
        assert ok, f"Save multi-answer failed: {msg}"
        print("Saved multi-answer for Q2 -> Options [A, C]")

    print("\n=== TEST 5: RECORD VIOLATION (PROCTORING STRIKE) ===")
    ok, viol_res = mathquiz_service.record_student_violation(token, "Browser tab switched", {"screen": "1920x1080"})
    assert ok, "Record violation failed"
    print(f"Strike recorded: Strike #{viol_res['strike_number']} of {viol_res['max_strikes']}")

    print("\n=== TEST 6: SUBMIT ATTEMPT & AUTO-EVALUATE ===")
    ok, sub_summary, err = mathquiz_service.submit_attempt_by_token(token, auto=False, reason="Submitted by student")
    assert ok, f"Submission failed: {err}"
    print(f"Attempt submitted successfully! Status: {sub_summary['status']}, Result release status: {sub_summary['result_status']}")

    print("\n=== TEST 7: STUDENT RESULT LOOKUP BEFORE PUBLICATION ===")
    # Temporarily hide results to verify gating
    quiz = MQQuiz.query.filter_by(quiz_code='MATH2026').first()
    mathquiz_service.set_result_publication(str(quiz.id), publish=False, admin_user_id=1)

    ok, res_data, err = mathquiz_service.lookup_student_result(student.register_number, student.email, 'MATH2026')
    assert ok, f"Lookup failed: {err}"
    assert res_data[0]['is_published'] is False, "Result must be HIDDEN before publication!"
    print(f"Verified hidden status: '{res_data[0]['message']}'")

    print("\n=== TEST 8: ADMIN PUBLISHES RESULTS ===")
    ok, msg = mathquiz_service.set_result_publication(str(quiz.id), publish=True, admin_user_id=1)
    assert ok, f"Publish results failed: {msg}"
    print(f"Results published: {msg}")

    print("\n=== TEST 9: STUDENT RESULT LOOKUP AFTER PUBLICATION ===")
    ok, res_data_pub, err = mathquiz_service.lookup_student_result(student.register_number, student.email, 'MATH2026')
    assert ok, f"Lookup after publish failed: {err}"
    scorecard = res_data_pub[0]
    assert scorecard['is_published'] is True, "Result must now be PUBLISHED!"
    print(f"Official Scorecard: {scorecard['final_score']} / {scorecard['maximum_marks']} ({scorecard['percentage']}%) - Attendance: {scorecard['attendance']}")

    print("\n=== TEST 10: 7-SHEET CONSOLIDATED EXCEL WORKBOOK ===")
    excel_stream = mathquiz_service.generate_consolidated_excel(str(quiz.id))
    excel_bytes = excel_stream.getvalue()
    assert len(excel_bytes) > 5000, "Excel workbook should be substantial"
    print(f"Consolidated 7-Sheet Excel generated! Size: {len(excel_bytes)} bytes.")

    print("\n=== TEST 11: ADMIN AUTHORIZES RETAKE FLOW ===")
    # Student attempts to restart without auth -> should be blocked
    ok_b, data_b, err_b = mathquiz_service.start_or_resume_attempt(str(quiz.id), student.id, '127.0.0.1')
    assert not ok_b, "Should be blocked without admin retake authorization"
    print("Blocked unauthorized retake correctly.")

    # Admin authorizes retake with mandatory reason
    auth_ok, auth_msg = mathquiz_service.admin_authorize_retake(str(quiz.id), student.id, "Medical emergency re-attempt", 1)
    assert auth_ok, f"Retake authorization failed: {auth_msg}"
    print(f"Admin retake authorized: {auth_msg}")

    # Student now resumes/starts Attempt #2
    ok_r, data_r, err_r = mathquiz_service.start_or_resume_attempt(str(quiz.id), student.id, '127.0.0.1')
    assert ok_r, f"Authorized retake failed to start: {err_r}"
    print(f"Attempt #2 started successfully! Attempt ID: {data_r['attempt_id']}")

    print("\nALL 11 END-TO-END INTEGRATION TESTS PASSED 100%!")
