from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager

db = SQLAlchemy()
login_manager = LoginManager()
login_manager.login_view = 'auth.login'
login_manager.login_message = 'Please log in to access the examination console.'
login_manager.login_message_category = 'warning'

from app.models.user import User, Student
from app.models.subject import Subject
from app.models.mathquiz import (
    MQQuiz, MQQuizStudent, MQQuestionBank, MQQuestion, MQQuestionOption,
    MQQuestionPool, MQPoolQuestion, MQQuestionSet, MQQuestionSetItem, MQAttempt,
    MQStudentAssignment, MQAnswer, MQViolation, MQQuestionMark, MQResult,
    MQImportJob, MQImportError, MQMarkAdjustment, MQAttendance, MQActivityLog
)

__all__ = [
    'db',
    'login_manager',
    'User',
    'Student',
    'Subject',
    'MQQuiz',
    'MQQuizStudent',
    'MQQuestionBank',
    'MQQuestion',
    'MQQuestionOption',
    'MQQuestionPool',
    'MQPoolQuestion',
    'MQQuestionSet',
    'MQQuestionSetItem',
    'MQAttempt',
    'MQStudentAssignment',
    'MQAnswer',
    'MQViolation',
    'MQQuestionMark',
    'MQResult',
    'MQImportJob',
    'MQImportError',
    'MQMarkAdjustment',
    'MQAttendance',
    'MQActivityLog',
]
