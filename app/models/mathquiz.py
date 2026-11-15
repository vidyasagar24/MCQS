import uuid
from datetime import datetime
from sqlalchemy.types import TypeDecorator, CHAR, JSON
from sqlalchemy.dialects.postgresql import UUID as PG_UUID, JSONB as PG_JSONB
from app.models import db

class GUID(TypeDecorator):
    """Platform-independent GUID type: uses native PostgreSQL UUID, else CHAR(36)."""
    impl = CHAR(36)
    cache_ok = True

    def load_dialect_impl(self, dialect):
        if dialect.name == 'postgresql':
            return dialect.type_descriptor(PG_UUID(as_uuid=True))
        return dialect.type_descriptor(CHAR(36))

    def process_bind_param(self, value, dialect):
        if value is None:
            return value
        if dialect.name == 'postgresql':
            return value if isinstance(value, uuid.UUID) else uuid.UUID(str(value))
        return str(value)

    def process_result_value(self, value, dialect):
        if value is None:
            return value
        return value if isinstance(value, uuid.UUID) else uuid.UUID(str(value))


class UniversalJSON(TypeDecorator):
    """Platform-independent JSON: uses PostgreSQL JSONB, else standard JSON."""
    impl = JSON
    cache_ok = True

    def load_dialect_impl(self, dialect):
        if dialect.name == 'postgresql':
            return dialect.type_descriptor(PG_JSONB())
        return dialect.type_descriptor(JSON())


class MQQuiz(db.Model):
    __tablename__ = 'mq_quizzes'

    id = db.Column(GUID(), primary_key=True, default=uuid.uuid4)
    title = db.Column(db.Text, nullable=False)
    quiz_code = db.Column(db.String(30), unique=True, nullable=False, index=True)
    subject_id = db.Column(db.Integer, db.ForeignKey('subjects.id', ondelete='SET NULL'), nullable=True)
    mapping_id = db.Column(db.Integer, nullable=True)
    duration_minutes = db.Column(db.Integer, nullable=False, default=60)
    total_questions = db.Column(db.Integer, nullable=False, default=10)
    total_marks = db.Column(db.Numeric(10, 2), nullable=False, default=10.0)
    passing_marks = db.Column(db.Numeric(10, 2), default=4.0)
    distribution_type = db.Column(db.String(30), nullable=False, default='random_pool')  # 'random_pool', 'round_robin', 'all_questions'
    round_robin_mode = db.Column(db.String(30), nullable=True)  # 'question_sets', 'individual_questions'
    negative_marking_enabled = db.Column(db.Boolean, default=False)
    negative_marks = db.Column(db.Numeric(10, 2), default=0.0)
    shuffle_questions = db.Column(db.Boolean, default=True)
    shuffle_options = db.Column(db.Boolean, default=True)
    max_violations_allowed = db.Column(db.Integer, default=3)
    result_release_status = db.Column(db.String(20), nullable=False, default='hidden')  # 'hidden', 'published'
    status = db.Column(db.String(20), nullable=False, default='draft')  # 'draft', 'scheduled', 'active', 'completed', 'archived'
    created_by = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    starts_at = db.Column(db.DateTime(timezone=True), nullable=True)
    ends_at = db.Column(db.DateTime(timezone=True), nullable=True)
    created_at = db.Column(db.DateTime(timezone=True), default=datetime.utcnow)
    updated_at = db.Column(db.DateTime(timezone=True), default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationships
    subject = db.relationship('Subject', backref='quizzes', lazy='joined')
    creator = db.relationship('User', backref='created_quizzes')
    questions = db.relationship('MQQuestion', back_populates='quiz', cascade='all, delete-orphan')
    students = db.relationship('MQQuizStudent', back_populates='quiz', cascade='all, delete-orphan')
    pools = db.relationship('MQQuestionPool', back_populates='quiz', cascade='all, delete-orphan')
    sets = db.relationship('MQQuestionSet', back_populates='quiz', cascade='all, delete-orphan')
    attempts = db.relationship('MQAttempt', back_populates='quiz')
    results = db.relationship('MQResult', back_populates='quiz')


class MQQuizStudent(db.Model):
    __tablename__ = 'mq_quiz_students'

    id = db.Column(GUID(), primary_key=True, default=uuid.uuid4)
    quiz_id = db.Column(GUID(), db.ForeignKey('mq_quizzes.id', ondelete='CASCADE'), nullable=False)
    student_id = db.Column(db.Integer, db.ForeignKey('students.id', ondelete='RESTRICT'), nullable=False)
    sap_id = db.Column(db.String(50), nullable=False, index=True)
    registered_at = db.Column(db.DateTime(timezone=True), default=datetime.utcnow)
    is_eligible = db.Column(db.Boolean, default=True)

    __table_args__ = (
        db.UniqueConstraint('quiz_id', 'student_id', name='uq_mq_quiz_student_id'),
        db.UniqueConstraint('quiz_id', 'sap_id', name='uq_mq_quiz_sap_id'),
    )

    quiz = db.relationship('MQQuiz', back_populates='students')
    student = db.relationship('Student', backref='quiz_registrations')


class MQQuestionBank(db.Model):
    __tablename__ = 'mq_question_banks'

    id = db.Column(GUID(), primary_key=True, default=uuid.uuid4)
    name = db.Column(db.String(150), nullable=False)
    subject_id = db.Column(db.Integer, db.ForeignKey('subjects.id', ondelete='SET NULL'), nullable=True)
    description = db.Column(db.Text, nullable=True)
    created_by = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    created_at = db.Column(db.DateTime(timezone=True), default=datetime.utcnow)


class MQQuestion(db.Model):
    __tablename__ = 'mq_questions'

    id = db.Column(GUID(), primary_key=True, default=uuid.uuid4)
    quiz_id = db.Column(GUID(), db.ForeignKey('mq_quizzes.id', ondelete='CASCADE'), nullable=True)
    question_bank_id = db.Column(GUID(), db.ForeignKey('mq_question_banks.id', ondelete='SET NULL'), nullable=True)
    subject_id = db.Column(db.Integer, db.ForeignKey('subjects.id', ondelete='SET NULL'), nullable=True)
    batch_name = db.Column(db.String(100), default='Batch 1')
    topic = db.Column(db.String(150), nullable=True)
    subtopic = db.Column(db.String(150), nullable=True)
    question_type = db.Column(db.String(20), default='single')  # 'single', 'multiple'
    difficulty = db.Column(db.String(20), default='Medium')  # 'Easy', 'Medium', 'Hard'
    latex_source = db.Column(db.Text, nullable=False)
    marks = db.Column(db.Numeric(10, 2), nullable=False, default=1.0)
    negative_marks = db.Column(db.Numeric(10, 2), default=0.0)
    explanation = db.Column(db.Text, nullable=True)
    image_path = db.Column(db.Text, nullable=True)
    is_active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime(timezone=True), default=datetime.utcnow)

    quiz = db.relationship('MQQuiz', back_populates='questions')
    subject = db.relationship('Subject', backref='questions', lazy='joined')
    options = db.relationship('MQQuestionOption', back_populates='question', cascade='all, delete-orphan', order_by='MQQuestionOption.display_order', lazy='selectin')


class MQQuestionOption(db.Model):
    __tablename__ = 'mq_question_options'

    id = db.Column(GUID(), primary_key=True, default=uuid.uuid4)
    question_id = db.Column(GUID(), db.ForeignKey('mq_questions.id', ondelete='CASCADE'), nullable=False)
    option_key = db.Column(db.CHAR(1), nullable=False)  # 'A', 'B', 'C', 'D', 'E'
    latex_source = db.Column(db.Text, nullable=False)
    is_correct = db.Column(db.Boolean, nullable=False, default=False)
    display_order = db.Column(db.Integer, nullable=False, default=1)

    __table_args__ = (
        db.UniqueConstraint('question_id', 'option_key', name='uq_mq_question_option_key'),
    )

    question = db.relationship('MQQuestion', back_populates='options')


class MQQuestionPool(db.Model):
    __tablename__ = 'mq_question_pools'

    id = db.Column(GUID(), primary_key=True, default=uuid.uuid4)
    quiz_id = db.Column(GUID(), db.ForeignKey('mq_quizzes.id', ondelete='CASCADE'), nullable=False)
    pool_name = db.Column(db.String(100), nullable=False)
    required_count = db.Column(db.Integer, nullable=False)
    marks_per_question = db.Column(db.Numeric(10, 2), nullable=False, default=1.0)

    quiz = db.relationship('MQQuiz', back_populates='pools')


class MQPoolQuestion(db.Model):
    __tablename__ = 'mq_pool_questions'

    id = db.Column(GUID(), primary_key=True, default=uuid.uuid4)
    pool_id = db.Column(GUID(), db.ForeignKey('mq_question_pools.id', ondelete='CASCADE'), nullable=False)
    question_id = db.Column(GUID(), db.ForeignKey('mq_questions.id', ondelete='CASCADE'), nullable=False)

    __table_args__ = (
        db.UniqueConstraint('pool_id', 'question_id', name='uq_mq_pool_question'),
    )


class MQQuestionSet(db.Model):
    __tablename__ = 'mq_question_sets'

    id = db.Column(GUID(), primary_key=True, default=uuid.uuid4)
    quiz_id = db.Column(GUID(), db.ForeignKey('mq_quizzes.id', ondelete='CASCADE'), nullable=False)
    set_name = db.Column(db.String(20), nullable=False)  # 'Set A', 'Set B'
    sequence = db.Column(db.Integer, nullable=False)
    created_at = db.Column(db.DateTime(timezone=True), default=datetime.utcnow)

    quiz = db.relationship('MQQuiz', back_populates='sets')
    items = db.relationship('MQQuestionSetItem', backref='question_set', cascade='all, delete-orphan')


class MQQuestionSetItem(db.Model):
    __tablename__ = 'mq_question_set_items'

    id = db.Column(GUID(), primary_key=True, default=uuid.uuid4)
    set_id = db.Column(GUID(), db.ForeignKey('mq_question_sets.id', ondelete='CASCADE'), nullable=False)
    question_id = db.Column(GUID(), db.ForeignKey('mq_questions.id', ondelete='CASCADE'), nullable=False)
    position = db.Column(db.Integer, nullable=False)

    question = db.relationship('MQQuestion')


class MQAttempt(db.Model):
    __tablename__ = 'mq_attempts'

    id = db.Column(GUID(), primary_key=True, default=uuid.uuid4)
    quiz_id = db.Column(GUID(), db.ForeignKey('mq_quizzes.id', ondelete='RESTRICT'), nullable=False)
    student_id = db.Column(db.Integer, db.ForeignKey('students.id', ondelete='RESTRICT'), nullable=False)
    sap_id = db.Column(db.String(50), nullable=False, index=True)
    session_token_hash = db.Column(db.String(64), nullable=False, index=True)
    assigned_set_id = db.Column(GUID(), db.ForeignKey('mq_question_sets.id'), nullable=True)
    attempt_number = db.Column(db.Integer, default=1, nullable=False)
    started_at = db.Column(db.DateTime(timezone=True), default=datetime.utcnow, nullable=False)
    expires_at = db.Column(db.DateTime(timezone=True), nullable=False)
    submitted_at = db.Column(db.DateTime(timezone=True), nullable=True)
    status = db.Column(db.String(30), nullable=False, default='in_progress')  # 'in_progress', 'submitted', 'auto_submitted', 'disqualified'
    total_marks = db.Column(db.Numeric(10, 2), nullable=True)
    submission_reason = db.Column(db.Text, nullable=True)
    client_ip = db.Column(db.String(50), nullable=True)
    system_fingerprint = db.Column(db.String(100), nullable=True)
    created_at = db.Column(db.DateTime(timezone=True), default=datetime.utcnow)

    __table_args__ = (
        db.UniqueConstraint('quiz_id', 'student_id', 'attempt_number', name='uq_mq_attempt_quiz_student_attempt_number'),
    )

    quiz = db.relationship('MQQuiz', back_populates='attempts')
    student = db.relationship('Student', backref='exam_attempts')
    assignments = db.relationship('MQStudentAssignment', backref='attempt', cascade='all, delete-orphan', order_by='MQStudentAssignment.position')
    answers = db.relationship('MQAnswer', backref='attempt', cascade='all, delete-orphan')
    violations = db.relationship('MQViolation', backref='attempt', cascade='all, delete-orphan')
    result = db.relationship('MQResult', back_populates='attempt', uselist=False, cascade='all, delete-orphan')


class MQStudentAssignment(db.Model):
    __tablename__ = 'mq_student_assignments'

    id = db.Column(GUID(), primary_key=True, default=uuid.uuid4)
    attempt_id = db.Column(GUID(), db.ForeignKey('mq_attempts.id', ondelete='CASCADE'), nullable=False)
    question_id = db.Column(GUID(), db.ForeignKey('mq_questions.id', ondelete='RESTRICT'), nullable=False)
    position = db.Column(db.Integer, nullable=False)
    options_permutation = db.Column(UniversalJSON(), nullable=True)
    assigned_at = db.Column(db.DateTime(timezone=True), default=datetime.utcnow)

    __table_args__ = (
        db.UniqueConstraint('attempt_id', 'question_id', name='uq_mq_assignment_attempt_question'),
        db.UniqueConstraint('attempt_id', 'position', name='uq_mq_assignment_attempt_position'),
    )

    question = db.relationship('MQQuestion')


class MQAnswer(db.Model):
    __tablename__ = 'mq_answers'

    id = db.Column(GUID(), primary_key=True, default=uuid.uuid4)
    attempt_id = db.Column(GUID(), db.ForeignKey('mq_attempts.id', ondelete='CASCADE'), nullable=False)
    question_id = db.Column(GUID(), db.ForeignKey('mq_questions.id', ondelete='RESTRICT'), nullable=False)
    selected_option = db.Column(db.CHAR(1), nullable=True)
    selected_options = db.Column(UniversalJSON(), default=list)
    answered_at = db.Column(db.DateTime(timezone=True), default=datetime.utcnow)
    idempotency_key = db.Column(db.String(64), nullable=True)
    revision_number = db.Column(db.Integer, default=1)

    __table_args__ = (
        db.UniqueConstraint('attempt_id', 'question_id', name='uq_mq_answer_attempt_question'),
    )

    question = db.relationship('MQQuestion')


class MQViolation(db.Model):
    __tablename__ = 'mq_violations'

    id = db.Column(GUID(), primary_key=True, default=uuid.uuid4)
    attempt_id = db.Column(GUID(), db.ForeignKey('mq_attempts.id', ondelete='CASCADE'), nullable=False)
    violation_type = db.Column(db.String(100), nullable=False)
    event_time = db.Column(db.DateTime(timezone=True), default=datetime.utcnow)
    strike_number = db.Column(db.Integer, nullable=False, default=1)
    event_metadata = db.Column('metadata', UniversalJSON(), default=dict)


class MQQuestionMark(db.Model):
    __tablename__ = 'mq_question_marks'

    id = db.Column(GUID(), primary_key=True, default=uuid.uuid4)
    attempt_id = db.Column(GUID(), db.ForeignKey('mq_attempts.id', ondelete='CASCADE'), nullable=False)
    question_id = db.Column(GUID(), db.ForeignKey('mq_questions.id', ondelete='RESTRICT'), nullable=False)
    maximum_marks = db.Column(db.Numeric(10, 2), nullable=False, default=1.0)
    awarded_marks = db.Column(db.Numeric(10, 2), nullable=False, default=0.0)
    is_correct = db.Column(db.Boolean, nullable=False, default=False)
    evaluated_at = db.Column(db.DateTime(timezone=True), default=datetime.utcnow)

    __table_args__ = (
        db.UniqueConstraint('attempt_id', 'question_id', name='uq_mq_question_mark_attempt_question'),
    )


class MQResult(db.Model):
    __tablename__ = 'mq_results'

    id = db.Column(GUID(), primary_key=True, default=uuid.uuid4)
    attempt_id = db.Column(GUID(), db.ForeignKey('mq_attempts.id', ondelete='CASCADE'), nullable=False)
    quiz_id = db.Column(GUID(), db.ForeignKey('mq_quizzes.id', ondelete='CASCADE'), nullable=False)
    student_id = db.Column(db.Integer, db.ForeignKey('students.id', ondelete='RESTRICT'), nullable=False)
    sap_id = db.Column(db.String(50), nullable=False, index=True)
    attendance_status = db.Column(db.String(20), nullable=False, default='Present')
    raw_score = db.Column(db.Numeric(10, 2), nullable=False, default=0.0)
    grace_marks = db.Column(db.Numeric(10, 2), default=0.0)
    adjustment_marks = db.Column(db.Numeric(10, 2), default=0.0)
    final_score = db.Column(db.Numeric(10, 2), nullable=False, default=0.0)
    maximum_marks = db.Column(db.Numeric(10, 2), nullable=False, default=0.0)
    percentage = db.Column(db.Numeric(7, 2), nullable=False, default=0.0)
    result_status = db.Column(db.String(30), nullable=False, default='EVALUATED')  # 'EVALUATED', 'UNDER_REVIEW', 'FINALIZED', 'PUBLISHED'
    evaluated_at = db.Column(db.DateTime(timezone=True), default=datetime.utcnow)
    is_published = db.Column(db.Boolean, default=False)
    published_at = db.Column(db.DateTime(timezone=True), nullable=True)
    published_by = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)

    __table_args__ = (
        db.UniqueConstraint('attempt_id', name='uq_mq_result_attempt'),
        db.UniqueConstraint('quiz_id', 'student_id', name='uq_mq_result_quiz_student'),
    )

    attempt = db.relationship('MQAttempt', back_populates='result')
    quiz = db.relationship('MQQuiz', back_populates='results')
    student = db.relationship('Student', backref='quiz_results')


class MQImportJob(db.Model):
    __tablename__ = 'mq_import_jobs'

    id = db.Column(GUID(), primary_key=True, default=uuid.uuid4)
    file_name = db.Column(db.Text, nullable=False)
    format = db.Column(db.String(20), nullable=False)
    total_records = db.Column(db.Integer, default=0)
    successful_records = db.Column(db.Integer, default=0)
    failed_records = db.Column(db.Integer, default=0)
    status = db.Column(db.String(30), default='completed')
    created_by = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)
    created_at = db.Column(db.DateTime(timezone=True), default=datetime.utcnow)


class MQImportError(db.Model):
    __tablename__ = 'mq_import_errors'

    id = db.Column(GUID(), primary_key=True, default=uuid.uuid4)
    job_id = db.Column(GUID(), db.ForeignKey('mq_import_jobs.id', ondelete='CASCADE'), nullable=False)
    row_number = db.Column(db.Integer, nullable=False)
    error_message = db.Column(db.Text, nullable=False)
    raw_data = db.Column(UniversalJSON(), nullable=True)


class MQMarkAdjustment(db.Model):
    __tablename__ = 'mq_mark_adjustments'

    id = db.Column(GUID(), primary_key=True, default=uuid.uuid4)
    result_id = db.Column(GUID(), db.ForeignKey('mq_results.id', ondelete='CASCADE'), nullable=False)
    student_id = db.Column(db.Integer, db.ForeignKey('students.id'), nullable=True)
    original_marks = db.Column(db.Numeric(10, 2), nullable=False)
    revised_marks = db.Column(db.Numeric(10, 2), nullable=False)
    reason = db.Column(db.Text, nullable=False)
    adjusted_by = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    adjusted_at = db.Column(db.DateTime(timezone=True), default=datetime.utcnow)


class MQAttendance(db.Model):
    __tablename__ = 'mq_attendance'

    id = db.Column(GUID(), primary_key=True, default=uuid.uuid4)
    quiz_id = db.Column(GUID(), db.ForeignKey('mq_quizzes.id', ondelete='CASCADE'), nullable=False)
    student_id = db.Column(db.Integer, db.ForeignKey('students.id', ondelete='RESTRICT'), nullable=False)
    sap_id = db.Column(db.String(50), nullable=False)
    attendance_status = db.Column(db.String(20), nullable=False, default='Absent')  # 'Present', 'Absent', 'In-Progress', 'Submitted', 'Disqualified', 'Excused'
    marked_by = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)
    marked_at = db.Column(db.DateTime(timezone=True), default=datetime.utcnow)
    reason = db.Column(db.Text, nullable=True)

    __table_args__ = (
        db.UniqueConstraint('quiz_id', 'student_id', name='uq_mq_attendance_quiz_student'),
    )

    quiz = db.relationship('MQQuiz')
    student = db.relationship('Student')


class MQActivityLog(db.Model):
    __tablename__ = 'mq_activity_logs'

    id = db.Column(GUID(), primary_key=True, default=uuid.uuid4)
    actor_user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)
    actor_role = db.Column(db.String(30), nullable=True)
    action = db.Column(db.String(100), nullable=False)
    entity_type = db.Column(db.String(50), nullable=False)
    entity_id = db.Column(db.String(100), nullable=True)
    details = db.Column(UniversalJSON(), default=dict)
    ip_address = db.Column(db.String(50), nullable=True)
    created_at = db.Column(db.DateTime(timezone=True), default=datetime.utcnow)
