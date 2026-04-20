from flask import Blueprint

from .auth import register_auth_routes
from .routes import register_page_routes
from .api import register_api_routes


def create_admin_blueprint(
    *,
    db_path: str,
    admin_password: str,
    hf_token: str,
    default_device: str,
    default_compute_type: str,
    port_range: str,
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
        "default_device": default_device,
        "default_compute_type": default_compute_type,
        "port_range": port_range,
    }

    register_auth_routes(bp, config)
    register_page_routes(bp, config)
    register_api_routes(bp, config)

    return bp
