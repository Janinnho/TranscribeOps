import os
import json
import uuid
from datetime import datetime, timezone, timedelta
from flask import Blueprint, request, jsonify, current_app, Response
from flask_login import login_required, current_user
from werkzeug.utils import secure_filename
from app import db
from app.models import Job

api_bp = Blueprint('api', __name__)

ALLOWED_AUDIO = {'mp3', 'wav', 'ogg', 'webm', 'flac', 'm4a', 'mp4', 'mpeg', 'mpga'}


def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_AUDIO


@api_bp.route('/upload', methods=['POST'])
@login_required
def upload():
    if 'file' not in request.files:
        return jsonify({'error': 'Keine Datei ausgewählt'}), 400

    file = request.files['file']
    if file.filename == '':
        return jsonify({'error': 'Keine Datei ausgewählt'}), 400

    if not allowed_file(file.filename):
        return jsonify({'error': 'Dateityp nicht erlaubt'}), 400

    job_type = request.form.get('job_type', 'transcription')
    speech_model_id = request.form.get('speech_model_id', type=int)
    language = request.form.get('language', '').strip() or None
    multi_speaker = request.form.get('multi_speaker') == 'true'

    filename = secure_filename(file.filename)
    unique_name = f"{uuid.uuid4().hex}_{filename}"
    filepath = os.path.join(current_app.config['UPLOAD_FOLDER'], unique_name)
    file.save(filepath)

    job = Job(
        user_id=current_user.id,
        job_type=job_type,
        title=filename,
        original_filename=filename,
        file_path=filepath,
        speech_model_id=speech_model_id,
        language=language,
        multi_speaker=multi_speaker,
        status='pending'
    )
    db.session.add(job)
    db.session.commit()

    from app.tasks import process_transcription
    process_transcription.delay(job.id)

    return jsonify({'job_id': job.public_id, 'status': 'pending'})


@api_bp.route('/upload-audio', methods=['POST'])
@login_required
def upload_audio():
    if 'audio' not in request.files:
        return jsonify({'error': 'Keine Audiodaten'}), 400

    file = request.files['audio']
    job_type = request.form.get('job_type', 'dictation')
    speech_model_id = request.form.get('speech_model_id', type=int)
    language = request.form.get('language', '').strip() or None
    multi_speaker = request.form.get('multi_speaker') == 'true'

    ext = 'webm'
    unique_name = f"{uuid.uuid4().hex}_recording.{ext}"
    filepath = os.path.join(current_app.config['UPLOAD_FOLDER'], unique_name)
    file.save(filepath)

    title = f"Aufnahme {datetime.now(timezone.utc).strftime('%d.%m.%Y %H:%M')}"
    job = Job(
        user_id=current_user.id,
        job_type=job_type,
        title=title,
        original_filename=f"recording.{ext}",
        file_path=filepath,
        speech_model_id=speech_model_id,
        language=language,
        multi_speaker=multi_speaker,
        status='pending'
    )
    db.session.add(job)
    db.session.commit()

    from app.tasks import process_transcription
    process_transcription.delay(job.id)

    return jsonify({'job_id': job.public_id, 'status': 'pending'})


@api_bp.route('/text-tool', methods=['POST'])
@login_required
def text_tool():
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

    job = Job(
        user_id=current_user.id,
        job_type='text_tool',
        title=f"Text Tool: {action}",
        tool_action=action,
        input_text=text,
        text_model_id=text_model_id,
        target_language=target_language,
        status='pending'
    )
    db.session.add(job)
    db.session.commit()

    from app.tasks import process_text_tool
    process_text_tool.delay(job.id)

    return jsonify({'job_id': job.public_id, 'status': 'pending'})


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
    return {
        'id': j.public_id,
        'title': j.title,
        'status': j.status,
        'created_at': j.created_at.strftime('%d.%m.%Y %H:%M'),
        'result_text': j.result_text,
        'diarized_segments': json.loads(j.diarized_segments) if j.diarized_segments else None,
        'summary_text': j.summary_text,
        'summary_status': j.summary_status,
        'error_message': j.error_message,
        'tool_action': j.tool_action,
        'multi_speaker': j.multi_speaker,
    }


@api_bp.route('/jobs/<string:job_type>')
@login_required
def get_jobs(job_type):
    if job_type not in ('transcription', 'meeting', 'dictation', 'text_tool'):
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


@api_bp.route('/job/<string:public_id>/download')
@login_required
def download_job(public_id):
    job = Job.query.filter_by(public_id=public_id, user_id=current_user.id).first()
    if not job:
        return jsonify({'error': 'Nicht gefunden'}), 404

    if job.diarized_segments:
        segments = json.loads(job.diarized_segments)
        lines = []
        for seg in segments:
            ts = f"[{_fmt_time(seg.get('start', 0))} - {_fmt_time(seg.get('end', 0))}]"
            lines.append(f"{ts} {seg['speaker']}: {seg['text'].strip()}")
        content = '\n'.join(lines)
    else:
        content = job.result_text or ''

    if job.summary_text:
        content += '\n\n--- Zusammenfassung ---\n' + job.summary_text

    title = job.title or f'job_{job.public_id}'
    safe_title = ''.join(c for c in title if c.isalnum() or c in ' _-.')[:50]
    filename = f"{safe_title}.txt"

    return Response(
        content,
        mimetype='text/plain; charset=utf-8',
        headers={'Content-Disposition': f'attachment; filename="{filename}"'}
    )


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
    if job.file_path and os.path.exists(job.file_path):
        os.remove(job.file_path)
    db.session.delete(job)
    db.session.commit()
    return jsonify({'status': 'deleted'})
