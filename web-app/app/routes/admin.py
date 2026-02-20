from functools import wraps
from flask import Blueprint, render_template, request, jsonify, redirect, url_for, flash
from flask_login import login_required, current_user
from app import db
from app.models import User, Group, SpeechModel, TextModel

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


@admin_bp.route('/')
@admin_required
def dashboard():
    users = User.query.order_by(User.created_at.desc()).all()
    groups = Group.query.all()
    speech_models = SpeechModel.query.all()
    text_models = TextModel.query.all()
    return render_template('admin/dashboard.html',
                           users=users, groups=groups,
                           speech_models=speech_models, text_models=text_models)


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
