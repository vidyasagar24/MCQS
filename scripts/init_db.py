"""
Standalone Database Initialization & Seeding Script for MCQS
Usage:
    python scripts/init_db.py [--url DATABASE_URL]
"""

import os
import sys
import argparse

# Parse argument before importing app so environment variable is set
parser = argparse.ArgumentParser(description="Initialize and seed MCQS database.")
parser.add_argument('--url', help="Target database connection URL", default=None)
args = parser.parse_args()

if args.url:
    os.environ['DATABASE_URL'] = args.url

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE_DIR)

from app import create_app
from app.models import (
    db, User, Student, Subject,
    MQQuiz, MQQuizStudent, MQQuestion, MQQuestionOption
)

def init_database(custom_db_url=None):
    app = create_app()

    with app.app_context():
        print(f"[*] Target Database URI: {app.config['SQLALCHEMY_DATABASE_URI']}")
        print("[*] Creating all database tables...")
        db.create_all()
        print("[+] All tables created successfully!")

        # 1. Seed Administrator & Faculty Users
        admin_user = User.query.filter_by(username='admin').first()
        if not admin_user:
            admin_user = User(username='admin', role='admin', is_active=True)
            admin_user.set_password('Admin@123')
            db.session.add(admin_user)
            print("[+] Created Administrator user: admin / Admin@123")
        else:
            print("[*] Administrator user already exists.")

        vvs_user = User.query.filter_by(username='vvs').first()
        if not vvs_user:
            vvs_user = User(username='vvs', role='faculty', is_active=True)
            vvs_user.set_password('Faculty@123')
            db.session.add(vvs_user)
            print("[+] Created Faculty user: vvs / Faculty@123")

        db.session.commit()

        # 2. Seed Subjects
        subj_math = Subject.query.filter_by(subject_code='MATH101').first()
        if not subj_math:
            subj_math = Subject(
                subject_code='MATH101',
                subject_name='Applied Mathematics II',
                programme_id=1,
                semester_id=2,
                credits=4,
                ica_max=50.0,
                tee_max=100.0,
                status='Active'
            )
            db.session.add(subj_math)

        subj_py = Subject.query.filter_by(subject_code='CS101').first()
        if not subj_py:
            subj_py = Subject(
                subject_code='CS101',
                subject_name='Python Programming & Algorithms',
                programme_id=1,
                semester_id=2,
                credits=4,
                ica_max=50.0,
                tee_max=100.0,
                status='Active'
            )
            db.session.add(subj_py)

        db.session.commit()

        # 3. Seed Students
        students_data = [
            ("2026CE001", "Meera Nair", "meera.nair@univ.edu"),
            ("2026CE002", "Arjun Rao", "arjun.rao@univ.edu"),
            ("2026CE003", "Rohan Sharma", "rohan.sharma@univ.edu"),
            ("2026CE004", "Priya Patel", "priya.patel@univ.edu"),
            ("2026CE005", "Siddharth Verma", "siddharth.verma@univ.edu"),
            ("2026CE006", "Ananya Gupta", "ananya.gupta@univ.edu"),
            ("2026CE007", "Kavya Iyer", "kavya.iyer@univ.edu"),
            ("2026CE008", "Vikram Singh", "vikram.singh@univ.edu"),
            ("2026CE009", "Aditya Kumar", "aditya.kumar@univ.edu"),
            ("2026CE010", "Sneha Reddy", "sneha.reddy@univ.edu"),
        ]

        for sap, name, email in students_data:
            st = Student.query.filter_by(register_number=sap).first()
            if not st:
                st = Student(
                    register_number=sap,
                    student_name=name,
                    email=email,
                    programme_id=1,
                    academic_year_id=3,
                    current_semester_id=2,
                    section_id=1,
                    status='Active'
                )
                db.session.add(st)

        db.session.commit()
        print(f"[+] Verified {len(students_data)} student records in roster.")

        # 4. Seed Active Quizzes
        def create_or_get_quiz(code, title, subject_id, duration=15, marks=10.0):
            q = MQQuiz.query.filter_by(quiz_code=code).first()
            if not q:
                q = MQQuiz(
                    title=title,
                    quiz_code=code,
                    subject_id=subject_id,
                    duration_minutes=duration,
                    total_questions=10,
                    total_marks=marks,
                    passing_marks=4.0,
                    distribution_type='all_questions',
                    negative_marking_enabled=False,
                    negative_marks=0.0,
                    shuffle_questions=True,
                    shuffle_options=True,
                    max_violations_allowed=3,
                    result_release_status='published',
                    status='active',
                    created_by=admin_user.id
                )
                db.session.add(q)
                db.session.commit()
                print(f"[+] Created active quiz: {code} - {title}")
            return q

        quiz_py = create_or_get_quiz('PYTHON26', 'Python Programming Examination', subj_py.id)
        quiz_math = create_or_get_quiz('MATH2026', 'Mid-Semester Examination: Applied Mathematics II', subj_math.id)
        quiz_py27 = create_or_get_quiz('PYTHON2627', 'python_test', subj_py.id)

        # 5. Enroll Students into Quizzes
        all_quizzes = [quiz_py, quiz_math, quiz_py27]
        all_students = Student.query.all()
        for q in all_quizzes:
            for s in all_students:
                qs = MQQuizStudent.query.filter_by(quiz_id=q.id, student_id=s.id).first()
                if not qs:
                    qs = MQQuizStudent(
                        quiz_id=q.id,
                        student_id=s.id,
                        sap_id=s.register_number,
                        is_eligible=True
                    )
                    db.session.add(qs)
        db.session.commit()
        print("[+] Enrolled students in active quizzes.")

        # 6. Seed 10 Questions
        def seed_questions(quiz, questions_spec):
            existing_count = MQQuestion.query.filter_by(quiz_id=quiz.id).count()
            if existing_count >= len(questions_spec):
                return
            for idx, spec in enumerate(questions_spec, start=1):
                quest = MQQuestion(
                    quiz_id=quiz.id,
                    subject_id=quiz.subject_id,
                    topic=spec.get('topic', 'General'),
                    latex_source=spec['latex'],
                    marks=1.0,
                    negative_marks=0.0,
                    question_type='single',
                    difficulty='Medium',
                    is_active=True
                )
                db.session.add(quest)
                db.session.flush()

                for opt_key, opt_text, is_corr in spec['options']:
                    opt = MQQuestionOption(
                        question_id=quest.id,
                        option_key=opt_key,
                        latex_source=opt_text,
                        is_correct=is_corr,
                        display_order=ord(opt_key) - ord('A') + 1
                    )
                    db.session.add(opt)
            db.session.commit()
            print(f"[+] Seeded {len(questions_spec)} questions for quiz: {quiz.quiz_code}")

        py_questions = [
            {"latex": r"Which of the following functions outputs text directly to the console in Python 3?", "options": [("A", r"\texttt{print()}", True), ("B", r"\texttt{echo()}", False), ("C", r"\texttt{console.log()}", False), ("D", r"\texttt{printf()}", False)]},
            {"latex": r"What is the output of the expression $2^{3} + 4 \times 2$ in standard Python syntax \texttt{2**3 + 4*2}?", "options": [("A", r"$16$", True), ("B", r"$24$", False), ("C", r"$12$", False), ("D", r"$14$", False)]},
            {"latex": r"Which built-in Python data type represents an ordered, immutable sequence of elements?", "options": [("A", r"\texttt{tuple}", True), ("B", r"\texttt{list}", False), ("C", r"\texttt{set}", False), ("D", r"\texttt{dict}", False)]},
            {"latex": r"Given a list \texttt{L = [10, 20, 30, 40, 50]}, what does the slicing expression \texttt{L[1:4]} return?", "options": [("A", r"\texttt{[20, 30, 40]}", True), ("B", r"\texttt{[10, 20, 30]}", False), ("C", r"\texttt{[20, 30]}", False), ("D", r"\texttt{[20, 30, 40, 50]}", False)]},
            {"latex": r"Which keyword is used to define an anonymous inline function in Python?", "options": [("A", r"\texttt{lambda}", True), ("B", r"\texttt{def}", False), ("C", r"\texttt{func}", False), ("D", r"\texttt{anon}", False)]},
            {"latex": r"What will be the boolean result of \texttt{bool([])} in Python?", "options": [("A", r"\texttt{False}", True), ("B", r"\texttt{True}", False), ("C", r"\texttt{None}", False), ("D", r"\texttt{TypeError}", False)]},
            {"latex": r"In Python object-oriented programming, what is the standard first parameter of an instance method?", "options": [("A", r"\texttt{self}", True), ("B", r"\texttt{this}", False), ("C", r"\texttt{cls}", False), ("D", r"\texttt{me}", False)]},
            {"latex": r"Which block is guaranteed to execute whether an exception was raised or not in a \texttt{try-except} construct?", "options": [("A", r"\texttt{finally}", True), ("B", r"\texttt{else}", False), ("C", r"\texttt{catch}", False), ("D", r"\texttt{always}", False)]},
            {"latex": r"What is the time complexity of looking up a unique key in a standard Python \texttt{dict} on average?", "options": [("A", r"$\mathcal{O}(1)$", True), ("B", r"$\mathcal{O}(n)$", False), ("C", r"$\mathcal{O}(\log n)$", False), ("D", r"$\mathcal{O}(n^2)$", False)]},
            {"latex": r"Question 10: Which comprehension syntax creates a set containing the squares of numbers from 0 to 4?", "options": [("A", r"\texttt{\{x**2 for x in range(5)\}}", True), ("B", r"\texttt{[x**2 for x in range(5)]}", False), ("C", r"\texttt{(x**2 for x in range(5))}", False), ("D", r"\texttt{set(x*2 for x in 5)}", False)]}
        ]
        seed_questions(quiz_py, py_questions)
        seed_questions(quiz_py27, py_questions)

        math_questions = [
            {"latex": r"Find the definite integral: $\int_{0}^{1} (3x^2 + 2x + 1) \, dx$.", "options": [("A", r"$3$", True), ("B", r"$2$", False), ("C", r"$4$", False), ("D", r"$1$", False)]},
            {"latex": r"What is the rank of the identity matrix $I_3 = \begin{pmatrix} 1 & 0 & 0 \\ 0 & 1 & 0 \\ 0 & 0 & 1 \end{pmatrix}$?", "options": [("A", r"$3$", True), ("B", r"$1$", False), ("C", r"$0$", False), ("D", r"$2$", False)]},
            {"latex": r"The solution to the first-order differential equation $\frac{dy}{dx} = 2y$ with $y(0) = 3$ is:", "options": [("A", r"$y = 3e^{2x}$", True), ("B", r"$y = 2e^{3x}$", False), ("C", r"$y = 3e^{-2x}$", False), ("D", r"$y = e^{6x}$", False)]},
            {"latex": r"Calculate the determinant: $\begin{vmatrix} 4 & 2 \\ 3 & 5 \end{vmatrix}$.", "options": [("A", r"$14$", True), ("B", r"$26$", False), ("C", r"$11$", False), ("D", r"$-14$", False)]},
            {"latex": r"If $f(x, y) = x^3 y^2$, compute the partial derivative $\frac{\partial^2 f}{\partial x \partial y}$:", "options": [("A", r"$6x^2 y$", True), ("B", r"$3x^2 y$", False), ("C", r"$6xy^2$", False), ("D", r"$x^3 + y^2$", False)]},
            {"latex": r"The eigenvalues of a diagonal matrix $D = \text{diag}(\lambda_1, \lambda_2, \lambda_3)$ are:", "options": [("A", r"$\lambda_1, \lambda_2, \lambda_3$", True), ("B", r"$\lambda_1 + \lambda_2 + \lambda_3$", False), ("C", r"$\det(D)$", False), ("D", r"$1, 1, 1$", False)]},
            {"latex": r"Evaluate the limit: $\lim_{x \to 0} \frac{\sin(5x)}{x}$.", "options": [("A", r"$5$", True), ("B", r"$1$", False), ("C", r"$0$", False), ("D", r"$\infty$", False)]},
            {"latex": r"The gradient of scalar field $\phi(x, y, z) = x^2 + y^2 + z^2$ at point $(1, 1, 1)$ is:", "options": [("A", r"$(2, 2, 2)$", True), ("B", r"$(1, 1, 1)$", False), ("C", r"$(3, 3, 3)$", False), ("D", r"$6$", False)]},
            {"latex": r"Which of the following series is convergent according to the $p$-series test?", "options": [("A", r"$\sum_{n=1}^\infty \frac{1}{n^2}$", True), ("B", r"$\sum_{n=1}^\infty \frac{1}{n}$", False), ("C", r"$\sum_{n=1}^\infty \frac{1}{\sqrt{n}}$", False), ("D", r"$\sum_{n=1}^\infty n$", False)]},
            {"latex": r"The Laplace transform $\mathcal{L}\{e^{at}\}$ for $s > a$ is equal to:", "options": [("A", r"$\frac{1}{s - a}$", True), ("B", r"$\frac{1}{s + a}$", False), ("C", r"$\frac{s}{s^2 + a^2}$", False), ("D", r"$\frac{a}{s^2 - a^2}$", False)]}
        ]
        seed_questions(quiz_math, math_questions)

        print("\n" + "=" * 60)
        print("[+] Standalone MCQS database initialized and verified!")
        print(f"    - Quizzes available: {MQQuiz.query.count()}")
        print(f"    - Questions in bank: {MQQuestion.query.count()}")
        print(f"    - Registered Students: {Student.query.count()}")
        print("=" * 60 + "\n")

if __name__ == '__main__':
    init_database(args.url)
