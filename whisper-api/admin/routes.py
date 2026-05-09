"""Admin UI HTML routes."""
from flask import Blueprint, render_template

from .auth import login_required
from .catalog import CATALOG, KIND_LABELS, KIND_COLORS
from .downloads import catalog_status, bundled_models_status
from . import db as admin_db
from . import supervisor


def register_page_routes(bp: Blueprint, config: dict) -> None:
    db_path = config["db_path"]

    @bp.route("/")
    @login_required
    def dashboard():
        entries = catalog_status(db_path)
        instances = admin_db.list_instances(db_path)
        model_to_instances: dict[str, list[dict]] = {}
        for inst in instances:
            model_to_instances.setdefault(inst["model"], []).append(inst)

        grouped = {"whisper": [], "parakeet": [], "diarize": [], "align": []}
        for e in entries:
            e["instances"] = model_to_instances.get(e["id"], [])
            grouped.setdefault(e["kind"], []).append(e)

        main_state = config["main_engine_state"]()
        main_cfg = main_state.get("config", {})
        system_info = {
            "default_model": config["default_model"],
            "default_device": config["default_device"],
            "default_compute_type": config["default_compute_type"],
            "default_batch_size": config["default_batch_size"],
            "port_range": config["port_range"],
            "hf_token_set": config["hf_token_set"],
            "api_key_env_set": config["api_key_env_set"],
            "main_engine_disabled": config["main_engine_disabled"],
            "main_engine_loaded": config["main_engine_loaded"](),
            "main_port": main_state.get("port", 8000),
            "main_engine": main_cfg.get("engine", "whisperx"),
            "main_model": main_cfg.get("model", config["default_model"]),
            "main_device": main_cfg.get("device", config["default_device"]),
            "main_compute_type": main_cfg.get("compute_type", config["default_compute_type"]),
            "main_reload_status": main_state.get("reload", {}).get("status", "idle"),
            "main_reload_error": main_state.get("reload", {}).get("error"),
        }

        return render_template(
            "dashboard.html",
            grouped=grouped,
            kind_labels=KIND_LABELS,
            kind_colors=KIND_COLORS,
            system_info=system_info,
            bundled_info=bundled_models_status(),
        )

    @bp.route("/models")
    @login_required
    def models():
        entries = catalog_status(db_path)
        return render_template(
            "models.html",
            entries=entries,
            kind_labels=KIND_LABELS,
            kind_colors=KIND_COLORS,
        )

    @bp.route("/instances")
    @login_required
    def instances():
        rows = admin_db.list_instances(db_path)
        statuses = [supervisor.instance_status(r) for r in rows]
        downloaded = [e for e in catalog_status(db_path) if e["downloaded"] and e["kind"] in ("whisper", "parakeet")]

        # Prepend the main engine on port 8000 as a synthetic "is_main" row
        # so it shows up in the same table. It can be edited (engine + model)
        # but not started/stopped/deleted — the lifecycle is tied to the
        # gunicorn process.
        main_state = config["main_engine_state"]()
        main_cfg = main_state.get("config", {})
        if main_state.get("disabled"):
            main_status = "disabled"
        elif main_state.get("reload", {}).get("status") == "loading":
            main_status = "loading"
        elif main_state.get("reload", {}).get("status") == "failed":
            main_status = "failed"
        elif main_state.get("loaded"):
            main_status = "running"
        else:
            main_status = "stopped"
        main_row = {
            "id": "main",
            "is_main": True,
            "name": "Main Engine (Default)",
            "engine": main_cfg.get("engine", "whisperx"),
            "model": main_cfg.get("model", ""),
            "device": main_cfg.get("device", config["default_device"]),
            "compute_type": main_cfg.get("compute_type", config["default_compute_type"]),
            "port": main_state.get("port", 8000),
            "pid": None,
            "enabled": not main_state.get("disabled"),
            "status": main_status,
            "reload_error": main_state.get("reload", {}).get("error"),
            "health": None,
            "cpu_pct": None,
            "rss_mb": None,
        }
        statuses.insert(0, main_row)

        return render_template(
            "instances.html",
            instances=statuses,
            downloaded_models=downloaded,
            port_range=config["port_range"],
            default_device=config["default_device"],
            default_compute_type=config["default_compute_type"],
            main_disabled=bool(main_state.get("disabled")),
        )

    @bp.route("/keys")
    @login_required
    def keys():
        rows = admin_db.list_api_keys(db_path)
        return render_template("api_keys.html", keys=rows)
