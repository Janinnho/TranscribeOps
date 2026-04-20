"""HuggingFace model downloads with progress tracking in SQLite."""
import logging
import os
import threading
import time
from pathlib import Path

from .db import update_download, get_download
from .catalog import by_repo_id

logger = logging.getLogger("whisper-api.downloads")

HF_CACHE_DIR = os.environ.get("HF_HOME", "/root/.cache/huggingface")


def _model_is_cached(repo_id: str) -> bool:
    """Cheap heuristic: look for a snapshot directory under ~/.cache/huggingface/hub."""
    root = Path(HF_CACHE_DIR) / "hub"
    if not root.exists():
        return False
    slug = "models--" + repo_id.replace("/", "--")
    target = root / slug / "snapshots"
    if not target.exists():
        return False
    # A snapshot must have at least one file.
    for snap in target.iterdir():
        if snap.is_dir() and any(snap.iterdir()):
            return True
    return False


def is_downloaded(repo_id: str) -> bool:
    return _model_is_cached(repo_id)


def disk_size_mb(repo_id: str) -> float:
    root = Path(HF_CACHE_DIR) / "hub"
    slug = "models--" + repo_id.replace("/", "--")
    base = root / slug
    if not base.exists():
        return 0.0
    total = 0
    for p in base.rglob("*"):
        try:
            if p.is_file() and not p.is_symlink():
                total += p.stat().st_size
        except OSError:
            continue
    return round(total / (1024 * 1024), 1)


def start_download(db_path: str, download_id: int, repo_id: str, hf_token: str) -> None:
    """Spawn a background thread that calls huggingface_hub.snapshot_download."""
    t = threading.Thread(
        target=_run_download,
        args=(db_path, download_id, repo_id, hf_token),
        daemon=True,
        name=f"hf-download-{download_id}",
    )
    t.start()


def _run_download(db_path: str, download_id: int, repo_id: str, hf_token: str) -> None:
    update_download(db_path, download_id, status="downloading", progress=0.0)
    try:
        # Short-circuit if already cached.
        if _model_is_cached(repo_id):
            update_download(db_path, download_id, status="done", progress=100.0, finished_at=int(time.time()))
            logger.info(f"Repo '{repo_id}' already cached, marking done.")
            return

        from huggingface_hub import snapshot_download
        from huggingface_hub.utils import HfHubHTTPError

        # Progress: sample after calling snapshot_download blocks. Since snapshot_download
        # doesn't provide a granular Python callback without hf_transfer, we poll bytes on disk
        # in a watcher thread until the call returns.
        stop_evt = threading.Event()
        watcher = threading.Thread(
            target=_watch_progress,
            args=(db_path, download_id, repo_id, stop_evt),
            daemon=True,
        )
        watcher.start()

        try:
            snapshot_download(
                repo_id=repo_id,
                cache_dir=HF_CACHE_DIR,
                token=hf_token or None,
            )
        finally:
            stop_evt.set()
            watcher.join(timeout=3)

        update_download(
            db_path, download_id,
            status="done", progress=100.0, finished_at=int(time.time()),
        )
        logger.info(f"Download finished: {repo_id}")
    except Exception as e:
        logger.exception(f"Download failed: {repo_id}")
        update_download(
            db_path, download_id,
            status="failed", error=str(e), finished_at=int(time.time()),
        )


def _watch_progress(db_path: str, download_id: int, repo_id: str, stop_evt: threading.Event):
    """Poll the model's on-disk size while the download runs."""
    target_dir = Path(HF_CACHE_DIR) / "hub" / ("models--" + repo_id.replace("/", "--"))
    last_bytes = 0
    while not stop_evt.is_set():
        bytes_done = 0
        if target_dir.exists():
            for p in target_dir.rglob("*"):
                try:
                    if p.is_file() and not p.is_symlink():
                        bytes_done += p.stat().st_size
                except OSError:
                    continue
        if bytes_done != last_bytes:
            # We don't know the total upfront without extra calls; progress stays at an
            # "in progress" marker (50%) until we transition to 'done' (100%).
            update_download(
                db_path, download_id,
                bytes_done=bytes_done,
                progress=min(95.0, max(5.0, 5.0 + bytes_done / (1024 * 1024 * 30))),  # heuristic
            )
            last_bytes = bytes_done
        if stop_evt.wait(2):
            return


def catalog_status(db_path: str) -> list[dict]:
    """Return enriched catalog entries with download status + in-flight download id."""
    from .catalog import CATALOG
    from .db import active_download_for_repo

    out = []
    for entry in CATALOG:
        active = active_download_for_repo(db_path, entry.repo_id)
        out.append({
            "id": entry.id,
            "repo_id": entry.repo_id,
            "kind": entry.kind,
            "engine": entry.engine,
            "display_name": entry.display_name,
            "description": entry.description,
            "size_hint": entry.size_hint,
            "requires_hf_token": entry.requires_hf_token,
            "downloaded": is_downloaded(entry.repo_id),
            "disk_size_mb": disk_size_mb(entry.repo_id),
            "active_download": active,
        })
    return out
