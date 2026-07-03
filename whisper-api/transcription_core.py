"""Shared transcription route registration used by both the main app and instance workers.

Registers /v1/audio/transcriptions (sync + async), /v1/audio/transcriptions/<task_id>,
/v1/models and /health against a given Engine instance.
"""
import os
import tempfile
import time
import uuid
import logging
import threading
from typing import Callable

from flask import Flask, request, jsonify

from engines import EngineUnavailable

logger = logging.getLogger("whisper-api.core")


def _to_srt(segments):
    lines = []
    for i, seg in enumerate(segments, 1):
        lines.append(f"{i}\n{_fmt_srt(seg['start'])} --> {_fmt_srt(seg['end'])}\n{seg['text'].strip()}\n")
    return "\n".join(lines)


def _to_vtt(segments):
    lines = ["WEBVTT\n"]
    for seg in segments:
        lines.append(f"{_fmt_vtt(seg['start'])} --> {_fmt_vtt(seg['end'])}\n{seg['text'].strip()}\n")
    return "\n".join(lines)


def _fmt_srt(seconds):
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = int(seconds % 60)
    ms = int((seconds % 1) * 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def _fmt_vtt(seconds):
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = int(seconds % 60)
    ms = int((seconds % 1) * 1000)
    return f"{h:02d}:{m:02d}:{s:02d}.{ms:03d}"


def register_routes(app: Flask, engine, auth_fn: Callable[[], bool], model_alias: str | None = None,
                    router=None, advertise_local_models: bool = True,
                    health_extra: Callable[[], dict] | None = None,
                    timeout_fn: Callable[[], int] | None = None,
                    activity_cb: Callable[[], None] | None = None):
    """Register transcription routes on `app`.

    Args:
        app: Flask app to mutate.
        engine: Engine instance.
        auth_fn: callable -> bool, True when request is authorized.
        model_alias: how to expose this engine in /v1/models and accept in `model` param.
        router: optional InstanceRouter (main process only). When set, the
            `model` form param is resolved first — requests for instance
            aliases are proxied to the owning worker instead of handled here.
        advertise_local_models: include this engine's entries in /v1/models
            (False when the main engine is disabled and only routing remains).
        health_extra: optional callable merged into the /health payload.
        timeout_fn: optional callable -> max processing seconds (0 = no limit),
            evaluated per request so admin-UI changes apply immediately.
            Sync requests answer 504 after expiry; async tasks flip to
            "failed". The engine call itself cannot be aborted — it finishes
            in the background and only the response is cut short.
        activity_cb: optional callable invoked when a transcription starts and
            finishes — used for idle-unload bookkeeping.
    """
    tasks: dict = {}
    tasks_lock = threading.Lock()
    transcribe_lock = threading.Lock()
    active = {"n": 0}
    active_lock = threading.Lock()
    TTL = 3600

    def _current_timeout() -> int:
        if timeout_fn is None:
            return 0
        try:
            return max(0, int(timeout_fn() or 0))
        except Exception:
            return 0

    def _cleanup_stale():
        now = time.time()
        with tasks_lock:
            stale = [tid for tid, t in tasks.items()
                     if t.get("status") in ("completed", "failed")
                     and now - t.get("completed_at", now) > TTL]
            for tid in stale:
                tasks.pop(tid, None)

    def _build_response(result, response_format):
        segments = result.segments
        full_text = result.text
        duration = round(segments[-1]["end"], 2) if segments else 0
        if response_format == "verbose_json":
            return {"text": full_text, "language": result.language, "duration": duration, "segments": segments}
        if response_format == "text":
            return {"_raw_text": full_text}
        if response_format == "srt":
            return {"_raw_text": _to_srt(segments)}
        if response_format == "vtt":
            return {"_raw_text": _to_vtt(segments)}
        return {"text": full_text}

    def _run(tmp_path, language, response_format, enable_diarize, prompt, filename, task_id=None):
        def _update(progress=None, step=None):
            # Called from the engine thread via progress_cb; the reader side
            # (task_status) runs on the request thread. Guard every touch of
            # the shared `tasks` dict so a cleanup pop() can't race a write.
            if not task_id:
                return
            with tasks_lock:
                entry = tasks.get(task_id)
                if entry is None:
                    return
                if progress is not None:
                    entry["progress"] = progress
                if step is not None:
                    entry["progress_step"] = step

        logger.info(f"Transcribing '{filename}' (engine={engine.name} model={engine.model} lang={language})")
        if activity_cb:
            try:
                activity_cb()
            except Exception:
                pass
        with active_lock:
            active["n"] += 1
        start = time.time()
        try:
            result = engine.transcribe(
                tmp_path,
                language=language,
                enable_diarize=enable_diarize,
                prompt=prompt,
                progress_cb=lambda p, s=None: _update(progress=p, step=s),
            )
        finally:
            with active_lock:
                active["n"] -= 1
            if activity_cb:
                try:
                    activity_cb()
                except Exception:
                    pass
        logger.info(f"Done in {round(time.time() - start, 2)}s (detected={result.language})")
        return _build_response(result, response_format)

    def _async_wrapper(task_id, tmp_path, language, response_format, enable_diarize, prompt, filename):
        # tasks.get() everywhere: the entry may have been popped in the
        # meantime (TTL cleanup or a timeout marked it failed and the poll
        # delivered that) — then the result is simply dropped.
        try:
            with transcribe_lock:
                result = _run(tmp_path, language, response_format, enable_diarize, prompt, filename, task_id=task_id)
            with tasks_lock:
                entry = tasks.get(task_id)
                if entry is not None and entry["status"] == "processing":
                    entry["status"] = "completed"
                    entry["progress"] = 100
                    entry["result"] = result
                    entry["completed_at"] = time.time()
        except Exception as e:
            logger.exception("Async transcription failed")
            with tasks_lock:
                entry = tasks.get(task_id)
                if entry is not None and entry["status"] == "processing":
                    entry["status"] = "failed"
                    entry["error"] = str(e)
                    entry["completed_at"] = time.time()
        finally:
            if os.path.exists(tmp_path):
                try:
                    os.unlink(tmp_path)
                except OSError:
                    pass

    @app.route("/v1/audio/transcriptions", methods=["POST"])
    def transcribe():
        if not auth_fn():
            return jsonify({"error": {"message": "Invalid API key.", "type": "auth_error"}}), 401
        if "file" not in request.files:
            return jsonify({"error": {"message": "No audio file provided.", "type": "invalid_request"}}), 400

        audio_file = request.files["file"]
        if audio_file.filename == "":
            return jsonify({"error": {"message": "Empty filename.", "type": "invalid_request"}}), 400

        if router is not None:
            model_param = request.form.get("model")
            kind, target = router.resolve(model_param)
            if kind == "unknown":
                return jsonify({"error": {
                    "message": f"Unbekanntes Modell '{model_param}'. "
                               f"Verfügbar: {', '.join(router.known_model_ids())}",
                    "type": "invalid_request",
                }}), 404
            if kind == "proxy":
                return router.proxy_transcribe(target)

        language = request.form.get("language", None)
        response_format = request.form.get("response_format", "json")
        enable_diarize = request.form.get("diarize", "false").lower() == "true"
        prompt = request.form.get("prompt") or None
        async_mode = request.form.get("async", "false").lower() == "true"

        suffix = os.path.splitext(audio_file.filename)[1] or ".wav"
        with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
            audio_file.save(tmp)
            tmp_path = tmp.name

        timeout = _current_timeout()

        if async_mode:
            _cleanup_stale()
            task_id = uuid.uuid4().hex
            with tasks_lock:
                tasks[task_id] = {
                    "status": "processing", "progress": 0, "progress_step": "",
                    "result": None, "error": None,
                    "started_at": time.time(), "timeout": timeout,
                }
            threading.Thread(
                target=_async_wrapper,
                args=(task_id, tmp_path, language, response_format, enable_diarize, prompt, audio_file.filename),
                daemon=True,
            ).start()
            return jsonify({"task_id": task_id}), 202

        def _error_response(e: Exception):
            if isinstance(e, EngineUnavailable):
                # Reload in flight or load never succeeded — distinguishable
                # from a real server error so clients can retry.
                logger.info("Transcription rejected: engine temporarily unavailable (%s)", e)
                return (
                    jsonify({"error": {"message": str(e), "type": "engine_unavailable"}}),
                    503,
                    {"Retry-After": "10"},
                )
            logger.error("Transcription failed", exc_info=e)
            return jsonify({"error": {"message": str(e), "type": "server_error"}}), 500

        def _success_response(result):
            if "_raw_text" in result:
                return result["_raw_text"], 200, {"Content-Type": "text/plain; charset=utf-8"}
            return jsonify(result)

        if timeout > 0:
            # Run in a worker thread so the request can answer 504 after the
            # deadline. The engine call cannot be aborted — the thread owns
            # the temp file and cleans it up whenever it finishes.
            holder: dict = {}
            done = threading.Event()

            def _sync_target():
                try:
                    with transcribe_lock:
                        holder["result"] = _run(tmp_path, language, response_format, enable_diarize, prompt, audio_file.filename)
                except Exception as e:
                    holder["error"] = e
                finally:
                    done.set()
                    if os.path.exists(tmp_path):
                        try:
                            os.unlink(tmp_path)
                        except OSError:
                            pass

            threading.Thread(target=_sync_target, daemon=True).start()
            if not done.wait(timeout):
                logger.warning(f"Sync transcription exceeded timeout of {timeout}s — answering 504.")
                return jsonify({"error": {
                    "message": f"Zeitüberschreitung: Verarbeitung dauerte länger als {timeout}s "
                               "(Timeout im Admin-UI pro Modell konfigurierbar).",
                    "type": "timeout",
                }}), 504
            if "error" in holder:
                return _error_response(holder["error"])
            return _success_response(holder["result"])

        try:
            with transcribe_lock:
                result = _run(tmp_path, language, response_format, enable_diarize, prompt, audio_file.filename)
            return _success_response(result)
        except Exception as e:
            return _error_response(e)
        finally:
            if os.path.exists(tmp_path):
                try:
                    os.unlink(tmp_path)
                except OSError:
                    pass

    @app.route("/v1/audio/transcriptions/<task_id>", methods=["GET"])
    def task_status(task_id):
        if not auth_fn():
            return jsonify({"error": {"message": "Invalid API key.", "type": "auth_error"}}), 401
        # Snapshot under the lock so a concurrent _update or a terminal pop()
        # can't tear a partial view. We build the response from the snapshot
        # (not the live dict) before releasing the lock, and only pop once
        # we've captured what we need.
        with tasks_lock:
            task = tasks.get(task_id)
            if task:
                # Enforce the per-model timeout on polls: a still-processing
                # task past its deadline flips to failed. The engine thread
                # keeps running but its late result is dropped.
                t_out = task.get("timeout") or 0
                if (task["status"] == "processing" and t_out > 0
                        and time.time() - task.get("started_at", time.time()) > t_out):
                    task["status"] = "failed"
                    task["error"] = (f"Zeitüberschreitung: Verarbeitung dauerte länger als {t_out}s "
                                     "(Timeout im Admin-UI pro Modell konfigurierbar).")
                    task["completed_at"] = time.time()
                resp = {
                    "status": task["status"],
                    "progress": task["progress"],
                    "progress_step": task["progress_step"],
                }
                if task["status"] == "completed":
                    resp["result"] = task["result"]
                    tasks.pop(task_id, None)
                elif task["status"] == "failed":
                    resp["error"] = task["error"]
                    tasks.pop(task_id, None)
                return jsonify(resp)
        # Not ours — maybe an instance's task (proxied via the router).
        # The HTTP hop happens outside tasks_lock on purpose.
        if router is not None:
            proxied = router.proxy_task_status(task_id)
            if proxied is not None:
                return proxied
        return jsonify({"error": "Task not found"}), 404

    @app.route("/v1/models", methods=["GET"])
    def list_models():
        if not auth_fn():
            return jsonify({"error": {"message": "Invalid API key.", "type": "auth_error"}}), 401
        data = []
        if advertise_local_models:
            data.append({"id": "whisper-1", "object": "model", "owned_by": "local",
                         "description": f"{engine.name}/{engine.model}"})
            if model_alias:
                data.append({"id": model_alias, "object": "model", "owned_by": "local"})
            data.append({"id": engine.model, "object": "model", "owned_by": "local"})
        if router is not None:
            data.extend(router.instance_model_entries())
        # De-dupe by id (alias may equal the underlying model name)
        seen = set()
        data = [d for d in data if not (d["id"] in seen or seen.add(d["id"]))]
        return jsonify({"object": "list", "data": data})

    @app.route("/health", methods=["GET"])
    def health():
        with active_lock:
            n_active = active["n"]
        payload = {
            "status": "ok",
            "engine": engine.name,
            "model": engine.model,
            "device": engine.device,
            "compute_type": engine.compute_type,
            "supports_alignment": engine.supports_alignment,
            "supports_diarization": engine.supports_diarization and bool(engine.hf_token),
            "active_requests": n_active,
        }
        if health_extra is not None:
            try:
                payload.update(health_extra())
            except Exception:
                logger.exception("health_extra failed")
        return jsonify(payload)

    # Introspection for the caller (e.g. the main process idle watchdog).
    def _active_count() -> int:
        with active_lock:
            return active["n"]

    return {"active_count": _active_count}
