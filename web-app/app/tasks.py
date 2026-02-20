import os
import json
import requests
from datetime import datetime, timezone
from app.celery_app import celery


def get_app():
    from app import create_app
    return create_app()


def _is_diarize_model(model):
    return 'diarize' in (model.model_id or '').lower()


@celery.task(bind=True)
def process_transcription(self, job_id):
    app = get_app()
    with app.app_context():
        from app import db
        from app.models import Job

        job = db.session.get(Job, job_id)
        if not job:
            return {'error': 'Job not found'}

        job.status = 'processing'
        job.celery_task_id = self.request.id
        db.session.commit()

        try:
            speech_model = job.speech_model
            if not speech_model:
                raise Exception('Kein Sprachmodell konfiguriert')

            # Load dictionary entries for prompt context
            dictionary_prompt = _get_dictionary_prompt(job.user_id)

            result = _call_speech_api(speech_model, job.file_path, job.language,
                                      job.multi_speaker, original_filename=job.original_filename,
                                      dictionary_prompt=dictionary_prompt)

            if isinstance(result, dict) and 'segments' in result:
                # Diarized result
                job.result_text = result.get('text', '')
                job.diarized_segments = json.dumps(result['segments'], ensure_ascii=False)
            else:
                job.result_text = result if isinstance(result, str) else result.get('text', str(result))

            job.status = 'completed'
            job.completed_at = datetime.now(timezone.utc)
        except Exception as e:
            job.status = 'failed'
            job.error_message = str(e)

        db.session.commit()
        return {'status': job.status, 'job_id': job_id}


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
def process_summary(self, job_id, text_model_id):
    app = get_app()
    with app.app_context():
        from app import db
        from app.models import Job, TextModel

        job = db.session.get(Job, job_id)
        text_model = db.session.get(TextModel, text_model_id)
        if not job or not text_model:
            return {'error': 'Job or model not found'}

        job.summary_status = 'processing'
        db.session.commit()

        try:
            prompt = f"Fasse den folgenden Text zusammen. Gib eine strukturierte Zusammenfassung:\n\n{job.result_text}"
            result = _call_text_api(text_model, prompt)
            job.summary_text = result
            job.summary_status = 'completed'
        except Exception as e:
            job.summary_text = f"Fehler: {str(e)}"
            job.summary_status = 'failed'

        db.session.commit()
        return {'status': 'done', 'job_id': job_id}


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


def _call_speech_api(model, file_path, language=None, multi_speaker=False, original_filename=None, dictionary_prompt=None):
    if model.provider == 'whisper_local':
        return _whisper_local(model, file_path, language, original_filename, dictionary_prompt)
    elif model.provider == 'openai':
        return _openai_speech(model, file_path, language, original_filename, dictionary_prompt)
    elif model.provider == 'azure':
        return _azure_speech(model, file_path, language, original_filename, dictionary_prompt)
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
        data = {'model': model.model_id or 'whisper-1',
                'response_format': 'verbose_json'}
        if language:
            data['language'] = language
        if dictionary_prompt:
            data['prompt'] = dictionary_prompt
        headers = {}
        if model.api_key:
            headers['Authorization'] = f'Bearer {model.api_key}'
        resp = requests.post(url, files=files, data=data, headers=headers, timeout=600)
    if not resp.ok:
        try:
            err_detail = resp.json()
        except Exception:
            err_detail = resp.text[:500]
        raise Exception(f"Whisper API Fehler ({resp.status_code}): {err_detail}")
    result = resp.json()
    return _parse_verbose_json(result)


def _openai_speech(model, file_path, language=None, original_filename=None, dictionary_prompt=None):
    url = 'https://api.openai.com/v1/audio/transcriptions'
    filename, mime = _get_file_info(file_path, original_filename)
    diarize = _is_diarize_model(model)
    is_whisper = 'whisper' in (model.model_id or '').lower()

    with open(file_path, 'rb') as f:
        files = {'file': (filename, f, mime)}
        data = {'model': model.model_id or 'whisper-1'}
        if language:
            data['language'] = language
        # prompt (dictionary) is only supported by whisper models
        if dictionary_prompt and is_whisper:
            data['prompt'] = dictionary_prompt
        if diarize:
            data['response_format'] = 'diarized_json'
            data['chunking_strategy'] = 'auto'
        elif is_whisper:
            data['response_format'] = 'verbose_json'
        headers = {'Authorization': f'Bearer {model.api_key}'}
        resp = requests.post(url, files=files, data=data, headers=headers, timeout=600)
    resp.raise_for_status()

    if diarize:
        return _parse_diarized_response(resp)
    result = resp.json()
    if is_whisper:
        return _parse_verbose_json(result)
    return result.get('text', str(result))


def _azure_speech(model, file_path, language=None, original_filename=None, dictionary_prompt=None):
    api_version = model.azure_api_version or '2024-06-01'
    deployment = model.azure_deployment or model.model_id
    url = f"{model.endpoint_url}/openai/deployments/{deployment}/audio/transcriptions?api-version={api_version}"
    filename, mime = _get_file_info(file_path, original_filename)
    diarize = _is_diarize_model(model)
    is_whisper = 'whisper' in (model.model_id or '').lower()

    with open(file_path, 'rb') as f:
        files = {'file': (filename, f, mime)}
        data = {}
        if language:
            data['language'] = language
        # prompt (dictionary) is only supported by whisper models
        if dictionary_prompt and is_whisper:
            data['prompt'] = dictionary_prompt
        if diarize:
            data['response_format'] = 'diarized_json'
            data['chunking_strategy'] = 'auto'
        elif is_whisper:
            data['response_format'] = 'verbose_json'
        headers = {'api-key': model.api_key}
        resp = requests.post(url, files=files, data=data, headers=headers, timeout=600)
    resp.raise_for_status()

    if diarize:
        return _parse_diarized_response(resp)
    result = resp.json()
    if is_whisper:
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


def _ollama_text(model, prompt):
    url = f"{model.endpoint_url}/api/chat"
    payload = {
        'model': model.model_id,
        'messages': [{'role': 'user', 'content': prompt}],
        'stream': False
    }
    resp = requests.post(url, json=payload, timeout=300)
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
    resp = requests.post(url, json=payload, headers=headers, timeout=300)
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
    resp = requests.post(url, json=payload, headers=headers, timeout=300)
    resp.raise_for_status()
    result = resp.json()
    return result['choices'][0]['message']['content']
