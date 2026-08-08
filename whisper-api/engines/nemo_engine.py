import logging
import os
import subprocess
import tempfile
from typing import Optional, Callable

from .base import Engine, TranscriptionResult
from .dictionary import apply_dictionary, parse_prompt

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


def _slice_wav(src: str, start: float, length: float) -> str:
    """Extract [start, start+length) of a PCM-WAV into a new tempfile."""
    fd, dst = tempfile.mkstemp(suffix=".wav", prefix="nemo_chunk_")
    os.close(fd)
    try:
        subprocess.run(
            [
                "ffmpeg", "-nostdin", "-y", "-loglevel", "error",
                "-ss", f"{start:.3f}", "-t", f"{length:.3f}",
                "-i", src,
                "-ac", "1", "-ar", "16000", "-c:a", "pcm_s16le",
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
        raise RuntimeError(f"ffmpeg failed to slice {src}: {stderr.strip()}") from e
    return dst


def _wav_duration_secs(path: str) -> Optional[float]:
    """Duration in seconds of a WAV written by _to_mono_wav / _slice_wav.

    Falls back to deriving it from the file size, which is exact for the
    mono/16 kHz/s16le format those two produce — without a duration the
    caller cannot slice, and an unsliced multi-hour file exhausts memory.
    """
    import wave
    try:
        with wave.open(path, "rb") as w:
            rate = w.getframerate()
            if rate:
                return w.getnframes() / rate
    except Exception:
        pass
    try:
        return os.path.getsize(path) / (16000 * 2)
    except OSError:
        return None


# Parakeet's encoder attends globally, so attention cost grows with the
# *square* of the audio length: a 2h50 file is ~127k encoder frames, i.e. tens
# of GB per head, and the OOM killer ends it long before it finishes. Slicing
# caps that — peak memory then depends on the slice, not the recording.
# Measured on parakeet-primeline (CPU), same 900 s of speech:
#   300 s slices ->  7.6 GB peak,  9.6x realtime
#   450 s slices -> 11.5 GB peak,  7.4x realtime
#   900 s, unsliced -> 32.6 GB peak, 4.4x realtime
# Whisper never needs this: its encoder is hard-capped at 30 s (N_FRAMES=3000)
# and WhisperX feeds it VAD chunks, so tensor sizes are length-independent.
_CHUNK_SECS = float(os.environ.get("NEMO_CHUNK_SECS", "300"))
# Slices overlap so a word straddling a boundary is transcribed intact; the
# duplicate half is dropped at the midpoint when the words are stitched.
_CHUNK_OVERLAP_SECS = float(os.environ.get("NEMO_CHUNK_OVERLAP_SECS", "5"))

_WORD_BOUNDARY = "▁"  # SentencePiece marker for "starts new word"
_SENTENCE_END = (".", "?", "!")


def _words_from_hypothesis(hyp, tokenizer, frame_time_s: float) -> list[dict]:
    """Build word-level [{word, start, end}] from a NeMo Hypothesis.

    Preferred path: `transcribe(..., timestamps=True)` fills
    `hyp.timestamp["word"]` with native word timestamps (works for TDT
    since ~NeMo 2.3; the 2.0.0 crash on merged BPE tokens is fixed).

    Fallback: read the raw fields y_sequence (token ids) + per-token
    encoder-frame indices and group BPE pieces into words by the
    SentencePiece "▁" prefix. The frame field was renamed `timestep` →
    `timestamp` in NeMo 2.x, so we accept both. Frame→seconds is
    window_stride × subsampling_factor (0.08 s for parakeet-tdt-0.6b-v3).
    """
    ts = getattr(hyp, "timestamp", None)
    if isinstance(ts, dict):
        native = [
            {"word": str(w.get("word", "")), "start": float(w.get("start", 0.0)), "end": float(w.get("end", 0.0))}
            for w in ts.get("word") or []
            if w.get("word")
        ]
        if native:
            return native

    y_seq = getattr(hyp, "y_sequence", None)
    timestep = getattr(hyp, "timestep", None)
    if timestep is None and not isinstance(ts, dict):
        timestep = ts  # NeMo >= 2.x: raw frame tensor lives in `timestamp`
    if y_seq is None or timestep is None:
        return []
    try:
        ids = [int(t) for t in y_seq]
        frames = [int(t) for t in timestep]
        pieces = tokenizer.ids_to_tokens(ids)
    except Exception:
        return []
    if not ids or len(ids) != len(frames) or len(pieces) != len(ids):
        return []

    words: list[dict] = []
    cur: Optional[dict] = None
    for piece, frame in zip(pieces, frames):
        starts_word = piece.startswith(_WORD_BOUNDARY) or cur is None
        text = piece[1:] if piece.startswith(_WORD_BOUNDARY) else piece
        t = frame * frame_time_s
        if starts_word:
            cur = {"word": text, "start": t, "end": t}
            words.append(cur)
        else:
            cur["word"] += text
            cur["end"] = t

    # End-time pass: each word ends when the next word starts; final word
    # gets a small heuristic tail proportional to its length.
    for i in range(len(words) - 1):
        words[i]["end"] = words[i + 1]["start"]
    if words:
        last = words[-1]
        last["end"] = max(last["end"], last["start"] + max(0.2, len(last["word"]) * 0.05))
    return words


def _diarize_words(words: list[dict], diarize_df) -> None:
    """Attach a 'speaker' field to each word by largest-overlap with pyannote turns.

    Mutates the words list in place. diarize_df is a pandas DataFrame with
    columns 'start', 'end', 'speaker' (whisperx.diarize.DiarizationPipeline shape).
    """
    if diarize_df is None or len(diarize_df) == 0 or not words:
        return
    starts = diarize_df["start"].to_numpy()
    ends = diarize_df["end"].to_numpy()
    speakers = diarize_df["speaker"].to_list()
    for w in words:
        ws, we = w["start"], w["end"]
        best_idx, best_ov = -1, 0.0
        for j in range(len(starts)):
            ov = min(we, ends[j]) - max(ws, starts[j])
            if ov > best_ov:
                best_ov = ov
                best_idx = j
        if best_idx < 0:
            # No overlap — prefer the nearest future turn; otherwise the
            # nearest prior turn (for words drifting past the last segment).
            future = [j for j in range(len(starts)) if starts[j] >= ws]
            if future:
                best_idx = future[0]
            else:
                best_idx = min(range(len(ends)), key=lambda j: ws - ends[j])
        w["speaker"] = speakers[best_idx]


def _segments_from_words(words: list[dict], with_speaker: bool) -> list[dict]:
    """Group consecutive words into segments. Cut on sentence-ending
    punctuation, plus on speaker change when diarized."""
    segments: list[dict] = []
    if not words:
        return segments

    bucket: list[dict] = []
    cur_speaker = words[0].get("speaker") if with_speaker else None

    def flush():
        if not bucket:
            return
        entry = {
            "id": len(segments),
            "start": round(bucket[0]["start"], 2),
            "end": round(bucket[-1]["end"], 2),
            "text": " ".join(w["word"] for w in bucket).strip(),
            "words": [
                {"word": w["word"], "start": round(w["start"], 2), "end": round(w["end"], 2)}
                for w in bucket
            ],
        }
        if with_speaker and bucket[0].get("speaker"):
            entry["speaker"] = bucket[0]["speaker"]
        segments.append(entry)

    for w in words:
        spk = w.get("speaker") if with_speaker else None
        if bucket and with_speaker and spk != cur_speaker:
            flush()
            bucket = []
            cur_speaker = spk
        bucket.append(w)
        if w["word"].endswith(_SENTENCE_END):
            flush()
            bucket = []
            cur_speaker = spk
    flush()
    return segments


class NeMoEngine(Engine):
    """NVIDIA NeMo ASR engine (Parakeet family)."""

    name = "nemo"
    supports_alignment = False
    supports_diarization = True

    MODEL_ID_MAP = {
        "parakeet-tdt-0.6b-v3": "nvidia/parakeet-tdt-0.6b-v3",
        "parakeet-tdt-0.6b-v2": "nvidia/parakeet-tdt-0.6b-v2",
        "parakeet-tdt-1.1b": "nvidia/parakeet-tdt-1.1b",
        "parakeet-primeline": "primeline/parakeet-primeline",
    }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._model = None
        self._diarize_pipeline = None
        self._frame_time_s: Optional[float] = None

    @staticmethod
    def _find_cached_nemo_file(repo: str) -> Optional[str]:
        """Locate a .nemo checkpoint for `repo` in the local HF snapshot cache."""
        import glob
        hf_home = os.environ.get("HF_HOME", os.path.expanduser("~/.cache/huggingface"))
        slug = "models--" + repo.replace("/", "--")
        for base in (os.path.join(hf_home, "hub", slug), os.path.join(hf_home, slug)):
            hits = sorted(glob.glob(os.path.join(base, "snapshots", "*", "*.nemo")))
            if hits:
                return hits[0]
        return None

    @staticmethod
    def _restore_from_hub(asr_model_cls, repo: str):
        """Download the repo's .nemo checkpoint from HuggingFace and restore it."""
        from huggingface_hub import hf_hub_download, list_repo_files
        nemo_files = [f for f in list_repo_files(repo) if f.endswith(".nemo")]
        if not nemo_files:
            raise RuntimeError(
                f"Repo '{repo}' enthält keine .nemo-Checkpoint-Datei — "
                "kein für die NeMo-Engine ladbares Modell."
            )
        path = hf_hub_download(repo_id=repo, filename=nemo_files[0])
        return asr_model_cls.restore_from(path, map_location="cpu")

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

        # Community fine-tunes (e.g. primeline/parakeet-primeline) publish a
        # bare .nemo checkpoint with an arbitrary filename — from_pretrained()
        # can't resolve those. Prefer a .nemo file from the local HF snapshot
        # cache (populated by the admin download), then fall back to
        # from_pretrained (works for the nvidia/* repos), then to fetching
        # the repo's .nemo file directly.
        nemo_path = self._find_cached_nemo_file(repo) if "/" in repo else None
        if nemo_path:
            logger.info(f"Restoring NeMo model from cached checkpoint: {nemo_path}")
            self._model = ASRModel.restore_from(nemo_path, map_location="cpu")
        else:
            try:
                self._model = ASRModel.from_pretrained(model_name=repo)
            except Exception as e:
                if "/" not in repo:
                    raise
                logger.info(f"from_pretrained failed for '{repo}' ({e}) — looking for a .nemo file in the repo.")
                self._model = self._restore_from_hub(ASRModel, repo)
        try:
            self._model = self._model.to(self.device)
        except Exception as e:
            logger.warning(f"Could not move NeMo model to {self.device}: {e}")
        self._model.eval()

        # Frame→seconds: feature stride × encoder subsampling. Fallback to
        # 0.08 s (parakeet-tdt-0.6b-v3 default) if the cfg can't be read.
        try:
            ws = float(self._model.cfg.preprocessor.window_stride)
            sub = float(getattr(self._model.encoder, "subsampling_factor", 8))
            self._frame_time_s = ws * sub
        except Exception:
            self._frame_time_s = 0.08
        logger.info(f"NeMo model '{repo}' loaded (frame_time={self._frame_time_s:.4f}s).")

    def _transcribe_one(self, path: str) -> tuple[str, list[dict]]:
        """Run NeMo over one audio file, returning (text, word list)."""
        # timestamps=True is required since NeMo 2.x for word-level timestamps
        # (dictionary replacement + diarization depend on them). Older NeMo
        # versions don't know the kwarg — fall back.
        try:
            outputs = self._model.transcribe(
                [path], return_hypotheses=True, timestamps=True
            )
        except TypeError:
            outputs = self._model.transcribe([path], return_hypotheses=True)

        # Normalise NeMo's wildly inconsistent return shape:
        #   [hyp1, hyp2, ...]                            (plain list)
        #   ([hyp1, hyp2, ...], [all_hyps_per_sample])   (RNNT/TDT tuple)
        #   [[hyp1], [hyp2]]                             (nested per sample)
        if isinstance(outputs, tuple):
            outputs = outputs[0] if outputs else None
        if outputs and isinstance(outputs, list) and outputs and isinstance(outputs[0], list):
            outputs = outputs[0]
        hyp = outputs[0] if outputs else None

        if hyp is None:
            return "", []
        if isinstance(hyp, str):
            return hyp, []
        text = getattr(hyp, "text", "") or ""
        words = _words_from_hypothesis(
            hyp, self._model.tokenizer, self._frame_time_s or 0.08
        )
        return text, words

    def _transcribe_chunked(
        self, path: str, duration: float, prog: Callable[[int, Optional[str]], None]
    ) -> tuple[str, list[dict]]:
        """Transcribe long audio slice by slice and stitch the words together.

        Peak memory is set by the slice length, not the file length, so a
        three-hour recording costs the same as a fifteen-minute one. Slices
        overlap by _CHUNK_OVERLAP_SECS; where two slices both transcribed the
        same moment, the seam is placed in the middle of the overlap and each
        side keeps only its own half.
        """
        starts: list[float] = []
        t = 0.0
        while t < duration:
            starts.append(t)
            t += _CHUNK_SECS
        # A tail shorter than the overlap was already covered in full by the
        # previous slice; slicing it again would hand NeMo a near-empty file.
        if len(starts) > 1 and duration - starts[-1] <= _CHUNK_OVERLAP_SECS:
            starts.pop()
        logger.info(
            f"Audio is {duration:.0f}s — transcribing in {len(starts)} slice(s) "
            f"of {_CHUNK_SECS:.0f}s (+{_CHUNK_OVERLAP_SECS:.0f}s overlap)."
        )

        all_words: list[dict] = []
        texts: list[str] = []
        for i, start in enumerate(starts):
            length = min(_CHUNK_SECS + _CHUNK_OVERLAP_SECS, duration - start)
            chunk = _slice_wav(path, start, length)
            try:
                text, words = self._transcribe_one(chunk)
            finally:
                try:
                    os.unlink(chunk)
                except OSError:
                    pass

            for w in words:
                w["start"] += start
                w["end"] += start

            if i > 0:
                # Everything before the seam belongs to the previous slice,
                # everything from it on to this one.
                seam = start + _CHUNK_OVERLAP_SECS / 2.0
                while all_words and all_words[-1]["start"] >= seam:
                    all_words.pop()
                words = [w for w in words if w["start"] >= seam]

            all_words.extend(words)
            if text:
                texts.append(text)
            # Spread the transcription phase over 5..65 so long files visibly
            # advance instead of sitting at 5 % for hours.
            prog(5 + int(60 * (i + 1) / len(starts)), "transcribe")

        # Words are the stitched source of truth; the per-slice texts still
        # contain the overlap duplicates, so they only serve as a fallback for
        # models that return no timestamps at all.
        if all_words:
            return " ".join(w["word"] for w in all_words), all_words
        return " ".join(t for t in texts if t), []

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
            duration = _wav_duration_secs(mono_path)
            if duration is not None and duration > _CHUNK_SECS:
                text, words = self._transcribe_chunked(mono_path, duration, _prog)
            else:
                text, words = self._transcribe_one(mono_path)
            _prog(70, "postprocess")

            dict_words = parse_prompt(prompt) if prompt else []
            if dict_words and words:
                replacements = apply_dictionary(words, dict_words)
                if replacements:
                    logger.info(f"Applied {replacements} dictionary replacement(s).")
                    # Mapping targets can blank out spoken-command tokens.
                    words = [w for w in words if w["word"]]
                    text = " ".join(w["word"] for w in words)

            with_speaker = False
            if enable_diarize and words:
                pipeline = self._get_diarize_pipeline()
                if pipeline is None:
                    logger.warning("Diarization requested but no HF_TOKEN — skipping.")
                else:
                    _prog(80, "diarize")
                    try:
                        import whisperx
                        audio = whisperx.load_audio(mono_path)
                        diarize_df = pipeline(audio)
                        _diarize_words(words, diarize_df)
                        with_speaker = True
                    except Exception as e:
                        logger.warning(f"Diarization failed (continuing without): {e}")
        finally:
            if is_tmp:
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
            text=text.strip(),
            language=language or "en",
            segments=segments,
        )
