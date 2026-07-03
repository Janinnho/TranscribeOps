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
from router import InstanceRouter
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
        # On-demand wake-up after idle unload: `loader` builds+loads an
        # engine synchronously; `_wake_lock` serialises concurrent wakers.
        self._loader = None
        self._wake_lock = threading.Lock()

    def set_loader(self, loader) -> None:
        self._loader = loader

    def update_config(self, config: dict) -> None:
        """Refresh the config snapshot without touching the loaded engine."""
        with self._lock:
            self._config = dict(config)

    def _wake(self):
        """Blocking on-demand load after an idle unload ("sleeping")."""
        with self._wake_lock:
            with self._lock:
                if self._real is not None:
                    return self._real
            logger.info("Main engine was idle-unloaded — loading on demand.")
            self.set_reload("loading")
            try:
                engine, cfg = self._loader()
            except Exception as e:
                logger.exception("On-demand load of main engine failed")
                self.set_reload("sleeping", str(e))
                raise EngineUnavailable(f"Main-Engine konnte nicht geladen werden: {e}")
            self.set_real(engine, cfg)
            self.set_reload("idle")
            return engine

    def unload(self) -> None:
        """Drop the engine to free RAM; next transcribe() reloads it."""
        with self._lock:
            self._real = None
            self._reload = {"status": "sleeping", "error": None, "started_at": None}
        gc.collect()

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
        if real is None and reload_status == "sleeping" and self._loader is not None:
            real = self._wake()
        if real is None:
            # Distinguish transient (reload in flight) from terminal (load
            # never succeeded). Both map to 503, but the message differs so
            # clients can log something useful.
            if reload_status == "loading":
                raise EngineUnavailable("Main-Engine wird gerade neu geladen.")
            if reload_status == "disabled":
                raise EngineUnavailable(
                    "Main-Engine ist deaktiviert (DISABLE_MAIN_ENGINE=1). "
                    "Bitte über den model-Parameter eine Instanz ansprechen."
                )
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
        "timeout_secs": 600,      # Default wie das frühere gunicorn-Timeout; 0 = unbegrenzt
        "idle_unload_secs": 0,    # 0 = dauerhaft im RAM
    }
    saved = admin_db.kv_get_json(ADMIN_DB_PATH, MAIN_CFG_KEY)
    if isinstance(saved, dict):
        for k in ("engine", "model", "device", "compute_type"):
            if saved.get(k):
                cfg[k] = saved[k]
        for k in ("timeout_secs", "idle_unload_secs"):
            if k in saved:  # absent = pre-feature config -> keep the default
                try:
                    cfg[k] = max(0, int(saved[k] or 0))
                except (TypeError, ValueError):
                    pass
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
        _main_proxy.set_reload("disabled")
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

    old_cfg = _resolve_main_config()

    def _secs(key: str) -> int:
        raw = new_cfg.get(key)
        if raw is None or raw == "":
            return old_cfg.get(key, 0)
        try:
            val = int(raw)
        except (TypeError, ValueError):
            raise ValueError(f"'{key}' muss eine Zahl in Sekunden sein (0 = aus).")
        if val < 0:
            raise ValueError(f"'{key}' darf nicht negativ sein.")
        return val

    cfg = {
        "engine": engine, "model": model, "device": device, "compute_type": compute_type,
        "timeout_secs": _secs("timeout_secs"),
        "idle_unload_secs": _secs("idle_unload_secs"),
    }

    # Timeout/Idle-only changes don't touch the loaded model — persist and
    # return without the disruptive reload (they're read per request anyway).
    if all(cfg[k] == old_cfg.get(k) for k in ("engine", "model", "device", "compute_type")):
        admin_db.kv_set_json(ADMIN_DB_PATH, MAIN_CFG_KEY, cfg)
        _main_proxy.update_config(cfg)
        return {"status": "idle"}

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


def _load_main_engine_for_wake():
    """Loader for on-demand wake-up after an idle unload (blocking)."""
    cfg = _resolve_main_config()
    engine = _build_engine(cfg)
    engine.load()
    return engine, cfg


_main_proxy.set_loader(_load_main_engine_for_wake)

# Last-activity timestamp for the main engine's idle unload.
_main_activity = {"last": time.time()}
_main_activity_lock = threading.Lock()


def _touch_main_activity():
    with _main_activity_lock:
        _main_activity["last"] = time.time()


# Model-parameter router: port 8000 is the single entry point; requests whose
# `model` names an instance alias are proxied to that instance's worker.
# `local_aliases_fn` is evaluated per request so a hot-swapped main model
# keeps resolving to the main engine.
_router = InstanceRouter(
    ADMIN_DB_PATH,
    local_aliases_fn=lambda: {m for m in (_main_proxy.model,) if m and not DISABLE_MAIN_ENGINE},
)

# Always register routes against the proxy — even if the initial load failed
# or the main engine is disabled. The proxy raises a clear 503 on transcribe()
# for local models; instance models are proxied by the router either way.
_core = register_routes(
    app,
    _main_proxy,
    check_auth,
    model_alias=None,
    router=_router,
    advertise_local_models=not DISABLE_MAIN_ENGINE,
    health_extra=lambda: {
        "main_engine_loaded": _main_proxy.state()["loaded"],
        "mode": "admin-only" if DISABLE_MAIN_ENGINE else "full",
    },
    timeout_fn=lambda: _resolve_main_config().get("timeout_secs", 0),
    activity_cb=_touch_main_activity,
)


def _main_idle_watchdog():
    """Unload the main engine after idle_unload_secs without traffic.

    The next transcription request wakes it up via the proxy's loader
    (blocking load in-request). Active transcriptions block the unload.
    """
    while True:
        time.sleep(60)
        try:
            if DISABLE_MAIN_ENGINE:
                continue
            idle = _resolve_main_config().get("idle_unload_secs") or 0
            if idle <= 0:
                continue
            if not _main_proxy.state()["loaded"]:
                continue
            if _core["active_count"]() > 0:
                continue
            with _main_activity_lock:
                last = _main_activity["last"]
            if time.time() - last < idle:
                continue
            logger.info(f"Idle-unload: dropping main engine after {int(time.time() - last)}s without traffic.")
            _main_proxy.unload()
        except Exception:
            logger.exception("Main idle watchdog tick failed")


threading.Thread(target=_main_idle_watchdog, daemon=True, name="main-idle-watchdog").start()

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
    # After respawn: watch for idle instances to unload (frees RAM; the
    # router restarts them on demand).
    supervisor.start_idle_watchdog()

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
