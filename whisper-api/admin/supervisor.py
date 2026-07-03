"""Instance lifecycle management.

An "instance" is a subprocess running worker.py, serving /v1/* on its own port.
Started/stopped on demand, respawned on main-process startup.
"""
import logging
import os
import signal
import socket
import subprocess
import sys
import time
from pathlib import Path
from typing import Optional

import requests

from . import db as admin_db

logger = logging.getLogger("whisper-api.supervisor")

_config = {
    "db_path": None,
    "port_range": "8100-8120",
    "hf_token": "",
}

# pid -> subprocess.Popen so we can reap children cleanly on shutdown
_children: dict[int, subprocess.Popen] = {}


def configure(*, db_path: str, port_range: str, hf_token: str) -> None:
    _config["db_path"] = db_path
    _config["port_range"] = port_range
    _config["hf_token"] = hf_token


def _port_range_tuple() -> tuple[int, int]:
    raw = _config["port_range"]
    try:
        lo, hi = raw.split("-", 1)
        return int(lo), int(hi)
    except Exception:
        return 8100, 8120


def _is_port_free(port: int) -> bool:
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        s.bind(("127.0.0.1", port))
        return True
    except OSError:
        return False
    finally:
        s.close()


def allocate_port() -> int:
    lo, hi = _port_range_tuple()
    used = admin_db.used_ports(_config["db_path"])
    for p in range(lo, hi + 1):
        if p in used:
            continue
        if not _is_port_free(p):
            continue
        return p
    raise RuntimeError(f"No free port available in range {lo}-{hi}")


def start_instance(instance_id: int) -> Optional[int]:
    row = admin_db.get_instance(_config["db_path"], instance_id)
    if row is None:
        raise ValueError(f"Instance {instance_id} not found")

    # Already running?
    pid = row.get("pid")
    if pid and _pid_alive(pid):
        return pid

    worker_path = Path(__file__).resolve().parent.parent / "worker.py"
    cmd = [
        sys.executable, str(worker_path),
        "--port", str(row["port"]),
        "--engine", row["engine"],
        "--model", row["model"],
        "--alias", row["name"],
        "--instance-id", str(row["id"]),
        "--device", row["device"],
        "--compute-type", row["compute_type"],
        "--db-path", _config["db_path"],
    ]
    env = os.environ.copy()
    env["HF_TOKEN"] = _config["hf_token"] or env.get("HF_TOKEN", "")

    logger.info(f"Starting instance {instance_id} ({row['name']}): {' '.join(cmd)}")
    proc = subprocess.Popen(cmd, env=env)
    _children[proc.pid] = proc
    admin_db.update_instance_pid(_config["db_path"], instance_id, proc.pid)
    admin_db.update_instance_enabled(_config["db_path"], instance_id, True)
    return proc.pid


def stop_instance(instance_id: int, *, disable: bool = True) -> bool:
    row = admin_db.get_instance(_config["db_path"], instance_id)
    if row is None:
        return False
    pid = row.get("pid")
    if pid and _pid_alive(pid):
        _terminate_pid(pid)
    admin_db.update_instance_pid(_config["db_path"], instance_id, None)
    if disable:
        admin_db.update_instance_enabled(_config["db_path"], instance_id, False)
    return True


def delete_instance(instance_id: int) -> None:
    stop_instance(instance_id, disable=True)
    admin_db.delete_instance(_config["db_path"], instance_id)


def respawn_enabled() -> None:
    if not _config["db_path"]:
        return
    # Stored PIDs are from the previous container lifecycle — even if a PID
    # number happens to be "alive" in this new /proc namespace, it's a
    # different process. Zero them out before the liveness check so we
    # don't skip instances whose old PID collides with e.g. the gunicorn
    # master or a sibling we just spawned in this same loop.
    instances = admin_db.list_instances(_config["db_path"], enabled_only=True)
    for row in instances:
        if row.get("pid") is not None:
            admin_db.update_instance_pid(_config["db_path"], row["id"], None)
    for row in instances:
        try:
            start_instance(row["id"])
        except Exception as e:
            logger.error(f"Failed to respawn instance {row['id']}: {e}")


def ensure_running(instance_id: int, wait_secs: int = 300) -> bool:
    """Start an instance if needed and wait until /health answers.

    Used by the router to wake sleeping (idle-unloaded) instances on demand.
    Returns True once the worker serves /health, False on timeout/failure.
    """
    row = admin_db.get_instance(_config["db_path"], instance_id)
    if row is None:
        return False
    pid = row.get("pid")
    if not (pid and _pid_alive(pid)):
        try:
            start_instance(instance_id)
        except Exception as e:
            logger.error(f"ensure_running: start of instance {instance_id} failed: {e}")
            return False
    deadline = time.time() + wait_secs
    while time.time() < deadline:
        try:
            r = requests.get(f"http://127.0.0.1:{row['port']}/health", timeout=2)
            if r.status_code == 200:
                return True
        except Exception:
            pass
        time.sleep(2)
    logger.error(f"ensure_running: instance {instance_id} did not become healthy within {wait_secs}s")
    return False


def idle_watchdog_tick() -> None:
    """Stop instances that exceeded their idle_unload_secs without traffic.

    Only stops workers that are reachable and report zero active requests —
    a long-running transcription updates last_used_at only at start/end, so
    the health check is what protects mid-flight work.
    """
    now = time.time()
    for row in admin_db.list_instances(_config["db_path"], enabled_only=True):
        idle = row.get("idle_unload_secs") or 0
        if idle <= 0:
            continue
        pid = row.get("pid")
        if not (pid and _pid_alive(pid)):
            continue
        last = row.get("last_used_at") or row.get("created_at") or 0
        if now - last < idle:
            continue
        try:
            r = requests.get(f"http://127.0.0.1:{row['port']}/health", timeout=2)
            if not r.ok or r.json().get("active_requests", 0) > 0:
                continue
        except Exception:
            continue  # unreachable/starting — don't kill blindly
        logger.info(f"Idle-unload: stopping instance {row['id']} ({row['name']}) "
                    f"after {int(now - last)}s without traffic.")
        stop_instance(row["id"], disable=False)


def start_idle_watchdog(interval_secs: int = 60) -> None:
    import threading

    def _loop():
        while True:
            time.sleep(interval_secs)
            try:
                idle_watchdog_tick()
            except Exception:
                logger.exception("idle_watchdog_tick failed")

    threading.Thread(target=_loop, daemon=True, name="instance-idle-watchdog").start()


def stop_all() -> None:
    for pid, proc in list(_children.items()):
        try:
            _terminate_pid(pid)
        except Exception:
            pass
        _children.pop(pid, None)


def _pid_alive(pid: int) -> bool:
    try:
        import psutil
        return psutil.pid_exists(pid) and psutil.Process(pid).status() != psutil.STATUS_ZOMBIE
    except Exception:
        try:
            os.kill(pid, 0)
            return True
        except OSError:
            return False


def _terminate_pid(pid: int) -> None:
    try:
        os.kill(pid, signal.SIGTERM)
    except OSError:
        return
    # Grace period
    deadline = time.time() + 30
    while time.time() < deadline and _pid_alive(pid):
        time.sleep(0.5)
    if _pid_alive(pid):
        try:
            os.kill(pid, signal.SIGKILL)
        except OSError:
            pass


def instance_status(row: dict) -> dict:
    pid = row.get("pid")
    alive = bool(pid and _pid_alive(pid))
    health = None
    cpu_pct = None
    rss_mb = None

    if alive:
        try:
            r = requests.get(f"http://127.0.0.1:{row['port']}/health", timeout=1.5)
            if r.status_code == 200:
                health = r.json()
        except Exception:
            health = None
        try:
            import psutil
            p = psutil.Process(pid)
            cpu_pct = p.cpu_percent(interval=0.0)
            rss_mb = round(p.memory_info().rss / (1024 * 1024), 1)
        except Exception:
            pass

    if not alive and row.get("enabled"):
        # With idle-unload configured, "enabled but not running" is the
        # expected resting state (the router starts it on demand) — a real
        # crash is indistinguishable here and also just gets restarted on
        # the next request.
        status = "sleeping" if (row.get("idle_unload_secs") or 0) > 0 else "crashed"
    elif alive:
        status = "running"
    else:
        status = "stopped"

    return {
        "id": row["id"],
        "name": row["name"],
        "engine": row["engine"],
        "model": row["model"],
        "purpose": row["purpose"],
        "device": row["device"],
        "compute_type": row["compute_type"],
        "port": row["port"],
        "pid": pid,
        "enabled": bool(row.get("enabled")),
        "status": status,
        "health": health,
        "cpu_pct": cpu_pct,
        "rss_mb": rss_mb,
        "timeout_secs": row.get("timeout_secs") or 0,
        "idle_unload_secs": row.get("idle_unload_secs") or 0,
        "last_used_at": row.get("last_used_at"),
    }
