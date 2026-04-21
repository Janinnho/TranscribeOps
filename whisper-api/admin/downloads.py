"""HuggingFace model downloads with progress tracking in SQLite."""
import logging
import os
import threading
import time
from pathlib import Path

from .db import update_download, get_download
from .catalog import by_repo_id

logger = logging.getLogger("whisper-api.downloads")

HF_HOME_DIR = os.environ.get("HF_HOME", "/root/.cache/huggingface")
# huggingface_hub's snapshot_download expects the "hub" subdirectory as cache_dir
# to stay consistent with the default HF layout used by whisperx/pyannote.
HF_CACHE_DIR = os.path.join(HF_HOME_DIR, "hub")


def _snapshot_dirs(repo_id: str) -> list[Path]:
    """Return all candidate directories where a given repo's snapshot may live.

    Covers both the canonical `$HF_HOME/hub/models--…` layout and the legacy
    `$HF_HOME/models--…` layout (older versions of this code called
    snapshot_download with cache_dir=$HF_HOME directly).
    """
    slug = "models--" + repo_id.replace("/", "--")
    return [Path(HF_CACHE_DIR) / slug, Path(HF_HOME_DIR) / slug]


def _model_is_cached(repo_id: str) -> bool:
    for base in _snapshot_dirs(repo_id):
        snaps = base / "snapshots"
        if not snaps.exists():
            continue
        for snap in snaps.iterdir():
            if snap.is_dir() and any(snap.iterdir()):
                return True
    return False


def is_downloaded(repo_id: str) -> bool:
    return _model_is_cached(repo_id)


def disk_size_mb(repo_id: str) -> float:
    total = 0
    for base in _snapshot_dirs(repo_id):
        if not base.exists():
            continue
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
    target_dirs = _snapshot_dirs(repo_id)
    last_bytes = 0
    while not stop_evt.is_set():
        bytes_done = 0
        for target_dir in target_dirs:
            if not target_dir.exists():
                continue
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


# Pyannote repos that WhisperX loads in-process when a request asks for
# diarization. They require an HF token and accepted model licenses.
# We fetch them on first boot rather than at image-build time so the token
# stays runtime-only (no secret baked into image layers).
PYANNOTE_REPOS: tuple[str, ...] = (
    "pyannote/segmentation-3.0",
    "pyannote/speaker-diarization-3.1",
)


def ensure_pyannote_models(hf_token: str) -> None:
    """Synchronously download pyannote models if missing.

    Idempotent: if the snapshots are already in the HF cache we return fast.
    Called from the main process before the engine loads, so diarization is
    ready to use as soon as the HTTP server accepts requests.

    Never raises: missing token or network failures log a warning and let
    transcription continue without diarization.
    """
    missing = [r for r in PYANNOTE_REPOS if not _model_is_cached(r)]
    if not missing:
        return

    if not hf_token:
        logger.warning(
            "ensure_pyannote_models: HF_TOKEN not set — skipping pyannote download. "
            "Diarization will not be available. Missing: %s",
            ", ".join(missing),
        )
        return

    try:
        from huggingface_hub import snapshot_download
    except Exception as e:
        logger.warning("ensure_pyannote_models: huggingface_hub unavailable: %s", e)
        return

    for repo in missing:
        try:
            logger.info("ensure_pyannote_models: downloading %s ...", repo)
            snapshot_download(repo_id=repo, cache_dir=HF_CACHE_DIR, token=hf_token)
            logger.info("ensure_pyannote_models: %s ready.", repo)
        except Exception as e:
            logger.warning(
                "ensure_pyannote_models: failed to fetch %s: %s. "
                "Diarization may not work until this is resolved.",
                repo, e,
            )


def bundled_models_status() -> dict:
    """Report runtime presence of container-bundled alignment + diarization models.

    Used by the admin dashboard to show a single static "ships with the
    container" section instead of the old per-model download tiles.

    - Alignment: five torchaudio wav2vec2 bundles pre-fetched at image build
      time. We detect them by scanning `~/.cache/torch/hub/checkpoints/` for
      any `.pt` file — torchaudio's exact filename varies by version/bundle
      so we just report presence + count rather than a per-language match.
    - Diarization: the two pyannote repos in PYANNOTE_REPOS. Fetched on
      first boot by ensure_pyannote_models() iff HF_TOKEN is set.
    """
    import pathlib

    torch_ckpt_dir = pathlib.Path.home() / ".cache" / "torch" / "hub" / "checkpoints"
    # torchaudio saves wav2vec2 checkpoints with both `.pt` (voxpopuli bundles)
    # and `.pth` (fairseq base_960h) extensions — match either.
    try:
        torch_files = sorted(
            p.name for p in torch_ckpt_dir.iterdir()
            if p.is_file() and p.suffix in (".pt", ".pth")
        ) if torch_ckpt_dir.exists() else []
    except OSError:
        torch_files = []

    pyannote = [
        {"repo_id": r, "cached": _model_is_cached(r)}
        for r in PYANNOTE_REPOS
    ]

    return {
        "align": {
            "dir": str(torch_ckpt_dir),
            "files": torch_files,
            "count": len(torch_files),
            # We expect exactly 5 bundles from prefetch_torch_align.py.
            # Fewer means the build step missed something or the cache volume
            # was mounted over /root/.cache (clobbering the bundled files).
            "all_present": len(torch_files) >= 5,
        },
        "diarize": {
            "repos": pyannote,
            "all_present": all(p["cached"] for p in pyannote),
        },
    }


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
