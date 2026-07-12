from flask import Blueprint, render_template, request, redirect, url_for, flash, abort, session
from flask_login import login_required, current_user
from flask_babel import gettext as _
from app import db
from app.models import Job, Meeting, Dictation, DictionaryEntry
from app.utils import safe_next_url

main_bp = Blueprint('main', __name__)


@main_bp.route('/lang/<string:code>')
def set_language(code):
    """Switch UI language. Persists to user record if logged in; otherwise to session."""
    if code not in ('en', 'de'):
        code = 'en'
    if current_user.is_authenticated:
        current_user.language = code
        db.session.commit()
    session['lang'] = code
    # Reject open redirects: only allow relative URLs on this host.
    next_url = safe_next_url(request.args.get('next')) or safe_next_url(request.referrer)
    return redirect(next_url or url_for('main.transcription'))


@main_bp.route('/')
@login_required
def index():
    return redirect(url_for('main.transcription'))


@main_bp.route('/transcription')
@login_required
def transcription():
    if not current_user.has_transcription_access():
        flash(_('No access to transcription.'), 'danger')
        return redirect(url_for('main.settings'))
    single_models = current_user.get_available_speech_models(mode='single', function='transcription')
    multi_models = current_user.get_available_speech_models(mode='multi', function='transcription')
    text_models = current_user.get_available_text_models()
    audio_save_enabled, audio_save_default = current_user.get_audio_save_settings()
    hide_single_model = current_user.get_hide_single_model()
    return render_template('main/transcription.html',
                           single_models=single_models,
                           multi_models=multi_models,
                           text_models=text_models,
                           audio_save_enabled=audio_save_enabled,
                           audio_save_default=audio_save_default,
                           hide_single_model=hide_single_model)


@main_bp.route('/meeting')
@login_required
def meeting():
    if not current_user.has_meeting_access():
        flash(_('No access to meeting.'), 'danger')
        return redirect(url_for('main.settings'))
    speech_models = current_user.get_available_speech_models(mode='multi', function='meeting')
    text_models = current_user.get_available_text_models()
    audio_save_enabled, audio_save_default = current_user.get_audio_save_settings()
    hide_single_model = current_user.get_hide_single_model()
    return render_template('main/meeting.html',
                           speech_models=speech_models,
                           text_models=text_models,
                           audio_save_enabled=audio_save_enabled,
                           audio_save_default=audio_save_default,
                           hide_single_model=hide_single_model)


@main_bp.route('/dictation')
@login_required
def dictation():
    if not current_user.has_dictation_access():
        flash(_('No access to dictation.'), 'danger')
        return redirect(url_for('main.settings'))
    speech_models = current_user.get_available_speech_models(mode='single', function='dictation')
    hide_single_model = current_user.get_hide_single_model()
    return render_template('main/dictation.html',
                           speech_models=speech_models,
                           hide_single_model=hide_single_model)


@main_bp.route('/text-tools')
@login_required
def text_tools():
    if not current_user.has_text_tools_access():
        flash(_('No access to text tools.'), 'danger')
        return redirect(url_for('main.settings'))
    text_models = current_user.get_available_text_models(function='text_tools')
    hide_single_model = current_user.get_hide_single_model()
    return render_template('main/text_tools.html',
                           text_models=text_models,
                           hide_single_model=hide_single_model)


@main_bp.route('/chat')
@login_required
def chat():
    if not current_user.has_chat_access():
        flash(_('No access to chat.'), 'danger')
        return redirect(url_for('main.settings'))
    text_models = current_user.get_available_text_models(function='chat')
    hide_single_model = current_user.get_hide_single_model()
    return render_template('main/chat.html',
                           text_models=text_models,
                           hide_single_model=hide_single_model)


@main_bp.route('/transcription-job/<string:public_id>')
@login_required
def transcription_job_detail(public_id):
    if not current_user.has_transcription_access():
        abort(403)
    job = Job.query.filter_by(public_id=public_id, user_id=current_user.id).first()
    if not job:
        abort(404)
    text_models = current_user.get_available_text_models(function='summary')
    chat_models = current_user.get_available_text_models(function='chat')
    hide_single_model = current_user.get_hide_single_model()
    return render_template('main/job_detail.html',
                           job=job, record_type='job',
                           text_models=text_models,
                           chat_models=chat_models,
                           hide_single_model=hide_single_model,
                           back_url=url_for('main.transcription'))


@main_bp.route('/meeting-job/<string:public_id>')
@login_required
def meeting_job_detail(public_id):
    if not current_user.has_meeting_access():
        abort(403)
    m = Meeting.query.filter_by(public_id=public_id, user_id=current_user.id).first()
    if not m:
        abort(404)
    text_models = current_user.get_available_text_models(function='summary')
    chat_models = current_user.get_available_text_models(function='chat')
    hide_single_model = current_user.get_hide_single_model()
    return render_template('main/job_detail.html',
                           job=m, record_type='meeting',
                           text_models=text_models,
                           chat_models=chat_models,
                           hide_single_model=hide_single_model,
                           back_url=url_for('main.meeting'))


@main_bp.route('/dictation-job/<string:public_id>')
@login_required
def dictation_job_detail(public_id):
    if not current_user.has_dictation_access():
        abort(403)
    d = Dictation.query.filter_by(public_id=public_id, user_id=current_user.id).first()
    if not d:
        abort(404)
    text_models = current_user.get_available_text_models(function='summary')
    chat_models = current_user.get_available_text_models(function='chat')
    hide_single_model = current_user.get_hide_single_model()
    return render_template('main/job_detail.html',
                           job=d, record_type='dictation',
                           text_models=text_models,
                           chat_models=chat_models,
                           hide_single_model=hide_single_model,
                           back_url=url_for('main.dictation'))


@main_bp.route('/job/<string:public_id>')
@login_required
def job_detail_legacy(public_id):
    """Legacy redirect — find record type and redirect to typed URL."""
    if Job.query.filter_by(public_id=public_id, user_id=current_user.id).first():
        return redirect(url_for('main.transcription_job_detail', public_id=public_id))
    if Meeting.query.filter_by(public_id=public_id, user_id=current_user.id).first():
        return redirect(url_for('main.meeting_job_detail', public_id=public_id))
    if Dictation.query.filter_by(public_id=public_id, user_id=current_user.id).first():
        return redirect(url_for('main.dictation_job_detail', public_id=public_id))
    abort(404)


@main_bp.route('/dictionary')
@login_required
def dictionary():
    if not current_user.has_dictionary_access():
        flash(_('No access to dictionary.'), 'danger')
        return redirect(url_for('main.transcription'))
    return render_template('main/dictionary.html')


@main_bp.route('/settings', methods=['GET', 'POST'])
@login_required
def settings():
    if request.method == 'POST':
        theme = request.form.get('theme', 'auto')
        if theme in ('light', 'dark', 'auto'):
            current_user.theme = theme
        language = request.form.get('language', '')
        if language in ('en', 'de'):
            current_user.language = language
            # Sync session so the next response renders in the new language.
            session['lang'] = language
        elif language == '':
            current_user.language = None
            session.pop('lang', None)
        history_mode = request.form.get('history_mode', 'default')
        if history_mode == 'default':
            current_user.history_days = None
        elif history_mode == 'unlimited':
            current_user.history_days = 0
        else:
            days = request.form.get('history_days', 30, type=int)
            if 1 <= days <= 365:
                current_user.history_days = days
        db.session.commit()
        flash(_('Settings saved.'), 'success')
        return redirect(url_for('main.settings'))
    from app.models import SystemSetting
    hist_setting = SystemSetting.query.get('default_history_days')
    global_days = int(hist_setting.value) if hist_setting else 30
    global_history_label = _('Unlimited') if global_days == 0 else _('%(days)s days', days=global_days)
    return render_template('main/settings.html', global_history_label=global_history_label)


@main_bp.route('/api-keys')
@login_required
def api_keys():
    if not current_user.has_api_access():
        flash(_('No access to API keys.'), 'danger')
        return redirect(url_for('main.settings'))
    # Same per-function restrictions as the /v1 API itself: transcription
    # for speech, chat for plain completions, text_tools for Textmuster.
    speech_models = current_user.get_available_speech_models(function='transcription')
    chat_models = current_user.get_available_text_models(function='chat')
    pattern_models = current_user.get_available_text_models(function='text_tools')
    chat_ids = {m.id for m in chat_models}
    pattern_ids = {m.id for m in pattern_models}
    text_model_rows = []
    seen = set()
    for m in chat_models + pattern_models:
        if m.id in seen:
            continue
        seen.add(m.id)
        text_model_rows.append((m, m.id in chat_ids, m.id in pattern_ids))
    base_url = request.url_root.rstrip('/') + '/v1'
    return render_template('main/api_keys.html',
                           speech_models=speech_models,
                           text_model_rows=text_model_rows,
                           base_url=base_url,
                           text_actions=['rewrite', 'grammar', 'translate', 'summarize'])
