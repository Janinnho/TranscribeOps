import logging
import os
import subprocess
import tempfile
import unicodedata
from difflib import SequenceMatcher
from typing import Optional, Callable

from .base import Engine, TranscriptionResult

logger = logging.getLogger("whisper-api.engine.nemo")

_DICT_MIN_LEN = 4
_DICT_MIN_RATIO = 0.78
_DICT_LEN_TOLERANCE = 0.30
_PUNCT_CHARS = ",.!?:;\"'„""—–-…()[]{}«»‚'"


def _normalize_for_match(s: str) -> str:
    """Lowercase + strip diacritics + ß→ss for fuzzy comparison."""
    s = unicodedata.normalize("NFKD", s).lower().replace("ß", "ss")
    return "".join(c for c in s if not unicodedata.combining(c))


def _split_punct(token: str) -> tuple[str, str, str]:
    """Split (leading_punct, core, trailing_punct)."""
    i = 0
    while i < len(token) and token[i] in _PUNCT_CHARS:
        i += 1
    j = len(token)
    while j > i and token[j - 1] in _PUNCT_CHARS:
        j -= 1
    return token[:i], token[i:j], token[j:]


def _parse_prompt(prompt: str) -> list[str]:
    """Split a comma-separated dictionary prompt into clean entries."""
    if not prompt:
        return []
    out: list[str] = []
    seen: set[str] = set()
    for raw in prompt.split(","):
        w = raw.strip()
        if len(w) < _DICT_MIN_LEN:
            continue
        key = w.lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(w)
    return out


def _apply_dictionary(words: list[dict], dict_words: list[str]) -> int:
    """Replace ASR'd words with phonetically-similar dictionary entries.

    Mutates `words` in place. Multi-token entries (e.g. "Jannik Baader")
    are matched against sliding N-word windows of the transcript and
    replaced token-for-token so that timestamps stay aligned. Single-token
    entries match individual words. Each transcript word is replaced at
    most once; longer entries take precedence (greedy). Preserves outer
    punctuation. Returns total number of replacements.
    """
    if not words or not dict_words:
        return 0

    multi: list[tuple[list[str], list[str]]] = []  # (tokens_orig, tokens_norm)
    single: list[tuple[str, str]] = []             # (orig, norm)
    for entry in dict_words:
        toks = entry.split()
        if len(toks) >= 2:
            multi.append((toks, [_normalize_for_match(t) for t in toks]))
        elif toks:
            single.append((toks[0], _normalize_for_match(toks[0])))

    replaced: set[int] = set()
    n_repl = 0

    # Multi-word pass first, longer entries first (greedy: a 3-token entry
    # mustn't be blocked by a 2-token entry consuming the first two words).
    multi.sort(key=lambda x: -len(x[0]))
    for tokens_orig, tokens_norm in multi:
        m = len(tokens_orig)
        cand_joined = " ".join(tokens_norm)
        cand_len = len(cand_joined)
        max_diff = max(1, _DICT_LEN_TOLERANCE * cand_len)
        for i in range(0, len(words) - m + 1):
            if any((i + k) in replaced for k in range(m)):
                continue
            cores: list[str] = []
            ok = True
            for k in range(m):
                _, core, _ = _split_punct(words[i + k]["word"])
                if not core:
                    ok = False
                    break
                cores.append(core)
            if not ok:
                continue
            joined_core = " ".join(_normalize_for_match(c) for c in cores)
            if abs(len(joined_core) - cand_len) > max_diff:
                continue
            if joined_core == cand_joined:
                continue  # already correct
            score = SequenceMatcher(a=joined_core, b=cand_joined).ratio()
            if score >= _DICT_MIN_RATIO:
                for k in range(m):
                    leading, _, trailing = _split_punct(words[i + k]["word"])
                    words[i + k]["word"] = leading + tokens_orig[k] + trailing
                    replaced.add(i + k)
                n_repl += m

    # Single-word pass — skip indices already touched by the multi-word pass.
    for idx, word_obj in enumerate(words):
        if idx in replaced:
            continue
        leading, core, trailing = _split_punct(word_obj["word"])
        if len(core) < _DICT_MIN_LEN:
            continue
        core_norm = _normalize_for_match(core)
        best_orig = None
        best_score = 0.0
        for orig, cand_norm in single:
            if abs(len(core_norm) - len(cand_norm)) > max(1, _DICT_LEN_TOLERANCE * len(cand_norm)):
                continue
            if cand_norm == core_norm:
                if orig != core:
                    best_orig, best_score = orig, 1.0
                break
            score = SequenceMatcher(a=core_norm, b=cand_norm).ratio()
            if score > best_score:
                best_score = score
                best_orig = orig
        if best_orig is not None and best_score >= _DICT_MIN_RATIO and best_orig != core:
            word_obj["word"] = leading + best_orig + trailing
            n_repl += 1

    return n_repl


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


_WORD_BOUNDARY = "▁"  # SentencePiece marker for "starts new word"
_SENTENCE_END = (".", "?", "!")


def _words_from_hypothesis(hyp, tokenizer, frame_time_s: float) -> list[dict]:
    """Build word-level [{word, start, end}] from a NeMo Hypothesis.

    NeMo 2.0.0 cannot expose word/segment timestamps for TDT models — the
    built-in compute_rnnt_timestamps path crashes on merged BPE tokens.
    Instead we read the raw fields: y_sequence (token ids) + timestep
    (encoder-frame index per token), and group BPE pieces into words by
    the SentencePiece "▁" prefix. Frame→seconds is window_stride ×
    subsampling_factor (0.08 s for parakeet-tdt-0.6b-v3).
    """
    y_seq = getattr(hyp, "y_sequence", None)
    timestep = getattr(hyp, "timestep", None)
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
    }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._model = None
        self._diarize_pipeline = None
        self._frame_time_s: Optional[float] = None

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

        # Frame→seconds: feature stride × encoder subsampling. Fallback to
        # 0.08 s (parakeet-tdt-0.6b-v3 default) if the cfg can't be read.
        try:
            ws = float(self._model.cfg.preprocessor.window_stride)
            sub = float(getattr(self._model.encoder, "subsampling_factor", 8))
            self._frame_time_s = ws * sub
        except Exception:
            self._frame_time_s = 0.08
        logger.info(f"NeMo model '{repo}' loaded (frame_time={self._frame_time_s:.4f}s).")

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
            outputs = self._model.transcribe([mono_path], return_hypotheses=True)
            _prog(70, "postprocess")

            # Normalise NeMo's wildly inconsistent return shape:
            #   [hyp1, hyp2, ...]                            (plain list)
            #   ([hyp1, hyp2, ...], [all_hyps_per_sample])   (RNNT/TDT tuple)
            #   [[hyp1], [hyp2]]                             (nested per sample)
            if isinstance(outputs, tuple):
                outputs = outputs[0] if outputs else None
            if outputs and isinstance(outputs, list) and outputs and isinstance(outputs[0], list):
                outputs = outputs[0]
            hyp = outputs[0] if outputs else None

            text = ""
            words: list[dict] = []
            if hyp is None:
                pass
            elif isinstance(hyp, str):
                text = hyp
            else:
                text = getattr(hyp, "text", "") or ""
                words = _words_from_hypothesis(hyp, self._model.tokenizer, self._frame_time_s or 0.08)

            dict_words = _parse_prompt(prompt) if prompt else []
            if dict_words and words:
                replacements = _apply_dictionary(words, dict_words)
                if replacements:
                    logger.info(f"Applied {replacements} dictionary replacement(s).")
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
