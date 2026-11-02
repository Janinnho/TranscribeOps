"""Parakeet Ultra / Redux via sherpa-onnx (third whisper-api engine).

Moondream ships these models for the Photon runtime (CPU AVX-512 / Apple
Metal). Photon is a poor fit for this image: it is a separate stack from
the pinned torch/NeMo/WhisperX wheels, and it does not give us a Linux
server path that loads both Ultra and Redux. sherpa-onnx does. Its wheel
bundles ONNX Runtime and does not change those pins.

Catalog downloads are community ``nemo_transducer`` exports, not the
Photon/safetensors repos:

* Ultra — ``erponce/sherpa-onnx-parakeet-ultra-tdt-0.6b-v3-int8``
  (int8 encoder/decoder/joiner, ~653 MB). Same layout as the k2-fsa
  Parakeet TDT 0.6B v3 export, so other Ultra int8 bundles
  (tpmaerk, leogaudin, Olicorne) load too if they contain the four files.
* Redux — ``cohearo/sherpa-onnx-nemo-parakeet-redux`` (~397 MB). Loose
  files of the Codyfederer sherpa package; the encoder is eschmidbauer's
  ONNX export of the 178 MB ternary Photon weights, packed as MatMulNBits.

Both are CC-BY-4.0 (NVIDIA Parakeet TDT 0.6B v3, then Moondream).
sherpa-onnx 1.13.8 is the release those exports were checked against:
it detects TDT graphs from the ``tdt`` marker in the ONNX metadata.

The PyPI wheel is CPU-only (``-DSHERPA_ONNX_ENABLE_GPU`` is off). Asking
for CUDA makes sherpa print a fallback and keep running on CPU, so a
``cuda`` device would otherwise look healthy while never touching a GPU.
We probe that message and report the CPU fallback on /health.

Long audio is cut into short windows. Parakeet's encoder attention grows
with the square of the recording, and these ONNX graphs are the ones
captioning tools run in 20–30 s windows — not NeMo's 300 s slices.
"""
import inspect
import logging
import os
import subprocess
import tempfile
import time
import wave
from typing import Callable, Optional

import numpy as np

from .base import Engine, TranscriptionResult
from .dictionary import apply_dictionary, parse_prompt
from .nemo_engine import _diarize_words, _segments_from_words

logger = logging.getLogger("whisper-api.engine.parakeet_onnx")

# Catalog ids → sherpa-onnx HuggingFace repos (not the Photon repos).
MODEL_ID_MAP = {
    "parakeet-ultra": "erponce/sherpa-onnx-parakeet-ultra-tdt-0.6b-v3-int8",
    "parakeet-redux": "cohearo/sherpa-onnx-nemo-parakeet-redux",
}

# Official Moondream ids. snapshot_download of those repos fetches
# safetensors/Photon weights this engine cannot load.
_PHOTON_REPOS = {
    "moondream/parakeet-ultra": MODEL_ID_MAP["parakeet-ultra"],
    "moondream/parakeet-redux": MODEL_ID_MAP["parakeet-redux"],
}

# NeMo Parakeet TDT 0.6B v3 mel dimension. sherpa often overrides this
# from ONNX metadata; 128 matches the Ultra/Redux export cards.
_FEATURE_DIM = 128
_SAMPLE_RATE = 16000

_BUNDLE_STEMS = ("encoder", "decoder", "joiner")

_gpu_probe: Optional[bool] = None

# Half the visible CPUs was faster than 4 and faster than "all of them" on a
# 16-thread host. The cap stops a 32-thread box from oversubscribing the
# ONNX session; PARAKEET_ONNX_NUM_THREADS still overrides it.
_THREAD_CAP = 8
_logged_thread_choice: Optional[tuple] = None


def _available_cpus() -> int:
    """CPUs this process may run on. Affinity first, then ``cpu_count``."""
    try:
        cpus = os.sched_getaffinity(0)
    except (AttributeError, OSError):
        cpus = None
    else:
        if cpus:
            return len(cpus)
    count = os.cpu_count() or 1
    return count if count > 0 else 1


def _default_num_threads(available: int) -> tuple[int, bool]:
    """Return ``(threads, cap_applied)`` for an automatic thread count.

    Roughly half the available CPUs, at least 1, at most ``_THREAD_CAP``.
    ``cap_applied`` is true when the half was larger than the cap.
    """
    available = max(1, int(available))
    half = max(1, available // 2)
    if half > _THREAD_CAP:
        return _THREAD_CAP, True
    return half, False


def _num_threads() -> int:
    """sherpa-onnx intra-op threads.

    An explicit ``PARAKEET_ONNX_NUM_THREADS`` wins, including values above
    the cap. Otherwise use :func:`_default_num_threads`. The effective
    value is logged once per distinct choice, and again when the cap
    reduces the half-CPU default.
    """
    global _logged_thread_choice
    raw = os.environ.get("PARAKEET_ONNX_NUM_THREADS", "").strip()
    if raw:
        try:
            threads = max(1, int(raw))
        except ValueError:
            logger.warning(
                "PARAKEET_ONNX_NUM_THREADS=%r is not an integer; using the default.",
                raw,
            )
        else:
            choice = ("env", threads)
            if choice != _logged_thread_choice:
                logger.info(
                    "parakeet_onnx threads=%s (PARAKEET_ONNX_NUM_THREADS).",
                    threads,
                )
                _logged_thread_choice = choice
            return threads

    available = _available_cpus()
    threads, capped = _default_num_threads(available)
    choice = ("default", threads, available, capped)
    if choice != _logged_thread_choice:
        if capped:
            logger.info(
                "parakeet_onnx threads=%s (available CPUs=%s, half=%s, cap %s applies). "
                "Set PARAKEET_ONNX_NUM_THREADS to override.",
                threads, available, available // 2, _THREAD_CAP,
            )
        else:
            logger.info(
                "parakeet_onnx threads=%s (available CPUs=%s).",
                threads, available,
            )
        _logged_thread_choice = choice
    return threads


def _chunk_params() -> tuple[float, float]:
    """Window and overlap in seconds. Read per call so tests can override."""
    def _float(name: str, default: float) -> float:
        raw = os.environ.get(name, "").strip()
        if not raw:
            return default
        try:
            return float(raw)
        except ValueError:
            logger.warning("%s=%r is not a number; using %s.", name, raw, default)
            return default

    chunk = max(5.0, _float("PARAKEET_ONNX_CHUNK_SECS", 30.0))
    overlap = _float("PARAKEET_ONNX_CHUNK_OVERLAP_SECS", 2.0)
    overlap = max(0.0, min(overlap, chunk / 2.0))
    return chunk, overlap


def resolve_provider(device: str, *, gpu_available: bool, override: str = "") -> tuple[str, Optional[str]]:
    """Pick a sherpa execution provider.

    Returns ``(provider, german_note)``. ``provider`` is ``cpu`` or ``cuda``.
    The note is shown in the admin UI when the configured device is not
    what will actually run.
    """
    override = (override or "").strip().lower()
    wants_gpu = device.startswith("cuda") or device == "mps"

    if override == "cpu":
        note = "PARAKEET_ONNX_PROVIDER=cpu — Transkription läuft auf CPU." if wants_gpu else None
        return "cpu", note
    if override and override != "cuda":
        return "cpu", (
            f"PARAKEET_ONNX_PROVIDER={override} wird nicht unterstützt, läuft auf CPU."
        )

    use_cuda = override == "cuda" or device.startswith("cuda")
    if use_cuda:
        if gpu_available:
            note = None
            if device.startswith("cuda:") and device not in ("cuda", "cuda:0"):
                note = (
                    "sherpa-onnx nutzt das Standard-CUDA-Gerät, "
                    "nicht die Nummer im Device-Namen."
                )
            return "cuda", note
        return "cpu", (
            "sherpa-onnx in diesem Image ist ohne GPU gebaut (nur CPU). "
            "Parakeet Ultra/Redux laufen auf CPU. "
            "CUDA braucht ein sherpa-onnx mit -DSHERPA_ONNX_ENABLE_GPU=ON."
        )
    if device == "mps":
        return "cpu", "Parakeet ONNX nutzt in diesem Image kein MPS und läuft auf CPU."
    return "cpu", None


def gpu_provider_available() -> bool:
    """True when this sherpa-onnx build can actually create a CUDA session.

    The CPU wheel accepts ``provider='cuda'`` and then logs that it is
    falling back to CPU. Trusting the request would make /health report
    a GPU that is not in use. Cached for the process.
    """
    global _gpu_probe
    if _gpu_probe is None:
        _gpu_probe = _probe_gpu_provider()
    return _gpu_probe


def _probe_gpu_provider() -> bool:
    try:
        import sherpa_onnx
    except ImportError:
        return False

    read_fd, write_fd = os.pipe()
    saved = os.dup(2)
    try:
        os.dup2(write_fd, 2)
        try:
            # /dev/null exists, so the failure is "not an ONNX model"
            # rather than "file missing" — provider selection still runs
            # and the CPU wheel logs the GPU fallback first.
            sherpa_onnx.OfflineRecognizer.from_transducer(
                encoder=os.devnull,
                decoder=os.devnull,
                joiner=os.devnull,
                tokens=os.devnull,
                model_type="nemo_transducer",
                provider="cuda",
                num_threads=1,
            )
        except Exception:
            pass
    finally:
        os.dup2(saved, 2)
        os.close(saved)
        os.close(write_fd)

    os.set_blocking(read_fd, False)
    chunks: list[bytes] = []
    while True:
        try:
            data = os.read(read_fd, 1 << 16)
        except BlockingIOError:
            break
        if not data:
            break
        chunks.append(data)
    os.close(read_fd)
    text = b"".join(chunks).decode("utf-8", "replace")
    if not text or "Fallback to cpu" in text or "SHERPA_ONNX_ENABLE_GPU" in text:
        return False
    return "CUDAExecutionProvider" in text


def _pick_onnx(directory: str, stem: str) -> Optional[str]:
    """Prefer the int8 file. Redux publishes float names; Ultra publishes int8."""
    for name in (f"{stem}.int8.onnx", f"{stem}.onnx"):
        path = os.path.join(directory, name)
        if os.path.isfile(path):
            return path
    return None


def _bundle_in_dir(directory: str) -> Optional[dict]:
    paths = {stem: _pick_onnx(directory, stem) for stem in _BUNDLE_STEMS}
    tokens = os.path.join(directory, "tokens.txt")
    if not all(paths.values()) or not os.path.isfile(tokens):
        return None
    paths["tokens"] = tokens
    return paths


def _find_bundle_in_tree(root: str) -> Optional[dict]:
    direct = _bundle_in_dir(root)
    if direct:
        return direct
    try:
        names = sorted(os.listdir(root))
    except OSError:
        return None
    for name in names:
        child = os.path.join(root, name)
        # HF snapshots are full of file symlinks; only step into real dirs.
        if os.path.isdir(child) and not os.path.islink(child):
            hit = _bundle_in_dir(child)
            if hit:
                return hit
    return None


def repo_for_model(model: str) -> Optional[str]:
    """Map a catalog id or Photon repo id to the sherpa-onnx repo.

    Returns None when ``model`` is a local directory or already a repo id
    we should download as-is. Unknown bare names raise.
    """
    if os.path.isdir(model):
        return None
    if model in MODEL_ID_MAP:
        return MODEL_ID_MAP[model]
    if model in _PHOTON_REPOS:
        logger.warning(
            "Model '%s' is the Photon/safetensors repo; using sherpa-onnx export '%s'.",
            model, _PHOTON_REPOS[model],
        )
        return _PHOTON_REPOS[model]
    if "/" in model:
        return model
    known = ", ".join(sorted(MODEL_ID_MAP))
    raise RuntimeError(
        f"Unbekanntes Parakeet-ONNX-Modell '{model}'. "
        f"Katalog-IDs: {known}. Oder ein HuggingFace-Repo mit "
        "encoder/decoder/joiner (.onnx oder .int8.onnx) und tokens.txt."
    )


def _snapshot_dirs(repo: str, hf_home: str) -> list[str]:
    slug = "models--" + repo.replace("/", "--")
    bases = [
        os.path.join(hf_home, "hub", slug, "snapshots"),
        os.path.join(hf_home, slug, "snapshots"),
    ]
    found = []
    for base in bases:
        if not os.path.isdir(base):
            continue
        for name in os.listdir(base):
            snap = os.path.join(base, name)
            if os.path.isdir(snap):
                found.append(snap)
    found.sort(key=lambda p: os.path.getmtime(p), reverse=True)
    return found


def _default_download(repo: str, hf_home: str, token: str) -> None:
    from huggingface_hub import snapshot_download
    snapshot_download(
        repo_id=repo,
        cache_dir=os.path.join(hf_home, "hub"),
        token=token or None,
    )


def locate_bundle(
    model: str,
    *,
    hf_home: Optional[str] = None,
    token: str = "",
    download_fn: Optional[Callable[..., None]] = None,
) -> dict:
    """Find encoder/decoder/joiner/tokens for ``model``.

    ``download_fn(repo, hf_home, token)`` defaults to ``snapshot_download``
    into the same HF hub cache the admin UI uses.
    """
    if os.path.isdir(model):
        bundle = _find_bundle_in_tree(model)
        if bundle:
            return bundle
        raise RuntimeError(
            f"Verzeichnis '{model}' enthält kein sherpa-onnx-Paket "
            "(encoder/decoder/joiner als .onnx oder .int8.onnx, plus tokens.txt)."
        )

    repo = repo_for_model(model)
    home = hf_home or os.environ.get("HF_HOME", os.path.expanduser("~/.cache/huggingface"))
    for snap in _snapshot_dirs(repo, home):
        bundle = _find_bundle_in_tree(snap)
        if bundle:
            return bundle

    downloader = download_fn or _default_download
    logger.info("sherpa-onnx bundle for '%s' not cached; downloading %s", model, repo)
    downloader(repo, home, token)
    for snap in _snapshot_dirs(repo, home):
        bundle = _find_bundle_in_tree(snap)
        if bundle:
            return bundle
    raise RuntimeError(
        f"Kein sherpa-onnx-Paket für '{model}' im Repo '{repo}' gefunden. "
        "Erwartet werden encoder(.int8).onnx, decoder(.int8).onnx, "
        "joiner(.int8).onnx und tokens.txt. "
        "Im Admin-UI das Katalogmodell herunterladen."
    )


def words_from_tokens(tokens, timestamps) -> list[dict]:
    """Group sherpa BPE pieces into ``{word, start, end}``.

    sherpa-onnx 1.13 returns Parakeet pieces with a leading space at each
    word (``' G'``, ``'uten'``, ``' Tag'``). Some exports still use the
    SentencePiece ``▁`` marker. Times are seconds.
    """
    words: list[dict] = []
    cur: Optional[dict] = None
    n = min(len(tokens), len(timestamps))
    for i in range(n):
        raw = "" if tokens[i] is None else str(tokens[i])
        if not raw:
            continue
        try:
            ts = float(timestamps[i])
        except (TypeError, ValueError):
            continue
        starts_word = False
        piece = raw
        if raw.startswith("▁"):
            starts_word = True
            piece = raw[1:]
        elif raw[:1].isspace():
            starts_word = True
            piece = raw.lstrip()
        elif cur is None:
            starts_word = True
        if not piece or (piece.startswith("<") and piece.endswith(">")):
            continue
        if starts_word:
            if cur is not None:
                cur["end"] = max(cur["end"], ts)
            cur = {"word": piece, "start": ts, "end": ts}
            words.append(cur)
        else:
            cur["word"] += piece
            cur["end"] = ts
    if words:
        last = words[-1]
        if last["end"] <= last["start"]:
            last["end"] = last["start"] + 0.08
    return [w for w in words if w.get("word")]


def merge_chunk_words(
    previous: list[dict],
    new_words: list[dict],
    chunk_start: float,
    overlap: float,
) -> list[dict]:
    """Drop the duplicated half of an overlap. Mutates ``previous``.

    The seam sits in the middle of the overlap. Words that start before
    it stay with the previous window; words that start on or after it
    come from this window. No-op when this window has no timestamps —
    deleting the previous tail with nothing to replace it would punch
    a hole in the transcript.
    """
    if overlap <= 0 or not new_words:
        return new_words
    seam = chunk_start + overlap / 2.0
    while previous and previous[-1]["start"] >= seam:
        previous.pop()
    return [w for w in new_words if w["start"] >= seam]


def _to_mono_wav(src_path: str) -> tuple[str, bool]:
    fd, dst = tempfile.mkstemp(suffix=".wav", prefix="parakeet_onnx_")
    os.close(fd)
    try:
        subprocess.run(
            [
                "ffmpeg", "-nostdin", "-y", "-loglevel", "error",
                "-i", src_path,
                "-ac", "1",
                "-ar", str(_SAMPLE_RATE),
                "-c:a", "pcm_s16le",
                dst,
            ],
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
        )
    except subprocess.CalledProcessError as e:
        try:
            os.unlink(dst)
        except OSError:
            pass
        stderr = e.stderr.decode("utf-8", errors="replace") if e.stderr else ""
        raise RuntimeError(
            f"ffmpeg failed to convert {src_path} to mono WAV: {stderr.strip()}"
        ) from e
    return dst, True


def _read_f32(path: str) -> tuple[int, np.ndarray]:
    """Read a mono 16-bit PCM WAV into a float32 array in ``[-1, 1]``.

    ``int16 / 32768`` is exact in float32 (a power-of-two scale), so these
    values match the Python floats the old per-window reader produced.
    """
    with wave.open(path, "rb") as handle:
        if handle.getnchannels() != 1 or handle.getsampwidth() != 2:
            raise RuntimeError(f"expected mono 16-bit WAV, got {path}")
        rate = handle.getframerate() or _SAMPLE_RATE
        raw = handle.readframes(handle.getnframes())
    if not raw:
        return rate, np.empty(0, dtype=np.float32)
    # WAV PCM is little-endian. frombuffer shares ``raw``; astype copies.
    samples = np.frombuffer(raw, dtype="<i2").astype(np.float32)
    samples /= np.float32(32768.0)
    return rate, samples


def _window_f32(samples: np.ndarray, rate: int, start: float, length: float) -> np.ndarray:
    """Slice ``[start, start+length)`` the way the old ffmpeg window did.

    That command passed ``-ss`` and ``-t`` formatted to milliseconds
    (``:.3f``). At 16 kHz a millisecond is 16 samples, so the quantized
    timestamp lands on a sample; ``round`` absorbs the binary error in
    ``0.001 * 16000``. The slice is a view — sherpa copies it in.
    """
    if rate <= 0 or samples.size == 0 or length <= 0:
        return samples[:0]
    start_q = float(f"{start:.3f}")
    length_q = float(f"{length:.3f}")
    if length_q <= 0:
        return samples[:0]
    start_i = int(round(start_q * rate))
    count = int(round(length_q * rate))
    if count <= 0 or start_i >= samples.size:
        return samples[:0]
    if start_i < 0:
        start_i = 0
    end = min(samples.size, start_i + count)
    return samples[start_i:end]


def _log_phases(duration: float, convert_s: float, decode_s: float, diarize_s: float) -> None:
    """One line for short and long audio: duration, phase times, RTF."""
    elapsed = convert_s + decode_s + diarize_s
    rtf = (elapsed / duration) if duration and duration > 0 else 0.0
    logger.info(
        "Audio is %.2fs — convert=%.3fs decode=%.3fs diarize=%.3fs rtf=%.3f",
        duration or 0.0, convert_s, decode_s, diarize_s, rtf,
    )


class ParakeetOnnxEngine(Engine):
    """sherpa-onnx engine for Moondream Parakeet Ultra and Parakeet Redux."""

    name = "parakeet_onnx"
    supports_alignment = False
    # Word times are real, so pyannote can label them the same way NeMo does.
    # The CPU sherpa wheel does not change that: diarization is still torch.
    supports_diarization = True

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._recognizer = None
        self._bundle: Optional[dict] = None
        self._diarize_pipeline = None

    def _build_recognizer(self, provider: str):
        import sherpa_onnx
        kwargs = {
            "encoder": self._bundle["encoder"],
            "decoder": self._bundle["decoder"],
            "joiner": self._bundle["joiner"],
            "tokens": self._bundle["tokens"],
            "num_threads": _num_threads(),
            "sample_rate": _SAMPLE_RATE,
            "feature_dim": _FEATURE_DIM,
            "decoding_method": "greedy_search",
            "model_type": "nemo_transducer",
            "provider": provider,
        }
        params = inspect.signature(sherpa_onnx.OfflineRecognizer.from_transducer).parameters
        accepted = {key: value for key, value in kwargs.items() if key in params}
        missing = [key for key in ("encoder", "decoder", "joiner", "tokens") if key not in accepted]
        if missing:
            raise RuntimeError(
                "Diese sherpa-onnx-Version kennt from_transducer nicht in der "
                f"erwarteten Form (fehlend: {', '.join(missing)})."
            )
        if "model_type" not in accepted:
            raise RuntimeError(
                "Diese sherpa-onnx-Version kann model_type='nemo_transducer' nicht setzen. "
                "Benötigt wird sherpa-onnx 1.13.8 (Parakeet-TDT-Metadaten)."
            )
        return sherpa_onnx.OfflineRecognizer.from_transducer(**accepted)

    def load(self) -> None:
        try:
            import sherpa_onnx  # noqa: F401
        except ImportError as e:
            raise RuntimeError(
                "sherpa-onnx ist nicht installiert — Parakeet Ultra/Redux brauchen "
                "die Engine parakeet_onnx. Im Whisper-Image kommt das Paket aus "
                "requirements.txt (sherpa-onnx==1.13.8) und ändert die "
                "WhisperX-/NeMo-Pins nicht."
            ) from e

        self._bundle = locate_bundle(self.model, token=self.hf_token)
        provider, note = resolve_provider(
            self.device,
            gpu_available=gpu_provider_available(),
            override=os.environ.get("PARAKEET_ONNX_PROVIDER", ""),
        )
        if provider != "cuda" and self.device != "cpu":
            self.device = "cpu"
        elif provider == "cuda" and not str(self.device).startswith("cuda"):
            self.device = "cuda"
        if note:
            self.device_note = note
            logger.warning(note)

        logger.info(
            "Loading parakeet_onnx '%s' via %s (provider=%s, compute_type=%s ignored, threads=%s)",
            self.model, self._bundle["encoder"], provider, self.compute_type, _num_threads(),
        )
        try:
            self._recognizer = self._build_recognizer(provider)
        except Exception as e:
            if provider == "cpu":
                raise
            self.device = "cpu"
            self.device_note = (
                f"sherpa-onnx Provider '{provider}' fehlgeschlagen, läuft auf CPU: {e}"
            )[:500]
            logger.warning(self.device_note)
            self._recognizer = self._build_recognizer("cpu")
        logger.info("parakeet_onnx model '%s' loaded.", self.model)

    def _decode_samples(self, rate: int, samples) -> tuple[str, list[dict]]:
        # ``samples`` is a float32 numpy array. sherpa-onnx 1.13.8 takes
        # std::vector<float>; pybind copies the array. A Python list of
        # one float per sample is the path this replaced.
        if samples is None or len(samples) == 0:
            return "", []
        stream = self._recognizer.create_stream()
        stream.accept_waveform(rate, samples)
        self._recognizer.decode_stream(stream)
        result = stream.result
        text = (getattr(result, "text", "") or "").strip()
        tokens = list(getattr(result, "tokens", []) or [])
        timestamps = list(getattr(result, "timestamps", []) or [])
        words = words_from_tokens(tokens, timestamps)
        if not text and words:
            text = " ".join(word["word"] for word in words)
        return text, words

    def _transcribe_chunked(self, samples: np.ndarray, rate: int, duration: float, prog) -> tuple[str, list[dict]]:
        chunk, overlap = _chunk_params()
        starts: list[float] = []
        cursor = 0.0
        while cursor < duration - 1e-3:
            starts.append(cursor)
            cursor += chunk
        if len(starts) > 1 and duration - starts[-1] <= overlap:
            starts.pop()
        logger.info(
            "Audio is %.0fs — parakeet_onnx using %s window(s) of %.0fs (+%.1fs overlap).",
            duration, len(starts), chunk, overlap,
        )

        all_words: list[dict] = []
        texts: list[str] = []
        for index, start in enumerate(starts):
            length = min(chunk + overlap, max(0.0, duration - start))
            window = _window_f32(samples, rate, start, length)
            text, words = self._decode_samples(rate, window)
            for word in words:
                word["start"] += start
                word["end"] += start
            if index > 0:
                words = merge_chunk_words(all_words, words, start, overlap)
            all_words.extend(words)
            if text:
                texts.append(text.strip())
            prog(5 + int(60 * (index + 1) / len(starts)), "transcribe")

        if all_words:
            return " ".join(word["word"] for word in all_words).strip(), all_words
        return " ".join(text for text in texts if text), []

    def _get_diarize_pipeline(self):
        if self._diarize_pipeline is not None:
            return self._diarize_pipeline
        if not self.hf_token:
            return None
        from whisperx.diarize import DiarizationPipeline
        logger.info("Loading diarization pipeline...")
        self._diarize_pipeline = DiarizationPipeline(
            model_name="pyannote/speaker-diarization-3.1",
            token=self.hf_token,
            device=self.device,
        )
        return self._diarize_pipeline

    def transcribe(
        self,
        audio_path: str,
        language: Optional[str] = None,
        enable_diarize: bool = False,
        prompt: Optional[str] = None,
        progress_cb: Optional[Callable[[int, str], None]] = None,
    ) -> TranscriptionResult:
        if self._recognizer is None:
            self.load()

        def _prog(percent, step=None):
            if progress_cb:
                progress_cb(percent, step)

        # Parakeet TDT picks the language itself (25 European languages).
        # The request language is recorded, not forced.
        reported = (language or "").strip() or "auto"

        _prog(5, "transcribe")
        convert_s = decode_s = diarize_s = 0.0
        duration = 0.0
        mono_path = None
        is_tmp = False
        try:
            t_convert = time.perf_counter()
            try:
                mono_path, is_tmp = _to_mono_wav(audio_path)
                rate, samples = _read_f32(mono_path)
                duration = (len(samples) / float(rate)) if rate else 0.0
            finally:
                convert_s = time.perf_counter() - t_convert
            chunk, _overlap = _chunk_params()
            t_decode = time.perf_counter()
            try:
                if duration > chunk:
                    text, words = self._transcribe_chunked(samples, rate, duration, _prog)
                else:
                    text, words = self._decode_samples(rate, samples)
                _prog(70, "postprocess")

                dict_words = parse_prompt(prompt) if prompt else []
                if dict_words and words:
                    replacements = apply_dictionary(words, dict_words)
                    if replacements:
                        logger.info("Applied %s dictionary replacement(s).", replacements)
                        words = [word for word in words if word["word"]]
                        text = " ".join(word["word"] for word in words)
            finally:
                decode_s = time.perf_counter() - t_decode

            with_speaker = False
            if enable_diarize and words:
                try:
                    pipeline = self._get_diarize_pipeline()
                except Exception as e:
                    pipeline = None
                    logger.warning("Diarization unavailable (continuing without): %s", e)
                if pipeline is None:
                    if not self.hf_token:
                        logger.warning("Diarization requested but no HF_TOKEN — skipping.")
                else:
                    _prog(80, "diarize")
                    t_diarize = time.perf_counter()
                    try:
                        import whisperx
                        audio = whisperx.load_audio(mono_path)
                        diarize_df = pipeline(audio)
                        _diarize_words(words, diarize_df)
                        with_speaker = True
                    except Exception as e:
                        logger.warning("Diarization failed (continuing without): %s", e)
                    finally:
                        diarize_s = time.perf_counter() - t_diarize
        finally:
            # Short clips used to log nothing. Always record duration and
            # the three phases once conversion has produced a file.
            if mono_path is not None:
                _log_phases(duration, convert_s, decode_s, diarize_s)
            if is_tmp and mono_path:
                try:
                    os.unlink(mono_path)
                except OSError:
                    pass

        _prog(95)
        if words:
            segments = _segments_from_words(words, with_speaker=with_speaker)
        elif text:
            segments = [{"id": 0, "start": 0.0, "end": 0.0, "text": text}]
        else:
            segments = []
        _prog(100)
        return TranscriptionResult(
            text=(text or "").strip(),
            language=reported,
            segments=segments,
        )
