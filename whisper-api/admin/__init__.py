from flask import Blueprint

from .auth import register_auth_routes
from .routes import register_page_routes
from .api import register_api_routes


def create_admin_blueprint(
    *,
    db_path: str,
    admin_password: str,
    hf_token: str,
    default_model: str = "medium",
    default_device: str,
    default_compute_type: str,
    default_batch_size: int = 16,
    port_range: str,
    main_engine_loaded=None,
    main_engine_disabled: bool = False,
    main_engine_state=None,
    update_main_engine=None,
    reload_main_engine=None,
    api_key_env_set: bool = False,
) -> Blueprint:
    bp = Blueprint(
        "admin",
        __name__,
        template_folder="../templates",
        static_folder="../static",
        static_url_path="/static",
    )

    config = {
        "db_path": db_path,
        "admin_password": admin_password,
        "hf_token": hf_token,
        "default_model": default_model,
        "default_device": default_device,
        "default_compute_type": default_compute_type,
        "default_batch_size": default_batch_size,
        "port_range": port_range,
        "main_engine_loaded": main_engine_loaded or (lambda: False),
        "main_engine_disabled": main_engine_disabled,
        "main_engine_state": main_engine_state or (lambda: {
            "loaded": False, "config": {}, "reload": {"status": "idle", "error": None},
            "disabled": main_engine_disabled, "port": 8000,
        }),
        "update_main_engine": update_main_engine,
        "reload_main_engine": reload_main_engine,
        "api_key_env_set": api_key_env_set,
        "hf_token_set": bool(hf_token),
    }

    register_auth_routes(bp, config)
    register_page_routes(bp, config)
    register_api_routes(bp, config)

    return bp
