import os
import uuid
from flask import Blueprint, render_template, request, jsonify, current_app
from flask_login import login_required, current_user
from werkzeug.utils import secure_filename
from app import db
from app.models import Job, User

main_bp = Blueprint('main', __name__)

ALLOWED_AUDIO = {'mp3', 'wav', 'ogg', 'webm', 'flac', 'm4a', 'mp4', 'mpeg', 'mpga'}


def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_AUDIO


@main_bp.route('/')
@login_required
def index():
    return redirect(url_for('main.transcription'))


@main_bp.route('/transcription')
@login_required
def transcription():
    speech_models = current_user.get_available_speech_models()
    text_models = current_user.get_available_text_models()
    return render_template('main/transcription.html',
                           speech_models=speech_models,
                           text_models=text_models)


@main_bp.route('/meeting')
@login_required
def meeting():
    speech_models = current_user.get_available_speech_models()
    text_models = current_user.get_available_text_models()
    return render_template('main/meeting.html',
                           speech_models=speech_models,
                           text_models=text_models)


@main_bp.route('/dictation')
@login_required
def dictation():
    speech_models = current_user.get_available_speech_models()
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
        from flask import flash
        flash('Einstellungen gespeichert.', 'success')
    return render_template('main/settings.html')


# Need this import at the top level for url_for in index()
from flask import redirect, url_for
