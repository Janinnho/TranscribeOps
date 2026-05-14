"""Admin UI JSON endpoints under /admin/api/*."""
import logging
import secrets
import uuid

from flask import Blueprint, jsonify, request
from flask_babel import gettext as _

from engines import EngineBusy

from .auth import login_required
from . import db as admin_db
from . import supervisor
from . import downloads
from .catalog import by_id, by_repo_id, CATALOG
from .engines_list import engines_choices

logger = logging.getLogger("whisper-api.admin.api")


def register_api_routes(bp: Blueprint, config: dict) -> None:
    db_path = config["db_path"]
    hf_token = config["hf_token"]

    # ----- API keys -------------------------------------------------------
    @bp.route("/api/keys", methods=["GET"])
    @login_required
    def api_keys_list():
        return jsonify({"keys": admin_db.list_api_keys(db_path)})

    @bp.route("/api/keys", methods=["POST"])
    @login_required
    def api_keys_create():
        data = request.get_json(silent=True) or {}
        label = (data.get("label") or "").strip() or "unnamed"
        raw = "wsk_" + secrets.token_urlsafe(32)
        key_id = admin_db.create_api_key(db_path, label, raw)
        return jsonify({
            "id": key_id,
            "label": label,
            "raw_key": raw,
            "warning": _("This key is shown only once — save it now!"),
        })

    @bp.route("/api/keys/<int:key_id>", methods=["DELETE"])
    @login_required
    def api_keys_revoke(key_id: int):
        admin_db.revoke_api_key(db_path, key_id)
        return jsonify({"ok": True})

    # ----- Downloads ------------------------------------------------------
    @bp.route("/api/downloads", methods=["POST"])
    @login_required
    def api_downloads_start():
        data = request.get_json(silent=True) or {}
        repo_id = (data.get("repo_id") or "").strip()
        if not repo_id:
            return jsonify({"error": "repo_id required"}), 400

        catalog_entry = by_repo_id(repo_id)
        kind = (data.get("kind") or (catalog_entry.kind if catalog_entry else "whisper")).strip()

        existing = admin_db.active_download_for_repo(db_path, repo_id)
        if existing:
            return jsonify({"id": existing["id"], "status": existing["status"], "reused": True})

        dl_id = admin_db.create_download(db_path, repo_id, kind)
        downloads.start_download(db_path, dl_id, repo_id, hf_token)
        return jsonify({"id": dl_id, "status": "downloading", "reused": False})

    @bp.route("/api/downloads", methods=["GET"])
    @login_required
    def api_downloads_list():
        return jsonify({"downloads": admin_db.list_downloads(db_path)})

    @bp.route("/api/downloads/<int:dl_id>", methods=["GET"])
    @login_required
    def api_download_get(dl_id: int):
        row = admin_db.get_download(db_path, dl_id)
        if not row:
            return jsonify({"error": "not found"}), 404
        return jsonify(row)

    @bp.route("/api/catalog", methods=["GET"])
    @login_required
    def api_catalog():
        return jsonify({"entries": downloads.catalog_status(db_path)})

    # ----- Instances ------------------------------------------------------
    @bp.route("/api/instances", methods=["GET"])
    @login_required
    def api_instances_list():
        rows = admin_db.list_instances(db_path)
        return jsonify({"instances": [supervisor.instance_status(r) for r in rows]})

    @bp.route("/api/instances", methods=["POST"])
    @login_required
    def api_instances_create():
        data = request.get_json(silent=True) or {}
        name = (data.get("name") or "").strip()
        engine = (data.get("engine") or "whisperx").strip()
        model = (data.get("model") or "").strip()
        device = (data.get("device") or config["default_device"]).strip()
        compute_type = (data.get("compute_type") or config["default_compute_type"]).strip()
        purpose = (data.get("purpose") or "transcription").strip()
        port_raw = data.get("port")

        if not name or not model:
            return jsonify({"error": "name and model are required"}), 400
        if engine not in {"whisperx", "nemo"}:
            return jsonify({"error": f"unknown engine '{engine}'"}), 400

        try:
            port = int(port_raw) if port_raw else supervisor.allocate_port()
        except Exception as e:
            return jsonify({"error": f"port allocation failed: {e}"}), 400

        try:
            inst_id = admin_db.create_instance(
                db_path,
                name=name, engine=engine, model=model, purpose=purpose,
                device=device, compute_type=compute_type, port=port,
            )
        except Exception as e:
            return jsonify({"error": f"db error: {e}"}), 400

        try:
            supervisor.start_instance(inst_id)
        except Exception as e:
            admin_db.delete_instance(db_path, inst_id)
            return jsonify({"error": f"start failed: {e}"}), 500

        row = admin_db.get_instance(db_path, inst_id)
        return jsonify(supervisor.instance_status(row))

    @bp.route("/api/instances/<int:inst_id>/start", methods=["POST"])
    @login_required
    def api_instances_start(inst_id: int):
        try:
            supervisor.start_instance(inst_id)
        except Exception as e:
            return jsonify({"error": str(e)}), 500
        row = admin_db.get_instance(db_path, inst_id)
        return jsonify(supervisor.instance_status(row))

    @bp.route("/api/instances/<int:inst_id>/stop", methods=["POST"])
    @login_required
    def api_instances_stop(inst_id: int):
        supervisor.stop_instance(inst_id)
        row = admin_db.get_instance(db_path, inst_id)
        if row is None:
            return jsonify({"ok": True})
        return jsonify(supervisor.instance_status(row))

    @bp.route("/api/instances/<int:inst_id>", methods=["DELETE"])
    @login_required
    def api_instances_delete(inst_id: int):
        supervisor.delete_instance(inst_id)
        return jsonify({"ok": True})

    @bp.route("/api/engines", methods=["GET"])
    @login_required
    def api_engines():
        return jsonify({"engines": engines_choices()})

    # ----- Main engine ----------------------------------------------------
    @bp.route("/api/main-engine", methods=["GET"])
    @login_required
    def api_main_engine_get():
        get_state = config.get("main_engine_state")
        if get_state is None:
            return jsonify({"error": "main engine state unavailable"}), 500
        return jsonify(get_state())

    @bp.route("/api/main-engine", methods=["POST"])
    @login_required
    def api_main_engine_update():
        if config.get("main_engine_disabled"):
            return jsonify({"error": _("Main engine is disabled via DISABLE_MAIN_ENGINE.")}), 400
        update = config.get("update_main_engine")
        if update is None:
            return jsonify({"error": "update_main_engine handler not configured"}), 500

        data = request.get_json(silent=True) or {}
        try:
            reload_state = update(data)
        except ValueError as e:
            # User-supplied bad input — message is from our own validation,
            # safe to surface verbatim.
            return jsonify({"error": str(e)}), 400
        except EngineBusy as e:
            # A reload is already in flight — caller should retry, not a
            # server fault.
            return jsonify({"error": str(e)}), 409
        except Exception:
            # Don't leak internal exception text (paths, config values, etc.)
            # to the client. Log full traceback server-side and hand back a
            # short error id the user can quote when reporting problems.
            err_id = uuid.uuid4().hex[:8]
            logger.exception("Main engine update failed [err_id=%s]", err_id)
            return jsonify({
                "error": _("Reload failed — see server log for details."),
                "error_id": err_id,
            }), 500

        return jsonify({"reload": reload_state, "state": config["main_engine_state"]()})

    @bp.route("/api/main-engine/reload", methods=["POST"])
    @login_required
    def api_main_engine_reload():
        if config.get("main_engine_disabled"):
            return jsonify({"error": _("Main engine is disabled via DISABLE_MAIN_ENGINE.")}), 400
        do_reload = config.get("reload_main_engine")
        if do_reload is None:
            return jsonify({"error": "reload handler not configured"}), 500
        reload_state = do_reload()
        return jsonify({"reload": reload_state, "state": config["main_engine_state"]()})
