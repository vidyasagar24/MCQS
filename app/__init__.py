from flask import Flask, redirect, url_for
from app.config import Config
from app.models import db, login_manager, User

def create_app(config_class=Config):
    app = Flask(__name__)
    app.config.from_object(config_class)

    # Initialize extensions
    db.init_app(app)
    login_manager.init_app(app)

    @login_manager.user_loader
    def load_user(user_id):
        try:
            return User.query.get(int(user_id))
        except Exception:
            db.session.rollback()
            return None

    # Register Blueprints
    from app.routes.auth import auth_bp
    from app.routes.mathquiz import mathquiz_bp

    app.register_blueprint(auth_bp)
    app.register_blueprint(mathquiz_bp)

    # Context processors
    @app.context_processor
    def inject_global_vars():
        return {
            'app_title': 'MathQuiz – Online Mathematics Examination Portal',
            'app_version': '1.0'
        }

    # Root route redirects to student examination login
    @app.route('/')
    @app.route('/api/index')
    @app.route('/api/index.py')
    @app.route('/api')
    def root_index():
        return redirect(url_for('mathquiz.student_portal'))

    return app
