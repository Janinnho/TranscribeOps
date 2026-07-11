"""OpenAI-compatible API (/v1) authenticated via personal API keys.

Endpoints mirror the OpenAI contract so third-party apps work out of the box:
  POST /v1/audio/transcriptions          (blocking; async=true -> task_id)
  GET  /v1/audio/transcriptions/<id>     (poll async result)
  POST /v1/chat/completions              (incl. stream + Textmuster pseudo-models)
  GET  /v1/models

Transcriptions are ephemeral: no Job record is created. All per-model settings
(audio splitting, upload limits, dictionary prompt, parallel slots) still apply.
Error responses use the OpenAI envelope and stay in English (machine interface).
"""
import hashlib
import json
import os
import time
import uuid
from datetime import datetime, timezone
from functools import wraps

from flask import Blueprint, request, jsonify, current_app, g, Response, stream_with_context
from werkzeug.utils import secure_filename

from app import db
from app.models import ApiKey

v1_bp = Blueprint('v1', __name__)

TEXT_ACTIONS = ('rewrite', 'grammar', 'translate', 'summarize')
RESPONSE_FORMATS = ('json', 'verbose_json', 'text')


def _api_error(message, type_='invalid_request_error', status=400, retry_after=None):
    resp = jsonify({'error': {'message': message, 'type': type_}})
    if retry_after:
        resp.headers['Retry-After'] = str(retry_after)
    return resp, status


def require_api_key(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        auth = request.headers.get('Authorization', '')
        if not auth.startswith('Bearer '):
            return _api_error('Missing API key. Use "Authorization: Bearer <key>".',
                              'authentication_error', 401)
        raw = auth[7:].strip()
        key_hash = hashlib.sha256(raw.encode()).hexdigest()
        key = ApiKey.query.filter_by(key_hash=key_hash, is_active=True).first()
        if not key or not key.user or not key.user.is_active_user or not key.user.has_api_access():
            return _api_error('Invalid API key.', 'authentication_error', 401)
        g.api_user = key.user
        g.api_key = key
        # Throttle the last_used_at write to at most once per minute per key.
        now = datetime.now(timezone.utc)
        last = key.last_used_at
        if last is not None and last.tzinfo is None:
            last = last.replace(tzinfo=timezone.utc)
        if last is None or (now - last).total_seconds() > 60:
            key.last_used_at = now
            db.session.commit()
        return f(*args, **kwargs)
    return wrapper


def _find_by_name(models, name):
    name_l = (name or '').strip().lower()
    for m in models:
        if m.name.lower() == name_l:
            return m
    return None


@v1_bp.route('/models')
@require_api_key
def list_models():
    created = int(time.time())

    def entry(model_id):
        return {'id': model_id, 'object': 'model', 'created': created, 'owned_by': 'transcribeops'}

    data = [entry(m.name) for m in g.api_user.get_available_speech_models()]
    for m in g.api_user.get_available_text_models():
        data.append(entry(m.name))
        data.extend(entry(f'{m.name}:{action}') for action in TEXT_ACTIONS)
    return jsonify({'object': 'list', 'data': data})


@v1_bp.route('/audio/transcriptions', methods=['POST'])
@require_api_key
def create_transcription():
    from app.routes.api import allowed_file, _extract_audio_duration
    from app.tasks import (_acquire_slot, _release_slot, _call_speech_api, _api_task_update,
                           process_api_transcription, merge_dictionary_prompt,
                           format_transcription_result)

    file = request.files.get('file')
    if not file or file.filename == '':
        return _api_error('No file provided (multipart form field "file").')
    if not allowed_file(file.filename):
        return _api_error('File type not allowed.')

    speech_models = g.api_user.get_available_speech_models()
    model_name = request.form.get('model', '').strip()
    model = _find_by_name(speech_models, model_name)
    if not model:
        available = ', '.join(m.name for m in speech_models) or '(none)'
        return _api_error(f'Unknown model "{model_name}". Available models: {available}',
                          'invalid_request_error', 404)

    response_format = request.form.get('response_format', '').strip() or 'json'
    if response_format not in RESPONSE_FORMATS:
        return _api_error(f'Unsupported response_format "{response_format}". '
                          f'Supported: {", ".join(RESPONSE_FORMATS)}')

    # Size limits: group-wide and per-model.
    file.seek(0, 2)
    file_size = file.tell()
    file.seek(0)
    group_max_mb = g.api_user.get_max_upload_size_mb()
    if group_max_mb > 0 and file_size > group_max_mb * 1024 * 1024:
        return _api_error(f'File too large. Maximum upload size: {group_max_mb} MB.',
                          'invalid_request_error', 413)
    if model.max_upload_size_mb and file_size > model.max_upload_size_mb * 1024 * 1024:
        return _api_error(f'File too large for this model. Maximum: {model.max_upload_size_mb} MB.',
                          'invalid_request_error', 413)

    language = request.form.get('language', '').strip() or None
    client_prompt = request.form.get('prompt', '')
    run_async = request.form.get('async', '').strip().lower() == 'true'

    filename = secure_filename(file.filename)
    unique_name = f"{uuid.uuid4().hex}_{filename}"
    filepath = os.path.join(current_app.config['UPLOAD_FOLDER'], unique_name)
    file.save(filepath)

    if model.max_upload_duration_secs:
        duration = _extract_audio_duration(filepath)
        if duration and duration > model.max_upload_duration_secs:
            os.remove(filepath)
            return _api_error(f'Audio too long for this model. Maximum: '
                              f'{model.max_upload_duration_secs}s, file: {int(duration)}s.',
                              'invalid_request_error', 413)

    if run_async:
        task_id = uuid.uuid4().hex
        _api_task_update(task_id, user_id=g.api_user.id, status='pending', progress=0)
        process_api_transcription.delay(task_id, filepath, filename, model.id,
                                        g.api_user.id, language, client_prompt, response_format)
        return jsonify({'task_id': task_id, 'status': 'pending'}), 202

    # Blocking mode: run the transcription inline (splitting/provider routing
    # included). Limited by the gunicorn worker timeout — long files should
    # use async=true.
    limit = model.max_parallel_tasks or 0
    if not _acquire_slot('speech', model.id, limit=limit):
        os.remove(filepath)
        return _api_error('Too many parallel requests for this model. Retry later.',
                          'rate_limit_error', 429, retry_after=10)
    try:
        prompt = merge_dictionary_prompt(model, g.api_user.id, client_prompt)
        result = _call_speech_api(
            model, filepath, language=language,
            multi_speaker=bool(model.supports_diarize),
            original_filename=filename, dictionary_prompt=prompt,
        )
    except Exception as e:
        return _api_error(f'Transcription failed: {e}', 'api_error', 502)
    finally:
        _release_slot('speech', model.id, limit=limit)
        if os.path.exists(filepath):
            try:
                os.remove(filepath)
            except OSError:
                pass

    formatted = format_transcription_result(result, response_format)
    if response_format == 'text':
        return Response(formatted, mimetype='text/plain')
    return jsonify(formatted)


@v1_bp.route('/audio/transcriptions/<string:task_id>')
@require_api_key
def get_transcription_task(task_id):
    from app.tasks import _api_task_get
    state = _api_task_get(task_id)
    if not state or state.get('user_id') != g.api_user.id:
        return _api_error('Task not found.', 'invalid_request_error', 404)
    payload = {
        'task_id': task_id,
        'status': state.get('status'),
        'progress': state.get('progress', 0),
    }
    if state.get('status') == 'completed':
        payload['result'] = state.get('result')
    elif state.get('status') == 'failed':
        payload['error'] = state.get('error')
    return jsonify(payload)


@v1_bp.route('/chat/completions', methods=['POST'])
@require_api_key
def chat_completions():
    from app.tasks import (_acquire_slot, _release_slot, _call_chat_api, _stream_chat,
                           _build_text_prompt)

    data = request.get_json(silent=True)
    if not data:
        return _api_error('Invalid or missing JSON body.')
    model_name = (data.get('model') or '').strip()
    messages = data.get('messages')
    if not model_name or not isinstance(messages, list) or not messages:
        return _api_error('"model" and a non-empty "messages" array are required.')

    # Textmuster pseudo-models: "<model>:rewrite" etc. apply the pattern
    # prompt to the last user message server-side.
    action = None
    base_name = model_name
    base, sep, suffix = model_name.rpartition(':')
    if sep and base and suffix in TEXT_ACTIONS:
        action = suffix
        base_name = base

    text_models = g.api_user.get_available_text_models()
    model = _find_by_name(text_models, base_name)
    if not model:
        available = []
        for m in text_models:
            available.append(m.name)
            available.extend(f'{m.name}:{a}' for a in TEXT_ACTIONS)
        return _api_error(f'Unknown model "{model_name}". Available models: '
                          f'{", ".join(available) or "(none)"}',
                          'invalid_request_error', 404)

    clean = []
    for m in messages:
        if not isinstance(m, dict) or m.get('role') not in ('system', 'user', 'assistant') \
                or not isinstance(m.get('content'), str):
            return _api_error('Each message needs a "role" (system/user/assistant) '
                              'and a string "content".')
        clean.append({'role': m['role'], 'content': m['content']})

    if action:
        target_language = (data.get('target_language') or '').strip() or 'Englisch'
        for m in reversed(clean):
            if m['role'] == 'user':
                m['content'] = _build_text_prompt(action, m['content'], target_language)
                break
        else:
            return _api_error('Text pattern models require at least one user message.')

    stream = bool(data.get('stream'))
    limit = model.max_parallel_tasks or 0
    if not _acquire_slot('text', model.id, limit=limit):
        return _api_error('Too many parallel requests for this model. Retry later.',
                          'rate_limit_error', 429, retry_after=10)

    completion_id = 'chatcmpl-' + uuid.uuid4().hex
    created = int(time.time())

    if stream:
        def generate():
            # Slot release must happen here: the view returns before the
            # stream is consumed, and the client may disconnect mid-stream.
            try:
                first = {'id': completion_id, 'object': 'chat.completion.chunk',
                         'created': created, 'model': model_name,
                         'choices': [{'index': 0, 'delta': {'role': 'assistant'},
                                      'finish_reason': None}]}
                yield f'data: {json.dumps(first)}\n\n'
                for token in _stream_chat(model, clean):
                    chunk = {'id': completion_id, 'object': 'chat.completion.chunk',
                             'created': created, 'model': model_name,
                             'choices': [{'index': 0, 'delta': {'content': token},
                                          'finish_reason': None}]}
                    yield f'data: {json.dumps(chunk)}\n\n'
                final = {'id': completion_id, 'object': 'chat.completion.chunk',
                         'created': created, 'model': model_name,
                         'choices': [{'index': 0, 'delta': {}, 'finish_reason': 'stop'}]}
                yield f'data: {json.dumps(final)}\n\n'
                yield 'data: [DONE]\n\n'
            except Exception as e:
                err = {'error': {'message': f'Chat completion failed: {e}', 'type': 'api_error'}}
                yield f'data: {json.dumps(err)}\n\n'
            finally:
                _release_slot('text', model.id, limit=limit)
        return Response(stream_with_context(generate()), mimetype='text/event-stream')

    try:
        content = _call_chat_api(model, clean)
    except Exception as e:
        return _api_error(f'Chat completion failed: {e}', 'api_error', 502)
    finally:
        _release_slot('text', model.id, limit=limit)

    prompt_chars = sum(len(m['content']) for m in clean)
    return jsonify({
        'id': completion_id,
        'object': 'chat.completion',
        'created': created,
        'model': model_name,
        'choices': [{
            'index': 0,
            'message': {'role': 'assistant', 'content': content},
            'finish_reason': 'stop',
        }],
        # Token counts are estimates (chars/4) — the providers used here do
        # not consistently report usage.
        'usage': {
            'prompt_tokens': prompt_chars // 4,
            'completion_tokens': len(content) // 4,
            'total_tokens': (prompt_chars + len(content)) // 4,
        },
    })
