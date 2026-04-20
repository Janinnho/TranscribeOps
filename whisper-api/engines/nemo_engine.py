import logging
from typing import Optional, Callable

from .base import Engine, TranscriptionResult

logger = logging.getLogger("whisper-api.engine.nemo")


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
        outputs = self._model.transcribe([audio_path], timestamps=True)
        _prog(95, "postprocess")

        # NeMo returns either a list of Hypothesis objects or a list of strings.
        # With timestamps=True it returns objects with .timestamp and .text attrs.
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
