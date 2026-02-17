import os
import json
import requests
from datetime import datetime, timezone
from app.celery_app import celery


def get_app():
    from app import create_app
    return create_app()


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

            result_text = _call_speech_api(speech_model, job.file_path, job.language, job.multi_speaker,
                                                     original_filename=job.original_filename)
            job.result_text = result_text
            job.status = 'completed'
            job.completed_at = datetime.now(timezone.utc)
        except Exception as e:
            job.status = 'failed'
            job.error_message = str(e)

        db.session.commit()
        return {'status': job.status, 'job_id': job_id}


@celery.task(bind=True)
def process_text_tool(self, job_id):
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
            text_model = job.text_model
            if not text_model:
                raise Exception('Kein Textmodell konfiguriert')

            prompt = _build_text_prompt(job.tool_action, job.input_text, job.target_language)
            result = _call_text_api(text_model, prompt)
            job.result_text = result
            job.status = 'completed'
            job.completed_at = datetime.now(timezone.utc)
        except Exception as e:
            job.status = 'failed'
            job.error_message = str(e)

        db.session.commit()
        return {'status': job.status, 'job_id': job_id}


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

        try:
            prompt = f"Fasse den folgenden Text zusammen. Gib eine strukturierte Zusammenfassung:\n\n{job.result_text}"
            result = _call_text_api(text_model, prompt)
            job.summary_text = result
        except Exception as e:
            job.summary_text = f"Fehler: {str(e)}"

        db.session.commit()
        return {'status': 'done', 'job_id': job_id}


def _call_speech_api(model, file_path, language=None, multi_speaker=False, original_filename=None):
    if model.provider == 'whisper_local':
        return _whisper_local(model, file_path, language, original_filename)
    elif model.provider == 'openai':
        return _openai_speech(model, file_path, language, original_filename)
    elif model.provider == 'azure':
        return _azure_speech(model, file_path, language, original_filename)
    else:
        raise Exception(f'Unbekannter Provider: {model.provider}')


MIME_TYPES = {
    '.mp3': 'audio/mpeg', '.wav': 'audio/wav', '.ogg': 'audio/ogg',
    '.webm': 'audio/webm', '.flac': 'audio/flac', '.m4a': 'audio/mp4',
    '.mp4': 'audio/mp4', '.mpeg': 'audio/mpeg', '.mpga': 'audio/mpeg',
}


def _whisper_local(model, file_path, language=None, original_filename=None):
    url = model.endpoint_url
    filename = original_filename or os.path.basename(file_path)
    ext = os.path.splitext(filename)[1].lower()
    mime = MIME_TYPES.get(ext, 'application/octet-stream')
    with open(file_path, 'rb') as f:
        files = {'file': (filename, f, mime)}
        data = {'model': model.model_id or 'whisper-1'}
        if language:
            data['language'] = language
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
    return result.get('text', json.dumps(result))


def _openai_speech(model, file_path, language=None, original_filename=None):
    url = 'https://api.openai.com/v1/audio/transcriptions'
    filename = original_filename or os.path.basename(file_path)
    ext = os.path.splitext(filename)[1].lower()
    mime = MIME_TYPES.get(ext, 'application/octet-stream')
    with open(file_path, 'rb') as f:
        files = {'file': (filename, f, mime)}
        data = {'model': model.model_id or 'whisper-1'}
        if language:
            data['language'] = language
        headers = {'Authorization': f'Bearer {model.api_key}'}
        resp = requests.post(url, files=files, data=data, headers=headers, timeout=600)
    resp.raise_for_status()
    result = resp.json()
    return result.get('text', json.dumps(result))


def _azure_speech(model, file_path, language=None, original_filename=None):
    api_version = model.azure_api_version or '2024-06-01'
    deployment = model.azure_deployment or model.model_id
    url = f"{model.endpoint_url}/openai/deployments/{deployment}/audio/transcriptions?api-version={api_version}"
    filename = original_filename or os.path.basename(file_path)
    ext = os.path.splitext(filename)[1].lower()
    mime = MIME_TYPES.get(ext, 'application/octet-stream')
    with open(file_path, 'rb') as f:
        files = {'file': (filename, f, mime)}
        data = {}
        if language:
            data['language'] = language
        headers = {'api-key': model.api_key}
        resp = requests.post(url, files=files, data=data, headers=headers, timeout=600)
    resp.raise_for_status()
    result = resp.json()
    return result.get('text', json.dumps(result))


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
