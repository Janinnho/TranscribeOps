import os
import tempfile
import time
import logging
from flask import Flask, request, jsonify
from faster_whisper import WhisperModel

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("whisper-api")

app = Flask(__name__)

# Configuration via environment variables
API_KEY = os.environ.get("WHISPER_API_KEY", "")
DEFAULT_MODEL_SIZE = os.environ.get("WHISPER_MODEL", "medium")
DEVICE = os.environ.get("WHISPER_DEVICE", "cpu")
COMPUTE_TYPE = os.environ.get("WHISPER_COMPUTE_TYPE", "int8")

# Model cache
_models = {}


def get_model(model_size):
    """Load and cache a Whisper model."""
    if model_size not in _models:
        logger.info(f"Loading Whisper model '{model_size}' on {DEVICE} ({COMPUTE_TYPE})...")
        _models[model_size] = WhisperModel(model_size, device=DEVICE, compute_type=COMPUTE_TYPE)
        logger.info(f"Model '{model_size}' loaded successfully.")
    return _models[model_size]


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
logger.info("Whisper API ready.")


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

    # Map model parameter: "whisper-1" uses the default model, otherwise use as model size
    if model_param in ("whisper-1", "whisper-large-v3"):
        model_size = DEFAULT_MODEL_SIZE
    else:
        model_size = model_param

    # Save uploaded file temporarily
    suffix = os.path.splitext(audio_file.filename)[1] or ".wav"
    tmp_path = None
    try:
        with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
            tmp_path = tmp.name
            audio_file.save(tmp)
        model = get_model(model_size)

        transcribe_kwargs = {
            "beam_size": 5,
            "vad_filter": True,
        }
        if language:
            transcribe_kwargs["language"] = language

        logger.info(f"Transcribing '{audio_file.filename}' with model '{model_size}', language={language}")
        start_time = time.time()

        segments, info = model.transcribe(tmp_path, **transcribe_kwargs)
        text_parts = []
        all_segments = []
        for segment in segments:
            text_parts.append(segment.text)
            all_segments.append({
                "id": segment.id,
                "start": round(segment.start, 2),
                "end": round(segment.end, 2),
                "text": segment.text,
            })

        full_text = "".join(text_parts).strip()
        duration = round(time.time() - start_time, 2)
        logger.info(f"Transcription complete in {duration}s, detected language: {info.language}")

        # Response format
        if response_format == "verbose_json":
            return jsonify({
                "text": full_text,
                "language": info.language,
                "duration": round(info.duration, 2),
                "segments": all_segments,
            })
        elif response_format == "text":
            return full_text, 200, {"Content-Type": "text/plain; charset=utf-8"}
        elif response_format == "srt":
            return _to_srt(all_segments), 200, {"Content-Type": "text/plain; charset=utf-8"}
        elif response_format == "vtt":
            return _to_vtt(all_segments), 200, {"Content-Type": "text/plain; charset=utf-8"}
        else:
            # Default: json
            return jsonify({"text": full_text})

    except Exception as e:
        logger.error(f"Transcription failed: {e}", exc_info=True)
        return jsonify({"error": {"message": str(e), "type": "server_error"}}), 500
    finally:
        if tmp_path:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass


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
        "default_model": DEFAULT_MODEL_SIZE,
        "device": DEVICE,
        "compute_type": COMPUTE_TYPE,
        "models_loaded": list(_models.keys()),
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
