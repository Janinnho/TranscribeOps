"""Per-instance worker: serves /v1/* on its own port using a dedicated engine.

Spawned by admin/supervisor.py as a subprocess.
"""
import argparse
import hmac
import logging
import os

from flask import Flask, request

from engines import get_engine
from transcription_core import register_routes


logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("whisper-api.worker")


def _build_app(args) -> Flask:
    engine_cls = get_engine(args.engine)
    engine = engine_cls(
        model=args.model,
        device=args.device,
        compute_type=args.compute_type,
        hf_token=os.environ.get("HF_TOKEN", ""),
        batch_size=int(os.environ.get("WHISPER_BATCH_SIZE", "16")),
    )
    engine.load()

    app = Flask(__name__)

    # Shared auth: accept either WHISPER_API_KEY env or any active DB key.
    from admin.db import key_is_active, touch_api_key_last_used, count_active_keys
    api_key_env = os.environ.get("WHISPER_API_KEY", "")
    db_path = args.db_path

    def check_auth() -> bool:
        auth = request.headers.get("Authorization", "")
        if not auth.startswith("Bearer "):
            if not api_key_env and count_active_keys(db_path) == 0:
                return True
            return False
        token = auth[7:]
        if api_key_env and hmac.compare_digest(token, api_key_env):
            return True
        if key_is_active(db_path, token):
            touch_api_key_last_used(db_path, token)
            return True
        return False

    # Timeout + idle bookkeeping live in the instances table so admin-UI
    # changes apply without restarting the worker. Reads are per-request,
    # which is negligible next to a transcription.
    timeout_fn = None
    activity_cb = None
    if args.instance_id:
        from admin.db import get_instance, touch_instance_last_used

        def timeout_fn():
            row = get_instance(db_path, args.instance_id)
            return (row or {}).get("timeout_secs") or 0

        def activity_cb():
            touch_instance_last_used(db_path, args.instance_id)

    register_routes(app, engine, check_auth, model_alias=args.alias or args.model,
                    timeout_fn=timeout_fn, activity_cb=activity_cb)
    return app


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, required=True)
    parser.add_argument("--engine", required=True, choices=["whisperx", "nemo"])
    parser.add_argument("--model", required=True)
    parser.add_argument("--alias", default=None,
                        help="Instance name; exposed in /v1/models and used as routing alias.")
    parser.add_argument("--instance-id", type=int, default=None,
                        help="Row id in the instances table; enables per-instance timeout and idle tracking.")
    parser.add_argument("--device", default="cpu")
    parser.add_argument("--compute-type", default="int8")
    parser.add_argument("--db-path", required=True)
    args = parser.parse_args()

    app = _build_app(args)
    # Loopback only: instances are reached exclusively through the router on
    # the main port; their own ports are an internal implementation detail.
    logger.info(f"Worker listening on 127.0.0.1:{args.port} (engine={args.engine} model={args.model} alias={args.alias or args.model})")

    from werkzeug.serving import run_simple
    run_simple("127.0.0.1", args.port, app, threaded=True, use_reloader=False)


if __name__ == "__main__":
    main()
