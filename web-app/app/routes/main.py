from flask import Blueprint, render_template, request, redirect, url_for, flash
from flask_login import login_required, current_user
from app import db

main_bp = Blueprint('main', __name__)


@main_bp.route('/')
@login_required
def index():
    return redirect(url_for('main.transcription'))


@main_bp.route('/transcription')
@login_required
def transcription():
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
    speech_models = current_user.get_available_speech_models(mode='multi')
    text_models = current_user.get_available_text_models()
    return render_template('main/meeting.html',
                           speech_models=speech_models,
                           text_models=text_models)


@main_bp.route('/dictation')
@login_required
def dictation():
    speech_models = current_user.get_available_speech_models(mode='single')
    return render_template('main/dictation.html',
                           speech_models=speech_models)


@main_bp.route('/text-tools')
@login_required
def text_tools():
    text_models = current_user.get_available_text_models()
    return render_template('main/text_tools.html',
                           text_models=text_models)


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
