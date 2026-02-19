import uuid
from datetime import datetime, timezone
from flask_login import UserMixin
from werkzeug.security import generate_password_hash, check_password_hash
from app import db

# Association tables
user_groups = db.Table('user_groups',
    db.Column('user_id', db.Integer, db.ForeignKey('users.id'), primary_key=True),
    db.Column('group_id', db.Integer, db.ForeignKey('groups.id'), primary_key=True)
)

group_speech_models = db.Table('group_speech_models',
    db.Column('group_id', db.Integer, db.ForeignKey('groups.id'), primary_key=True),
    db.Column('speech_model_id', db.Integer, db.ForeignKey('speech_models.id'), primary_key=True)
)

group_text_models = db.Table('group_text_models',
    db.Column('group_id', db.Integer, db.ForeignKey('groups.id'), primary_key=True),
    db.Column('text_model_id', db.Integer, db.ForeignKey('text_models.id'), primary_key=True)
)


def _gen_uid():
    return uuid.uuid4().hex


class User(UserMixin, db.Model):
    __tablename__ = 'users'
    id = db.Column(db.Integer, primary_key=True)
    display_name = db.Column(db.String(80), nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False)
    password_hash = db.Column(db.String(256), nullable=False)
    is_admin = db.Column(db.Boolean, default=False)
    is_active_user = db.Column(db.Boolean, default=True)
    theme = db.Column(db.String(20), default='auto')  # light, dark, auto
    history_days = db.Column(db.Integer, default=30)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))

    groups = db.relationship('Group', secondary=user_groups, backref=db.backref('users', lazy='dynamic'))
    jobs = db.relationship('Job', backref='user', lazy='dynamic')

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

    def get_available_speech_models(self, mode=None):
        if self.is_admin:
            q = SpeechModel.query.filter_by(is_active=True)
        else:
            model_ids = set()
            for group in self.groups:
                for model in group.speech_models:
                    if model.is_active:
                        model_ids.add(model.id)
            q = SpeechModel.query.filter(SpeechModel.id.in_(model_ids)) if model_ids else SpeechModel.query.filter(False)
        if mode == 'single':
            q = q.filter(SpeechModel.speaker_mode.in_(['single', 'both']))
        elif mode == 'multi':
            q = q.filter(SpeechModel.speaker_mode.in_(['multi', 'both']))
        return q.all()

    def get_available_text_models(self):
        if self.is_admin:
            return TextModel.query.filter_by(is_active=True).all()
        models = set()
        for group in self.groups:
            for model in group.text_models:
                if model.is_active:
                    models.add(model)
        return list(models)


class Group(db.Model):
    __tablename__ = 'groups'
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(80), unique=True, nullable=False)
    description = db.Column(db.String(255))
    is_default = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))

    speech_models = db.relationship('SpeechModel', secondary=group_speech_models,
                                     backref=db.backref('groups', lazy='dynamic'))
    text_models = db.relationship('TextModel', secondary=group_text_models,
                                   backref=db.backref('groups', lazy='dynamic'))


class SpeechModel(db.Model):
    __tablename__ = 'speech_models'
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    display_name = db.Column(db.String(100), nullable=False)
    provider = db.Column(db.String(50), nullable=False)
    endpoint_url = db.Column(db.String(500))
    api_key = db.Column(db.String(500))
    model_id = db.Column(db.String(100))
    azure_deployment = db.Column(db.String(100))
    azure_api_version = db.Column(db.String(50))
    speaker_mode = db.Column(db.String(10), default='single')
    is_active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))


class TextModel(db.Model):
    __tablename__ = 'text_models'
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    display_name = db.Column(db.String(100), nullable=False)
    provider = db.Column(db.String(50), nullable=False)
    endpoint_url = db.Column(db.String(500))
    api_key = db.Column(db.String(500))
    model_id = db.Column(db.String(100))
    azure_deployment = db.Column(db.String(100))
    azure_api_version = db.Column(db.String(50))
    is_active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))


class Job(db.Model):
    __tablename__ = 'jobs'
    id = db.Column(db.Integer, primary_key=True)
    public_id = db.Column(db.String(32), unique=True, nullable=False, default=_gen_uid)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    job_type = db.Column(db.String(30), nullable=False)
    status = db.Column(db.String(20), default='pending')
    title = db.Column(db.String(255))
    original_filename = db.Column(db.String(255))
    file_path = db.Column(db.String(500))
    speech_model_id = db.Column(db.Integer, db.ForeignKey('speech_models.id'))
    text_model_id = db.Column(db.Integer, db.ForeignKey('text_models.id'))
    language = db.Column(db.String(10))
    multi_speaker = db.Column(db.Boolean, default=False)
    input_text = db.Column(db.Text)
    result_text = db.Column(db.Text)
    diarized_segments = db.Column(db.Text)
    summary_text = db.Column(db.Text)
    summary_status = db.Column(db.String(20))
    tool_action = db.Column(db.String(30))
    target_language = db.Column(db.String(50))
    error_message = db.Column(db.Text)
    celery_task_id = db.Column(db.String(155))
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
    completed_at = db.Column(db.DateTime)

    speech_model = db.relationship('SpeechModel', backref='jobs')
    text_model = db.relationship('TextModel', backref='jobs')
