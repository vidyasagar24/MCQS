# MathQuiz – Application & Deployment Audit Report
**Document Code:** MQ-AUDIT-001  
**Project:** Academic Assessment Management System (AAMS) + MathQuiz Online Examination Extension  
**Environment:** Vercel (Serverless Python 3.12) + Supabase (PostgreSQL 15 Pooler)  
**Date:** 15 November 2026  

---

## 1. Executive Summary & Purpose
This audit analyzes the existing Academic Assessment Management System (AAMS) codebase (`F:\ICA_Project2`) to ensure that the new **MathQuiz** online mathematics examination system integrates smoothly as an additive extension.

**Core Principle:** 100% Preservation of existing application architecture, routing structures, database records, and authentication flows. Zero destructive changes.

---

## 2. Deployment Architecture & Hosting Environment

### 2.1 Vercel Serverless Hosting
- **Entrypoint:** `api/index.py`
- **Routing Configuration (`vercel.json`):**
  ```json
  {
    "regions": ["cle1"],
    "rewrites": [
      {
        "source": "/(.*)",
        "destination": "/api/index.py"
      }
    ]
  }
  ```
- **Execution Mode:** Read-only root filesystem on AWS Lambda / Vercel container.
- **Instance Directory:** Dynamic fallback to `tempfile.gettempdir()/academic_assessment_instance` to accommodate serverless environments where local file writing is restricted to `/tmp`.

### 2.2 Database Driver & Connectivity
- **Driver:** Pure Python `pg8000` via SQLAlchemy `postgresql+pg8000://` scheme.
- **Rationale:** Avoids native C-extension (`libpq.so`) crashes and GLIBC version mismatches in lightweight AWS Lambda / Vercel Linux runtimes.
- **Connection Pooler:** Connected to Supabase transaction pooler on port 5432 with explicit SSL context (`ssl.create_default_context()`).

---

## 3. Existing Routing & Blueprint Structure

| Blueprint | Prefix / Paths | Key Responsibilities |
| :--- | :--- | :--- |
| `auth_bp` | `/login`, `/logout`, `/change-password` | Faculty & Administrator authentication via Flask-Login. |
| `admin_bp` | `/admin/*` | Master data: programmes, academic years, semesters, sections, faculty mappings. |
| `faculty_bp` | `/faculty/*` | Faculty portal: course allocations, marks entry, class rosters. |
| `reports_bp` | `/reports/*` | Analytics, consolidated grade sheets, PDF and Excel generation. |
| `api_bp` | `/api/*` | Existing marks submission REST endpoints. |
| **`mathquiz_bp`** | `/mathquiz/*`, `/api/mq/*` | **New MathQuiz online examination portal, proctoring, and REST endpoints.** |

---

## 4. Frontend Technology Stack & Reuse Strategy

1. **Base Shell & Layout:**
   - Templating engine: Jinja2 (`app/templates/base.html`).
   - UI Framework: Bootstrap 5.3.3 + FontAwesome 6.5.1 + Custom CSS.
2. **MathQuiz Client Layer:**
   - **Student Entrance:** `app/templates/mathquiz/student_login.html` (Vanilla JS + SAP ID/Email/Quiz Code verification).
   - **Exam Room:** `app/templates/mathquiz/exam.html` (Proctored fullscreen, MathJax 3 mathematical equation rendering, immediate autosave, dynamic watermarking, question palette).
   - **Result Scorecard:** `app/templates/mathquiz/result.html` (Admin-controlled release gate).
   - **Admin/Faculty Console:** `app/templates/mathquiz/admin.html` (LaTeX question editor, symbol toolbar, bulk question ingestion, 15 distribution templates).
3. **Libraries Used:**
   - **MathJax 3 (`tex-svg.js`):** High-fidelity mathematical rendering of complex integrals, matrices, limits, and Greek symbols.
   - **SheetJS (`xlsx.full.min.js`):** In-browser template parsing and export inspection.

---

## 5. Security & Authentication Integration

1. **Admin / Faculty Authentication:**
   - Reuses existing `public.users` table with scrypt password hashing.
   - Handled transparently by `@login_required` and `@admin_required` decorators.
2. **Student Authentication:**
   - **No account creation overhead:** 500 simultaneous students do not require pre-created Supabase Auth accounts.
   - **Verification:** Server-authoritative matching of Student Name + SAP ID (`students.register_number`) + Registered Email (`students.email`) + Examination Code (`mq_quizzes.quiz_code`).
   - **Session Integrity:** Cryptographic 256-bit session token generated upon start; stored as a SHA-256 hash in `mq_attempts.session_token_hash`.
   - **Generic Failure Responses:** Prevents brute-force user enumeration by returning consistent error messages.

---

## 6. Regression Testing & Verification

- **Automated Regression Suite:** `test_app.py` runs 24 unit and integration tests covering the existing AAMS application.
- **Test Result:** 24 out of 24 tests passed (100% success rate) in 20.9 seconds.
- **Compatibility:** Models use universal type decorators (`GUID` and `UniversalJSON`) ensuring complete test compatibility on in-memory SQLite and production PostgreSQL.
