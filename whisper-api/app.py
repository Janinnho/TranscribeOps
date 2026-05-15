import os
import atexit
import gc
import hashlib
import hmac
import logging
import signal
import threading
import time

from flask import Flask, request, jsonify, session, redirect, url_for
from flask_babel import Babel

from engines import get_engine, EngineUnavailable, EngineBusy
from transcription_core import register_routes
from admin import create_admin_blueprint
from admin.db import init_db, touch_api_key_last_used, key_is_active
from admin import db as admin_db
from admin import supervisor
from i18n import compile_translations, client_strings_for

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
DISABLE_MAIN_ENGINE = os.environ.get("DISABLE_MAIN_ENGINE", "0") == "1"

MAIN_CFG_KEY = "main_engine_config"

# --- App ---------------------------------------------------------------------
app = Flask(__name__)

if ADMIN_SESSION_SECRET:
    app.secret_key = ADMIN_SESSION_SECRET
elif ADMIN_PASSWORD:
    app.secret_key = hashlib.sha256((ADMIN_PASSWORD + "::session").encode()).hexdigest()
else:
    app.secret_key = hashlib.sha256(os.urandom(32)).hexdigest()

# --- i18n --------------------------------------------------------------------
_TRANSLATIONS_DIR = os.path.join(os.path.dirname(__file__), "translations")
app.config["BABEL_DEFAULT_LOCALE"] = "en"
app.config["BABEL_SUPPORTED_LOCALES"] = ["en", "de"]
app.config["BABEL_TRANSLATION_DIRECTORIES"] = _TRANSLATIONS_DIR
compile_translations(_TRANSLATIONS_DIR)


def _select_locale():
    supported = ["en", "de"]
    lang = session.get("lang")
    if lang in supported:
        return lang
    best = request.accept_languages.best_match(supported)
    return best or "en"


babel = Babel(app, locale_selector=_select_locale)


@app.route("/lang/<code>")
def set_language(code):
    if code not in ("en", "de"):
        code = "en"
    session["lang"] = code
    nxt = request.args.get("next") or request.referrer or url_for("admin.dashboard")
    if isinstance(nxt, str) and nxt.startswith("/") and not nxt.startswith("//"):
        return redirect(nxt)
    return redirect(url_for("admin.dashboard"))


@app.context_processor
def _inject_i18n():
    from flask_babel import get_locale
    try:
        current = str(get_locale() or "en")
    except Exception:
        current = "en"
    return {
        "current_lang": current,
        "supported_locales": app.config["BABEL_SUPPORTED_LOCALES"],
        "client_i18n": client_strings_for(current),
    }

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
    """Return True iff the admin DB has at least one active key.

    On DB failure we fail-closed (return True, pretending keys exist) so the
    no-auth-configured fallback in check_auth() stays disabled and we never
    accidentally serve requests without credentials during a transient DB
    hiccup.
    """
    from admin.db import count_active_keys
    try:
        return count_active_keys(ADMIN_DB_PATH) > 0
    except Exception as e:
        logger.warning(
            "count_active_keys failed (%s) — assuming keys exist to stay fail-closed.",
            e,
        )
        return True


# --- Main engine: hot-swappable proxy ----------------------------------------
class _EngineProxy:
    """Stable handle for the main-process engine, allowing live reload.

    `register_routes()` captures the engine reference once at startup. When the
    admin UI changes the engine type/model, we can't recreate the closures —
    so we hand it this proxy instead. Attribute access (`.transcribe`,
    `.name`, `.model`, `.device`, `.compute_type`, `.supports_*`) is forwarded
    to the currently loaded `_real` engine. Swap is atomic under `_lock`.

    During reload, `_real` is None: `transcribe()` raises and the metadata
    properties fall back to the desired config so /health, /v1/models and
    log lines still render something sane.
    """

    def __init__(self, initial_config: dict):
        self._real = None
        self._config = dict(initial_config)
        self._reload = {"status": "idle", "error": None, "started_at": None}
        self._lock = threading.Lock()

    def set_real(self, engine, config: dict | None = None) -> None:
        with self._lock:
            self._real = engine
            if config is not None:
                self._config = dict(config)

    def set_reload(self, status: str, error: str | None = None) -> None:
        with self._lock:
            self._reload = {
                "status": status,
                "error": error,
                "started_at": time.time() if status == "loading" else self._reload.get("started_at"),
            }

    def state(self) -> dict:
        with self._lock:
            return {
                "loaded": self._real is not None,
                "config": dict(self._config),
                "reload": dict(self._reload),
            }

    # ----- duck-typed Engine surface used by transcription_core -----
    @property
    def name(self) -> str:
        return self._real.name if self._real else self._config.get("engine", "")

    @property
    def model(self) -> str:
        return self._real.model if self._real else self._config.get("model", "")

    @property
    def device(self) -> str:
        return self._real.device if self._real else self._config.get("device", "")

    @property
    def compute_type(self) -> str:
        return self._real.compute_type if self._real else self._config.get("compute_type", "")

    @property
    def hf_token(self) -> str:
        return self._real.hf_token if self._real else ""

    @property
    def supports_alignment(self) -> bool:
        return bool(self._real.supports_alignment) if self._real else False

    @property
    def supports_diarization(self) -> bool:
        return bool(self._real.supports_diarization) if self._real else False

    def transcribe(self, *args, **kwargs):
        with self._lock:
            real = self._real
            reload_status = self._reload.get("status")
        if real is None:
            # Distinguish transient (reload in flight) from terminal (load
            # never succeeded). Both map to 503, but the message differs so
            # clients can log something useful.
            if reload_status == "loading":
                raise EngineUnavailable("Main-Engine wird gerade neu geladen.")
            raise EngineUnavailable(
                "Main-Engine nicht geladen "
                "(letzter Reload fehlgeschlagen oder Konfiguration ungültig)."
            )
        return real.transcribe(*args, **kwargs)


def _resolve_main_config() -> dict:
    """Merge env defaults with persisted DB overrides."""
    cfg = {
        "engine": "whisperx",
        "model": DEFAULT_MODEL_SIZE,
        "device": DEVICE,
        "compute_type": COMPUTE_TYPE,
    }
    saved = admin_db.kv_get_json(ADMIN_DB_PATH, MAIN_CFG_KEY)
    if isinstance(saved, dict):
        for k in ("engine", "model", "device", "compute_type"):
            if saved.get(k):
                cfg[k] = saved[k]
    return cfg


def _build_engine(cfg: dict):
    engine_cls = get_engine(cfg["engine"])
    return engine_cls(
        model=cfg["model"],
        device=cfg["device"],
        compute_type=cfg["compute_type"],
        hf_token=HF_TOKEN,
        batch_size=BATCH_SIZE,
    )


_main_proxy = _EngineProxy(_resolve_main_config())


def _start_main_engine_blocking() -> None:
    """Synchronously load the configured main engine on the gunicorn worker.

    Port 8000 always serves transcription using the configured engine so existing
    clients keep working. Instances configured through the admin UI are additional
    parallel workers on their own ports.

    Set DISABLE_MAIN_ENGINE=1 to run the main process in admin-only mode.
    """
    if DISABLE_MAIN_ENGINE:
        logger.info("DISABLE_MAIN_ENGINE=1 — main process will not preload a model.")
        return

    # Ensure pyannote diarization models are present before the engine loads.
    # Torchaudio alignment bundles come with the image; pyannote needs a
    # runtime HF_TOKEN so we fetch it on first boot. Never fatal: missing
    # models just disable diarization, transcription keeps working.
    try:
        from admin.downloads import ensure_pyannote_models
        ensure_pyannote_models(HF_TOKEN)
    except Exception as e:
        logger.warning(f"ensure_pyannote_models failed unexpectedly: {e}", exc_info=True)

    cfg = _resolve_main_config()
    logger.info(f"Preloading main engine ({cfg['engine']}/{cfg['model']}) on main process.")
    try:
        engine = _build_engine(cfg)
        engine.load()
        _main_proxy.set_real(engine, cfg)
    except Exception as e:
        logger.error(f"Failed to load main engine: {e}", exc_info=True)
        _main_proxy.set_real(None, cfg)


def reload_main_engine(_slot_already_reserved: bool = False) -> dict:
    """Reload the main engine in the background using the persisted config.

    Reload sequence: drop the running engine first (free memory), GC, then
    construct + load the new engine. While loading, /v1/audio/transcriptions
    returns HTTP 503 — that's expected. On failure we surface the error in
    `_main_proxy.state()['reload']` so the admin UI can show it.

    `_slot_already_reserved=True` is set by `update_main_engine_config()`,
    which has already flipped the reload state to "loading" under the lock
    to atomically prevent racing config writes. In that case we skip the
    coalescing check (it would always trip on our own set).
    """
    if DISABLE_MAIN_ENGINE:
        return {"status": "disabled"}

    if not _slot_already_reserved:
        state = _main_proxy.state()
        if state["reload"]["status"] == "loading":
            return state["reload"]
        _main_proxy.set_reload("loading")

    cfg = _resolve_main_config()
    _main_proxy.set_real(None, cfg)

    def _bg():
        try:
            gc.collect()
            engine = _build_engine(cfg)
            engine.load()
            _main_proxy.set_real(engine, cfg)
            _main_proxy.set_reload("idle")
            logger.info(f"Main engine reloaded ({cfg['engine']}/{cfg['model']}).")
        except Exception as e:
            logger.exception("Main engine reload failed")
            _main_proxy.set_reload("failed", str(e))

    threading.Thread(target=_bg, daemon=True, name="main-engine-reload").start()
    return _main_proxy.state()["reload"]


def update_main_engine_config(new_cfg: dict) -> dict:
    """Validate + persist new config, then reload.

    Refuses to persist while a reload is already in flight. Without this
    guard, a second update would overwrite `admin_kv` while `reload_main_engine()`
    coalesces against the still-running thread — the running engine ends up
    on the *old* config but the DB claims the *new* one, so the next reload
    or container restart silently switches to a configuration that was
    never validated.
    """
    allowed_engines = {"whisperx", "nemo"}
    engine = (new_cfg.get("engine") or "").strip()
    if engine not in allowed_engines:
        raise ValueError(f"Unbekannte Engine '{engine}'. Erlaubt: {sorted(allowed_engines)}")

    model = (new_cfg.get("model") or "").strip()
    if not model:
        raise ValueError("Modell darf nicht leer sein.")

    device = (new_cfg.get("device") or DEVICE).strip()
    compute_type = (new_cfg.get("compute_type") or COMPUTE_TYPE).strip()

    cfg = {"engine": engine, "model": model, "device": device, "compute_type": compute_type}

    # Reserve the reload slot under the proxy lock *before* persisting. If
    # another reload is mid-flight, refuse — caller must retry once it ends.
    # set_reload("loading") is idempotent enough that briefly setting it twice
    # in the success path (here + inside reload_main_engine) is harmless.
    with _main_proxy._lock:
        if _main_proxy._reload.get("status") == "loading":
            raise EngineBusy(
                "Ein Reload läuft bereits. Bitte abwarten und erneut versuchen."
            )
        _main_proxy._reload = {"status": "loading", "error": None, "started_at": time.time()}

    try:
        admin_db.kv_set_json(ADMIN_DB_PATH, MAIN_CFG_KEY, cfg)
    except Exception:
        # Persist failed — release the slot so a retry is possible.
        _main_proxy.set_reload("idle")
        raise

    return reload_main_engine(_slot_already_reserved=True)


def get_main_engine_state() -> dict:
    """Snapshot for the admin UI: config, load status, reload state, port."""
    state = _main_proxy.state()
    state["disabled"] = DISABLE_MAIN_ENGINE
    state["port"] = 8000
    return state


# --- Engine + routes ---------------------------------------------------------
_start_main_engine_blocking()

if not DISABLE_MAIN_ENGINE:
    # Always register routes against the proxy — even if the initial load
    # failed. The proxy raises a clear error on transcribe() until a
    # subsequent reload succeeds.
    register_routes(app, _main_proxy, check_auth, model_alias=None)
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
        main_engine_loaded=lambda: _main_proxy.state()["loaded"],
        main_engine_disabled=DISABLE_MAIN_ENGINE,
        main_engine_state=get_main_engine_state,
        update_main_engine=update_main_engine_config,
        reload_main_engine=reload_main_engine,
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
