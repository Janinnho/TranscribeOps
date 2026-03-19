import os
import json
import uuid
from datetime import datetime, timezone, timedelta
from flask import Blueprint, request, jsonify, current_app, Response, send_file
from flask_login import login_required, current_user
from werkzeug.utils import secure_filename
from app import db
from app.models import Job, Meeting, Dictation, TextTask, DictionaryEntry, ChatMessage, SpeechModel
from app.utils import format_dt, now_local

api_bp = Blueprint('api', __name__)

ALLOWED_AUDIO = {'mp3', 'wav', 'ogg', 'webm', 'flac', 'm4a', 'mp4', 'mpeg', 'mpga'}


def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_AUDIO


def _extract_audio_duration(filepath):
    """Extract audio duration in seconds using ffprobe. Returns float or None."""
    import subprocess
    try:
        result = subprocess.run(
            ['ffprobe', '-v', 'error', '-show_entries', 'format=duration',
             '-of', 'default=noprint_wrappers=1:nokey=1', filepath],
            capture_output=True, text=True, timeout=30
        )
        return float(result.stdout.strip()) if result.stdout.strip() else None
    except Exception:
        return None


def _estimate_total_processing_secs(record):
    """Estimate total processing time for a record based on model speed."""
    if not record.audio_duration_secs:
        return None
    speech_model = record.speech_model
    if not speech_model or not speech_model.processing_speed:
        return None
    return record.audio_duration_secs * speech_model.processing_speed / 60.0


def _remaining_secs_for_processing(record):
    """Calculate remaining seconds for a currently-processing record."""
    total_estimate = _estimate_total_processing_secs(record)
    if total_estimate is None:
        return None
    started = record.processing_started_at
    if started:
        if started.tzinfo is None:
            started = started.replace(tzinfo=timezone.utc)
        elapsed = (datetime.now(timezone.utc) - started).total_seconds()
        return max(0, total_estimate - elapsed)
    return total_estimate


def _compute_eta_seconds(record):
    """Compute estimated remaining seconds for a processing record."""
    total_estimate = _estimate_total_processing_secs(record)
    if total_estimate is None:
        return None

    if record.status == 'pending':
        queue_extra = _queue_wait_seconds(record)
        return round(total_estimate + queue_extra)

    if record.status == 'processing':
        remaining = _remaining_secs_for_processing(record)
        return round(remaining) if remaining is not None else None

    return None


def _queue_wait_seconds(pending_record):
    """Estimate how long a pending record must wait for currently processing jobs on the same model."""
    if not pending_record.speech_model_id:
        return 0
    extra = 0
    for model_cls in (Job, Meeting, Dictation):
        processing = model_cls.query.filter_by(
            speech_model_id=pending_record.speech_model_id,
            status='processing'
        ).all()
        for r in processing:
            remaining = _remaining_secs_for_processing(r)
            if remaining is not None:
                extra += remaining
    return extra


def _eta_fields(record):
    """Return dict with ETA-related fields for API responses."""
    started = record.processing_started_at
    if started and started.tzinfo is None:
        started = started.replace(tzinfo=timezone.utc)
    total = _estimate_total_processing_secs(record)
    return {
        'eta_seconds': _compute_eta_seconds(record),
        'audio_duration_secs': record.audio_duration_secs,
        'processing_started_at': started.isoformat() if started else None,
        'estimated_total_secs': round(total) if total is not None else None,
    }


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

    # Check group upload size limit
    max_upload_mb = current_user.get_max_upload_size_mb()
    if max_upload_mb > 0:
        file.seek(0, 2)
        file_size = file.tell()
        file.seek(0)
        if file_size > max_upload_mb * 1024 * 1024:
            return jsonify({'error': f'Datei zu groß. Maximale Upload-Größe: {max_upload_mb} MB'}), 413

    job_type = request.form.get('job_type', 'transcription')
    speech_model_id = request.form.get('speech_model_id', type=int)
    language = request.form.get('language', '').strip() or None
    multi_speaker = request.form.get('multi_speaker') == 'true'
    save_audio = request.form.get('save_audio') == '1'

    # Check speech model upload limits
    if speech_model_id:
        speech_model = db.session.get(SpeechModel, speech_model_id)
        if speech_model:
            # File size limit
            if speech_model.max_upload_size_mb and speech_model.max_upload_size_mb > 0:
                file.seek(0, 2)
                file_size = file.tell()
                file.seek(0)
                if file_size > speech_model.max_upload_size_mb * 1024 * 1024:
                    return jsonify({'error': f'Datei zu groß für dieses Modell. Maximum: {speech_model.max_upload_size_mb} MB'}), 413
            # Duration limit
            if speech_model.max_upload_duration_secs and speech_model.max_upload_duration_secs > 0:
                import subprocess
                filename_tmp = secure_filename(file.filename)
                tmp_name = f"{uuid.uuid4().hex}_{filename_tmp}"
                tmp_path = os.path.join(current_app.config['UPLOAD_FOLDER'], tmp_name)
                file.save(tmp_path)
                try:
                    result = subprocess.run(
                        ['ffprobe', '-v', 'error', '-show_entries', 'format=duration',
                         '-of', 'default=noprint_wrappers=1:nokey=1', tmp_path],
                        capture_output=True, text=True, timeout=30
                    )
                    duration = float(result.stdout.strip()) if result.stdout.strip() else 0
                    if duration > speech_model.max_upload_duration_secs:
                        os.remove(tmp_path)
                        mins = int(speech_model.max_upload_duration_secs // 60)
                        return jsonify({'error': f'Audio zu lang für dieses Modell. Maximum: {mins} Minuten ({speech_model.max_upload_duration_secs}s), Datei: {int(duration)}s'}), 413
                except Exception:
                    pass
                # File already saved, reuse it
                filepath = tmp_path
                filename = filename_tmp
                unique_name = tmp_name
                file_already_saved = True

    if not locals().get('file_already_saved'):
        filename = secure_filename(file.filename)
        unique_name = f"{uuid.uuid4().hex}_{filename}"
        filepath = os.path.join(current_app.config['UPLOAD_FOLDER'], unique_name)
        file.save(filepath)

    # Extract audio duration (reuse from validation if available)
    audio_duration = locals().get('duration') or _extract_audio_duration(filepath)

    if job_type == 'meeting':
        record = Meeting(
            user_id=current_user.id, title=filename, original_filename=filename,
            file_path=filepath, speech_model_id=speech_model_id, language=language,
            audio_saved=save_audio, audio_duration_secs=audio_duration, status='pending'
        )
        db.session.add(record)
        db.session.commit()
        from app.tasks import process_meeting
        process_meeting.delay(record.id)
    else:
        record = Job(
            user_id=current_user.id, job_type='transcription', title=filename,
            original_filename=filename, file_path=filepath, speech_model_id=speech_model_id,
            language=language, multi_speaker=multi_speaker, audio_saved=save_audio,
            audio_duration_secs=audio_duration, status='pending'
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

    # Check group upload size limit
    max_upload_mb = current_user.get_max_upload_size_mb()
    if max_upload_mb > 0:
        file.seek(0, 2)
        file_size = file.tell()
        file.seek(0)
        if file_size > max_upload_mb * 1024 * 1024:
            return jsonify({'error': f'Datei zu groß. Maximale Upload-Größe: {max_upload_mb} MB'}), 413

    job_type = request.form.get('job_type', 'dictation')
    speech_model_id = request.form.get('speech_model_id', type=int)
    language = request.form.get('language', '').strip() or None
    save_audio = request.form.get('save_audio') == '1'

    ext = 'webm'
    unique_name = f"{uuid.uuid4().hex}_recording.{ext}"
    filepath = os.path.join(current_app.config['UPLOAD_FOLDER'], unique_name)
    file.save(filepath)

    audio_duration = _extract_audio_duration(filepath)
    title = f"Aufnahme {now_local().strftime('%d.%m.%Y %H:%M')}"

    if job_type == 'meeting':
        record = Meeting(
            user_id=current_user.id, title=title, original_filename=f"recording.{ext}",
            file_path=filepath, speech_model_id=speech_model_id, language=language,
            audio_saved=save_audio, audio_duration_secs=audio_duration, status='pending'
        )
        db.session.add(record)
        db.session.commit()
        from app.tasks import process_meeting
        process_meeting.delay(record.id)
    else:
        record = Dictation(
            user_id=current_user.id, title=title, original_filename=f"recording.{ext}",
            file_path=filepath, speech_model_id=speech_model_id, language=language,
            audio_saved=save_audio, audio_duration_secs=audio_duration, status='pending'
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
        'error_message': _sanitize_error(t.error_message),
        'created_at': format_dt(t.created_at),
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


def _sanitize_error(msg):
    """Hide technical error details — real errors only visible in admin job list."""
    if not msg:
        return msg
    return 'Ein Fehler ist aufgetreten, bitte kontaktieren Sie den Administrator.'


def _job_to_dict(j):
    segments = json.loads(j.diarized_segments) if j.diarized_segments else None
    has_speakers = bool(segments and any('speaker' in seg for seg in segments))
    # In single-speaker mode, suppress speaker display even if diarize model returned speakers
    if not j.multi_speaker:
        has_speakers = False
    return {
        'id': j.public_id,
        'title': j.title,
        'status': j.status,
        'progress': j.progress or 0,
        'created_at': format_dt(j.created_at),
        'result_text': j.result_text,
        'diarized_segments': segments,
        'has_speakers': has_speakers,
        'summary_text': j.summary_text,
        'summary_status': j.summary_status,
        'title_status': j.title_status,
        'speaker_identify_status': j.speaker_identify_status,
        'error_message': _sanitize_error(j.error_message),
        'tool_action': j.tool_action,
        'multi_speaker': j.multi_speaker,
        'audio_available': bool(j.file_path and j.audio_saved and os.path.exists(j.file_path)),
        **_eta_fields(j),
    }


@api_bp.route('/jobs/<string:job_type>')
@login_required
def get_jobs(job_type):
    if job_type not in ('transcription',):
        return jsonify({'error': 'Ungültiger Typ'}), 400

    history = current_user.get_effective_history_days()
    q = Job.query.filter_by(user_id=current_user.id, job_type=job_type)
    if history > 0:
        q = q.filter(Job.created_at >= datetime.now(timezone.utc) - timedelta(days=history))
    jobs = q.order_by(Job.created_at.desc()).limit(50).all()

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

    # Cancel auto-speaker identification if running
    if job.speaker_identify_status == 'processing':
        job.speaker_identify_status = 'cancelled'

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
        'created_at': format_dt(e.created_at),
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
    if job.file_path and os.path.exists(job.file_path):
        os.remove(job.file_path)
    ChatMessage.query.filter_by(record_type='job', record_id=job.id).delete()
    db.session.delete(job)
    db.session.commit()
    return jsonify({'status': 'deleted'})


def _update_segment_text(record, segment_index, new_text, has_speakers):
    """Update a single segment's text and regenerate result_text."""
    if not record.diarized_segments:
        return {'error': 'Keine Segmente vorhanden'}, 400
    segments = json.loads(record.diarized_segments)
    if not isinstance(segment_index, int) or segment_index < 0 or segment_index >= len(segments):
        return {'error': 'Ungültiger Segmentindex'}, 400
    if not new_text or not new_text.strip():
        return {'error': 'Text darf nicht leer sein'}, 400
    segments[segment_index]['text'] = ' ' + new_text.strip()
    record.diarized_segments = json.dumps(segments, ensure_ascii=False)
    # Regenerate result_text from segments
    lines = []
    for seg in segments:
        if has_speakers and 'speaker' in seg:
            lines.append(f"[{seg['speaker']}]: {seg['text'].strip()}")
        else:
            lines.append(seg['text'].strip())
    record.result_text = '\n'.join(lines)
    db.session.commit()
    return None, None


@api_bp.route('/job/<string:public_id>/title', methods=['PATCH'])
@login_required
def update_job_title(public_id):
    job = Job.query.filter_by(public_id=public_id, user_id=current_user.id).first()
    if not job:
        return jsonify({'error': 'Nicht gefunden'}), 404
    data = request.get_json() or {}
    title = (data.get('title') or '').strip()
    if not title:
        return jsonify({'error': 'Titel darf nicht leer sein'}), 400
    job.title = title[:255]
    # Cancel auto-title if running
    if job.title_status == 'processing':
        job.title_status = 'cancelled'
    db.session.commit()
    return jsonify({'status': 'ok', 'title': job.title})


@api_bp.route('/job/<string:public_id>/segment', methods=['PATCH'])
@login_required
def update_job_segment(public_id):
    job = Job.query.filter_by(public_id=public_id, user_id=current_user.id).first()
    if not job:
        return jsonify({'error': 'Nicht gefunden'}), 404
    data = request.get_json() or {}
    try:
        segment_index = int(data.get('segment_index'))
    except (TypeError, ValueError):
        return jsonify({'error': 'Ungültiger Segmentindex'}), 400
    new_text = (data.get('text') or '').strip()
    err, code = _update_segment_text(job, segment_index, new_text, job.multi_speaker)
    if err:
        return jsonify(err), code
    return jsonify(_job_to_dict(job))


# --- Meetings ---

def _meeting_to_dict(m):
    segments = json.loads(m.diarized_segments) if m.diarized_segments else None
    has_speakers = bool(segments and any('speaker' in seg for seg in segments))
    return {
        'id': m.public_id,
        'title': m.title,
        'status': m.status,
        'progress': m.progress or 0,
        'created_at': format_dt(m.created_at),
        'result_text': m.result_text,
        'diarized_segments': segments,
        'has_speakers': has_speakers,
        'summary_text': m.summary_text,
        'summary_status': m.summary_status,
        'title_status': m.title_status,
        'speaker_identify_status': m.speaker_identify_status,
        'error_message': _sanitize_error(m.error_message),
        'multi_speaker': True,
        'audio_available': bool(m.file_path and m.audio_saved and os.path.exists(m.file_path)),
        **_eta_fields(m),
    }


@api_bp.route('/meetings')
@login_required
def get_meetings():
    history = current_user.get_effective_history_days()
    q = Meeting.query.filter_by(user_id=current_user.id)
    if history > 0:
        q = q.filter(Meeting.created_at >= datetime.now(timezone.utc) - timedelta(days=history))
    meetings = q.order_by(Meeting.created_at.desc()).limit(50).all()
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
    if m.file_path and os.path.exists(m.file_path):
        os.remove(m.file_path)
    ChatMessage.query.filter_by(record_type='meeting', record_id=m.id).delete()
    db.session.delete(m)
    db.session.commit()
    return jsonify({'status': 'deleted'})


@api_bp.route('/meeting/<string:public_id>/title', methods=['PATCH'])
@login_required
def update_meeting_title(public_id):
    m = Meeting.query.filter_by(public_id=public_id, user_id=current_user.id).first()
    if not m:
        return jsonify({'error': 'Nicht gefunden'}), 404
    data = request.get_json() or {}
    title = (data.get('title') or '').strip()
    if not title:
        return jsonify({'error': 'Titel darf nicht leer sein'}), 400
    m.title = title[:255]
    # Cancel auto-title if running
    if m.title_status == 'processing':
        m.title_status = 'cancelled'
    db.session.commit()
    return jsonify({'status': 'ok', 'title': m.title})


@api_bp.route('/meeting/<string:public_id>/segment', methods=['PATCH'])
@login_required
def update_meeting_segment(public_id):
    m = Meeting.query.filter_by(public_id=public_id, user_id=current_user.id).first()
    if not m:
        return jsonify({'error': 'Nicht gefunden'}), 404
    data = request.get_json() or {}
    try:
        segment_index = int(data.get('segment_index'))
    except (TypeError, ValueError):
        return jsonify({'error': 'Ungültiger Segmentindex'}), 400
    new_text = (data.get('text') or '').strip()
    err, code = _update_segment_text(m, segment_index, new_text, True)
    if err:
        return jsonify(err), code
    return jsonify(_meeting_to_dict(m))


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

    # Cancel auto-speaker identification if running
    if m.speaker_identify_status == 'processing':
        m.speaker_identify_status = 'cancelled'

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
        'progress': d.progress or 0,
        'created_at': format_dt(d.created_at),
        'result_text': d.result_text,
        'diarized_segments': segments,
        'has_speakers': False,
        'error_message': _sanitize_error(d.error_message),
        'multi_speaker': False,
        'audio_available': bool(d.file_path and d.audio_saved and os.path.exists(d.file_path)),
        **_eta_fields(d),
    }


@api_bp.route('/dictations')
@login_required
def get_dictations():
    history = current_user.get_effective_history_days()
    q = Dictation.query.filter_by(user_id=current_user.id)
    if history > 0:
        q = q.filter(Dictation.created_at >= datetime.now(timezone.utc) - timedelta(days=history))
    dictations = q.order_by(Dictation.created_at.desc()).limit(50).all()
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
    if d.file_path and os.path.exists(d.file_path):
        os.remove(d.file_path)
    db.session.delete(d)
    db.session.commit()
    return jsonify({'status': 'deleted'})


@api_bp.route('/dictation/<string:public_id>/title', methods=['PATCH'])
@login_required
def update_dictation_title(public_id):
    d = Dictation.query.filter_by(public_id=public_id, user_id=current_user.id).first()
    if not d:
        return jsonify({'error': 'Nicht gefunden'}), 404
    data = request.get_json() or {}
    title = (data.get('title') or '').strip()
    if not title:
        return jsonify({'error': 'Titel darf nicht leer sein'}), 400
    d.title = title[:255]
    db.session.commit()
    return jsonify({'status': 'ok', 'title': d.title})


@api_bp.route('/dictation/<string:public_id>/segment', methods=['PATCH'])
@login_required
def update_dictation_segment(public_id):
    d = Dictation.query.filter_by(public_id=public_id, user_id=current_user.id).first()
    if not d:
        return jsonify({'error': 'Nicht gefunden'}), 404
    data = request.get_json() or {}
    try:
        segment_index = int(data.get('segment_index'))
    except (TypeError, ValueError):
        return jsonify({'error': 'Ungültiger Segmentindex'}), 400
    new_text = (data.get('text') or '').strip()
    err, code = _update_segment_text(d, segment_index, new_text, False)
    if err:
        return jsonify(err), code
    return jsonify(_dictation_to_dict(d))


@api_bp.route('/dictation/<string:public_id>/download')
@login_required
def download_dictation(public_id):
    d = Dictation.query.filter_by(public_id=public_id, user_id=current_user.id).first()
    if not d:
        return jsonify({'error': 'Nicht gefunden'}), 404
    return _download_audio_record(d)


# ── Audio Streaming Endpoints ─────────────────────────────────────────

def _serve_audio(record, download=False):
    """Serve an audio file with HTTP Range support for seeking."""
    if not record.file_path or not record.audio_saved or not os.path.exists(record.file_path):
        return jsonify({'error': 'Keine Audiodatei verfügbar'}), 404
    as_attachment = download or request.args.get('download') == '1'
    return send_file(
        record.file_path,
        conditional=True,
        as_attachment=as_attachment,
        download_name=os.path.basename(record.file_path)
    )


@api_bp.route('/job/<string:public_id>/audio')
@login_required
def stream_job_audio(public_id):
    job = Job.query.filter_by(public_id=public_id, user_id=current_user.id).first()
    if not job:
        return jsonify({'error': 'Nicht gefunden'}), 404
    return _serve_audio(job)


@api_bp.route('/meeting/<string:public_id>/audio')
@login_required
def stream_meeting_audio(public_id):
    m = Meeting.query.filter_by(public_id=public_id, user_id=current_user.id).first()
    if not m:
        return jsonify({'error': 'Nicht gefunden'}), 404
    return _serve_audio(m)


@api_bp.route('/dictation/<string:public_id>/audio')
@login_required
def stream_dictation_audio(public_id):
    d = Dictation.query.filter_by(public_id=public_id, user_id=current_user.id).first()
    if not d:
        return jsonify({'error': 'Nicht gefunden'}), 404
    return _serve_audio(d)


# ── KI Chat Endpoints ────────────────────────────────────────────────

def _resolve_chat_record(record_type, public_id):
    """Resolve record_type + public_id to the actual record and its integer ID."""
    if record_type == 'job':
        record = Job.query.filter_by(public_id=public_id, user_id=current_user.id).first()
    elif record_type == 'meeting':
        record = Meeting.query.filter_by(public_id=public_id, user_id=current_user.id).first()
    else:
        return None, None
    return (record, record.id) if record else (None, None)


def _chat_msg_to_dict(m):
    return {
        'id': m.public_id,
        'role': m.role,
        'content': m.content,
        'status': m.status,
        'created_at': format_dt(m.created_at),
    }


@api_bp.route('/chat/<string:record_type>/<string:public_id>')
@login_required
def get_chat_messages(record_type, public_id):
    """Return all chat messages for a record."""
    record, record_id = _resolve_chat_record(record_type, public_id)
    if not record:
        return jsonify({'error': 'Nicht gefunden'}), 404

    messages = ChatMessage.query.filter_by(
        record_type=record_type, record_id=record_id, user_id=current_user.id
    ).order_by(ChatMessage.created_at).all()

    return jsonify({
        'messages': [_chat_msg_to_dict(m) for m in messages],
        'has_pending': any(m.status == 'processing' for m in messages)
    })


@api_bp.route('/chat/<string:record_type>/<string:public_id>', methods=['POST'])
@login_required
def send_chat_message(record_type, public_id):
    """Send a user message and queue an AI response."""
    record, record_id = _resolve_chat_record(record_type, public_id)
    if not record:
        return jsonify({'error': 'Nicht gefunden'}), 404

    data = request.get_json() or {}
    content = (data.get('content') or '').strip()
    text_model_id = data.get('text_model_id')

    if not content:
        return jsonify({'error': 'Nachricht darf nicht leer sein'}), 400
    try:
        text_model_id = int(text_model_id)
    except (TypeError, ValueError):
        return jsonify({'error': 'Kein Textmodell ausgewählt'}), 400

    # Save user message
    user_msg = ChatMessage(
        record_type=record_type, record_id=record_id,
        user_id=current_user.id, role='user',
        content=content, status='completed'
    )
    db.session.add(user_msg)
    db.session.flush()

    # Create placeholder assistant message
    assistant_msg = ChatMessage(
        record_type=record_type, record_id=record_id,
        user_id=current_user.id, role='assistant',
        content='', status='processing',
        text_model_id=text_model_id
    )
    db.session.add(assistant_msg)
    db.session.commit()

    # Queue Celery task
    from app.tasks import process_chat_message
    process_chat_message.delay(assistant_msg.id, text_model_id)

    return jsonify({
        'user_message': _chat_msg_to_dict(user_msg),
        'assistant_message': _chat_msg_to_dict(assistant_msg)
    })


@api_bp.route('/chat/<string:record_type>/<string:public_id>', methods=['DELETE'])
@login_required
def clear_chat(record_type, public_id):
    """Delete all chat messages for a record."""
    record, record_id = _resolve_chat_record(record_type, public_id)
    if not record:
        return jsonify({'error': 'Nicht gefunden'}), 404

    ChatMessage.query.filter_by(
        record_type=record_type, record_id=record_id, user_id=current_user.id
    ).delete()
    db.session.commit()
    return jsonify({'status': 'cleared'})
