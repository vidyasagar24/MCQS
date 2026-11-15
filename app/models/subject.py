from datetime import datetime
from app.models import db

class Subject(db.Model):
    __tablename__ = 'subjects'

    id = db.Column(db.Integer, primary_key=True)
    subject_code = db.Column(db.String(30), nullable=False, index=True)
    subject_name = db.Column(db.String(150), nullable=False)
    programme_id = db.Column(db.Integer, nullable=False, default=1)
    semester_id = db.Column(db.Integer, nullable=False, default=1)
    credits = db.Column(db.Integer, nullable=False, default=4)
    ica_max = db.Column(db.Float, nullable=False, default=50.0)
    tee_max = db.Column(db.Float, nullable=False, default=100.0)
    status = db.Column(db.String(20), default='Active', nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    def __repr__(self):
        return f"<Subject {self.subject_code} - {self.subject_name}>"
