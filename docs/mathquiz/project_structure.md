# MathQuiz – Codebase Organization & Module Directory Map
**Document Code:** MQ-STRUC-001  
**Project:** MathQuiz Mathematics Examination & Assessment Management System  
**Version:** 1.0  
**Date:** 15 November 2026  

---

## 1. Directory Tree

```
F:\ICA_Project2/
│
├── api/
│   └── index.py                     # Vercel Serverless Function entrypoint (cle1 region)
│
├── app/
│   ├── __init__.py                  # Flask Application Factory (Blueprint registrations)
│   ├── config.py                    # Dual dialect config (pg8000 on Supabase, SQLite fallback)
│   │
│   ├── models/
│   │   ├── __init__.py              # Central SQLAlchemy models registry
│   │   ├── academic.py              # Existing AAMS models (Students, Faculty, Subjects, etc.)
│   │   ├── user.py                  # User authentication model (scrypt hashing)
│   │   └── mathquiz.py              # MathQuiz models (MQQuiz, MQQuestion, MQAttempt, etc.)
│   │
│   ├── routes/
│   │   ├── auth.py                  # Login, Logout, Password changes
│   │   ├── admin.py                 # Academic master data management
│   │   ├── faculty.py               # Faculty course allocations and marks entry
│   │   ├── reports.py               # Institutional grade sheets & analytics
│   │   ├── api.py                   # Existing assessment APIs
│   │   └── mathquiz.py              # MathQuiz student portal, admin console & REST APIs
│   │
│   ├── services/
│   │   └── mathquiz_service.py      # Core MathQuiz engine:
│   │                                # - Verification & Session tokens
│   │                                # - Paper generation (4 distribution algorithms)
│   │                                # - Immediate answer autosave
│   │                                # - Proctoring violations & strikes
│   │                                # - Exact-match MCQ evaluation ($S = C$)
│   │                                # - Admin retake authorization
│   │                                # - Bulk question importer (5 formats)
│   │                                # - 7-sheet consolidated Excel generator
│   │
│   ├── static/
│   │   ├── css/custom.css           # Institutional portal styles
│   │   └── templates/               # 15 Downloadable distribution templates:
│   │       ├── random-pool/         # .xlsx, .csv, .docx, .json, .tex
│   │       ├── round-robin/         # .xlsx, .csv, .docx, .json, .tex
│   │       ├── all-questions/       # .xlsx, .csv, .docx, .json, .tex
│   │       └── general/             # template_student_roster.xlsx
│   │
│   └── templates/
│       ├── base.html                # Master portal layout with MathQuiz navigation
│       ├── admin/dashboard.html     # Admin dashboard with quick-access MathQuiz console
│       └── mathquiz/
│           ├── student_login.html   # Student verification portal
│           ├── exam.html            # Proctored room: MathJax 3, watermarks, timer, palette
│           ├── result.html          # Student scorecard lookup (Admin gate respected)
│           └── admin.html           # Admin & Faculty management console
│
├── docs/
│   └── mathquiz/                    # Milestone 1 Governance & Architecture Package:
│       ├── database_inventory.md    # Database audit and live schema inventory
│       ├── application_audit.md     # Application structure & deployment audit
│       ├── mathquiz_erd.md          # Comprehensive Mermaid ER diagram
│       ├── schema_compatibility.md  # Data type & dialect compatibility analysis
│       ├── 001_mathquiz_schema.sql  # Supabase additive migration script
│       ├── rls_permission_matrix.md # Security, RLS and RBAC permissions matrix
│       ├── edge_function_spec.md    # REST API & Edge Function specification
│       └── project_structure.md     # Codebase map and module responsibilities
│
├── scratch/
│   ├── load_test_500.js             # k6 concurrency script for 500 simultaneous candidates
│   └── test_mathquiz_e2e.py         # 11-stage automated end-to-end integration test
│
├── requirements.txt                 # Python dependencies (Flask, openpyxl, python-docx, pg8000)
├── vercel.json                      # Serverless deployment configuration
└── test_app.py                      # AAMS 24-test regression verification suite
```

---

## 2. Component Responsibility Matrix

| Module | Location | Responsibilities |
| :--- | :--- | :--- |
| **Data Layer** | `app/models/mathquiz.py` | Universal SQLAlchemy schema supporting PostgreSQL 15 and SQLite. |
| **Logic Layer** | `app/services/mathquiz_service.py` | Distribution, autosave, exact-match scoring, retakes, Excel reporting. |
| **Controller** | `app/routes/mathquiz.py` | Public and role-gated HTTP endpoints. |
| **Student UI** | `app/templates/mathquiz/exam.html` | MathJax rendering, responsive palette, fullscreen proctoring. |
| **Admin UI** | `app/templates/mathquiz/admin.html` | Examination configuration, LaTeX editor, bulk importer, result toggle. |
| **Verification** | `scratch/test_mathquiz_e2e.py` | 11-stage integration test verifying TRD compliance. |
| **Load Testing** | `scratch/load_test_500.js` | k6 load test simulating 500 concurrent candidates. |
