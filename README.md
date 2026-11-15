# MathQuiz – Online Mathematics Examination & Assessment Management System

[![Target Capacity](https://img.shields.io/badge/Concurrency-500%20Students-blue)](https://github.com/vidyasagar24/MCQS)
[![Stack](https://img.shields.io/badge/Stack-Python%20%7C%20Flask%20%7C%20Supabase%20%7C%20Vercel-success)](https://github.com/vidyasagar24/MCQS)
[![MathJax](https://img.shields.io/badge/Math-MathJax%203%20LaTeX-orange)](https://github.com/vidyasagar24/MCQS)
[![License](https://img.shields.io/badge/License-Proprietary%20Academic-lightgrey)](https://github.com/vidyasagar24/MCQS)

**MathQuiz** is an online mathematics MCQ examination, real-time proctoring, and assessment management platform. It features full LaTeX mathematical expression rendering via MathJax 3, four question distribution algorithms, immediate answer autosave, proctoring security monitors, exact-match multiple-choice scoring ($S = C$), administrator-controlled result publication, and 7-sheet consolidated Excel reporting.

---

## 1. System Architecture

```
                    +------------------------------------+
                    |       MathQuiz Web Platform        |
                    |   (Vercel Serverless / HTML5 UI)   |
                    +-----------------+------------------+
                                      |
            +-------------------------+-------------------------+
            |                                                   |
            v                                                   v
+-----------------------+                           +-----------------------+
|   Candidate Portal    |                           |  Faculty/Admin Portal |
| SAP ID + Email + Code |                           | Examination Console   |
+-----------+-----------+                           +-----------+-----------+
            |                                                   |
            +-------------------------+-------------------------+
                                      |
                                      v
                    +------------------------------------+
                    |       Flask & SQLAlchemy Engine    |
                    |  - 4 Distribution Engines          |
                    |  - Exact-Match Evaluator (S = C)   |
                    |  - 5-Format Question Parser        |
                    |  - 7-Sheet Excel Generator         |
                    +-----------------+------------------+
                                      |
                                      v
                    +------------------------------------+
                    |        Supabase PostgreSQL         |
                    |  - 19 Additive `mq_*` Tables       |
                    |  - Institutional Records           |
                    |  - Server-Authoritative Expiry     |
                    +------------------------------------+
```

---

## 2. Key Product Capabilities

- **Mathematical Notation (LaTeX & MathJax 3):** Native rendering of complex integrals ($\int_a^b$), limits ($\lim_{x \to 0}$), matrices, sums ($\sum$), Greek symbols, and fractions.
- **Four Question Distribution Algorithms:**
  1. *Random Pool:* Topic and difficulty quota sampling.
  2. *Round-Robin Question Sets:* Cyclic assignment of Set A, Set B, Set C, Set D.
  3. *Round-Robin Individual Questions:* Cyclic sequence with rotational starting offsets.
  4. *All Questions:* Standard delivery with option shuffling.
- **Exact-Match Multiple-Choice Scoring ($S = C$):**
  Full marks are awarded only when the candidate's selected choice set $S$ exactly equals the correct choice set $C$. Partial or incorrect choices receive configured negative marks or zero. Unanswered questions receive zero.
- **Immediate Answer Autosave:**
  Persists answers to the database immediately upon every selection change, providing *Saving...*, *Saved*, or *Unsaved (offline)* feedback with idempotency protection.
- **Proctoring Security & Watermarking:**
  Enforces mandatory fullscreen, detects window blur and tab switching, prevents PrintScreen/DevTools key shortcuts, applies candidate-specific translucent watermarks (`NAME • SAP • EMAIL • TIME`), and tracks violation strikes.
- **Admin-Controlled Result Release Gate:**
  Scorecards remain strictly hidden from candidates until an Administrator finalizes marks and clicks *Publish Results*.
- **Admin Retake Authorization:**
  Single attempt allowed by default. Administrators can authorize retakes with a mandatory reason, allocating fresh papers while preserving all previous attempt histories and audit logs.
- **Bulk Question Importer:**
  Ingests question banks across 5 formats: Excel (`.xlsx`), CSV (`.csv`), JSON (`.json`), LaTeX (`.tex`), and Word (`.docx`).
- **15 Downloadable Templates:**
  Pre-formatted templates for all 3 distribution modes across all 5 file formats, plus a Student Roster spreadsheet.
- **7-Sheet Consolidated Excel Export:**
  Downloads `MATHQUIZ_<QUIZ_CODE>_RESULTS_<DATE>.xlsx` containing:
  1. *Student Summary:* Candidate grades, percentages, and statuses.
  2. *Question-wise Marks:* Question-by-question scoring.
  3. *Attendance:* Present, absent, in-progress, submitted tracking.
  4. *Question Analysis:* Accuracy percentages and difficulty breakdown.
  5. *Distribution:* Paper set mapping and question sequence snapshot.
  6. *Violations:* Proctoring events and strike timestamps.
  7. *Mark Adjustments:* Audited manual mark corrections with reasons.

---

## 3. Directory Layout

```
F:\MCQS/
├── api/
│   └── index.py                     # Vercel Serverless Function entrypoint
├── app/
│   ├── __init__.py                  # Flask Application Factory
│   ├── config.py                    # Database connection & pooling configuration
│   ├── models/
│   │   ├── __init__.py              # Central SQLAlchemy models registry
│   │   ├── mathquiz.py              # 19 MathQuiz database models (mq_*)
│   │   ├── user.py                  # User authentication and Student models
│   │   └── subject.py               # Subject master model
│   ├── routes/
│   │   ├── auth.py                  # Admin / Faculty authentication
│   │   └── mathquiz.py              # Student portal, Admin console & REST APIs
│   ├── services/
│   │   └── mathquiz_service.py      # Core distribution, autosave & evaluation engine
│   ├── static/
│   │   └── templates/               # 15 Downloadable distribution templates
│   ├── templates/
│   │   ├── base.html                # Master portal layout
│   │   ├── auth/login.html          # Admin / Faculty login view
│   │   └── mathquiz/
│   │       ├── student_login.html   # Student verification portal
│   │       ├── exam.html            # Proctored room: MathJax 3, timer, palette
│   │       ├── result.html          # Candidate scorecard lookup
│   │       └── admin.html           # Admin & Faculty management console
│   └── utils/
│       └── decorators.py            # RBAC decorators (admin_required, faculty_required)
├── docs/
│   └── mathquiz/                    # Milestone 1 Governance & Architecture Package
├── scratch/
│   ├── load_test_500.js             # k6 concurrency test for 500 simultaneous candidates
│   └── test_mathquiz_e2e.py         # 11-stage automated end-to-end integration test
├── requirements.txt                 # Dependencies
├── vercel.json                      # Vercel deployment configuration
└── run.py                           # Local execution entrypoint
```

---

## 4. Local Setup & Execution

### 4.1 Prerequisites
- Python 3.10+
- Pip / Virtual environment

### 4.2 Installation
```bash
git clone https://github.com/vidyasagar24/MCQS.git
cd MCQS
pip install -r requirements.txt
```

### 4.3 Configure Environment
Create a `.env` file in the root directory:
```ini
DATABASE_URL=postgresql+pg8000://postgres.YOUR_PROJECT_REF:YOUR_PASSWORD@aws-1-us-east-2.pooler.supabase.com:5432/postgres?sslmode=require
SECRET_KEY=your-secure-secret-key
FLASK_DEBUG=True
PORT=5000
```

### 4.4 Run Local Server
```bash
python run.py
```
- Student Portal: `http://127.0.0.1:5000/mathquiz/student`
- Admin Console: `http://127.0.0.1:5000/mathquiz/admin` (Default: `admin` / `Admin@123`)

---

## 5. Verification & Testing

### 5.1 End-to-End Integration Suite (11 Stages)
```bash
python scratch/test_mathquiz_e2e.py
```
Validates:
1. Student verification & roster validation
2. Attempt initialization & paper generation
3. Answer key masking (keys never leaked to client)
4. Immediate single & multiple-answer autosave
5. Proctoring violation strike recording
6. Submission & exact-match auto-evaluation
7. Scorecard isolation prior to publication
8. Administrator result publication toggle
9. Official scorecard retrieval
10. 7-sheet consolidated Excel workbook generation
11. Administrator retake authorization and attempt isolation

### 5.2 High-Capacity Load Testing (k6)
Simulate 500 concurrent candidates taking an examination:
```bash
k6 run scratch/load_test_500.js
```
- Targets P95 response time $< 2.5$ seconds
- Error rate $< 2.0\%$ under sustained 500-concurrency peak

---

## 6. Production Deployment (Vercel)

1. Connect the GitHub repository `https://github.com/vidyasagar24/MCQS` in the Vercel dashboard.
2. Set Environment Variables:
   - `DATABASE_URL`: Your Supabase pooler URL
   - `SECRET_KEY`: A strong random string
3. Deploy. Vercel automatically detects `vercel.json` and routes requests to `api/index.py`.
