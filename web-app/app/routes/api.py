import os
import json
import uuid
import logging
from datetime import datetime, timezone, timedelta
from flask import Blueprint, request, jsonify, current_app, Response
from flask_login import login_required, current_user
from werkzeug.utils import secure_filename
from app import db
from app.models import Job, Meeting, Dictation, TextTask, DictionaryEntry

api_bp = Blueprint('api', __name__)
logger = logging.getLogger(__name__)

ALLOWED_AUDIO = {'mp3', 'wav', 'ogg', 'webm', 'flac', 'm4a', 'mp4', 'mpeg', 'mpga'}
ALLOWED_MIME_PREFIXES = ('audio/', 'video/')


def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_AUDIO


def allowed_mime_type(content_type):
    if not content_type:
        logger.debug("File upload missing Content-Type header; skipping MIME check")
        return True  # Allow if not provided (some clients omit it)
    mime = content_type.split(';')[0].strip().lower()
    return mime == 'application/octet-stream' or any(mime.startswith(p) for p in ALLOWED_MIME_PREFIXES)


@api_bp.route('/upload', methods=['POST'])
@login_required
def upload():
    if 'file' not in request.files:
        return jsonify({'error': 'Keine Datei ausgewählt'}), 400

    file = request.files['file']
    if file.filename == '':
        return jsonify({'error': 'Keine Datei ausgewählt'}), 400

    if not allowed_file(file.filename) or not allowed_mime_type(file.content_type):
        return jsonify({'error': 'Dateityp nicht erlaubt'}), 400

    job_type = request.form.get('job_type', 'transcription')
    speech_model_id = request.form.get('speech_model_id', type=int)
    language = request.form.get('language', '').strip() or None
    multi_speaker = request.form.get('multi_speaker') == 'true'

    filename = secure_filename(file.filename)
    unique_name = f"{uuid.uuid4().hex}_{filename}"
    upload_folder = os.path.abspath(current_app.config['UPLOAD_FOLDER'])
    filepath = os.path.abspath(os.path.join(upload_folder, unique_name))
    if os.path.commonpath([upload_folder, filepath]) != upload_folder:
        return jsonify({'error': 'Ungültiger Dateipfad'}), 400
    file.save(filepath)

    if job_type == 'meeting':
        record = Meeting(
            user_id=current_user.id, title=filename, original_filename=filename,
            file_path=filepath, speech_model_id=speech_model_id, language=language, status='pending'
        )
        db.session.add(record)
        db.session.commit()
        from app.tasks import process_meeting
        process_meeting.delay(record.id)
    else:
        record = Job(
            user_id=current_user.id, job_type='transcription', title=filename,
            original_filename=filename, file_path=filepath, speech_model_id=speech_model_id,
            language=language, multi_speaker=multi_speaker, status='pending'
        )
        db.session.add(record)
        db.session.commit()
        from app.tasks import process_transcription
        process_transcription.delay(record.id)

    return jsonify({'job_id': record.public_id, 'status': 'pending'})


@api_bp.route('/upload-audio', methods=['POST'])
@login_required
def upload_audio():
    if 'audio' not in request.files:
        return jsonify({'error': 'Keine Audiodaten'}), 400

    file = request.files['audio']
    job_type = request.form.get('job_type', 'dictation')
    speech_model_id = request.form.get('speech_model_id', type=int)
    language = request.form.get('language', '').strip() or None

    ext = 'webm'
    unique_name = f"{uuid.uuid4().hex}_recording.{ext}"
    filepath = os.path.join(current_app.config['UPLOAD_FOLDER'], unique_name)
    file.save(filepath)

    title = f"Aufnahme {datetime.now(timezone.utc).strftime('%d.%m.%Y %H:%M')}"

    if job_type == 'meeting':
        record = Meeting(
            user_id=current_user.id, title=title, original_filename=f"recording.{ext}",
            file_path=filepath, speech_model_id=speech_model_id, language=language, status='pending'
        )
        db.session.add(record)
        db.session.commit()
        from app.tasks import process_meeting
        process_meeting.delay(record.id)
    else:
        record = Dictation(
            user_id=current_user.id, title=title, original_filename=f"recording.{ext}",
            file_path=filepath, speech_model_id=speech_model_id, language=language, status='pending'
        )
        db.session.add(record)
        db.session.commit()
        from app.tasks import process_dictation
        process_dictation.delay(record.id)

    return jsonify({'job_id': record.public_id, 'status': 'pending'})


@api_bp.route('/text-task', methods=['POST'])
@login_required
def create_text_task():
    data = request.get_json()
    if not data:
        return jsonify({'error': 'Keine Daten'}), 400

    action = data.get('action')
    text = data.get('text', '').strip()
    text_model_id = data.get('text_model_id')
    target_language = data.get('target_language', '')

    if not text:
        return jsonify({'error': 'Kein Text eingegeben'}), 400
    if action not in ('rewrite', 'grammar', 'translate', 'summarize'):
        return jsonify({'error': 'Ungültige Aktion'}), 400

    try:
        text_model_id = int(text_model_id)
    except (TypeError, ValueError):
        return jsonify({'error': 'Kein Textmodell ausgewählt'}), 400

    task = TextTask(
        user_id=current_user.id,
        action=action,
        input_text=text,
        text_model_id=text_model_id,
        target_language=target_language,
        status='pending'
    )
    db.session.add(task)
    db.session.commit()

    from app.tasks import process_text_tool
    process_text_tool.delay(task.id)

    return jsonify({'id': task.public_id, 'status': 'pending'})


@api_bp.route('/text-task/<string:public_id>')
@login_required
def get_text_task(public_id):
    task = TextTask.query.filter_by(public_id=public_id, user_id=current_user.id).first()
    if not task:
        return jsonify({'error': 'Nicht gefunden'}), 404
    return jsonify(_text_task_to_dict(task))


@api_bp.route('/text-tasks')
@login_required
def get_text_tasks():
    tasks = TextTask.query.filter_by(
        user_id=current_user.id
    ).order_by(TextTask.created_at.desc()).limit(20).all()
    return jsonify([_text_task_to_dict(t) for t in tasks])


@api_bp.route('/text-task/<string:public_id>', methods=['DELETE'])
@login_required
def delete_text_task(public_id):
    task = TextTask.query.filter_by(public_id=public_id, user_id=current_user.id).first()
    if not task:
        return jsonify({'error': 'Nicht gefunden'}), 404
    db.session.delete(task)
    db.session.commit()
    return jsonify({'status': 'deleted'})


def _text_task_to_dict(t):
    ACTION_LABELS = {
        'rewrite': 'Umschreiben',
        'grammar': 'Grammatik',
        'translate': 'Übersetzen',
        'summarize': 'Zusammenfassen',
    }
    return {
        'id': t.public_id,
        'action': t.action,
        'action_label': ACTION_LABELS.get(t.action, t.action),
        'status': t.status,
        'input_text': t.input_text,
        'result_text': t.result_text,
        'error_message': t.error_message,
        'created_at': t.created_at.strftime('%d.%m.%Y %H:%M'),
    }


@api_bp.route('/summarize/<string:public_id>', methods=['POST'])
@login_required
def summarize(public_id):
    job = Job.query.filter_by(public_id=public_id, user_id=current_user.id).first()
    if not job:
        return jsonify({'error': 'Job nicht gefunden'}), 404

    data = request.get_json() or {}
    text_model_id = data.get('text_model_id')
    try:
        text_model_id = int(text_model_id)
    except (TypeError, ValueError):
        return jsonify({'error': 'Kein Textmodell ausgewählt'}), 400

    job.summary_status = 'processing'
    job.summary_text = None
    db.session.commit()

    from app.tasks import process_summary
    process_summary.delay(job.id, text_model_id)

    return jsonify({'status': 'processing'})


def _job_to_dict(j):
    segments = json.loads(j.diarized_segments) if j.diarized_segments else None
    has_speakers = bool(segments and any('speaker' in seg for seg in segments))
    return {
        'id': j.public_id,
        'title': j.title,
        'status': j.status,
        'created_at': j.created_at.strftime('%d.%m.%Y %H:%M'),
        'result_text': j.result_text,
        'diarized_segments': segments,
        'has_speakers': has_speakers,
        'summary_text': j.summary_text,
        'summary_status': j.summary_status,
        'error_message': j.error_message,
        'tool_action': j.tool_action,
        'multi_speaker': j.multi_speaker,
    }


@api_bp.route('/jobs/<string:job_type>')
@login_required
def get_jobs(job_type):
    if job_type not in ('transcription',):
        return jsonify({'error': 'Ungültiger Typ'}), 400

    cutoff = datetime.now(timezone.utc) - timedelta(days=current_user.history_days)
    jobs = Job.query.filter_by(
        user_id=current_user.id,
        job_type=job_type
    ).filter(Job.created_at >= cutoff).order_by(Job.created_at.desc()).limit(50).all()

    return jsonify([_job_to_dict(j) for j in jobs])


@api_bp.route('/job/<string:public_id>')
@login_required
def get_job(public_id):
    job = Job.query.filter_by(public_id=public_id, user_id=current_user.id).first()
    if not job:
        return jsonify({'error': 'Nicht gefunden'}), 404
    return jsonify(_job_to_dict(job))


@api_bp.route('/job/<string:public_id>/speakers', methods=['POST'])
@login_required
def update_speakers(public_id):
    job = Job.query.filter_by(public_id=public_id, user_id=current_user.id).first()
    if not job:
        return jsonify({'error': 'Nicht gefunden'}), 404
    if not job.diarized_segments:
        return jsonify({'error': 'Keine Sprechersegmente'}), 400

    data = request.get_json()
    renames = data.get('renames', {})
    if not renames:
        return jsonify({'error': 'Keine Umbenennungen'}), 400

    segments = json.loads(job.diarized_segments)
    for seg in segments:
        old_name = seg.get('speaker', '')
        if old_name in renames:
            seg['speaker'] = renames[old_name]

    job.diarized_segments = json.dumps(segments, ensure_ascii=False)

    lines = []
    for seg in segments:
        lines.append(f"[{seg['speaker']}]: {seg['text'].strip()}")
    job.result_text = '\n'.join(lines)

    db.session.commit()
    return jsonify(_job_to_dict(job))


def _download_audio_record(record):
    """Shared download logic for Job, Meeting, Dictation."""
    if record.diarized_segments:
        segments = json.loads(record.diarized_segments)
        lines = []
        for seg in segments:
            ts = f"[{_fmt_time(seg.get('start', 0))} - {_fmt_time(seg.get('end', 0))}]"
            if 'speaker' in seg:
                lines.append(f"{ts} {seg['speaker']}: {seg['text'].strip()}")
            else:
                lines.append(f"{ts} {seg['text'].strip()}")
        content = '\n'.join(lines)
    else:
        content = record.result_text or ''

    if hasattr(record, 'summary_text') and record.summary_text:
        content += '\n\n--- Zusammenfassung ---\n' + record.summary_text

    title = record.title or f'record_{record.public_id}'
    safe_title = ''.join(c for c in title if c.isalnum() or c in ' _-.')[:50]
    filename = f"{safe_title}.txt"

    return Response(
        content,
        mimetype='text/plain; charset=utf-8',
        headers={'Content-Disposition': f'attachment; filename="{filename}"'}
    )


@api_bp.route('/job/<string:public_id>/download')
@login_required
def download_job(public_id):
    job = Job.query.filter_by(public_id=public_id, user_id=current_user.id).first()
    if not job:
        return jsonify({'error': 'Nicht gefunden'}), 404
    return _download_audio_record(job)


# --- Dictionary ---

@api_bp.route('/dictionary')
@login_required
def get_dictionary():
    if not current_user.has_dictionary_access():
        return jsonify({'error': 'Kein Zugriff auf das Wörterbuch'}), 403
    entries = DictionaryEntry.query.filter_by(
        user_id=current_user.id
    ).order_by(DictionaryEntry.word).all()
    return jsonify([_dict_entry_to_dict(e) for e in entries])


@api_bp.route('/dictionary', methods=['POST'])
@login_required
def create_dictionary_entry():
    if not current_user.has_dictionary_access():
        return jsonify({'error': 'Kein Zugriff auf das Wörterbuch'}), 403
    data = request.get_json()
    if not data:
        return jsonify({'error': 'Keine Daten'}), 400

    word = (data.get('word') or '').strip()
    description = (data.get('description') or '').strip()
    if not word:
        return jsonify({'error': 'Wort ist erforderlich'}), 400

    # Check for duplicate
    existing = DictionaryEntry.query.filter_by(user_id=current_user.id, word=word).first()
    if existing:
        return jsonify({'error': 'Dieses Wort existiert bereits'}), 409

    entry = DictionaryEntry(user_id=current_user.id, word=word, description=description)
    db.session.add(entry)
    db.session.commit()
    return jsonify(_dict_entry_to_dict(entry)), 201


@api_bp.route('/dictionary/<int:entry_id>', methods=['PUT'])
@login_required
def update_dictionary_entry(entry_id):
    if not current_user.has_dictionary_access():
        return jsonify({'error': 'Kein Zugriff auf das Wörterbuch'}), 403
    entry = DictionaryEntry.query.filter_by(id=entry_id, user_id=current_user.id).first()
    if not entry:
        return jsonify({'error': 'Nicht gefunden'}), 404

    data = request.get_json()
    word = (data.get('word') or '').strip()
    if not word:
        return jsonify({'error': 'Wort ist erforderlich'}), 400

    # Check duplicate (different entry)
    existing = DictionaryEntry.query.filter(
        DictionaryEntry.user_id == current_user.id,
        DictionaryEntry.word == word,
        DictionaryEntry.id != entry_id
    ).first()
    if existing:
        return jsonify({'error': 'Dieses Wort existiert bereits'}), 409

    entry.word = word
    entry.description = (data.get('description') or '').strip()
    db.session.commit()
    return jsonify(_dict_entry_to_dict(entry))


@api_bp.route('/dictionary/<int:entry_id>', methods=['DELETE'])
@login_required
def delete_dictionary_entry(entry_id):
    if not current_user.has_dictionary_access():
        return jsonify({'error': 'Kein Zugriff auf das Wörterbuch'}), 403
    entry = DictionaryEntry.query.filter_by(id=entry_id, user_id=current_user.id).first()
    if not entry:
        return jsonify({'error': 'Nicht gefunden'}), 404
    db.session.delete(entry)
    db.session.commit()
    return jsonify({'status': 'deleted'})


def _dict_entry_to_dict(e):
    return {
        'id': e.id,
        'word': e.word,
        'description': e.description or '',
        'created_at': e.created_at.strftime('%d.%m.%Y %H:%M'),
    }


def _fmt_time(seconds):
    m = int(seconds // 60)
    s = int(seconds % 60)
    return f"{m:02d}:{s:02d}"


@api_bp.route('/job/<string:public_id>', methods=['DELETE'])
@login_required
def delete_job(public_id):
    job = Job.query.filter_by(public_id=public_id, user_id=current_user.id).first()
    if not job:
        return jsonify({'error': 'Nicht gefunden'}), 404
    if job.file_path:
        try:
            os.remove(job.file_path)
        except FileNotFoundError:
            pass
    db.session.delete(job)
    db.session.commit()
    return jsonify({'status': 'deleted'})


# --- Meetings ---

def _meeting_to_dict(m):
    segments = json.loads(m.diarized_segments) if m.diarized_segments else None
    has_speakers = bool(segments and any('speaker' in seg for seg in segments))
    return {
        'id': m.public_id,
        'title': m.title,
        'status': m.status,
        'created_at': m.created_at.strftime('%d.%m.%Y %H:%M'),
        'result_text': m.result_text,
        'diarized_segments': segments,
        'has_speakers': has_speakers,
        'summary_text': m.summary_text,
        'summary_status': m.summary_status,
        'error_message': m.error_message,
        'multi_speaker': True,
    }


@api_bp.route('/meetings')
@login_required
def get_meetings():
    cutoff = datetime.now(timezone.utc) - timedelta(days=current_user.history_days)
    meetings = Meeting.query.filter_by(
        user_id=current_user.id
    ).filter(Meeting.created_at >= cutoff).order_by(Meeting.created_at.desc()).limit(50).all()
    return jsonify([_meeting_to_dict(m) for m in meetings])


@api_bp.route('/meeting/<string:public_id>')
@login_required
def get_meeting(public_id):
    m = Meeting.query.filter_by(public_id=public_id, user_id=current_user.id).first()
    if not m:
        return jsonify({'error': 'Nicht gefunden'}), 404
    return jsonify(_meeting_to_dict(m))


@api_bp.route('/meeting/<string:public_id>', methods=['DELETE'])
@login_required
def delete_meeting(public_id):
    m = Meeting.query.filter_by(public_id=public_id, user_id=current_user.id).first()
    if not m:
        return jsonify({'error': 'Nicht gefunden'}), 404
    if m.file_path:
        try:
            os.remove(m.file_path)
        except FileNotFoundError:
            pass
    db.session.delete(m)
    db.session.commit()
    return jsonify({'status': 'deleted'})


@api_bp.route('/meeting/<string:public_id>/speakers', methods=['POST'])
@login_required
def update_meeting_speakers(public_id):
    m = Meeting.query.filter_by(public_id=public_id, user_id=current_user.id).first()
    if not m:
        return jsonify({'error': 'Nicht gefunden'}), 404
    if not m.diarized_segments:
        return jsonify({'error': 'Keine Sprechersegmente'}), 400
    data = request.get_json()
    renames = data.get('renames', {})
    if not renames:
        return jsonify({'error': 'Keine Umbenennungen'}), 400
    segments = json.loads(m.diarized_segments)
    for seg in segments:
        old_name = seg.get('speaker', '')
        if old_name in renames:
            seg['speaker'] = renames[old_name]
    m.diarized_segments = json.dumps(segments, ensure_ascii=False)
    lines = [f"[{seg['speaker']}]: {seg['text'].strip()}" for seg in segments]
    m.result_text = '\n'.join(lines)
    db.session.commit()
    return jsonify(_meeting_to_dict(m))


@api_bp.route('/meeting/<string:public_id>/download')
@login_required
def download_meeting(public_id):
    m = Meeting.query.filter_by(public_id=public_id, user_id=current_user.id).first()
    if not m:
        return jsonify({'error': 'Nicht gefunden'}), 404
    return _download_audio_record(m)


@api_bp.route('/summarize-meeting/<string:public_id>', methods=['POST'])
@login_required
def summarize_meeting(public_id):
    m = Meeting.query.filter_by(public_id=public_id, user_id=current_user.id).first()
    if not m:
        return jsonify({'error': 'Meeting nicht gefunden'}), 404
    data = request.get_json() or {}
    text_model_id = data.get('text_model_id')
    try:
        text_model_id = int(text_model_id)
    except (TypeError, ValueError):
        return jsonify({'error': 'Kein Textmodell ausgewählt'}), 400
    m.summary_status = 'processing'
    m.summary_text = None
    db.session.commit()
    from app.tasks import process_summary
    process_summary.delay(m.id, text_model_id, model_type='meeting')
    return jsonify({'status': 'processing'})


# --- Dictations ---

def _dictation_to_dict(d):
    segments = json.loads(d.diarized_segments) if d.diarized_segments else None
    return {
        'id': d.public_id,
        'title': d.title,
        'status': d.status,
        'created_at': d.created_at.strftime('%d.%m.%Y %H:%M'),
        'result_text': d.result_text,
        'diarized_segments': segments,
        'has_speakers': False,
        'error_message': d.error_message,
        'multi_speaker': False,
    }


@api_bp.route('/dictations')
@login_required
def get_dictations():
    cutoff = datetime.now(timezone.utc) - timedelta(days=current_user.history_days)
    dictations = Dictation.query.filter_by(
        user_id=current_user.id
    ).filter(Dictation.created_at >= cutoff).order_by(Dictation.created_at.desc()).limit(50).all()
    return jsonify([_dictation_to_dict(d) for d in dictations])


@api_bp.route('/dictation/<string:public_id>')
@login_required
def get_dictation(public_id):
    d = Dictation.query.filter_by(public_id=public_id, user_id=current_user.id).first()
    if not d:
        return jsonify({'error': 'Nicht gefunden'}), 404
    return jsonify(_dictation_to_dict(d))


@api_bp.route('/dictation/<string:public_id>', methods=['DELETE'])
@login_required
def delete_dictation(public_id):
    d = Dictation.query.filter_by(public_id=public_id, user_id=current_user.id).first()
    if not d:
        return jsonify({'error': 'Nicht gefunden'}), 404
    if d.file_path:
        try:
            os.remove(d.file_path)
        except FileNotFoundError:
            pass
    db.session.delete(d)
    db.session.commit()
    return jsonify({'status': 'deleted'})


@api_bp.route('/dictation/<string:public_id>/download')
@login_required
def download_dictation(public_id):
    d = Dictation.query.filter_by(public_id=public_id, user_id=current_user.id).first()
    if not d:
        return jsonify({'error': 'Nicht gefunden'}), 404
    return _download_audio_record(d)
