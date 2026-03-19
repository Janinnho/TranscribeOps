import os
import tempfile
import time
import logging
import uuid
import threading
import torch
from flask import Flask, request, jsonify
import whisperx

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("whisper-api")

app = Flask(__name__)

# Configuration via environment variables
API_KEY = os.environ.get("WHISPER_API_KEY", "")
DEFAULT_MODEL_SIZE = os.environ.get("WHISPER_MODEL", "medium")
DEVICE = os.environ.get("WHISPER_DEVICE", "cpu")
COMPUTE_TYPE = os.environ.get("WHISPER_COMPUTE_TYPE", "int8")
BATCH_SIZE = int(os.environ.get("WHISPER_BATCH_SIZE", "16"))
HF_TOKEN = os.environ.get("HF_TOKEN", "")

# Model caches
_models = {}
_align_models = {}
_diarize_pipeline = None

# Async task tracking
_tasks = {}
_tasks_lock = threading.Lock()
_TASK_TTL_SECS = 3600  # Clean up completed tasks after 1 hour

# Lock to ensure only one transcription runs at a time (models are not thread-safe)
_transcription_lock = threading.Lock()


def _cleanup_stale_tasks():
    """Remove completed/failed tasks older than TTL."""
    now = time.time()
    with _tasks_lock:
        stale = [tid for tid, t in _tasks.items()
                 if t.get("status") in ("completed", "failed")
                 and now - t.get("completed_at", now) > _TASK_TTL_SECS]
        for tid in stale:
            del _tasks[tid]


def get_model(model_size):
    """Load and cache a WhisperX model."""
    if model_size not in _models:
        logger.info(f"Loading WhisperX model '{model_size}' on {DEVICE} ({COMPUTE_TYPE})...")
        _models[model_size] = whisperx.load_model(
            model_size, DEVICE, compute_type=COMPUTE_TYPE
        )
        logger.info(f"Model '{model_size}' loaded successfully.")
    return _models[model_size]


def get_align_model(language_code):
    """Load and cache alignment model for a language."""
    if language_code not in _align_models:
        logger.info(f"Loading alignment model for language '{language_code}'...")
        model_a, metadata = whisperx.load_align_model(
            language_code=language_code, device=DEVICE
        )
        _align_models[language_code] = (model_a, metadata)
        logger.info(f"Alignment model for '{language_code}' loaded.")
    return _align_models[language_code]


def get_diarize_pipeline():
    """Load and cache diarization pipeline (requires HF_TOKEN)."""
    global _diarize_pipeline
    if _diarize_pipeline is None:
        if not HF_TOKEN:
            return None
        logger.info("Loading diarization pipeline...")
        from whisperx.diarize import DiarizationPipeline
        _diarize_pipeline = DiarizationPipeline(
            model_name="pyannote/speaker-diarization-3.1",
            token=HF_TOKEN, device=DEVICE
        )
        logger.info("Diarization pipeline loaded.")
    return _diarize_pipeline


def check_auth():
    """Validate API key if one is configured."""
    if not API_KEY:
        return True
    auth = request.headers.get("Authorization", "")
    if auth.startswith("Bearer "):
        token = auth[7:]
        return token == API_KEY
    return False


# Preload default model at startup
logger.info(f"Preloading default model '{DEFAULT_MODEL_SIZE}'...")
_default_model = get_model(DEFAULT_MODEL_SIZE)
logger.info("WhisperX API ready.")


def _process_transcription(tmp_path, model_size, language, response_format, enable_diarize, filename, task_id=None, prompt=None):
    """Core transcription logic. If task_id is provided, updates _tasks with progress."""
    def _update(progress=None, step=None):
        if task_id and task_id in _tasks:
            if progress is not None:
                _tasks[task_id]["progress"] = progress
            if step is not None:
                _tasks[task_id]["progress_step"] = step

    model = get_model(model_size)

    transcribe_kwargs = {"batch_size": BATCH_SIZE}
    if language:
        transcribe_kwargs["language"] = language
    # Note: WhisperX's transcribe() does not support initial_prompt.
    # The prompt parameter is accepted from the API but not forwarded to WhisperX.

    logger.info(f"Transcribing '{filename}' with model '{model_size}', language={language}")
    start_time = time.time()

    # Step 1: Transcribe
    _update(progress=5, step="transcribe")
    result = model.transcribe(tmp_path, **transcribe_kwargs)
    detected_language = result.get("language", language or "unknown")
    _update(progress=70)

    # Step 2: Align (word-level timestamps)
    _update(progress=70, step="align")
    try:
        model_a, metadata = get_align_model(detected_language)
        audio = whisperx.load_audio(tmp_path)
        result = whisperx.align(
            result["segments"], model_a, metadata, audio, DEVICE,
            return_char_alignments=False
        )
    except Exception as e:
        logger.warning(f"Alignment failed (continuing without): {e}")
    _update(progress=90)

    # Step 3: Diarize (optional)
    if enable_diarize and HF_TOKEN:
        _update(progress=90, step="diarize")
        try:
            diarize_pipeline = get_diarize_pipeline()
            if diarize_pipeline is not None:
                audio = whisperx.load_audio(tmp_path)
                diarize_segments = diarize_pipeline(audio)
                result = whisperx.assign_word_speakers(diarize_segments, result)
                logger.info("Speaker diarization applied.")
        except Exception as e:
            logger.warning(f"Diarization failed (continuing without): {e}")
    _update(progress=100)

    # Build segments list
    all_segments = []
    text_parts = []
    for i, seg in enumerate(result.get("segments", [])):
        seg_data = {
            "id": i,
            "start": round(seg.get("start", 0), 2),
            "end": round(seg.get("end", 0), 2),
            "text": seg.get("text", ""),
        }
        if "speaker" in seg:
            seg_data["speaker"] = seg["speaker"]
        if "words" in seg:
            seg_data["words"] = [
                {
                    "word": w.get("word", ""),
                    "start": round(w.get("start", 0), 2),
                    "end": round(w.get("end", 0), 2),
                }
                for w in seg["words"]
                if "start" in w and "end" in w
            ]
        all_segments.append(seg_data)
        text_parts.append(seg.get("text", ""))

    full_text = "".join(text_parts).strip()
    duration = round(time.time() - start_time, 2)
    logger.info(f"Transcription complete in {duration}s, detected language: {detected_language}")

    # Calculate audio duration from segments
    audio_duration = round(all_segments[-1]["end"], 2) if all_segments else 0

    # Build response based on format
    if response_format == "verbose_json":
        return {
            "text": full_text,
            "language": detected_language,
            "duration": audio_duration,
            "segments": all_segments,
        }
    elif response_format == "text":
        return {"_raw_text": full_text}
    elif response_format == "srt":
        return {"_raw_text": _to_srt(all_segments)}
    elif response_format == "vtt":
        return {"_raw_text": _to_vtt(all_segments)}
    else:
        return {"text": full_text}


def _run_async_task(task_id, tmp_path, model_size, language, response_format, enable_diarize, filename, prompt=None):
    """Background thread wrapper for async transcription."""
    try:
        with _transcription_lock:
            result = _process_transcription(tmp_path, model_size, language, response_format, enable_diarize, filename, task_id=task_id, prompt=prompt)
        with _tasks_lock:
            _tasks[task_id]["status"] = "completed"
            _tasks[task_id]["progress"] = 100
            _tasks[task_id]["result"] = result
            _tasks[task_id]["completed_at"] = time.time()
    except Exception as e:
        logger.error(f"Async transcription failed: {e}", exc_info=True)
        with _tasks_lock:
            _tasks[task_id]["status"] = "failed"
            _tasks[task_id]["error"] = str(e)
            _tasks[task_id]["completed_at"] = time.time()
    finally:
        if os.path.exists(tmp_path):
            os.unlink(tmp_path)


@app.route("/v1/audio/transcriptions", methods=["POST"])
def transcribe():
    # Auth check
    if not check_auth():
        return jsonify({"error": {"message": "Invalid API key.", "type": "auth_error"}}), 401

    # File check
    if "file" not in request.files:
        return jsonify({"error": {"message": "No audio file provided.", "type": "invalid_request"}}), 400

    audio_file = request.files["file"]
    if audio_file.filename == "":
        return jsonify({"error": {"message": "Empty filename.", "type": "invalid_request"}}), 400

    # Parameters
    model_param = request.form.get("model", "whisper-1")
    language = request.form.get("language", None)
    response_format = request.form.get("response_format", "json")
    prompt = request.form.get("prompt", None)
    enable_diarize = request.form.get("diarize", "false").lower() == "true"
    async_mode = request.form.get("async", "false").lower() == "true"

    # Map model parameter
    if model_param in ("whisper-1", "whisper-large-v3"):
        model_size = DEFAULT_MODEL_SIZE
    else:
        model_size = model_param

    # Save uploaded file temporarily
    suffix = os.path.splitext(audio_file.filename)[1] or ".wav"
    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
        audio_file.save(tmp)
        tmp_path = tmp.name

    # Async mode: start background thread and return task_id
    if async_mode:
        _cleanup_stale_tasks()
        task_id = uuid.uuid4().hex
        with _tasks_lock:
            _tasks[task_id] = {
                "status": "processing",
                "progress": 0,
                "progress_step": "",
                "result": None,
                "error": None,
            }
        thread = threading.Thread(
            target=_run_async_task,
            args=(task_id, tmp_path, model_size, language, response_format, enable_diarize, audio_file.filename, prompt),
            daemon=True,
        )
        thread.start()
        return jsonify({"task_id": task_id}), 202

    # Synchronous mode (original behavior)
    try:
        with _transcription_lock:
            result = _process_transcription(tmp_path, model_size, language, response_format, enable_diarize, audio_file.filename, prompt=prompt)

        # Handle raw text responses (text/srt/vtt)
        if "_raw_text" in result:
            return result["_raw_text"], 200, {"Content-Type": "text/plain; charset=utf-8"}
        return jsonify(result)

    except Exception as e:
        logger.error(f"Transcription failed: {e}", exc_info=True)
        return jsonify({"error": {"message": str(e), "type": "server_error"}}), 500
    finally:
        os.unlink(tmp_path)


@app.route("/v1/audio/transcriptions/<task_id>", methods=["GET"])
def get_task_status(task_id):
    """Poll endpoint for async transcription progress."""
    if not check_auth():
        return jsonify({"error": {"message": "Invalid API key.", "type": "auth_error"}}), 401

    task = _tasks.get(task_id)
    if not task:
        return jsonify({"error": "Task not found"}), 404

    response = {
        "status": task["status"],
        "progress": task["progress"],
        "progress_step": task["progress_step"],
    }
    if task["status"] == "completed":
        response["result"] = task["result"]
        del _tasks[task_id]
    elif task["status"] == "failed":
        response["error"] = task["error"]
        del _tasks[task_id]
    return jsonify(response)


@app.route("/v1/models", methods=["GET"])
def list_models():
    """OpenAI-compatible models endpoint."""
    if not check_auth():
        return jsonify({"error": {"message": "Invalid API key.", "type": "auth_error"}}), 401

    models = [
        {"id": "whisper-1", "object": "model", "owned_by": "local", "description": f"Default ({DEFAULT_MODEL_SIZE})"},
    ]
    for size in ["tiny", "base", "small", "medium", "large-v3", "turbo"]:
        models.append({"id": size, "object": "model", "owned_by": "local"})

    return jsonify({"object": "list", "data": models})


@app.route("/health", methods=["GET"])
def health():
    return jsonify({
        "status": "ok",
        "engine": "whisperx",
        "default_model": DEFAULT_MODEL_SIZE,
        "device": DEVICE,
        "compute_type": COMPUTE_TYPE,
        "batch_size": BATCH_SIZE,
        "diarization_available": bool(HF_TOKEN),
        "models_loaded": list(_models.keys()),
        "align_models_loaded": list(_align_models.keys()),
    })


def _to_srt(segments):
    lines = []
    for i, seg in enumerate(segments, 1):
        start = _format_time_srt(seg["start"])
        end = _format_time_srt(seg["end"])
        lines.append(f"{i}\n{start} --> {end}\n{seg['text'].strip()}\n")
    return "\n".join(lines)


def _to_vtt(segments):
    lines = ["WEBVTT\n"]
    for seg in segments:
        start = _format_time_vtt(seg["start"])
        end = _format_time_vtt(seg["end"])
        lines.append(f"{start} --> {end}\n{seg['text'].strip()}\n")
    return "\n".join(lines)


def _format_time_srt(seconds):
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = int(seconds % 60)
    ms = int((seconds % 1) * 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def _format_time_vtt(seconds):
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = int(seconds % 60)
    ms = int((seconds % 1) * 1000)
    return f"{h:02d}:{m:02d}:{s:02d}.{ms:03d}"


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8000, debug=False)
