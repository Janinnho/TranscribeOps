"""Accelerator detection: resolves ``device=auto`` and describes the hardware.

Deliberately import-light — torch is imported lazily inside the probe so that
importing this module stays cheap for worker.py's argument parsing and for
rendering admin pages. The probe result is cached because importing torch costs
a couple of seconds and the dashboard asks on every page view.

ROCm note: PyTorch's ROCm build exposes AMD cards through the *CUDA* API —
``torch.cuda.is_available()`` is True and the device string is ``"cuda"`` on an
AMD card. ``torch.version.hip`` is what tells the two apart, and it only
matters for what we display; the device string stays ``"cuda"`` either way.

CTranslate2 caveat: faster-whisper (and therefore the WhisperX engine) runs on
CTranslate2, which has no HIP/ROCm backend at all. On an AMD box torch reports
a usable "cuda" device that CTranslate2 cannot touch — hence
``ctranslate2_has_cuda()``, which the WhisperX engine uses to fall back to CPU
for the ASR pass with a visible note instead of a cryptic crash.
"""
import logging
import threading

logger = logging.getLogger("whisper-api.hardware")

AUTO = "auto"

# Device strings the admin UI and API accept. Anything starting with "cuda"
# is allowed too, so an explicit "cuda:1" reaches torch untouched.
KNOWN_DEVICES = (AUTO, "cpu", "cuda", "mps")

_probe_cache: dict | None = None
_probe_lock = threading.Lock()

_ct2_cache: bool | None = None
_ct2_lock = threading.Lock()


def _probe_uncached() -> dict:
    info = {
        "backend": "cpu",       # 'rocm' | 'cuda' | 'mps' | 'cpu'
        "device": "cpu",        # what detect_device() would pick
        "gpu_name": None,
        "gpu_memory_gb": None,
        "gpu_count": 0,
        "torch_version": None,
        "cuda_version": None,
        "hip_version": None,
        "error": None,
    }
    try:
        import torch
    except Exception as e:
        info["error"] = f"torch not importable: {e}"
        return info

    info["torch_version"] = getattr(torch, "__version__", None)
    info["cuda_version"] = getattr(torch.version, "cuda", None)
    info["hip_version"] = getattr(torch.version, "hip", None)

    try:
        if torch.cuda.is_available():
            info["device"] = "cuda"
            # A ROCm wheel sets torch.version.hip and leaves .cuda at None.
            info["backend"] = "rocm" if info["hip_version"] else "cuda"
            info["gpu_count"] = torch.cuda.device_count()
            props = torch.cuda.get_device_properties(0)
            info["gpu_name"] = props.name
            info["gpu_memory_gb"] = round(props.total_memory / (1024 ** 3), 1)
            return info
    except Exception as e:
        # A half-configured ROCm install (missing kfd, unsupported gfx arch)
        # throws right here. Report it instead of silently claiming CPU.
        info["error"] = f"GPU probe failed: {e}"

    try:
        if torch.backends.mps.is_available():
            info["device"] = "mps"
            info["backend"] = "mps"
            info["gpu_name"] = "Apple Silicon (MPS)"
            info["gpu_count"] = 1
    except Exception:
        pass

    return info


def probe(refresh: bool = False) -> dict:
    """Cached hardware description. Safe to call from request handlers."""
    global _probe_cache
    with _probe_lock:
        if _probe_cache is None or refresh:
            _probe_cache = _probe_uncached()
        return dict(_probe_cache)


def detect_device() -> str:
    """Best available torch device: 'cuda' (NVIDIA *or* AMD/ROCm), 'mps', 'cpu'."""
    return probe()["device"]


def resolve_device(device: str) -> str:
    """Map 'auto' onto real hardware; pass every explicit choice through.

    Explicit values are never second-guessed — someone who wrote 'cuda' gets
    'cuda', even on a box where the probe finds nothing. Downgrading that
    silently is how a misconfiguration turns into a mystery.
    """
    d = (device or "").strip()
    if not d:
        return "cpu"
    if d.lower() == AUTO:
        resolved = detect_device()
        logger.info(f"device=auto resolved to '{resolved}' ({probe()['backend']}).")
        return resolved
    return d


def ctranslate2_has_cuda() -> bool:
    """True when the installed CTranslate2 can actually use a GPU.

    False on CPU-only wheels *and* on every AMD/ROCm setup — CTranslate2 has
    no HIP backend, so torch reporting a 'cuda' device says nothing about it.
    """
    global _ct2_cache
    with _ct2_lock:
        if _ct2_cache is None:
            try:
                import ctranslate2
                _ct2_cache = ctranslate2.get_cuda_device_count() > 0
            except Exception as e:
                logger.debug(f"CTranslate2 CUDA probe failed: {e}")
                _ct2_cache = False
        return _ct2_cache


def describe(info: dict | None = None) -> str:
    """One-line human summary for logs and the dashboard."""
    info = info or probe()
    if info["backend"] == "cpu":
        return "CPU" + (f" ({info['error']})" if info.get("error") else "")
    parts = [info.get("gpu_name") or info["backend"].upper()]
    if info.get("gpu_memory_gb"):
        parts.append(f"{info['gpu_memory_gb']} GB")
    if info["backend"] == "rocm":
        parts.append(f"ROCm {info.get('hip_version') or '?'}")
    elif info["backend"] == "cuda":
        parts.append(f"CUDA {info.get('cuda_version') or '?'}")
    if info.get("gpu_count", 0) > 1:
        parts.append(f"{info['gpu_count']}x")
    return " · ".join(parts)
