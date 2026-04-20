import logging
from typing import Optional, Callable

from .base import Engine, TranscriptionResult

logger = logging.getLogger("whisper-api.engine.whisperx")


class WhisperXEngine(Engine):
    name = "whisperx"
    supports_alignment = True
    supports_diarization = True

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._model = None
        self._align_models: dict = {}
        self._diarize_pipeline = None

    def load(self) -> None:
        import whisperx
        logger.info(f"Loading WhisperX model '{self.model}' on {self.device} ({self.compute_type})...")
        self._model = whisperx.load_model(self.model, self.device, compute_type=self.compute_type)
        logger.info(f"WhisperX model '{self.model}' loaded.")

    def _get_align_model(self, language_code: str):
        import whisperx
        if language_code not in self._align_models:
            logger.info(f"Loading alignment model for '{language_code}'...")
            model_a, metadata = whisperx.load_align_model(language_code=language_code, device=self.device)
            self._align_models[language_code] = (model_a, metadata)
        return self._align_models[language_code]

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
        progress_cb: Optional[Callable[[int, str], None]] = None,
    ) -> TranscriptionResult:
        import whisperx
        if self._model is None:
            self.load()

        def _prog(p, s=None):
            if progress_cb:
                progress_cb(p, s)

        kwargs = {"batch_size": self.batch_size}
        if language:
            kwargs["language"] = language

        _prog(5, "transcribe")
        result = self._model.transcribe(audio_path, **kwargs)
        detected = result.get("language", language or "unknown")
        _prog(70, "align")

        try:
            model_a, metadata = self._get_align_model(detected)
            audio = whisperx.load_audio(audio_path)
            result = whisperx.align(
                result["segments"], model_a, metadata, audio, self.device,
                return_char_alignments=False,
            )
        except Exception as e:
            logger.warning(f"Alignment failed (continuing without): {e}")

        _prog(90)

        if enable_diarize:
            pipeline = self._get_diarize_pipeline()
            if pipeline is not None:
                _prog(90, "diarize")
                try:
                    audio = whisperx.load_audio(audio_path)
                    diarize_segments = pipeline(audio)
                    result = whisperx.assign_word_speakers(diarize_segments, result)
                except Exception as e:
                    logger.warning(f"Diarization failed (continuing without): {e}")

        _prog(100)

        segments = []
        text_parts = []
        for i, seg in enumerate(result.get("segments", [])):
            entry = {
                "id": i,
                "start": round(seg.get("start", 0), 2),
                "end": round(seg.get("end", 0), 2),
                "text": seg.get("text", ""),
            }
            if "speaker" in seg:
                entry["speaker"] = seg["speaker"]
            if "words" in seg:
                entry["words"] = [
                    {
                        "word": w.get("word", ""),
                        "start": round(w.get("start", 0), 2),
                        "end": round(w.get("end", 0), 2),
                    }
                    for w in seg["words"]
                    if "start" in w and "end" in w
                ]
            segments.append(entry)
            text_parts.append(seg.get("text", ""))

        return TranscriptionResult(
            text="".join(text_parts).strip(),
            language=detected,
            segments=segments,
        )
