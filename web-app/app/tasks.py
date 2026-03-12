import os
import shutil
import subprocess
import json
import time
import requests
from datetime import datetime, timezone
from app.celery_app import celery


def get_app():
    from app import create_app
    return create_app()


def _is_diarize_model(model):
    return model.supports_diarize


def _convert_to_mp3(src_path):
    """Convert any audio file to MP3 using ffmpeg. Returns the MP3 path."""
    mp3_path = os.path.splitext(src_path)[0] + '.mp3'
    if src_path.lower().endswith('.mp3'):
        return src_path  # already MP3
    try:
        subprocess.run(
            ['ffmpeg', '-i', src_path, '-codec:a', 'libmp3lame', '-q:a', '4', '-y', mp3_path],
            check=True, capture_output=True, timeout=600
        )
        # Remove original file after successful conversion
        if os.path.exists(mp3_path) and mp3_path != src_path:
            os.remove(src_path)
        return mp3_path
    except Exception:
        # If conversion fails, keep original
        return src_path


def _persist_audio_file(record, app):
    """Before transcription: convert to MP3 and copy to permanent storage.
    The original file in uploads stays untouched for the transcription API."""
    from app import db

    if not record.audio_saved or not record.file_path:
        return

    src_path = record.file_path
    storage_path = app.config.get('AUDIO_STORAGE_PATH', app.config['UPLOAD_FOLDER'])

    # Convert to MP3 into storage dir
    base_name = os.path.splitext(os.path.basename(src_path))[0] + '.mp3'
    dest_path = os.path.join(storage_path, base_name)

    if src_path.lower().endswith('.mp3'):
        # Already MP3 — just copy
        shutil.copy2(src_path, dest_path)
    else:
        try:
            subprocess.run(
                ['ffmpeg', '-i', src_path, '-codec:a', 'libmp3lame', '-q:a', '4', '-y', dest_path],
                check=True, capture_output=True, timeout=600
            )
        except Exception:
            # Fallback: copy original
            shutil.copy2(src_path, dest_path)

    record.file_path = dest_path
    db.session.commit()


def _cleanup_temp_file(record, temp_path):
    """After transcription: delete the original upload file.
    If audio was not saved, also clear file_path on the record."""
    from app import db

    if temp_path and os.path.exists(temp_path):
        try:
            os.remove(temp_path)
        except OSError:
            pass

    if not record.audio_saved:
        record.file_path = None
        db.session.commit()


def _run_speech_processing(record, multi_speaker=False, audio_path=None):
    """Shared audio processing logic for Job, Meeting, and Dictation.
    audio_path overrides record.file_path (used when original temp file differs from stored path)."""
    from app import db

    file_path = audio_path or record.file_path

    def progress_callback(percent):
        try:
            record.progress = min(int(percent), 100)
            db.session.commit()
        except Exception:
            db.session.rollback()

    try:
        speech_model = record.speech_model
        if not speech_model:
            raise Exception('Kein Sprachmodell konfiguriert')

        record.progress = 0
        db.session.commit()

        dictionary_prompt = _get_dictionary_prompt(record.user_id)

        result = _call_speech_api(speech_model, file_path, record.language,
                                  multi_speaker, original_filename=record.original_filename,
                                  dictionary_prompt=dictionary_prompt,
                                  progress_callback=progress_callback)

        if isinstance(result, dict) and 'segments' in result:
            record.result_text = result.get('text', '')
            record.diarized_segments = json.dumps(result['segments'], ensure_ascii=False)
        else:
            record.result_text = result if isinstance(result, str) else result.get('text', str(result))

        record.status = 'completed'
        record.progress = 100
        record.completed_at = datetime.now(timezone.utc)
    except Exception as e:
        db.session.rollback()
        record.status = 'failed'
        record.error_message = str(e)

    try:
        db.session.commit()
    except Exception:
        db.session.rollback()


@celery.task(bind=True)
def process_transcription(self, job_id):
    app = get_app()
    with app.app_context():
        from app import db
        from app.models import Job, User

        job = db.session.get(Job, job_id)
        if not job:
            return {'error': 'Job not found'}

        job.status = 'processing'
        job.celery_task_id = self.request.id
        db.session.commit()

        temp_path = job.file_path
        _persist_audio_file(job, app)
        _run_speech_processing(job, multi_speaker=job.multi_speaker, audio_path=temp_path)
        _cleanup_temp_file(job, temp_path)

        if job.status == 'completed':
            _trigger_auto_tasks(job.user_id, job.id, 'job')

        return {'status': job.status, 'job_id': job_id}


@celery.task(bind=True)
def process_meeting(self, meeting_id):
    app = get_app()
    with app.app_context():
        from app import db
        from app.models import Meeting, User

        meeting = db.session.get(Meeting, meeting_id)
        if not meeting:
            return {'error': 'Meeting not found'}

        meeting.status = 'processing'
        meeting.celery_task_id = self.request.id
        db.session.commit()

        temp_path = meeting.file_path
        _persist_audio_file(meeting, app)
        _run_speech_processing(meeting, multi_speaker=True, audio_path=temp_path)
        _cleanup_temp_file(meeting, temp_path)

        if meeting.status == 'completed':
            _trigger_auto_tasks(meeting.user_id, meeting.id, 'meeting')

        return {'status': meeting.status, 'meeting_id': meeting_id}


@celery.task(bind=True)
def process_dictation(self, dictation_id):
    app = get_app()
    with app.app_context():
        from app import db
        from app.models import Dictation, User

        dictation = db.session.get(Dictation, dictation_id)
        if not dictation:
            return {'error': 'Dictation not found'}

        dictation.status = 'processing'
        dictation.celery_task_id = self.request.id
        db.session.commit()

        temp_path = dictation.file_path
        _persist_audio_file(dictation, app)
        _run_speech_processing(dictation, multi_speaker=False, audio_path=temp_path)
        _cleanup_temp_file(dictation, temp_path)

        return {'status': dictation.status, 'dictation_id': dictation_id}


@celery.task(bind=True)
def process_text_tool(self, task_id):
    app = get_app()
    with app.app_context():
        from app import db
        from app.models import TextTask

        task = db.session.get(TextTask, task_id)
        if not task:
            return {'error': 'Task not found'}

        task.status = 'processing'
        db.session.commit()

        try:
            text_model = task.text_model
            if not text_model:
                raise Exception('Kein Textmodell konfiguriert')

            prompt = _build_text_prompt(task.action, task.input_text, task.target_language)
            result = _call_text_api(text_model, prompt)
            task.result_text = result
            task.status = 'completed'
            task.completed_at = datetime.now(timezone.utc)
        except Exception as e:
            task.status = 'failed'
            task.error_message = str(e)

        db.session.commit()
        return {'status': task.status, 'task_id': task_id}


@celery.task(bind=True)
def process_summary(self, record_id, text_model_id, model_type='job'):
    app = get_app()
    with app.app_context():
        from app import db
        from app.models import Job, Meeting, TextModel

        model_map = {'job': Job, 'meeting': Meeting}
        model_cls = model_map.get(model_type, Job)

        record = db.session.get(model_cls, record_id)
        text_model = db.session.get(TextModel, text_model_id)
        if not record or not text_model:
            return {'error': 'Record or model not found'}

        record.summary_status = 'processing'
        db.session.commit()

        try:
            summary_messages = [
                {'role': 'system', 'content': 'Du bist ein Assistent, der Transkriptionen zusammenfasst. Antworte ausschließlich mit der Zusammenfassung. Kommentiere oder bewerte den Text nicht.'},
                {'role': 'user', 'content': f"Fasse die folgende Transkription strukturiert zusammen. Gib nur die Zusammenfassung aus, keine Einleitung oder Kommentare:\n\n{record.result_text}"}
            ]
            result = _call_chat_api(text_model, summary_messages)
            record.summary_text = result
            record.summary_status = 'completed'
        except Exception as e:
            record.summary_text = f"Fehler: {str(e)}"
            record.summary_status = 'failed'

        db.session.commit()
        return {'status': 'done', 'record_id': record_id}


def _trigger_auto_tasks(user_id, record_id, model_type):
    """Check user's group settings and trigger auto-title/auto-summary/auto-speaker tasks."""
    from app import db
    from app.models import User, Job, Meeting
    user = User.query.get(user_id)
    if not user:
        return

    title_enabled, title_model_id = user.get_auto_title_settings()
    if title_enabled and title_model_id:
        process_auto_title.delay(record_id, title_model_id, model_type)

    # Auto-summary only for job and meeting (dictation has no summary fields)
    if model_type != 'dictation':
        summary_enabled, summary_model_id = user.get_auto_summary_settings()
        if summary_enabled and summary_model_id:
            process_summary.delay(record_id, summary_model_id, model_type)

    # Auto-speaker identification for job and meeting with diarized segments
    if model_type in ('job', 'meeting'):
        model_map = {'job': Job, 'meeting': Meeting}
        record = db.session.get(model_map[model_type], record_id)
        if record and record.diarized_segments:
            segments = json.loads(record.diarized_segments)
            has_speakers = any('speaker' in seg for seg in segments)
            if has_speakers:
                speaker_enabled, speaker_model_id = user.get_auto_speaker_settings()
                if speaker_enabled and speaker_model_id:
                    process_speaker_identification.delay(record_id, speaker_model_id, model_type)


@celery.task(bind=True)
def process_auto_title(self, record_id, text_model_id, model_type='job'):
    app = get_app()
    with app.app_context():
        from app import db
        from app.models import Job, Meeting, Dictation, TextModel

        model_map = {'job': Job, 'meeting': Meeting, 'dictation': Dictation}
        model_cls = model_map.get(model_type, Job)

        record = db.session.get(model_cls, record_id)
        text_model = db.session.get(TextModel, text_model_id)
        if not record or not text_model:
            return {'error': 'Record or model not found'}

        record.title_status = 'processing'
        db.session.commit()

        try:
            # Use first ~500 chars of result text for title generation
            snippet = (record.result_text or '')[:500]
            if not snippet:
                record.title_status = None
                db.session.commit()
                return {'status': 'skipped', 'reason': 'no text'}

            # Check if cancelled before LLM call
            db.session.refresh(record)
            if record.title_status == 'cancelled':
                return {'status': 'cancelled', 'record_id': record_id}

            prompt = (
                "Generiere einen kurzen, prägnanten Titel (max 5-8 Wörter) "
                "für folgende Transkription. Antworte NUR mit dem Titel als reinen Text, "
                "ohne Anführungszeichen, ohne Markdown, ohne Sternchen, ohne zusätzlichen Text:\n\n" + snippet
            )
            title = _call_text_api(text_model, prompt).strip().strip('"\'*#_ ')

            # Check if cancelled after LLM call
            db.session.refresh(record)
            if record.title_status == 'cancelled':
                return {'status': 'cancelled', 'record_id': record_id}

            if title:
                record.title = title[:255]
                record.title_status = 'completed'
                db.session.commit()
        except Exception as e:
            record.title_status = 'failed'
            db.session.commit()

        return {'status': 'done', 'record_id': record_id}


@celery.task(bind=True)
def process_speaker_identification(self, record_id, text_model_id, model_type='job'):
    app = get_app()
    with app.app_context():
        from app import db
        from app.models import Job, Meeting, TextModel

        model_map = {'job': Job, 'meeting': Meeting}
        model_cls = model_map.get(model_type, Job)

        record = db.session.get(model_cls, record_id)
        text_model = db.session.get(TextModel, text_model_id)
        if not record or not text_model:
            return {'error': 'Record or model not found'}

        if not record.diarized_segments:
            return {'status': 'skipped', 'reason': 'no segments'}

        record.speaker_identify_status = 'processing'
        db.session.commit()

        try:
            segments = json.loads(record.diarized_segments)
            speaker_labels = list(set(seg.get('speaker', '') for seg in segments if seg.get('speaker')))
            if not speaker_labels:
                record.speaker_identify_status = None
                db.session.commit()
                return {'status': 'skipped', 'reason': 'no speakers'}

            # Build transcript snippet from first ~50 segments
            snippet_segments = segments[:50]
            transcript_lines = []
            for seg in snippet_segments:
                speaker = seg.get('speaker', '?')
                text = seg.get('text', '').strip()
                transcript_lines.append(f"[{speaker}]: {text}")
            transcript_snippet = '\n'.join(transcript_lines)

            prompt = (
                "Analysiere die folgende Transkription und versuche die echten Namen der Sprecher "
                "aus dem Gesprächsinhalt zu erkennen. Die aktuellen Sprecher-Labels sind: "
                + ', '.join(speaker_labels) + "\n\n"
                "Antworte NUR mit einem JSON-Objekt im Format:\n"
                '{"renames": {"ALTER_NAME": "NEUER_NAME"}}\n\n'
                "Wenn du einen Namen nicht erkennen kannst, lasse den Sprecher weg. "
                "Antworte ausschließlich mit dem JSON, ohne Markdown, ohne Erklärung.\n\n"
                "Transkription:\n" + transcript_snippet
            )

            # Check if cancelled before LLM call
            db.session.refresh(record)
            if record.speaker_identify_status == 'cancelled':
                return {'status': 'cancelled', 'record_id': record_id}

            result = _call_text_api(text_model, prompt)

            # Check if cancelled after LLM call
            db.session.refresh(record)
            if record.speaker_identify_status == 'cancelled':
                return {'status': 'cancelled', 'record_id': record_id}

            renames = _parse_speaker_renames(result, speaker_labels)
            if not renames:
                record.speaker_identify_status = 'completed'
                db.session.commit()
                return {'status': 'done', 'reason': 'no renames found'}

            # Apply renames to segments
            for seg in segments:
                old_name = seg.get('speaker', '')
                if old_name in renames:
                    seg['speaker'] = renames[old_name]

            record.diarized_segments = json.dumps(segments, ensure_ascii=False)

            # Regenerate result_text
            lines = [f"[{seg['speaker']}]: {seg['text'].strip()}" for seg in segments]
            record.result_text = '\n'.join(lines)

            record.speaker_identify_status = 'completed'
            db.session.commit()
        except Exception as e:
            record.speaker_identify_status = 'failed'
            db.session.commit()

        return {'status': 'done', 'record_id': record_id}


def _parse_speaker_renames(llm_response, valid_labels):
    """Parse LLM response for speaker renames. Robust against markdown code blocks."""
    import re
    # Strip markdown code blocks
    text = llm_response.strip()
    text = re.sub(r'^```(?:json)?\s*', '', text)
    text = re.sub(r'\s*```$', '', text)
    text = text.strip()

    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        # Try to find JSON object in the response
        match = re.search(r'\{[^{}]*"renames"\s*:\s*\{[^{}]*\}[^{}]*\}', text)
        if match:
            try:
                parsed = json.loads(match.group())
            except json.JSONDecodeError:
                return {}
        else:
            return {}

    renames = parsed.get('renames', {})
    # Validate: only keep renames where the old name is in valid_labels
    return {k: v for k, v in renames.items() if k in valid_labels and isinstance(v, str) and v.strip()}


def _get_dictionary_prompt(user_id):
    """Build a prompt string from the user's dictionary entries."""
    from app import db
    from app.models import DictionaryEntry, User
    user = db.session.get(User, user_id)
    if not user or not user.has_dictionary_access():
        return None
    entries = DictionaryEntry.query.filter_by(user_id=user_id).order_by(DictionaryEntry.word).all()
    if not entries:
        return None
    words = [e.word for e in entries]
    return ', '.join(words)


def _split_audio_file(file_path, max_size_mb, max_duration_secs=0):
    """Split an audio file into chunks smaller than max_size_mb and/or shorter than max_duration_secs.
    Returns a list of chunk file paths (sorted). Original file is not deleted."""
    import math

    file_size = os.path.getsize(file_path)
    max_size_bytes = max_size_mb * 1024 * 1024

    # Get duration using ffprobe
    try:
        result = subprocess.run(
            ['ffprobe', '-v', 'quiet', '-show_entries', 'format=duration',
             '-of', 'default=noprint_wrappers=1:nokey=1', file_path],
            capture_output=True, text=True, timeout=60
        )
        duration = float(result.stdout.strip())
    except Exception as e:
        raise Exception(f'Kann Audio-Dauer nicht ermitteln: {e}')

    needs_size_split = max_size_mb > 0 and file_size > max_size_bytes
    needs_duration_split = max_duration_secs > 0 and duration > max_duration_secs

    if not needs_size_split and not needs_duration_split:
        return [file_path]

    # Calculate number of chunks needed from both constraints, take the larger
    chunks_by_size = math.ceil(file_size / (max_size_bytes * 0.9)) if needs_size_split else 1
    chunks_by_duration = math.ceil(duration / (max_duration_secs * 0.9)) if needs_duration_split else 1
    num_chunks = max(chunks_by_size, chunks_by_duration)
    chunk_duration = duration / num_chunks

    base_path = os.path.splitext(file_path)[0]
    chunks = []

    for i in range(num_chunks):
        start = i * chunk_duration
        chunk_path = f"{base_path}_chunk{i:03d}.mp3"
        try:
            subprocess.run(
                ['ffmpeg', '-i', file_path, '-ss', str(start), '-t', str(chunk_duration),
                 '-codec:a', 'libmp3lame', '-q:a', '4', '-y', chunk_path],
                check=True, capture_output=True, timeout=600
            )
            if os.path.exists(chunk_path) and os.path.getsize(chunk_path) > 0:
                chunks.append(chunk_path)
        except Exception as e:
            # Clean up any created chunks on error
            for c in chunks:
                if os.path.exists(c):
                    os.remove(c)
            raise Exception(f'Fehler beim Aufteilen der Audiodatei: {e}')

    return chunks


def _merge_speech_results(results):
    """Merge multiple speech API results into one combined result."""
    all_text_parts = []
    all_segments = []
    time_offset = 0.0

    for result in results:
        if isinstance(result, dict) and 'segments' in result:
            all_text_parts.append(result.get('text', ''))
            for seg in result['segments']:
                adjusted_seg = dict(seg)
                adjusted_seg['start'] = seg.get('start', 0) + time_offset
                adjusted_seg['end'] = seg.get('end', 0) + time_offset
                all_segments.append(adjusted_seg)
            # Update time offset from the last segment's end time
            if result['segments']:
                time_offset = all_segments[-1]['end']
        else:
            text = result if isinstance(result, str) else result.get('text', str(result))
            all_text_parts.append(text)

    combined_text = ' '.join(all_text_parts).strip()

    if all_segments:
        return {'text': combined_text, 'segments': all_segments}
    return combined_text


def _extract_speaker_references(file_path, result, max_refs=5, clip_duration=5):
    """Extract short audio clips per speaker from the first chunk's diarized result.
    Returns a list of (speaker_label, clip_path) tuples."""
    import subprocess
    refs = []
    if not isinstance(result, dict) or 'segments' not in result:
        return refs

    # Find best segment per speaker (longest, at least 2s)
    speakers = {}
    for seg in result['segments']:
        speaker = seg.get('speaker')
        if not speaker or speaker == '?':
            continue
        seg_duration = seg.get('end', 0) - seg.get('start', 0)
        if seg_duration < 2:
            continue
        if speaker not in speakers or seg_duration > (speakers[speaker]['end'] - speakers[speaker]['start']):
            speakers[speaker] = seg

    for speaker, seg in list(speakers.items())[:max_refs]:
        start = seg['start']
        duration = min(seg['end'] - start, clip_duration)
        clip_path = f"{os.path.splitext(file_path)[0]}_ref_{speaker}.mp3"
        try:
            subprocess.run(
                ['ffmpeg', '-i', file_path, '-ss', str(start), '-t', str(duration),
                 '-codec:a', 'libmp3lame', '-q:a', '4', '-y', clip_path],
                capture_output=True, timeout=30
            )
            if os.path.exists(clip_path) and os.path.getsize(clip_path) > 0:
                refs.append((speaker, clip_path))
        except Exception:
            pass

    return refs


def _whisper_local_async(model, file_path, language=None, original_filename=None, dictionary_prompt=None, progress_callback=None):
    """Call local WhisperX API in async mode and poll for progress."""
    url = model.endpoint_url
    filename, mime = _get_file_info(file_path, original_filename)
    with open(file_path, 'rb') as f:
        files = {'file': (filename, f, mime)}
        data = {'model': model.model_id or 'whisper-1', 'async': 'true'}
        if model.supports_diarize:
            data['response_format'] = 'verbose_json'
            data['diarize'] = 'true'
        elif model.supports_timestamps:
            data['response_format'] = 'verbose_json'
        if language:
            data['language'] = language
        if dictionary_prompt and model.supports_prompt:
            data['prompt'] = dictionary_prompt
        headers = {}
        if model.api_key:
            headers['Authorization'] = f'Bearer {model.api_key}'
        resp = requests.post(url, files=files, data=data, headers=headers, timeout=30)

    if not resp.ok:
        try:
            err_detail = resp.json()
        except Exception:
            err_detail = resp.text[:500]
        raise Exception(f"Whisper API Fehler ({resp.status_code}): {err_detail}")

    task_id = resp.json().get('task_id')
    if not task_id:
        raise Exception('Whisper API hat keine task_id zurückgegeben')

    # Build poll URL from the base endpoint
    # endpoint_url is like http://whisper:8000/v1/audio/transcriptions
    poll_url = url.rstrip('/') + '/' + task_id
    timeout = getattr(model, 'request_timeout_secs', 0) or 600
    deadline = time.time() + timeout

    while time.time() < deadline:
        time.sleep(2)
        status_resp = requests.get(poll_url, headers=headers, timeout=10)
        if not status_resp.ok:
            continue
        status = status_resp.json()

        if progress_callback and 'progress' in status:
            progress_callback(status['progress'])

        if status['status'] == 'completed':
            result = status.get('result', {})
            if model.supports_diarize and result.get('segments'):
                return _parse_diarized_local(result)
            if model.supports_timestamps:
                return _parse_verbose_json(result)
            return result.get('text', str(result))
        elif status['status'] == 'failed':
            raise Exception(status.get('error', 'WhisperX task failed'))

    raise Exception('WhisperX Zeitüberschreitung')


def _call_speech_api(model, file_path, language=None, multi_speaker=False, original_filename=None, dictionary_prompt=None, progress_callback=None):
    import logging
    logger = logging.getLogger('transcribeops.tasks')

    max_size_mb = model.max_file_size_mb or 0
    max_duration = model.max_duration_secs or 0
    file_size = os.path.getsize(file_path)
    needs_split = (max_size_mb > 0 and file_size > max_size_mb * 1024 * 1024) or max_duration > 0

    if needs_split:
        chunks = _split_audio_file(file_path, max_size_mb, max_duration_secs=max_duration)
        if len(chunks) > 1:
            logger.info(f'Audio splitting: {file_size/(1024*1024):.1f} MB file split into {len(chunks)} chunks (size limit: {max_size_mb} MB, duration limit: {max_duration}s)')
            use_refs = getattr(model, 'use_speaker_references', False) and model.supports_diarize
            ref_files = []
            try:
                results = []
                speaker_refs = []
                for i, chunk_path in enumerate(chunks):
                    chunk_base = int((i / len(chunks)) * 100)
                    chunk_size = int(100 / len(chunks))

                    logger.info(f'Processing chunk {i+1}/{len(chunks)}: {os.path.basename(chunk_path)}')

                    if model.provider == 'whisper_local':
                        # Async mode with sub-progress
                        def chunk_progress(sub_pct, _base=chunk_base, _size=chunk_size):
                            if progress_callback:
                                progress_callback(_base + int(sub_pct * _size / 100))

                        r = _whisper_local_async(model, chunk_path, language, original_filename, dictionary_prompt,
                                                 progress_callback=chunk_progress)
                    else:
                        if i == 0 or not use_refs:
                            r = _call_speech_api_single(model, chunk_path, language, original_filename, dictionary_prompt)
                            if i == 0 and use_refs:
                                speaker_refs = _extract_speaker_references(file_path, r)
                                ref_files = [path for _, path in speaker_refs]
                                if speaker_refs:
                                    logger.info(f'Extracted {len(speaker_refs)} speaker references: {[s for s, _ in speaker_refs]}')
                        else:
                            r = _call_speech_api_single(
                                model, chunk_path, language, original_filename, dictionary_prompt,
                                speaker_references=speaker_refs
                            )
                        if progress_callback:
                            progress_callback(chunk_base + chunk_size)

                    results.append(r)
                return _merge_speech_results(results)
            finally:
                for chunk_path in chunks:
                    if chunk_path != file_path and os.path.exists(chunk_path):
                        os.remove(chunk_path)
                for ref_path in ref_files:
                    if os.path.exists(ref_path):
                        os.remove(ref_path)

    # Single chunk
    if model.provider == 'whisper_local':
        return _whisper_local_async(model, file_path, language, original_filename, dictionary_prompt,
                                    progress_callback=progress_callback)

    result = _call_speech_api_single(model, file_path, language, original_filename, dictionary_prompt)
    if progress_callback:
        progress_callback(100)
    return result


def _call_speech_api_single(model, file_path, language=None, original_filename=None, dictionary_prompt=None, speaker_references=None):
    if model.provider == 'whisper_local':
        return _whisper_local(model, file_path, language, original_filename, dictionary_prompt)
    elif model.provider == 'openai':
        return _openai_speech(model, file_path, language, original_filename, dictionary_prompt, speaker_references=speaker_references)
    elif model.provider == 'azure':
        return _azure_speech(model, file_path, language, original_filename, dictionary_prompt, speaker_references=speaker_references)
    else:
        raise Exception(f'Unbekannter Provider: {model.provider}')


MIME_TYPES = {
    '.mp3': 'audio/mpeg', '.wav': 'audio/wav', '.ogg': 'audio/ogg',
    '.webm': 'audio/webm', '.flac': 'audio/flac', '.m4a': 'audio/mp4',
    '.mp4': 'audio/mp4', '.mpeg': 'audio/mpeg', '.mpga': 'audio/mpeg',
}


def _get_file_info(file_path, original_filename):
    filename = original_filename or os.path.basename(file_path)
    ext = os.path.splitext(filename)[1].lower()
    mime = MIME_TYPES.get(ext, 'application/octet-stream')
    return filename, mime


def _whisper_local(model, file_path, language=None, original_filename=None, dictionary_prompt=None):
    url = model.endpoint_url
    filename, mime = _get_file_info(file_path, original_filename)
    with open(file_path, 'rb') as f:
        files = {'file': (filename, f, mime)}
        data = {'model': model.model_id or 'whisper-1'}
        if model.supports_diarize:
            data['response_format'] = 'verbose_json'
            data['diarize'] = 'true'
        elif model.supports_timestamps:
            data['response_format'] = 'verbose_json'
        if language:
            data['language'] = language
        if dictionary_prompt and model.supports_prompt:
            data['prompt'] = dictionary_prompt
        headers = {}
        if model.api_key:
            headers['Authorization'] = f'Bearer {model.api_key}'
        timeout = getattr(model, 'request_timeout_secs', 0) or 600
        resp = requests.post(url, files=files, data=data, headers=headers, timeout=timeout)
    if not resp.ok:
        try:
            err_detail = resp.json()
        except Exception:
            err_detail = resp.text[:500]
        raise Exception(f"Whisper API Fehler ({resp.status_code}): {err_detail}")
    result = resp.json()
    if model.supports_diarize and result.get('segments'):
        return _parse_diarized_local(result)
    if model.supports_timestamps:
        return _parse_verbose_json(result)
    return result.get('text', str(result))


def _openai_speech(model, file_path, language=None, original_filename=None, dictionary_prompt=None, speaker_references=None):
    url = 'https://api.openai.com/v1/audio/transcriptions'
    filename, mime = _get_file_info(file_path, original_filename)

    ref_handles = []
    try:
        with open(file_path, 'rb') as f:
            files = {'file': (filename, f, mime)}
            data = {'model': model.model_id or 'whisper-1'}
            if language:
                data['language'] = language
            if dictionary_prompt and model.supports_prompt:
                data['prompt'] = dictionary_prompt
            if model.supports_diarize:
                data['response_format'] = 'diarized_json'
                data['chunking_strategy'] = 'auto'
            elif model.supports_timestamps:
                data['response_format'] = 'verbose_json'
            # Add speaker reference clips for cross-chunk speaker identification
            if speaker_references:
                for i, (speaker_label, ref_path) in enumerate(speaker_references):
                    fh = open(ref_path, 'rb')
                    ref_handles.append(fh)
                    files[f'known_speaker_references[{i}][audio]'] = (f"{speaker_label}.mp3", fh, 'audio/mpeg')
                    data[f'known_speaker_references[{i}][label]'] = speaker_label
            headers = {'Authorization': f'Bearer {model.api_key}'}
            timeout = getattr(model, 'request_timeout_secs', 0) or 600
            resp = requests.post(url, files=files, data=data, headers=headers, timeout=timeout)
    finally:
        for fh in ref_handles:
            fh.close()
    if not resp.ok:
        try:
            err_detail = resp.json()
        except Exception:
            err_detail = resp.text[:500]
        raise Exception(f"OpenAI API Fehler ({resp.status_code}): {err_detail}")

    if model.supports_diarize:
        return _parse_diarized_response(resp)
    result = resp.json()
    if model.supports_timestamps:
        return _parse_verbose_json(result)
    return result.get('text', str(result))


def _azure_speech(model, file_path, language=None, original_filename=None, dictionary_prompt=None, speaker_references=None):
    api_version = model.azure_api_version or '2024-06-01'
    deployment = model.azure_deployment or model.model_id
    url = f"{model.endpoint_url}/openai/deployments/{deployment}/audio/transcriptions?api-version={api_version}"
    filename, mime = _get_file_info(file_path, original_filename)

    ref_handles = []
    try:
        with open(file_path, 'rb') as f:
            files = {'file': (filename, f, mime)}
            data = {}
            if language:
                data['language'] = language
            if dictionary_prompt and model.supports_prompt:
                data['prompt'] = dictionary_prompt
            if model.supports_diarize:
                data['response_format'] = 'diarized_json'
                data['chunking_strategy'] = 'auto'
            elif model.supports_timestamps:
                data['response_format'] = 'verbose_json'
            # Add speaker reference clips for cross-chunk speaker identification
            if speaker_references:
                for i, (speaker_label, ref_path) in enumerate(speaker_references):
                    fh = open(ref_path, 'rb')
                    ref_handles.append(fh)
                    files[f'known_speaker_references[{i}][audio]'] = (f"{speaker_label}.mp3", fh, 'audio/mpeg')
                    data[f'known_speaker_references[{i}][label]'] = speaker_label
            headers = {'api-key': model.api_key}
            timeout = getattr(model, 'request_timeout_secs', 0) or 600
            resp = requests.post(url, files=files, data=data, headers=headers, timeout=timeout)
    finally:
        for fh in ref_handles:
            fh.close()
    resp.raise_for_status()

    if model.supports_diarize:
        return _parse_diarized_response(resp)
    result = resp.json()
    if model.supports_timestamps:
        return _parse_verbose_json(result)
    return result.get('text', str(result))


def _parse_diarized_response(resp):
    """Parse SSE or JSON diarized response from OpenAI/Azure."""
    content_type = resp.headers.get('content-type', '')
    segments = []
    full_text = ''

    if 'text/event-stream' in content_type or resp.text.strip().startswith('{'):
        # Could be SSE (newline-delimited JSON) or single JSON
        for line in resp.text.strip().split('\n'):
            line = line.strip()
            if line.startswith('data: '):
                line = line[6:]
            if not line or line == '[DONE]':
                continue
            try:
                obj = json.loads(line)
                if obj.get('type') == 'transcript.text.segment':
                    segments.append({
                        'speaker': obj.get('speaker', '?'),
                        'text': obj.get('text', ''),
                        'start': obj.get('start', 0),
                        'end': obj.get('end', 0),
                    })
                elif obj.get('type') == 'transcript.text.done':
                    full_text = obj.get('text', '')
                elif 'segments' in obj:
                    # Direct JSON with segments array
                    for seg in obj['segments']:
                        segments.append({
                            'speaker': seg.get('speaker', '?'),
                            'text': seg.get('text', ''),
                            'start': seg.get('start', 0),
                            'end': seg.get('end', 0),
                        })
                    full_text = obj.get('text', '')
                elif 'text' in obj and not segments:
                    full_text = obj['text']
            except json.JSONDecodeError:
                continue

    if not full_text and segments:
        full_text = ' '.join(s['text'].strip() for s in segments)

    if segments:
        return {'text': full_text, 'segments': segments}
    return full_text or resp.text


def _parse_diarized_local(result):
    """Parse diarized response from local WhisperX API."""
    segments = []
    for seg in result.get('segments', []):
        segments.append({
            'speaker': seg.get('speaker', '?'),
            'text': seg.get('text', ''),
            'start': seg.get('start', 0),
            'end': seg.get('end', 0),
        })
    full_text = result.get('text', '')
    if not full_text and segments:
        full_text = ' '.join(s['text'].strip() for s in segments)
    return {'text': full_text, 'segments': segments}


def _parse_verbose_json(result):
    """Parse verbose_json response into text + timestamp segments (no speaker info)."""
    text = result.get('text', '')
    raw_segments = result.get('segments', [])
    if raw_segments:
        segments = [{
            'text': s.get('text', ''),
            'start': s.get('start', 0),
            'end': s.get('end', 0),
        } for s in raw_segments]
        return {'text': text, 'segments': segments}
    # Fallback: no segments available
    return text


def _build_text_prompt(action, text, target_language=None):
    if action == 'rewrite':
        return f"Schreibe den folgenden Text um und verbessere ihn stilistisch:\n\n{text}"
    elif action == 'grammar':
        return f"Prüfe den folgenden Text auf Grammatik und Rechtschreibung. Korrigiere Fehler und gib den korrigierten Text zurück. Liste die Änderungen am Ende auf:\n\n{text}"
    elif action == 'translate':
        return f"Übersetze den folgenden Text ins {target_language}:\n\n{text}"
    elif action == 'summarize':
        return f"Fasse den folgenden Text zusammen:\n\n{text}"
    else:
        return text


def _call_text_api(model, prompt):
    if model.provider == 'ollama':
        return _ollama_text(model, prompt)
    elif model.provider == 'openai':
        return _openai_text(model, prompt)
    elif model.provider == 'azure':
        return _azure_text(model, prompt)
    else:
        raise Exception(f'Unbekannter Provider: {model.provider}')


def _get_text_timeout(model):
    return getattr(model, 'request_timeout_secs', 0) or 300


def _ollama_text(model, prompt):
    url = f"{model.endpoint_url}/api/chat"
    payload = {
        'model': model.model_id,
        'messages': [{'role': 'user', 'content': prompt}],
        'stream': False
    }
    resp = requests.post(url, json=payload, timeout=_get_text_timeout(model))
    resp.raise_for_status()
    result = resp.json()
    return result.get('message', {}).get('content', json.dumps(result))


def _openai_text(model, prompt):
    url = 'https://api.openai.com/v1/chat/completions'
    payload = {
        'model': model.model_id,
        'messages': [{'role': 'user', 'content': prompt}]
    }
    headers = {
        'Authorization': f'Bearer {model.api_key}',
        'Content-Type': 'application/json'
    }
    resp = requests.post(url, json=payload, headers=headers, timeout=_get_text_timeout(model))
    resp.raise_for_status()
    result = resp.json()
    return result['choices'][0]['message']['content']


def _azure_text(model, prompt):
    api_version = model.azure_api_version or '2024-06-01'
    deployment = model.azure_deployment or model.model_id
    url = f"{model.endpoint_url}/openai/deployments/{deployment}/chat/completions?api-version={api_version}"
    payload = {
        'messages': [{'role': 'user', 'content': prompt}]
    }
    headers = {
        'api-key': model.api_key,
        'Content-Type': 'application/json'
    }
    resp = requests.post(url, json=payload, headers=headers, timeout=_get_text_timeout(model))
    resp.raise_for_status()
    result = resp.json()
    return result['choices'][0]['message']['content']


# ── Multi-turn chat API (full messages array) ────────────────────────

def _call_chat_api(model, messages):
    """Send a full messages array (multi-turn) to the text model."""
    if model.provider == 'ollama':
        return _ollama_chat(model, messages)
    elif model.provider == 'openai':
        return _openai_chat(model, messages)
    elif model.provider == 'azure':
        return _azure_chat(model, messages)
    else:
        raise Exception(f'Unbekannter Provider: {model.provider}')


def _ollama_chat(model, messages):
    url = f"{model.endpoint_url}/api/chat"
    payload = {'model': model.model_id, 'messages': messages, 'stream': False}
    resp = requests.post(url, json=payload, timeout=_get_text_timeout(model))
    resp.raise_for_status()
    result = resp.json()
    return result.get('message', {}).get('content', json.dumps(result))


def _openai_chat(model, messages):
    url = 'https://api.openai.com/v1/chat/completions'
    payload = {'model': model.model_id, 'messages': messages}
    headers = {'Authorization': f'Bearer {model.api_key}', 'Content-Type': 'application/json'}
    resp = requests.post(url, json=payload, headers=headers, timeout=_get_text_timeout(model))
    resp.raise_for_status()
    return resp.json()['choices'][0]['message']['content']


def _azure_chat(model, messages):
    api_version = model.azure_api_version or '2024-06-01'
    deployment = model.azure_deployment or model.model_id
    url = f"{model.endpoint_url}/openai/deployments/{deployment}/chat/completions?api-version={api_version}"
    payload = {'messages': messages}
    headers = {'api-key': model.api_key, 'Content-Type': 'application/json'}
    resp = requests.post(url, json=payload, headers=headers, timeout=_get_text_timeout(model))
    resp.raise_for_status()
    return resp.json()['choices'][0]['message']['content']


# ── Chat message Celery task ─────────────────────────────────────────

@celery.task(bind=True)
def process_chat_message(self, chat_message_id, text_model_id):
    app = get_app()
    with app.app_context():
        from app import db
        from app.models import ChatMessage, TextModel, Job, Meeting

        msg = db.session.get(ChatMessage, chat_message_id)
        text_model = db.session.get(TextModel, text_model_id)
        if not msg or not text_model:
            return {'error': 'Message or model not found'}

        msg.status = 'processing'
        db.session.commit()

        try:
            # Load transcript text from parent record
            model_map = {'job': Job, 'meeting': Meeting}
            record_cls = model_map.get(msg.record_type)
            record = db.session.get(record_cls, msg.record_id) if record_cls else None
            if not record or not record.result_text:
                raise Exception('Kein Transkriptionstext gefunden')

            transcript_text = record.result_text
            if len(transcript_text) > 8000:
                transcript_text = transcript_text[:8000] + '\n\n[... Text gekürzt ...]'

            system_msg = {
                'role': 'system',
                'content': (
                    'Du bist ein hilfreicher Assistent. Der Benutzer hat eine Transkription erstellt '
                    'und möchte Fragen dazu stellen. Hier ist der Transkriptionstext:\n\n'
                    f'{transcript_text}\n\n'
                    'Beantworte die Fragen des Benutzers basierend auf diesem Text. '
                    'Antworte auf Deutsch, es sei denn, der Benutzer fragt in einer anderen Sprache.'
                )
            }

            # Load conversation history (completed messages before this one)
            history = ChatMessage.query.filter_by(
                record_type=msg.record_type,
                record_id=msg.record_id,
                user_id=msg.user_id
            ).filter(
                ChatMessage.id <= msg.id,
                ChatMessage.status == 'completed'
            ).order_by(ChatMessage.created_at).all()

            messages = [system_msg]
            for h in history:
                messages.append({'role': h.role, 'content': h.content})

            result = _call_chat_api(text_model, messages)
            msg.content = result
            msg.status = 'completed'
        except Exception as e:
            msg.content = f'Fehler: {str(e)}'
            msg.status = 'failed'

        db.session.commit()
        return {'status': msg.status, 'chat_message_id': chat_message_id}
