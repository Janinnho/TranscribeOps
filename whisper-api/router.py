"""Model-parameter routing: dispatch /v1/* requests to instance workers.

The main process (port 8000) is the single external entry point. Requests
whose `model` form parameter names an instance (by alias/name, or by the
underlying model when unambiguous) are proxied to that instance's worker on
127.0.0.1:<port>; everything else is handled by the main engine in-process.

Async task ids returned by instances are remembered (task_id -> port) so
status polls on port 8000 reach the right worker. The map is in-memory; after
a main-process restart unknown task ids fall back to a fan-out probe across
all running instances.
"""
import logging
import os
import threading
import time

import requests
from flask import Response, jsonify, request

from admin import db as admin_db
from admin import supervisor
from admin.supervisor import _pid_alive

logger = logging.getLogger("whisper-api.router")

_CONNECT_TIMEOUT = 10
_READ_TIMEOUT = int(os.environ.get("ROUTER_READ_TIMEOUT", "3600"))
_STARTUP_TIMEOUT = int(os.environ.get("ROUTER_STARTUP_TIMEOUT", "300"))
_TASK_MAP_TTL = 24 * 3600


def _passthrough(resp: requests.Response) -> Response:
    return Response(
        resp.content,
        resp.status_code,
        content_type=resp.headers.get("Content-Type", "application/json"),
    )


def _auth_headers() -> dict:
    auth = request.headers.get("Authorization")
    return {"Authorization": auth} if auth else {}


class InstanceRouter:
    def __init__(self, db_path: str, local_aliases_fn):
        """
        Args:
            db_path: admin SQLite DB holding the instances table.
            local_aliases_fn: () -> set[str]; model names (besides "whisper-1"
                and empty) that the main engine serves itself. Evaluated per
                request so a hot-swapped main engine stays correct.
        """
        self._db_path = db_path
        self._local_aliases_fn = local_aliases_fn
        self._task_map: dict[str, tuple[int, float]] = {}
        self._lock = threading.Lock()

    # ----- resolution ---------------------------------------------------
    def resolve(self, model_param: str | None) -> tuple[str, dict | None]:
        """Map a `model` value to ("local", None), ("proxy", row) or ("unknown", None).

        Precedence: "" / "whisper-1" -> local; exact instance name -> proxy
        (an instance name deliberately shadows a same-named main-engine model);
        main-engine model name -> local; unique instance model name -> proxy.
        """
        name = (model_param or "").strip()
        if not name or name == "whisper-1":
            return ("local", None)
        rows = self._instances()
        for row in rows:
            if row["name"] == name:
                return ("proxy", row)
        try:
            if name in self._local_aliases_fn():
                return ("local", None)
        except Exception:
            logger.exception("local_aliases_fn failed")
        by_model = [r for r in rows if r["model"] == name]
        if len(by_model) == 1:
            return ("proxy", by_model[0])
        return ("unknown", None)

    def _instances(self) -> list[dict]:
        try:
            return admin_db.list_instances(self._db_path)
        except Exception:
            logger.exception("list_instances failed — routing sees no instances")
            return []

    def known_model_ids(self) -> list[str]:
        ids = ["whisper-1"]
        try:
            ids += sorted(a for a in self._local_aliases_fn() if a)
        except Exception:
            pass
        ids += [r["name"] for r in self._instances()]
        # de-dupe, keep order
        seen = set()
        return [i for i in ids if not (i in seen or seen.add(i))]

    def instance_model_entries(self) -> list[dict]:
        """Entries for /v1/models, keyed by alias.

        Running instances and enabled-but-sleeping ones (idle-unloaded,
        started on demand) are both usable; only explicitly stopped
        instances are hidden.
        """
        entries = []
        for row in self._instances():
            alive = bool(row.get("pid")) and _pid_alive(row["pid"])
            if not alive and not row.get("enabled"):
                continue
            entries.append({
                "id": row["name"],
                "object": "model",
                "owned_by": "local",
                "description": f"{row['engine']}/{row['model']}",
            })
        return entries

    # ----- proxying -------------------------------------------------------
    def proxy_transcribe(self, row: dict):
        """Forward the current transcription request to instance `row`.

        A sleeping instance (idle-unloaded, still enabled) is started on
        demand — the request then waits for the model load. Explicitly
        stopped instances (enabled=0) are NOT auto-started; that's the
        admin's call.
        """
        url = f"http://127.0.0.1:{row['port']}/v1/audio/transcriptions"
        upload = request.files["file"]
        # The instance enforces its own timeout_secs (504). Our read timeout
        # sits slightly above it so that answer reaches the client instead
        # of us cutting the connection first.
        inst_timeout = row.get("timeout_secs") or 0
        read_timeout = inst_timeout + 30 if inst_timeout > 0 else _READ_TIMEOUT

        def _attempt():
            upload.stream.seek(0)  # retry-safe after a failed first attempt
            files = {"file": (upload.filename, upload.stream, upload.mimetype)}
            return requests.post(
                url,
                files=files,
                data=request.form.to_dict(),
                headers=_auth_headers(),
                timeout=(_CONNECT_TIMEOUT, read_timeout),
            )

        try:
            try:
                resp = _attempt()
            except requests.ConnectionError:
                if not row.get("enabled"):
                    return (
                        jsonify({"error": {
                            "message": f"Modell '{row['name']}' ist gestoppt. Im Admin-UI starten.",
                            "type": "engine_unavailable",
                        }}),
                        503,
                        {"Retry-After": "30"},
                    )
                logger.info("Instance '%s' not running — starting on demand.", row["name"])
                if not supervisor.ensure_running(row["id"], wait_secs=_STARTUP_TIMEOUT):
                    return (
                        jsonify({"error": {
                            "message": f"Modell '{row['name']}' konnte nicht gestartet werden "
                                       "(siehe Server-Log).",
                            "type": "engine_unavailable",
                        }}),
                        503,
                        {"Retry-After": "30"},
                    )
                resp = _attempt()
        except requests.ConnectionError:
            logger.warning("Instance '%s' (port %s) unreachable", row["name"], row["port"])
            return (
                jsonify({"error": {
                    "message": f"Modell '{row['name']}' ist derzeit nicht erreichbar.",
                    "type": "engine_unavailable",
                }}),
                503,
                {"Retry-After": "10"},
            )
        except requests.Timeout:
            return jsonify({"error": {
                "message": f"Zeitüberschreitung bei Instanz '{row['name']}'.",
                "type": "timeout",
            }}), 504

        if resp.status_code == 202:
            try:
                task_id = (resp.json() or {}).get("task_id")
            except ValueError:
                task_id = None
            if task_id:
                self._record_task(task_id, row["port"])
        return _passthrough(resp)

    def proxy_task_status(self, task_id: str):
        """Flask response for an instance-owned task, or None if no instance knows it."""
        port = self._task_port(task_id)
        if port is not None:
            candidates = [port]
        else:
            # Mapping lost (e.g. main process restarted) — probe all running
            # instances; a miss is a fast 404.
            candidates = [
                r["port"] for r in self._instances()
                if r.get("pid") and _pid_alive(r["pid"])
            ]

        for p in candidates:
            try:
                resp = requests.get(
                    f"http://127.0.0.1:{p}/v1/audio/transcriptions/{task_id}",
                    headers=_auth_headers(),
                    timeout=(5, 30),
                )
            except requests.RequestException:
                continue
            if resp.status_code == 404 and port is None:
                continue  # fan-out probe: not this instance
            if resp.status_code == 404:
                self._forget_task(task_id)
            elif resp.status_code == 200:
                # Instances pop completed/failed tasks on delivery — once we
                # pass a terminal status through, the mapping is dead weight.
                try:
                    if resp.json().get("status") in ("completed", "failed"):
                        self._forget_task(task_id)
                except ValueError:
                    pass
            return _passthrough(resp)

        if port is not None:
            # We know the owner but can't reach it right now — let clients retry.
            return (
                jsonify({"error": {
                    "message": "Instanz für diese Task ist derzeit nicht erreichbar.",
                    "type": "engine_unavailable",
                }}),
                503,
                {"Retry-After": "10"},
            )
        return None

    # ----- task map -------------------------------------------------------
    def _record_task(self, task_id: str, port: int) -> None:
        now = time.time()
        with self._lock:
            stale = [t for t, (_, ts) in self._task_map.items() if now - ts > _TASK_MAP_TTL]
            for t in stale:
                self._task_map.pop(t, None)
            self._task_map[task_id] = (port, now)

    def _task_port(self, task_id: str) -> int | None:
        with self._lock:
            entry = self._task_map.get(task_id)
            return entry[0] if entry else None

    def _forget_task(self, task_id: str) -> None:
        with self._lock:
            self._task_map.pop(task_id, None)
