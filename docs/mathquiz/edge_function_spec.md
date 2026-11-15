# MathQuiz – Edge Functions & API Specification
**Document Code:** MQ-API-001  
**Project:** MathQuiz Mathematics Examination & Assessment Management System  
**Version:** 1.0  
**Date:** 15 November 2026  

---

## 1. Overview
All client-to-server operations in MathQuiz are exposed via secure, transactional REST endpoints implemented in `app/routes/mathquiz.py` and backed by `app/services/mathquiz_service.py`. These endpoints adhere to Supabase Edge Function specifications.

---

## 2. API Catalog & Endpoint Definitions

### 2.1 Student Verification (`POST /api/mq/verify-student`)
- **Access:** Public (Rate-limited, anti-enumeration).
- **Request Body:**
  ```json
  {
    "student_name": "Aarav Sharma",
    "sap_id": "2026CE001",
    "email": "aarav.sharma@institution.edu",
    "quiz_code": "MATH2026"
  }
  ```
- **Response (200 OK):**
  ```json
  {
    "success": true,
    "data": {
      "quiz_id": "4b3a5d45-06fd-4a49-99e6-eee844a32689",
      "student_id": 1,
      "student_name": "Aarav Sharma",
      "sap_id": "2026CE001",
      "quiz_title": "Applied Mathematics II Mid-Term",
      "duration_minutes": 60,
      "total_questions": 10,
      "total_marks": 20.0,
      "attempt_status": "not_started",
      "max_violations_allowed": 3
    }
  }
  ```

---

### 2.2 Start or Resume Attempt (`POST /api/mq/start-attempt`)
- **Access:** Validated Candidate.
- **Request Body:**
  ```json
  {
    "quiz_id": "4b3a5d45-06fd-4a49-99e6-eee844a32689",
    "student_id": 1
  }
  ```
- **Response (200 OK):**
  ```json
  {
    "success": true,
    "data": {
      "attempt_id": "d679a613-2d18-4e8c-8ea9-42b477e3c155",
      "session_token": "a4f89d01b873...",
      "status": "in_progress",
      "started_at": "2026-11-15T09:30:00Z",
      "expires_at": "2026-11-15T10:30:00Z",
      "remaining_seconds": 3600,
      "max_violations": 3
    }
  }
  ```

---

### 2.3 Retrieve Assigned Paper (`POST /api/mq/get-paper`)
- **Access:** Active Student Session Token.
- **Request Body:**
  ```json
  {
    "session_token": "a4f89d01b873..."
  }
  ```
- **Response (200 OK):** *(Answer keys stripped for security)*
  ```json
  {
    "success": true,
    "paper": {
      "attempt_id": "d679a613-2d18-4e8c-8ea9-42b477e3c155",
      "student_name": "Aarav Sharma",
      "sap_id": "2026CE001",
      "remaining_seconds": 3540,
      "questions": [
        {
          "position": 1,
          "question_id": "8f3b...",
          "question_type": "single",
          "latex_source": "Evaluate: $\\int_0^{\\pi/2} \\frac{\\sin^3 x}{\\sin^3 x + \\cos^3 x} dx$",
          "topic": "Integral Calculus",
          "marks": 2.0,
          "options": [
            { "key": "A", "latex": "$\\pi/2$" },
            { "key": "B", "latex": "$\\pi/4$" },
            { "key": "C", "latex": "$\\pi/6$" },
            { "key": "D", "latex": "$1$" }
          ],
          "saved_answer": null,
          "saved_options": []
        }
      ]
    }
  }
  ```

---

### 2.4 Immediate Answer Autosave (`POST /api/mq/save-answer`)
- **Access:** Active Student Session Token.
- **Request Body:**
  ```json
  {
    "session_token": "a4f89d01b873...",
    "question_id": "8f3b...",
    "selected_option": "B",
    "selected_options": ["B"],
    "idempotency_key": "q1_1763198000"
  }
  ```
- **Response (200 OK):**
  ```json
  {
    "success": true,
    "message": "Answer saved."
  }
  ```

---

### 2.5 Security Violation Recording (`POST /api/mq/record-violation`)
- **Access:** Active Student Session Token.
- **Request Body:**
  ```json
  {
    "session_token": "a4f89d01b873...",
    "violation_type": "Browser tab switched or minimized",
    "metadata": { "resolution": "1920x1080", "timestamp": "2026-11-15T09:35:10Z" }
  }
  ```
- **Response (200 OK):**
  ```json
  {
    "success": true,
    "data": {
      "strike_number": 1,
      "max_strikes": 3,
      "auto_submitted": false
    }
  }
  ```

---

### 2.6 Examination Submission (`POST /api/mq/submit-attempt`)
- **Access:** Active Student Session Token.
- **Request Body:**
  ```json
  {
    "session_token": "a4f89d01b873...",
    "auto": false,
    "reason": "Submitted by candidate"
  }
  ```
- **Response (200 OK):**
  ```json
  {
    "success": true,
    "summary": {
      "status": "submitted",
      "submitted_at": "2026-11-15T10:15:00Z",
      "total_attempted": 8,
      "total_questions": 8,
      "result_status": "hidden"
    }
  }
  ```

---

### 2.7 Result Publication Gate (`POST /api/mq/publish-results`)
- **Access:** Administrator Only (`@login_required` + `is_admin`).
- **Request Body:**
  ```json
  {
    "quiz_id": "4b3a5d45-06fd-4a49-99e6-eee844a32689",
    "publish": true
  }
  ```
- **Response (200 OK):**
  ```json
  {
    "success": true,
    "message": "Results published successfully."
  }
  ```

---

### 2.8 Admin Authorize Retake (`POST /api/mq/admin-reset-attempt`)
- **Access:** Administrator Only.
- **Request Body:**
  ```json
  {
    "quiz_id": "4b3a5d45-06fd-4a49-99e6-eee844a32689",
    "student_id": 1,
    "reason": "Technical disruption during first session"
  }
  ```
- **Response (200 OK):**
  ```json
  {
    "success": true,
    "message": "Retake authorized for student 2026CE001 (Attempt #2)."
  }
  ```

---

### 2.9 Bulk Question Ingestion (`POST /api/mq/upload-questions`)
- **Access:** Faculty or Administrator.
- **Multipart Form Data:**
  - `file`: (.xlsx, .csv, .json, .tex, .docx)
  - `quiz_id`: (optional UUID)
  - `bank_id`: (optional UUID)
- **Response (200 OK):**
  ```json
  {
    "success": true,
    "data": {
      "job_id": "962829eb-d59a-410e-a89b-64f135f9a2b0",
      "total_records": 8,
      "successful_records": 8,
      "failed_records": 0,
      "status": "completed",
      "errors": []
    }
  }
  ```

---

### 2.10 Consolidated 7-Sheet Export (`GET /api/mq/export-results/<quiz_id>`)
- **Access:** Faculty or Administrator.
- **Output:** Excel workbook stream with Content-Disposition `attachment; filename=MATHQUIZ_<CODE>_RESULTS_<DATE>.xlsx`.
- **Sheets:** Student Summary, Question-wise Marks, Attendance, Question Analysis, Distribution, Violations, Mark Adjustments.
