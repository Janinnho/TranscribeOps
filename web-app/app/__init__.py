from flask import Flask
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager
from flask_migrate import Migrate
from flask_wtf.csrf import CSRFProtect
from config import Config

db = SQLAlchemy()
login_manager = LoginManager()
migrate = Migrate()
csrf = CSRFProtect()


def create_app(config_class=Config):
    app = Flask(__name__)
    app.config.from_object(config_class)

    db.init_app(app)
    login_manager.init_app(app)
    migrate.init_app(app, db)
    csrf.init_app(app)

    login_manager.login_view = 'auth.login'
    login_manager.login_message = 'Bitte melden Sie sich an.'
    login_manager.login_message_category = 'info'

    from app.models import User

    @login_manager.user_loader
    def load_user(user_id):
        return db.session.get(User, int(user_id))

    from app.routes.auth import auth_bp
    from app.routes.main import main_bp
    from app.routes.admin import admin_bp
    from app.routes.api import api_bp

    app.register_blueprint(auth_bp)
    app.register_blueprint(main_bp)
    app.register_blueprint(admin_bp, url_prefix='/admin')
    app.register_blueprint(api_bp, url_prefix='/api')

    with app.app_context():
        import os
        os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
        os.makedirs(os.path.dirname(app.config['SQLALCHEMY_DATABASE_URI'].replace('sqlite:///', '')), exist_ok=True)
        db.create_all()
        _seed_defaults(app)

    return app


def _seed_defaults(app):
    from app.models import User, SpeechModel, TextModel
    if not User.query.first():
        admin = User(username='admin', email='admin@transcribeops.local', is_admin=True)
        admin.set_password('admin')
        db.session.add(admin)
        db.session.commit()
    if not SpeechModel.query.first():
        default_speech = SpeechModel(
            name='Local Whisper',
            display_name='Local Whisper',
            provider='whisper_local',
            endpoint_url='http://whisper:8080/v1/audio/transcriptions',
            model_id='whisper-1',
            is_active=True
        )
        db.session.add(default_speech)
        db.session.commit()
    if not TextModel.query.first():
        default_text = TextModel(
            name='Local Ollama',
            display_name='Local Ollama',
            provider='ollama',
            endpoint_url='http://ollama:11434',
            model_id='llama3',
            is_active=True
        )
        db.session.add(default_text)
        db.session.commit()
