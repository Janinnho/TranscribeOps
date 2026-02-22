from flask import Blueprint, render_template, request, redirect, url_for, flash, abort
from flask_login import login_required, current_user
from app import db
from app.models import Job, Meeting, Dictation, DictionaryEntry

main_bp = Blueprint('main', __name__)


@main_bp.route('/')
@login_required
def index():
    return redirect(url_for('main.transcription'))


@main_bp.route('/transcription')
@login_required
def transcription():
    if not current_user.has_transcription_access():
        flash('Kein Zugriff auf Transkription.', 'danger')
        return redirect(url_for('main.settings'))
    single_models = current_user.get_available_speech_models(mode='single')
    multi_models = current_user.get_available_speech_models(mode='multi')
    text_models = current_user.get_available_text_models()
    return render_template('main/transcription.html',
                           single_models=single_models,
                           multi_models=multi_models,
                           text_models=text_models)


@main_bp.route('/meeting')
@login_required
def meeting():
    if not current_user.has_meeting_access():
        flash('Kein Zugriff auf Meeting.', 'danger')
        return redirect(url_for('main.settings'))
    speech_models = current_user.get_available_speech_models(mode='multi')
    text_models = current_user.get_available_text_models()
    return render_template('main/meeting.html',
                           speech_models=speech_models,
                           text_models=text_models)


@main_bp.route('/dictation')
@login_required
def dictation():
    if not current_user.has_dictation_access():
        flash('Kein Zugriff auf Diktieren.', 'danger')
        return redirect(url_for('main.settings'))
    speech_models = current_user.get_available_speech_models(mode='single')
    return render_template('main/dictation.html',
                           speech_models=speech_models)


@main_bp.route('/text-tools')
@login_required
def text_tools():
    if not current_user.has_text_tools_access():
        flash('Kein Zugriff auf Text Tools.', 'danger')
        return redirect(url_for('main.settings'))
    text_models = current_user.get_available_text_models()
    return render_template('main/text_tools.html',
                           text_models=text_models)


@main_bp.route('/transcription-job/<string:public_id>')
@login_required
def transcription_job_detail(public_id):
    if not current_user.has_transcription_access():
        abort(403)
    job = Job.query.filter_by(public_id=public_id, user_id=current_user.id).first()
    if not job:
        abort(404)
    text_models = current_user.get_available_text_models()
    return render_template('main/job_detail.html',
                           job=job, record_type='job',
                           text_models=text_models,
                           back_url=url_for('main.transcription'))


@main_bp.route('/meeting-job/<string:public_id>')
@login_required
def meeting_job_detail(public_id):
    if not current_user.has_meeting_access():
        abort(403)
    m = Meeting.query.filter_by(public_id=public_id, user_id=current_user.id).first()
    if not m:
        abort(404)
    text_models = current_user.get_available_text_models()
    return render_template('main/job_detail.html',
                           job=m, record_type='meeting',
                           text_models=text_models,
                           back_url=url_for('main.meeting'))


@main_bp.route('/dictation-job/<string:public_id>')
@login_required
def dictation_job_detail(public_id):
    if not current_user.has_dictation_access():
        abort(403)
    d = Dictation.query.filter_by(public_id=public_id, user_id=current_user.id).first()
    if not d:
        abort(404)
    text_models = current_user.get_available_text_models()
    return render_template('main/job_detail.html',
                           job=d, record_type='dictation',
                           text_models=text_models,
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
        flash('Kein Zugriff auf das Wörterbuch.', 'danger')
        return redirect(url_for('main.transcription'))
    return render_template('main/dictionary.html')


@main_bp.route('/settings', methods=['GET', 'POST'])
@login_required
def settings():
    if request.method == 'POST':
        theme = request.form.get('theme', 'auto')
        history_days = request.form.get('history_days', 30, type=int)
        if theme in ('light', 'dark', 'auto'):
            current_user.theme = theme
        if 1 <= history_days <= 365:
            current_user.history_days = history_days
        db.session.commit()
        flash('Einstellungen gespeichert.', 'success')
    return render_template('main/settings.html')
