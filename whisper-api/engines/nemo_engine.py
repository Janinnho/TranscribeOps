import logging
import os
import subprocess
import tempfile
from typing import Optional, Callable

from .base import Engine, TranscriptionResult

logger = logging.getLogger("whisper-api.engine.nemo")


def _to_mono_wav(src_path: str) -> tuple[str, bool]:
    """Convert src_path to a mono 16 kHz PCM-WAV in a tempfile.

    NeMo's AudioToBPEDataset expects `(batch, time)` tensors — stereo inputs
    come back as `(batch, time, 2)` and the model rejects them. WhisperX
    sidesteps this by resampling with ffmpeg internally; for NeMo we have
    to do it ourselves. Returns `(path, is_tempfile)` — caller unlinks when
    the second value is True.
    """
    fd, dst = tempfile.mkstemp(suffix=".wav", prefix="nemo_mono_")
    os.close(fd)
    try:
        subprocess.run(
            [
                "ffmpeg", "-nostdin", "-y", "-loglevel", "error",
                "-i", src_path,
                "-ac", "1",        # downmix to mono
                "-ar", "16000",    # resample to 16 kHz (NeMo standard)
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


class NeMoEngine(Engine):
    """NVIDIA NeMo ASR engine (Parakeet family)."""

    name = "nemo"
    supports_alignment = False
    supports_diarization = False

    MODEL_ID_MAP = {
        "parakeet-tdt-0.6b-v3": "nvidia/parakeet-tdt-0.6b-v3",
        "parakeet-tdt-0.6b-v2": "nvidia/parakeet-tdt-0.6b-v2",
        "parakeet-tdt-1.1b": "nvidia/parakeet-tdt-1.1b",
    }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._model = None

    def load(self) -> None:
        try:
            from nemo.collections.asr.models import ASRModel
        except Exception as e:
            raise RuntimeError(
                "nemo_toolkit is not installed — Parakeet models require the NeMo engine. "
                "Install via pip install 'nemo_toolkit[asr]'."
            ) from e

        repo = self.MODEL_ID_MAP.get(self.model, self.model)
        logger.info(f"Loading NeMo ASR model '{repo}' on {self.device}...")
        self._model = ASRModel.from_pretrained(model_name=repo)
        try:
            self._model = self._model.to(self.device)
        except Exception as e:
            logger.warning(f"Could not move NeMo model to {self.device}: {e}")
        self._model.eval()
        logger.info(f"NeMo model '{repo}' loaded.")

    def transcribe(
        self,
        audio_path: str,
        language: Optional[str] = None,
        enable_diarize: bool = False,
        progress_cb: Optional[Callable[[int, str], None]] = None,
    ) -> TranscriptionResult:
        if self._model is None:
            self.load()

        def _prog(p, s=None):
            if progress_cb:
                progress_cb(p, s)

        _prog(5, "transcribe")

        # NeMo chokes on stereo input with:
        #   "Output shape mismatch occured for audio_signal in module
        #    AudioToBPEDataset : Output shape found : torch.Size([1, N, 2])"
        # Pre-convert to mono 16 kHz WAV via ffmpeg so the shape is always
        # (batch, time). Cheap and format-agnostic — any container works.
        mono_path, is_tmp = _to_mono_wav(audio_path)
        try:
            # Not every NeMo ASR architecture supports the `timestamps` kwarg
            # (e.g. plain EncDecRNNTModel vs. EncDecCTCModel). Try with,
            # fall back to without so the call still returns a text-only result.
            try:
                outputs = self._model.transcribe([mono_path], timestamps=True)
            except TypeError as e:
                if "timestamps" in str(e):
                    logger.info(
                        "NeMo model does not accept 'timestamps' kwarg — "
                        "falling back to text-only transcription."
                    )
                    outputs = self._model.transcribe([mono_path])
                else:
                    raise
        finally:
            if is_tmp:
                try:
                    os.unlink(mono_path)
                except OSError:
                    pass
        _prog(95, "postprocess")

        # Normalise NeMo's wildly inconsistent return shape.
        # Observed forms across engines/versions:
        #   [hyp1, hyp2, ...]                      (CTC models, plain list)
        #   ([hyp1, hyp2, ...], [all_hyps_per_sample])  (RNNT models, tuple)
        #   [[hyp1], [hyp2]]                       (nested per sample)
        # Always end up with `hyp` = one Hypothesis or str for our single input.
        if isinstance(outputs, tuple):
            outputs = outputs[0] if outputs else None
        if outputs and isinstance(outputs, list) and outputs and isinstance(outputs[0], list):
            outputs = outputs[0]
        segments: list[dict] = []
        text = ""
        hyp = outputs[0] if outputs else None

        if hyp is None:
            pass
        elif isinstance(hyp, str):
            text = hyp
            segments.append({"id": 0, "start": 0.0, "end": 0.0, "text": hyp})
        else:
            text = getattr(hyp, "text", "") or ""
            ts = getattr(hyp, "timestamp", None) or {}
            seg_list = ts.get("segment") if isinstance(ts, dict) else None
            word_list = ts.get("word") if isinstance(ts, dict) else None
            if seg_list:
                for i, s in enumerate(seg_list):
                    entry = {
                        "id": i,
                        "start": round(float(s.get("start", 0.0)), 2),
                        "end": round(float(s.get("end", 0.0)), 2),
                        "text": s.get("segment") or s.get("text") or "",
                    }
                    if word_list:
                        words_in_seg = [
                            w for w in word_list
                            if float(w.get("start", 0)) >= entry["start"]
                            and float(w.get("end", 0)) <= entry["end"] + 0.01
                        ]
                        if words_in_seg:
                            entry["words"] = [
                                {
                                    "word": w.get("word", ""),
                                    "start": round(float(w.get("start", 0)), 2),
                                    "end": round(float(w.get("end", 0)), 2),
                                }
                                for w in words_in_seg
                            ]
                    segments.append(entry)
            elif word_list:
                entry = {
                    "id": 0,
                    "start": round(float(word_list[0].get("start", 0)), 2),
                    "end": round(float(word_list[-1].get("end", 0)), 2),
                    "text": text,
                    "words": [
                        {
                            "word": w.get("word", ""),
                            "start": round(float(w.get("start", 0)), 2),
                            "end": round(float(w.get("end", 0)), 2),
                        }
                        for w in word_list
                    ],
                }
                segments.append(entry)
            else:
                segments.append({"id": 0, "start": 0.0, "end": 0.0, "text": text})

        _prog(100)
        return TranscriptionResult(
            text=text.strip(),
            language=language or "en",
            segments=segments,
        )
