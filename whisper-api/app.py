import os
import atexit
import hashlib
import hmac
import logging
import signal
import threading
import time

from flask import Flask, request, jsonify

from engines import WhisperXEngine
from transcription_core import register_routes
from admin import create_admin_blueprint
from admin.db import init_db, touch_api_key_last_used, key_is_active
from admin import supervisor

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("whisper-api")

# --- Configuration (env) -----------------------------------------------------
API_KEY = os.environ.get("WHISPER_API_KEY", "")
DEFAULT_MODEL_SIZE = os.environ.get("WHISPER_MODEL", "medium")
DEVICE = os.environ.get("WHISPER_DEVICE", "cpu")
COMPUTE_TYPE = os.environ.get("WHISPER_COMPUTE_TYPE", "int8")
BATCH_SIZE = int(os.environ.get("WHISPER_BATCH_SIZE", "16"))
HF_TOKEN = os.environ.get("HF_TOKEN", "")
ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "")
ADMIN_SESSION_SECRET = os.environ.get("ADMIN_SESSION_SECRET", "")
ADMIN_DB_PATH = os.environ.get("ADMIN_DB_PATH", "/root/.cache/transcribeops/admin.db")
INSTANCE_PORT_RANGE = os.environ.get("INSTANCE_PORT_RANGE", "8100-8120")

# --- App ---------------------------------------------------------------------
app = Flask(__name__)

if ADMIN_SESSION_SECRET:
    app.secret_key = ADMIN_SESSION_SECRET
elif ADMIN_PASSWORD:
    app.secret_key = hashlib.sha256((ADMIN_PASSWORD + "::session").encode()).hexdigest()
else:
    app.secret_key = hashlib.sha256(os.urandom(32)).hexdigest()

# --- SQLite init -------------------------------------------------------------
init_db(ADMIN_DB_PATH)

# --- Auth --------------------------------------------------------------------
def check_auth() -> bool:
    auth = request.headers.get("Authorization", "")
    if not auth.startswith("Bearer "):
        # No auth configured at all → allow
        return not API_KEY and not _has_active_db_keys()
    token = auth[7:]
    if API_KEY and hmac.compare_digest(token, API_KEY):
        return True
    if key_is_active(ADMIN_DB_PATH, token):
        touch_api_key_last_used(ADMIN_DB_PATH, token)
        return True
    return not API_KEY and not _has_active_db_keys()


def _has_active_db_keys() -> bool:
    from admin.db import count_active_keys
    try:
        return count_active_keys(ADMIN_DB_PATH) > 0
    except Exception:
        return False


# --- Engine + routes ---------------------------------------------------------
_main_engine = None


def _start_main_engine():
    """Preload the default engine on the main process.

    Port 8000 always serves transcription using WHISPER_MODEL so existing clients
    keep working. Instances configured through the admin UI are additional
    parallel workers on their own ports.

    Set DISABLE_MAIN_ENGINE=1 to run the main process in admin-only mode.
    """
    global _main_engine
    if os.environ.get("DISABLE_MAIN_ENGINE", "0") == "1":
        logger.info("DISABLE_MAIN_ENGINE=1 — main process will not preload a model.")
        return

    logger.info(f"Preloading default engine ({DEFAULT_MODEL_SIZE}) on main process.")
    _main_engine = WhisperXEngine(
        model=DEFAULT_MODEL_SIZE, device=DEVICE, compute_type=COMPUTE_TYPE,
        hf_token=HF_TOKEN, batch_size=BATCH_SIZE,
    )
    try:
        _main_engine.load()
    except Exception as e:
        logger.error(f"Failed to load default engine: {e}", exc_info=True)
        _main_engine = None


_start_main_engine()

if _main_engine is not None:
    register_routes(app, _main_engine, check_auth, model_alias=DEFAULT_MODEL_SIZE)
else:
    @app.route("/v1/audio/transcriptions", methods=["POST"])
    def _no_engine_transcribe():
        return jsonify({
            "error": {
                "message": "Main process has no engine loaded. Use an instance port instead.",
                "type": "config_error",
            }
        }), 503

    @app.route("/v1/models", methods=["GET"])
    def _no_engine_models():
        if not check_auth():
            return jsonify({"error": {"message": "Invalid API key.", "type": "auth_error"}}), 401
        return jsonify({"object": "list", "data": []})

    @app.route("/health", methods=["GET"])
    def _no_engine_health():
        return jsonify({"status": "ok", "engine": None, "mode": "admin-only"})

# --- Admin blueprint ---------------------------------------------------------
app.register_blueprint(
    create_admin_blueprint(
        db_path=ADMIN_DB_PATH,
        admin_password=ADMIN_PASSWORD,
        hf_token=HF_TOKEN,
        default_model=DEFAULT_MODEL_SIZE,
        default_device=DEVICE,
        default_compute_type=COMPUTE_TYPE,
        default_batch_size=BATCH_SIZE,
        port_range=INSTANCE_PORT_RANGE,
        main_engine_loaded=lambda: _main_engine is not None,
        main_engine_disabled=os.environ.get("DISABLE_MAIN_ENGINE", "0") == "1",
        api_key_env_set=bool(API_KEY),
    ),
    url_prefix="/admin",
)

# --- Supervisor lifecycle ----------------------------------------------------
supervisor.configure(db_path=ADMIN_DB_PATH, port_range=INSTANCE_PORT_RANGE, hf_token=HF_TOKEN)

# Respawn enabled instances, but only in the gunicorn worker (not during `flask --help` etc.)
def _maybe_respawn():
    try:
        supervisor.respawn_enabled()
    except Exception as e:
        logger.error(f"Failed to respawn instances: {e}", exc_info=True)

threading.Thread(target=_maybe_respawn, daemon=True).start()


def _shutdown(*_):
    try:
        supervisor.stop_all()
    except Exception:
        pass


atexit.register(_shutdown)
try:
    signal.signal(signal.SIGTERM, lambda *a: (_shutdown(), os._exit(0)))
except Exception:
    pass


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8000, debug=False)
