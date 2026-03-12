from functools import wraps
from flask import Blueprint, render_template, request, jsonify, redirect, url_for, flash
from flask_login import login_required, current_user
import os
from flask import current_app
from app import db
from app.models import User, Group, SpeechModel, TextModel, SystemSetting, Job, Meeting, Dictation, TextTask

admin_bp = Blueprint('admin', __name__)


def admin_required(f):
    @wraps(f)
    @login_required
    def decorated(*args, **kwargs):
        if not current_user.is_admin:
            flash('Zugriff verweigert.', 'danger')
            return redirect(url_for('main.transcription'))
        return f(*args, **kwargs)
    return decorated


def _dir_size(path):
    """Calculate total size of files in a directory (non-recursive for top level)."""
    total = 0
    try:
        for entry in os.scandir(path):
            if entry.is_file():
                total += entry.stat().st_size
    except (OSError, FileNotFoundError):
        pass
    return total


def _fmt_size(size_bytes):
    """Format byte size to human-readable string."""
    if size_bytes < 1024:
        return f"{size_bytes} B"
    elif size_bytes < 1024 * 1024:
        return f"{size_bytes / 1024:.1f} KB"
    elif size_bytes < 1024 * 1024 * 1024:
        return f"{size_bytes / (1024 * 1024):.1f} MB"
    else:
        return f"{size_bytes / (1024 * 1024 * 1024):.2f} GB"


@admin_bp.route('/')
@admin_required
def dashboard():
    users = User.query.order_by(User.created_at.desc()).all()
    groups = Group.query.all()
    speech_models = SpeechModel.query.all()
    text_models = TextModel.query.all()

    # Global tab data
    tz_setting = SystemSetting.query.get('timezone')
    current_timezone = tz_setting.value if tz_setting else 'Europe/Berlin'

    audio_path = current_app.config.get('AUDIO_STORAGE_PATH', '')
    upload_path = current_app.config.get('UPLOAD_FOLDER', '')
    db_url = current_app.config.get('SQLALCHEMY_DATABASE_URI', '')
    max_upload_mb = current_app.config.get('MAX_CONTENT_LENGTH', 0) // (1024 * 1024)

    stats = {
        'users': User.query.count(),
        'jobs': Job.query.count(),
        'meetings': Meeting.query.count(),
        'dictations': Dictation.query.count(),
        'text_tasks': TextTask.query.count(),
    }

    # SSO settings
    from app.sso import get_all_sso_settings
    sso_settings = get_all_sso_settings()

    return render_template('admin/dashboard.html',
                           users=users, groups=groups,
                           speech_models=speech_models, text_models=text_models,
                           current_timezone=current_timezone,
                           audio_storage_path=audio_path,
                           upload_folder=upload_path,
                           database_url=db_url,
                           max_upload_mb=max_upload_mb,
                           audio_disk_usage=_fmt_size(_dir_size(audio_path)),
                           upload_disk_usage=_fmt_size(_dir_size(upload_path)),
                           stats=stats,
                           sso_settings=sso_settings)


# --- User Management ---

@admin_bp.route('/user', methods=['POST'])
@admin_required
def create_user():
    data = request.form
    display_name = data.get('display_name', '').strip()
    email = data.get('email', '').strip()
    password = data.get('password', '')
    is_admin = data.get('is_admin') == 'on'

    if not display_name or not email or not password:
        flash('Alle Felder sind erforderlich.', 'danger')
        return redirect(url_for('admin.dashboard'))

    if User.query.filter_by(email=email).first():
        flash('E-Mail-Adresse existiert bereits.', 'danger')
        return redirect(url_for('admin.dashboard'))

    user = User(display_name=display_name, email=email, is_admin=is_admin)
    user.set_password(password)
    db.session.add(user)
    db.session.flush()  # get user.id before committing

    # Auto-assign to default groups
    default_groups = Group.query.filter_by(is_default=True).all()
    for g in default_groups:
        user.groups.append(g)

    db.session.commit()
    flash(f'Benutzer "{display_name}" erstellt.', 'success')
    return redirect(url_for('admin.dashboard'))


@admin_bp.route('/user/<int:user_id>', methods=['POST'])
@admin_required
def update_user(user_id):
    user = db.session.get(User, user_id)
    if not user:
        flash('Benutzer nicht gefunden.', 'danger')
        return redirect(url_for('admin.dashboard'))

    user.display_name = request.form.get('display_name', user.display_name).strip()
    user.email = request.form.get('email', user.email).strip()
    user.is_admin = request.form.get('is_admin') == 'on'
    user.is_active_user = request.form.get('is_active_user') == 'on'
    new_pw = request.form.get('password', '').strip()
    if new_pw:
        user.set_password(new_pw)

    group_ids = request.form.getlist('group_ids', type=int)
    user.groups = Group.query.filter(Group.id.in_(group_ids)).all() if group_ids else []

    db.session.commit()
    flash(f'Benutzer "{user.display_name}" aktualisiert.', 'success')
    return redirect(url_for('admin.dashboard'))


@admin_bp.route('/user/<int:user_id>/delete', methods=['POST'])
@admin_required
def delete_user(user_id):
    user = db.session.get(User, user_id)
    if not user:
        flash('Benutzer nicht gefunden.', 'danger')
        return redirect(url_for('admin.dashboard'))
    if user.id == current_user.id:
        flash('Sie können sich nicht selbst löschen.', 'danger')
        return redirect(url_for('admin.dashboard'))
    db.session.delete(user)
    db.session.commit()
    flash('Benutzer gelöscht.', 'success')
    return redirect(url_for('admin.dashboard'))


# --- Group Management ---

@admin_bp.route('/group', methods=['POST'])
@admin_required
def create_group():
    name = request.form.get('name', '').strip()
    description = request.form.get('description', '').strip()
    is_default = request.form.get('is_default') == 'on'
    if not name:
        flash('Gruppenname erforderlich.', 'danger')
        return redirect(url_for('admin.dashboard'))

    # If setting as default, unset other defaults
    if is_default:
        Group.query.filter_by(is_default=True).update({'is_default': False})

    dictionary_enabled = request.form.get('dictionary_enabled') == 'on'
    group = Group(name=name, description=description, is_default=is_default, dictionary_enabled=dictionary_enabled)

    # Feature toggles
    group.transcription_enabled = request.form.get('transcription_enabled') == 'on'
    group.meeting_enabled = request.form.get('meeting_enabled') == 'on'
    group.dictation_enabled = request.form.get('dictation_enabled') == 'on'
    group.text_tools_enabled = request.form.get('text_tools_enabled') == 'on'

    # Auto-title / auto-summary
    group.auto_title_enabled = request.form.get('auto_title_enabled') == 'on'
    group.auto_title_model_id = request.form.get('auto_title_model_id', type=int) or None
    group.auto_summary_enabled = request.form.get('auto_summary_enabled') == 'on'
    group.auto_summary_model_id = request.form.get('auto_summary_model_id', type=int) or None
    group.auto_speaker_enabled = request.form.get('auto_speaker_enabled') == 'on'
    group.auto_speaker_model_id = request.form.get('auto_speaker_model_id', type=int) or None

    # Audio save
    group.audio_save_enabled = request.form.get('audio_save_enabled') == 'on'
    group.audio_save_default = request.form.get('audio_save_default') == 'on'

    # UI
    group.hide_single_model = request.form.get('hide_single_model') == 'on'

    # Upload limit
    group.max_upload_size_mb = request.form.get('max_upload_size_mb', 0, type=int)

    speech_model_ids = request.form.getlist('speech_model_ids', type=int)
    text_model_ids = request.form.getlist('text_model_ids', type=int)
    group.speech_models = SpeechModel.query.filter(SpeechModel.id.in_(speech_model_ids)).all() if speech_model_ids else []
    group.text_models = TextModel.query.filter(TextModel.id.in_(text_model_ids)).all() if text_model_ids else []

    db.session.add(group)
    db.session.commit()
    flash(f'Gruppe "{name}" erstellt.', 'success')
    return redirect(url_for('admin.dashboard'))


@admin_bp.route('/group/<int:group_id>', methods=['POST'])
@admin_required
def update_group(group_id):
    group = db.session.get(Group, group_id)
    if not group:
        flash('Gruppe nicht gefunden.', 'danger')
        return redirect(url_for('admin.dashboard'))

    group.name = request.form.get('name', group.name).strip()
    group.description = request.form.get('description', '').strip()
    is_default = request.form.get('is_default') == 'on'

    # If setting as default, unset other defaults
    if is_default and not group.is_default:
        Group.query.filter(Group.id != group.id, Group.is_default == True).update({'is_default': False})
    group.is_default = is_default
    group.dictionary_enabled = request.form.get('dictionary_enabled') == 'on'

    # Feature toggles
    group.transcription_enabled = request.form.get('transcription_enabled') == 'on'
    group.meeting_enabled = request.form.get('meeting_enabled') == 'on'
    group.dictation_enabled = request.form.get('dictation_enabled') == 'on'
    group.text_tools_enabled = request.form.get('text_tools_enabled') == 'on'

    # Auto-title / auto-summary
    group.auto_title_enabled = request.form.get('auto_title_enabled') == 'on'
    group.auto_title_model_id = request.form.get('auto_title_model_id', type=int) or None
    group.auto_summary_enabled = request.form.get('auto_summary_enabled') == 'on'
    group.auto_summary_model_id = request.form.get('auto_summary_model_id', type=int) or None
    group.auto_speaker_enabled = request.form.get('auto_speaker_enabled') == 'on'
    group.auto_speaker_model_id = request.form.get('auto_speaker_model_id', type=int) or None

    # Audio save
    group.audio_save_enabled = request.form.get('audio_save_enabled') == 'on'
    group.audio_save_default = request.form.get('audio_save_default') == 'on'

    # UI
    group.hide_single_model = request.form.get('hide_single_model') == 'on'

    # Upload limit
    group.max_upload_size_mb = request.form.get('max_upload_size_mb', 0, type=int)

    speech_model_ids = request.form.getlist('speech_model_ids', type=int)
    text_model_ids = request.form.getlist('text_model_ids', type=int)
    group.speech_models = SpeechModel.query.filter(SpeechModel.id.in_(speech_model_ids)).all() if speech_model_ids else []
    group.text_models = TextModel.query.filter(TextModel.id.in_(text_model_ids)).all() if text_model_ids else []

    db.session.commit()
    flash(f'Gruppe "{group.name}" aktualisiert.', 'success')
    return redirect(url_for('admin.dashboard'))


@admin_bp.route('/group/<int:group_id>/delete', methods=['POST'])
@admin_required
def delete_group(group_id):
    group = db.session.get(Group, group_id)
    if not group:
        flash('Gruppe nicht gefunden.', 'danger')
        return redirect(url_for('admin.dashboard'))
    db.session.delete(group)
    db.session.commit()
    flash('Gruppe gelöscht.', 'success')
    return redirect(url_for('admin.dashboard'))


# --- Speech Model Management ---

@admin_bp.route('/speech-model', methods=['POST'])
@admin_required
def create_speech_model():
    model = SpeechModel(
        name=request.form.get('name', '').strip(),
        display_name=request.form.get('display_name', '').strip(),
        provider=request.form.get('provider', ''),
        endpoint_url=request.form.get('endpoint_url', '').strip(),
        api_key=request.form.get('api_key', '').strip(),
        model_id=request.form.get('model_id', '').strip(),
        azure_deployment=request.form.get('azure_deployment', '').strip(),
        azure_api_version=request.form.get('azure_api_version', '').strip(),
        speaker_mode=request.form.get('speaker_mode', 'single'),
        supports_prompt=request.form.get('supports_prompt') == 'on',
        supports_timestamps=request.form.get('supports_timestamps') == 'on',
        supports_diarize=request.form.get('supports_diarize') == 'on',
        max_file_size_mb=request.form.get('max_file_size_mb', 0, type=int),
        max_duration_secs=request.form.get('max_duration_secs', 0, type=int),
        max_upload_size_mb=request.form.get('max_upload_size_mb', 0, type=int),
        max_upload_duration_secs=request.form.get('max_upload_duration_secs', 0, type=int),
        request_timeout_secs=request.form.get('request_timeout_secs', 600, type=int),
        use_speaker_references=request.form.get('use_speaker_references') == 'on',
        is_active=request.form.get('is_active') == 'on'
    )
    db.session.add(model)
    db.session.commit()
    flash(f'Sprachmodell "{model.name}" erstellt.', 'success')
    return redirect(url_for('admin.dashboard'))


@admin_bp.route('/speech-model/<int:model_id>', methods=['POST'])
@admin_required
def update_speech_model(model_id):
    model = db.session.get(SpeechModel, model_id)
    if not model:
        flash('Modell nicht gefunden.', 'danger')
        return redirect(url_for('admin.dashboard'))

    model.name = request.form.get('name', model.name).strip()
    model.display_name = request.form.get('display_name', model.display_name).strip()
    model.provider = request.form.get('provider', model.provider)
    model.endpoint_url = request.form.get('endpoint_url', '').strip()
    model.model_id = request.form.get('model_id', '').strip()
    model.azure_deployment = request.form.get('azure_deployment', '').strip()
    model.azure_api_version = request.form.get('azure_api_version', '').strip()
    model.speaker_mode = request.form.get('speaker_mode', model.speaker_mode)
    model.supports_prompt = request.form.get('supports_prompt') == 'on'
    model.supports_timestamps = request.form.get('supports_timestamps') == 'on'
    model.supports_diarize = request.form.get('supports_diarize') == 'on'
    model.max_file_size_mb = request.form.get('max_file_size_mb', 0, type=int)
    model.max_duration_secs = request.form.get('max_duration_secs', 0, type=int)
    model.max_upload_size_mb = request.form.get('max_upload_size_mb', 0, type=int)
    model.max_upload_duration_secs = request.form.get('max_upload_duration_secs', 0, type=int)
    model.request_timeout_secs = request.form.get('request_timeout_secs', 600, type=int)
    model.use_speaker_references = request.form.get('use_speaker_references') == 'on'
    model.is_active = request.form.get('is_active') == 'on'
    new_key = request.form.get('api_key', '').strip()
    if new_key:
        model.api_key = new_key

    db.session.commit()
    flash(f'Sprachmodell "{model.name}" aktualisiert.', 'success')
    return redirect(url_for('admin.dashboard'))


@admin_bp.route('/speech-model/<int:model_id>/delete', methods=['POST'])
@admin_required
def delete_speech_model(model_id):
    model = db.session.get(SpeechModel, model_id)
    if not model:
        flash('Modell nicht gefunden.', 'danger')
        return redirect(url_for('admin.dashboard'))
    db.session.delete(model)
    db.session.commit()
    flash('Sprachmodell gelöscht.', 'success')
    return redirect(url_for('admin.dashboard'))


# --- Text Model Management ---

@admin_bp.route('/text-model', methods=['POST'])
@admin_required
def create_text_model():
    model = TextModel(
        name=request.form.get('name', '').strip(),
        display_name=request.form.get('display_name', '').strip(),
        provider=request.form.get('provider', ''),
        endpoint_url=request.form.get('endpoint_url', '').strip(),
        api_key=request.form.get('api_key', '').strip(),
        model_id=request.form.get('model_id', '').strip(),
        azure_deployment=request.form.get('azure_deployment', '').strip(),
        azure_api_version=request.form.get('azure_api_version', '').strip(),
        request_timeout_secs=request.form.get('request_timeout_secs', 300, type=int),
        is_active=request.form.get('is_active') == 'on'
    )
    db.session.add(model)
    db.session.commit()
    flash(f'Textmodell "{model.name}" erstellt.', 'success')
    return redirect(url_for('admin.dashboard'))


@admin_bp.route('/text-model/<int:model_id>', methods=['POST'])
@admin_required
def update_text_model(model_id):
    model = db.session.get(TextModel, model_id)
    if not model:
        flash('Modell nicht gefunden.', 'danger')
        return redirect(url_for('admin.dashboard'))

    model.name = request.form.get('name', model.name).strip()
    model.display_name = request.form.get('display_name', model.display_name).strip()
    model.provider = request.form.get('provider', model.provider)
    model.endpoint_url = request.form.get('endpoint_url', '').strip()
    model.model_id = request.form.get('model_id', '').strip()
    model.azure_deployment = request.form.get('azure_deployment', '').strip()
    model.azure_api_version = request.form.get('azure_api_version', '').strip()
    model.request_timeout_secs = request.form.get('request_timeout_secs', 300, type=int)
    model.is_active = request.form.get('is_active') == 'on'
    new_key = request.form.get('api_key', '').strip()
    if new_key:
        model.api_key = new_key

    db.session.commit()
    flash(f'Textmodell "{model.name}" aktualisiert.', 'success')
    return redirect(url_for('admin.dashboard'))


@admin_bp.route('/text-model/<int:model_id>/delete', methods=['POST'])
@admin_required
def delete_text_model(model_id):
    model = db.session.get(TextModel, model_id)
    if not model:
        flash('Modell nicht gefunden.', 'danger')
        return redirect(url_for('admin.dashboard'))
    db.session.delete(model)
    db.session.commit()
    flash('Textmodell gelöscht.', 'success')
    return redirect(url_for('admin.dashboard'))


# --- Global Settings ---

@admin_bp.route('/global', methods=['POST'])
@admin_required
def update_global():
    tz = request.form.get('timezone', 'Europe/Berlin').strip()
    setting = SystemSetting.query.get('timezone')
    if setting:
        setting.value = tz
    else:
        db.session.add(SystemSetting(key='timezone', value=tz))
    db.session.commit()
    flash('Globale Einstellungen gespeichert.', 'success')
    return redirect(url_for('admin.dashboard'))


# --- SSO Settings ---

@admin_bp.route('/sso', methods=['POST'])
@admin_required
def update_sso():
    from app.sso import save_sso_settings
    save_sso_settings(request.form)
    flash('Single-Sign-On Einstellungen gespeichert.', 'success')
    return redirect(url_for('admin.dashboard'))
