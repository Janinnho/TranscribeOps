import uuid
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

    from app.sso import init_oidc
    init_oidc(app)

    # Read version from VERSION file
    import os
    version_file = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'VERSION')
    try:
        with open(version_file) as f:
            app.config['APP_VERSION'] = f.read().strip()
    except FileNotFoundError:
        app.config['APP_VERSION'] = ''

    @app.context_processor
    def inject_version():
        return {'app_version': app.config.get('APP_VERSION', '')}

    with app.app_context():
        import os
        os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
        os.makedirs(app.config['AUDIO_STORAGE_PATH'], exist_ok=True)
        os.makedirs(os.path.dirname(app.config['SQLALCHEMY_DATABASE_URI'].replace('sqlite:///', '')), exist_ok=True)
        try:
            db.create_all()
        except Exception:
            pass  # Table may already exist (race condition with multiple workers)
        _apply_migrations()
        _seed_defaults(app)

    return app


def _apply_migrations():
    """Add missing columns to existing tables (lightweight auto-migration)."""
    from sqlalchemy import text, inspect
    inspector = inspect(db.engine)

    def _has_column(table, column):
        cols = [c['name'] for c in inspector.get_columns(table)]
        return column in cols

    def _has_table(table):
        return table in inspector.get_table_names()

    def _safe_execute(conn, sql):
        """Execute ALTER TABLE safely, ignoring duplicate column errors."""
        try:
            conn.execute(text(sql))
            conn.commit()
        except Exception:
            conn.rollback()

    with db.engine.connect() as conn:
        # Speech models
        if _has_table('speech_models') and not _has_column('speech_models', 'speaker_mode'):
            _safe_execute(conn, "ALTER TABLE speech_models ADD COLUMN speaker_mode VARCHAR(10) DEFAULT 'single'")

        # Jobs
        if _has_table('jobs'):
            if not _has_column('jobs', 'diarized_segments'):
                _safe_execute(conn, "ALTER TABLE jobs ADD COLUMN diarized_segments TEXT")
            if not _has_column('jobs', 'summary_status'):
                _safe_execute(conn, "ALTER TABLE jobs ADD COLUMN summary_status VARCHAR(20)")
            if not _has_column('jobs', 'public_id'):
                _safe_execute(conn, "ALTER TABLE jobs ADD COLUMN public_id VARCHAR(32)")
                # Backfill existing jobs with random public_ids
                try:
                    from app.models import Job
                    for job in Job.query.filter(Job.public_id.is_(None)).all():
                        job.public_id = uuid.uuid4().hex
                    db.session.commit()
                except Exception:
                    db.session.rollback()

        # Groups
        if _has_table('groups') and not _has_column('groups', 'is_default'):
            _safe_execute(conn, "ALTER TABLE groups ADD COLUMN is_default BOOLEAN DEFAULT 0")

        # Users: rename username -> display_name
        if _has_table('users') and _has_column('users', 'username') and not _has_column('users', 'display_name'):
            _safe_execute(conn, "ALTER TABLE users RENAME COLUMN username TO display_name")

        # Groups: dictionary_enabled
        if _has_table('groups') and not _has_column('groups', 'dictionary_enabled'):
            _safe_execute(conn, "ALTER TABLE groups ADD COLUMN dictionary_enabled BOOLEAN DEFAULT 1")

        # Groups: feature toggles
        if _has_table('groups'):
            if not _has_column('groups', 'transcription_enabled'):
                _safe_execute(conn, "ALTER TABLE groups ADD COLUMN transcription_enabled BOOLEAN DEFAULT 1")
            if not _has_column('groups', 'meeting_enabled'):
                _safe_execute(conn, "ALTER TABLE groups ADD COLUMN meeting_enabled BOOLEAN DEFAULT 1")
            if not _has_column('groups', 'dictation_enabled'):
                _safe_execute(conn, "ALTER TABLE groups ADD COLUMN dictation_enabled BOOLEAN DEFAULT 1")
            if not _has_column('groups', 'text_tools_enabled'):
                _safe_execute(conn, "ALTER TABLE groups ADD COLUMN text_tools_enabled BOOLEAN DEFAULT 1")
            if not _has_column('groups', 'auto_title_enabled'):
                _safe_execute(conn, "ALTER TABLE groups ADD COLUMN auto_title_enabled BOOLEAN DEFAULT 0")
            if not _has_column('groups', 'auto_title_model_id'):
                _safe_execute(conn, "ALTER TABLE groups ADD COLUMN auto_title_model_id INTEGER REFERENCES text_models(id)")
            if not _has_column('groups', 'auto_summary_enabled'):
                _safe_execute(conn, "ALTER TABLE groups ADD COLUMN auto_summary_enabled BOOLEAN DEFAULT 0")
            if not _has_column('groups', 'auto_summary_model_id'):
                _safe_execute(conn, "ALTER TABLE groups ADD COLUMN auto_summary_model_id INTEGER REFERENCES text_models(id)")

        # Speech models: capability flags
        if _has_table('speech_models'):
            if not _has_column('speech_models', 'supports_prompt'):
                _safe_execute(conn, "ALTER TABLE speech_models ADD COLUMN supports_prompt BOOLEAN DEFAULT 1")
            if not _has_column('speech_models', 'supports_timestamps'):
                _safe_execute(conn, "ALTER TABLE speech_models ADD COLUMN supports_timestamps BOOLEAN DEFAULT 1")
            if not _has_column('speech_models', 'supports_diarize'):
                _safe_execute(conn, "ALTER TABLE speech_models ADD COLUMN supports_diarize BOOLEAN DEFAULT 0")

        # Chat messages table
        if not _has_table('chat_messages'):
            from app.models import ChatMessage
            ChatMessage.__table__.create(db.engine)

        # Groups: audio save feature
        if _has_table('groups'):
            if not _has_column('groups', 'audio_save_enabled'):
                _safe_execute(conn, "ALTER TABLE groups ADD COLUMN audio_save_enabled BOOLEAN DEFAULT 0")
            if not _has_column('groups', 'audio_save_default'):
                _safe_execute(conn, "ALTER TABLE groups ADD COLUMN audio_save_default BOOLEAN DEFAULT 1")
            if not _has_column('groups', 'hide_single_model'):
                _safe_execute(conn, "ALTER TABLE groups ADD COLUMN hide_single_model BOOLEAN DEFAULT 1")

        # SystemSetting table
        if not _has_table('system_settings'):
            from app.models import SystemSetting
            SystemSetting.__table__.create(db.engine)

        # Speech models: max_file_size_mb and max_duration_secs
        if _has_table('speech_models') and not _has_column('speech_models', 'max_file_size_mb'):
            _safe_execute(conn, "ALTER TABLE speech_models ADD COLUMN max_file_size_mb INTEGER DEFAULT 0")
        if _has_table('speech_models') and not _has_column('speech_models', 'max_duration_secs'):
            _safe_execute(conn, "ALTER TABLE speech_models ADD COLUMN max_duration_secs INTEGER DEFAULT 0")
        if _has_table('speech_models') and not _has_column('speech_models', 'request_timeout_secs'):
            _safe_execute(conn, "ALTER TABLE speech_models ADD COLUMN request_timeout_secs INTEGER DEFAULT 600")
        if _has_table('speech_models') and not _has_column('speech_models', 'max_upload_size_mb'):
            _safe_execute(conn, "ALTER TABLE speech_models ADD COLUMN max_upload_size_mb INTEGER DEFAULT 0")
        if _has_table('speech_models') and not _has_column('speech_models', 'max_upload_duration_secs'):
            _safe_execute(conn, "ALTER TABLE speech_models ADD COLUMN max_upload_duration_secs INTEGER DEFAULT 0")
        if _has_table('speech_models') and not _has_column('speech_models', 'use_speaker_references'):
            _safe_execute(conn, "ALTER TABLE speech_models ADD COLUMN use_speaker_references BOOLEAN DEFAULT 0")

        # Groups: max_upload_size_mb
        if _has_table('groups') and not _has_column('groups', 'max_upload_size_mb'):
            _safe_execute(conn, "ALTER TABLE groups ADD COLUMN max_upload_size_mb INTEGER DEFAULT 0")

        # Users: auth_source and external_id for SSO
        if _has_table('users'):
            if not _has_column('users', 'auth_source'):
                _safe_execute(conn, "ALTER TABLE users ADD COLUMN auth_source VARCHAR(20) DEFAULT 'local'")
            if not _has_column('users', 'external_id'):
                _safe_execute(conn, "ALTER TABLE users ADD COLUMN external_id VARCHAR(255)")

        # Jobs/Meetings/Dictations: audio_saved flag
        if _has_table('jobs') and not _has_column('jobs', 'audio_saved'):
            _safe_execute(conn, "ALTER TABLE jobs ADD COLUMN audio_saved BOOLEAN DEFAULT 0")
        if _has_table('meetings') and not _has_column('meetings', 'audio_saved'):
            _safe_execute(conn, "ALTER TABLE meetings ADD COLUMN audio_saved BOOLEAN DEFAULT 0")
        if _has_table('dictations') and not _has_column('dictations', 'audio_saved'):
            _safe_execute(conn, "ALTER TABLE dictations ADD COLUMN audio_saved BOOLEAN DEFAULT 0")

        # Text models: request_timeout_secs
        if _has_table('text_models') and not _has_column('text_models', 'request_timeout_secs'):
            _safe_execute(conn, "ALTER TABLE text_models ADD COLUMN request_timeout_secs INTEGER DEFAULT 300")

        # Groups: auto_speaker
        if _has_table('groups') and not _has_column('groups', 'auto_speaker_enabled'):
            _safe_execute(conn, "ALTER TABLE groups ADD COLUMN auto_speaker_enabled BOOLEAN DEFAULT 0")
        if _has_table('groups') and not _has_column('groups', 'auto_speaker_model_id'):
            _safe_execute(conn, "ALTER TABLE groups ADD COLUMN auto_speaker_model_id INTEGER REFERENCES text_models(id)")

        # Jobs/Meetings: title_status, speaker_identify_status
        for tbl in ['jobs', 'meetings']:
            if _has_table(tbl) and not _has_column(tbl, 'title_status'):
                _safe_execute(conn, f"ALTER TABLE {tbl} ADD COLUMN title_status VARCHAR(20)")
            if _has_table(tbl) and not _has_column(tbl, 'speaker_identify_status'):
                _safe_execute(conn, f"ALTER TABLE {tbl} ADD COLUMN speaker_identify_status VARCHAR(20)")

        # Jobs/Meetings/Dictations: progress tracking
        if _has_table('jobs') and not _has_column('jobs', 'progress'):
            _safe_execute(conn, "ALTER TABLE jobs ADD COLUMN progress INTEGER DEFAULT 0")
        if _has_table('meetings') and not _has_column('meetings', 'progress'):
            _safe_execute(conn, "ALTER TABLE meetings ADD COLUMN progress INTEGER DEFAULT 0")
        if _has_table('dictations') and not _has_column('dictations', 'progress'):
            _safe_execute(conn, "ALTER TABLE dictations ADD COLUMN progress INTEGER DEFAULT 0")

        # Per-model parallel task limits
        if _has_table('speech_models') and not _has_column('speech_models', 'max_parallel_tasks'):
            _safe_execute(conn, "ALTER TABLE speech_models ADD COLUMN max_parallel_tasks INTEGER DEFAULT 0")
        if _has_table('text_models') and not _has_column('text_models', 'max_parallel_tasks'):
            _safe_execute(conn, "ALTER TABLE text_models ADD COLUMN max_parallel_tasks INTEGER DEFAULT 0")

        # Speech models: processing_speed for ETA estimation
        if _has_table('speech_models') and not _has_column('speech_models', 'processing_speed'):
            _safe_execute(conn, "ALTER TABLE speech_models ADD COLUMN processing_speed REAL DEFAULT 0")

        # Jobs/Meetings/Dictations: audio_duration_secs and processing_started_at for ETA
        for tbl in ['jobs', 'meetings', 'dictations']:
            if _has_table(tbl) and not _has_column(tbl, 'audio_duration_secs'):
                _safe_execute(conn, f"ALTER TABLE {tbl} ADD COLUMN audio_duration_secs REAL")
            if _has_table(tbl) and not _has_column(tbl, 'processing_started_at'):
                _safe_execute(conn, f"ALTER TABLE {tbl} ADD COLUMN processing_started_at DATETIME")

        # Per-function model restrictions
        if not _has_table('group_speech_model_functions'):
            from app.models import group_speech_model_functions
            group_speech_model_functions.create(bind=db.engine, checkfirst=True)
        if not _has_table('group_text_model_functions'):
            from app.models import group_text_model_functions
            group_text_model_functions.create(bind=db.engine, checkfirst=True)


def _seed_defaults(app):
    from app.models import User, Group, SpeechModel, TextModel, SystemSetting
    if not User.query.first():
        admin = User(display_name='Administrator', email='admin@transcribeops.local', is_admin=True)
        admin.set_password('admin')
        db.session.add(admin)
        db.session.commit()
    if not SpeechModel.query.first():
        default_speech = SpeechModel(
            name='Local Whisper',
            display_name='Local Whisper',
            provider='whisper_local',
            endpoint_url='http://whisper:8000/v1/audio/transcriptions',
            model_id='whisper-1',
            speaker_mode='both',
            is_active=True
        )
        db.session.add(default_speech)
        db.session.commit()
    if not TextModel.query.first():
        default_text = TextModel(
            name='Local Ollama',
            display_name='Local Ollama',
            provider='ollama',
            endpoint_url='http://host.containers.internal:11434',
            model_id='llama3.2',
            is_active=True
        )
        db.session.add(default_text)
        db.session.commit()
    # Seed default group if none exists
    if not Group.query.first():
        default_group = Group(
            name='Standard',
            description='Standard-Gruppe für neue Benutzer',
            is_default=True
        )
        db.session.add(default_group)
        db.session.commit()
    # Seed default timezone
    if not SystemSetting.query.get('timezone'):
        db.session.add(SystemSetting(key='timezone', value='Europe/Berlin'))
        db.session.commit()
    # Seed default history retention
    if not SystemSetting.query.get('default_history_days'):
        db.session.add(SystemSetting(key='default_history_days', value='30'))
        db.session.commit()
    db.session.commit()
