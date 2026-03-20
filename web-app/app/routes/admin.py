from functools import wraps
from flask import Blueprint, render_template, request, jsonify, redirect, url_for, flash
from flask_login import login_required, current_user
import os
from flask import current_app
from app import db
from app.models import (User, Group, SpeechModel, TextModel, SystemSetting, Job, Meeting, Dictation, TextTask,
                        ChatMessage, group_speech_model_functions, group_text_model_functions)

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
    hist_setting = SystemSetting.query.get('default_history_days')
    default_history_days = int(hist_setting.value) if hist_setting else 30

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

    # Global job list: recent jobs/meetings/dictations across all users
    from sqlalchemy import union_all, literal, text
    from app.utils import format_dt
    from app.routes.api import _compute_eta_seconds

    ACTION_LABELS = {
        'rewrite': 'Umschreiben',
        'grammar': 'Grammatik',
        'translate': 'Übersetzen',
        'summarize': 'Zusammenfassen',
    }

    def _build_record(record, rtype, record_type_str):
        user = db.session.get(User, record.user_id)
        eta = _compute_eta_seconds(record) if record.status in ('pending', 'processing') else None
        started = getattr(record, 'processing_started_at', None)
        if started and started.tzinfo is None:
            from datetime import timezone as tz
            started = started.replace(tzinfo=tz.utc)
        # TextTask has no speech_model; use text_model instead
        speech_model = getattr(record, 'speech_model', None)
        text_model = getattr(record, 'text_model', None)
        model_name = (speech_model.display_name if speech_model else
                      text_model.display_name if text_model else '-')
        # TextTask has no title; use action label
        title = getattr(record, 'title', None)
        if not title and hasattr(record, 'action'):
            title = ACTION_LABELS.get(record.action, record.action)
        return {
            'type': rtype,
            'record_type': record_type_str,
            'record_id': record.id,
            'title': title,
            'status': record.status,
            'user_name': user.display_name if user else '?',
            'user_email': user.email if user else '',
            'error_message': record.error_message,
            'created_at': format_dt(record.created_at),
            'created_at_raw': record.created_at,
            'speech_model': model_name,
            'eta_seconds': eta,
            'processing_started_at': started.isoformat() if started else None,
            'summary_status': getattr(record, 'summary_status', None),
            'title_status': getattr(record, 'title_status', None),
            'speaker_identify_status': getattr(record, 'speaker_identify_status', None),
            'chat_processing_count': ChatMessage.query.filter_by(
                record_type=record_type_str, record_id=record.id, status='processing'
            ).count() if record_type_str in ('job', 'meeting') else 0,
        }

    all_records = []
    for record in Job.query.order_by(Job.created_at.desc()).limit(100).all():
        all_records.append(_build_record(record, 'Transkription', 'job'))
    for record in Meeting.query.order_by(Meeting.created_at.desc()).limit(100).all():
        all_records.append(_build_record(record, 'Meeting', 'meeting'))
    for record in Dictation.query.order_by(Dictation.created_at.desc()).limit(100).all():
        all_records.append(_build_record(record, 'Diktat', 'dictation'))
    for record in TextTask.query.order_by(TextTask.created_at.desc()).limit(100).all():
        all_records.append(_build_record(record, 'Textverarbeitung', 'text_task'))
    all_records.sort(key=lambda r: r['created_at_raw'] or '', reverse=True)
    all_records = all_records[:100]

    # Build per-group function restriction maps for the template
    group_speech_fns = {}
    group_text_fns = {}
    for group in groups:
        speech_fns = {}
        rows = db.session.query(group_speech_model_functions).filter_by(group_id=group.id).all()
        for r in rows:
            speech_fns.setdefault(r.speech_model_id, []).append(r.function)
        group_speech_fns[group.id] = speech_fns

        text_fns = {}
        rows = db.session.query(group_text_model_functions).filter_by(group_id=group.id).all()
        for r in rows:
            text_fns.setdefault(r.text_model_id, []).append(r.function)
        group_text_fns[group.id] = text_fns

    return render_template('admin/dashboard.html',
                           users=users, groups=groups,
                           speech_models=speech_models, text_models=text_models,
                           group_speech_fns=group_speech_fns,
                           group_text_fns=group_text_fns,
                           current_timezone=current_timezone,
                           default_history_days=default_history_days,
                           audio_storage_path=audio_path,
                           upload_folder=upload_path,
                           database_url=db_url,
                           max_upload_mb=max_upload_mb,
                           audio_disk_usage=_fmt_size(_dir_size(audio_path)),
                           upload_disk_usage=_fmt_size(_dir_size(upload_path)),
                           stats=stats,
                           sso_settings=sso_settings,
                           all_records=all_records)


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
    db.session.flush()

    # Save per-function model restrictions
    _save_model_functions(group)

    db.session.commit()
    flash(f'Gruppe "{name}" erstellt.', 'success')
    return redirect(url_for('admin.dashboard'))


def _save_model_functions(group):
    """Save per-function model restrictions from form data."""
    # Clear old entries
    db.session.execute(group_speech_model_functions.delete().where(
        group_speech_model_functions.c.group_id == group.id))
    db.session.execute(group_text_model_functions.delete().where(
        group_text_model_functions.c.group_id == group.id))

    # Save speech model functions
    for model in group.speech_models:
        functions = request.form.getlist(f'speech_fn_{model.id}')
        for fn in functions:
            db.session.execute(group_speech_model_functions.insert().values(
                group_id=group.id, speech_model_id=model.id, function=fn))

    # Save text model functions
    for model in group.text_models:
        functions = request.form.getlist(f'text_fn_{model.id}')
        for fn in functions:
            db.session.execute(group_text_model_functions.insert().values(
                group_id=group.id, text_model_id=model.id, function=fn))


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

    # Save per-function model restrictions
    _save_model_functions(group)

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
    db.session.execute(group_speech_model_functions.delete().where(
        group_speech_model_functions.c.group_id == group.id))
    db.session.execute(group_text_model_functions.delete().where(
        group_text_model_functions.c.group_id == group.id))
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
        max_parallel_tasks=request.form.get('max_parallel_tasks', 0, type=int),
        processing_speed=request.form.get('processing_speed', 0, type=float),
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
    model.max_parallel_tasks = request.form.get('max_parallel_tasks', 0, type=int)
    model.processing_speed = request.form.get('processing_speed', 0, type=float)
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
        max_parallel_tasks=request.form.get('max_parallel_tasks', 0, type=int),
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
    model.max_parallel_tasks = request.form.get('max_parallel_tasks', 0, type=int)
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

    # Default history retention
    hist_val = request.form.get('default_history_days')
    if hist_val is not None:
        hist_val = hist_val.strip()
        # '0' = unlimited, otherwise positive integer
        if hist_val == '0' or (hist_val.isdigit() and int(hist_val) > 0):
            hist_setting = SystemSetting.query.get('default_history_days')
            if hist_setting:
                hist_setting.value = hist_val
            else:
                db.session.add(SystemSetting(key='default_history_days', value=hist_val))

    db.session.commit()
    flash('Globale Einstellungen gespeichert.', 'success')
    return redirect(url_for('admin.dashboard'))


# --- Job Cancellation ---

@admin_bp.route('/job/<record_type>/<int:record_id>/cancel', methods=['POST'])
@admin_required
def cancel_job(record_type, record_id):
    model_map = {'job': Job, 'meeting': Meeting, 'dictation': Dictation, 'text_task': TextTask}
    model_cls = model_map.get(record_type)
    if not model_cls:
        flash('Ungültiger Typ.', 'danger')
        return redirect(url_for('admin.dashboard'))

    record = db.session.get(model_cls, record_id)
    if not record or record.status not in ('pending', 'processing'):
        flash('Job nicht gefunden oder bereits abgeschlossen.', 'warning')
        return redirect(url_for('admin.dashboard'))

    if record.celery_task_id:
        from app.celery_app import celery
        celery.control.revoke(record.celery_task_id, terminate=True)

    record.status = 'failed'
    record.error_message = 'Vom Administrator abgebrochen'
    db.session.commit()
    flash('Job abgebrochen.', 'success')
    return redirect(url_for('admin.dashboard'))


# --- Sub-Task Cancellation ---

@admin_bp.route('/job/<record_type>/<int:record_id>/cancel-subtask', methods=['POST'])
@admin_required
def cancel_subtask(record_type, record_id):
    model_map = {'job': Job, 'meeting': Meeting}
    model_cls = model_map.get(record_type)
    subtask = request.form.get('subtask')
    if not model_cls or subtask not in ('title', 'summary', 'speaker', 'chat'):
        flash('Ungültiger Typ oder Sub-Task.', 'danger')
        return redirect(url_for('admin.dashboard'))

    record = db.session.get(model_cls, record_id)
    if not record:
        flash('Job nicht gefunden.', 'warning')
        return redirect(url_for('admin.dashboard'))

    if subtask == 'title' and record.title_status == 'processing':
        record.title_status = 'cancelled'
        db.session.commit()
        flash('Titelgenerierung abgebrochen.', 'success')
    elif subtask == 'summary' and record.summary_status == 'processing':
        record.summary_status = 'cancelled'
        db.session.commit()
        flash('Zusammenfassung abgebrochen.', 'success')
    elif subtask == 'speaker' and record.speaker_identify_status == 'processing':
        record.speaker_identify_status = 'cancelled'
        db.session.commit()
        flash('Sprechererkennung abgebrochen.', 'success')
    elif subtask == 'chat':
        processing_msgs = ChatMessage.query.filter_by(
            record_type=record_type, record_id=record_id, status='processing'
        ).all()
        for msg in processing_msgs:
            msg.status = 'failed'
            msg.content = 'Vom Administrator abgebrochen'
        db.session.commit()
        flash(f'{len(processing_msgs)} Chat-Nachricht(en) abgebrochen.', 'success')
    else:
        flash('Sub-Task läuft nicht oder bereits abgeschlossen.', 'warning')

    return redirect(url_for('admin.dashboard'))


# --- SSO Settings ---

@admin_bp.route('/sso', methods=['POST'])
@admin_required
def update_sso():
    from app.sso import save_sso_settings
    save_sso_settings(request.form)
    flash('Single-Sign-On Einstellungen gespeichert.', 'success')
    return redirect(url_for('admin.dashboard'))
