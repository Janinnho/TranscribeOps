"""Curated model catalog for the admin UI.

Each entry describes a model that can be downloaded from HuggingFace and
used by a whisper-api instance. `kind` drives the color grouping on the
dashboard: 'whisper' / 'parakeet' = transcription, 'diarize' = diarization,
'align' = alignment.
"""
from dataclasses import dataclass


@dataclass(frozen=True)
class CatalogEntry:
    id: str              # short ID used in forms (matches engine .model)
    repo_id: str         # HuggingFace repo
    kind: str            # 'whisper' | 'parakeet' | 'diarize' | 'align'
    engine: str          # 'whisperx' | 'nemo'
    display_name: str
    description: str
    size_hint: str       # human-readable rough size
    requires_hf_token: bool = False


CATALOG: list[CatalogEntry] = [
    # ----- faster-whisper / WhisperX transcription models -----
    CatalogEntry("tiny", "Systran/faster-whisper-tiny", "whisper", "whisperx",
                 "Whisper Tiny", "Sehr klein, schnellstes Modell — gut für Tests.",
                 "~75 MB"),
    CatalogEntry("base", "Systran/faster-whisper-base", "whisper", "whisperx",
                 "Whisper Base", "Klein, CPU-freundlich.", "~145 MB"),
    CatalogEntry("small", "Systran/faster-whisper-small", "whisper", "whisperx",
                 "Whisper Small", "Gute Balance zwischen Geschwindigkeit und Qualität.", "~465 MB"),
    CatalogEntry("medium", "Systran/faster-whisper-medium", "whisper", "whisperx",
                 "Whisper Medium", "Standard-Empfehlung für die meisten Fälle.", "~1.5 GB"),
    CatalogEntry("large-v3", "Systran/faster-whisper-large-v3", "whisper", "whisperx",
                 "Whisper Large v3", "Beste Whisper-Qualität, deutlich langsamer.", "~3 GB"),
    CatalogEntry("large-v3-turbo", "Systran/faster-whisper-large-v3-turbo", "whisper", "whisperx",
                 "Whisper Large v3 Turbo", "Large v3 beschleunigt; Qualität fast identisch.", "~1.5 GB"),

    # ----- Parakeet (NeMo) -----
    CatalogEntry("parakeet-tdt-0.6b-v3", "nvidia/parakeet-tdt-0.6b-v3", "parakeet", "nemo",
                 "Parakeet TDT 0.6B v3", "NVIDIA Parakeet TDT, schnelles ASR, Englisch.", "~1.2 GB"),
    CatalogEntry("parakeet-tdt-0.6b-v2", "nvidia/parakeet-tdt-0.6b-v2", "parakeet", "nemo",
                 "Parakeet TDT 0.6B v2", "Ältere Parakeet-Variante.", "~1.2 GB"),
    CatalogEntry("parakeet-tdt-1.1b", "nvidia/parakeet-tdt-1.1b", "parakeet", "nemo",
                 "Parakeet TDT 1.1B", "Größeres Parakeet-Modell.", "~2.2 GB"),

    # ----- Diarization -----
    CatalogEntry("pyannote-diarization-3.1", "pyannote/speaker-diarization-3.1", "diarize", "whisperx",
                 "pyannote Speaker Diarization 3.1",
                 "Sprechererkennung. Benötigt HF-Token + akzeptierte Lizenz.", "~250 MB", requires_hf_token=True),
    CatalogEntry("pyannote-segmentation-3.0", "pyannote/segmentation-3.0", "diarize", "whisperx",
                 "pyannote Segmentation 3.0",
                 "Wird von Diarization 3.1 intern benötigt.", "~20 MB", requires_hf_token=True),

    # ----- Alignment (wav2vec2 per language) -----
    # WhisperX lädt sprachabhängige Modelle automatisch. Hier die gängigsten zum Pre-Download.
    CatalogEntry("align-en", "jonatasgrosman/wav2vec2-large-xlsr-53-english", "align", "whisperx",
                 "Alignment Englisch", "wav2vec2 für englische Wort-Timings.", "~1.2 GB"),
    CatalogEntry("align-de", "jonatasgrosman/wav2vec2-large-xlsr-53-german", "align", "whisperx",
                 "Alignment Deutsch", "wav2vec2 für deutsche Wort-Timings.", "~1.2 GB"),
    CatalogEntry("align-fr", "jonatasgrosman/wav2vec2-large-xlsr-53-french", "align", "whisperx",
                 "Alignment Französisch", "wav2vec2 für französische Wort-Timings.", "~1.2 GB"),
    CatalogEntry("align-es", "jonatasgrosman/wav2vec2-large-xlsr-53-spanish", "align", "whisperx",
                 "Alignment Spanisch", "wav2vec2 für spanische Wort-Timings.", "~1.2 GB"),
    CatalogEntry("align-it", "jonatasgrosman/wav2vec2-large-xlsr-53-italian", "align", "whisperx",
                 "Alignment Italienisch", "wav2vec2 für italienische Wort-Timings.", "~1.2 GB"),
]


def by_repo_id(repo_id: str) -> CatalogEntry | None:
    for e in CATALOG:
        if e.repo_id == repo_id:
            return e
    return None


def by_id(id_: str) -> CatalogEntry | None:
    for e in CATALOG:
        if e.id == id_:
            return e
    return None


def by_kind(kind: str) -> list[CatalogEntry]:
    return [e for e in CATALOG if e.kind == kind]


def transcription_entries() -> list[CatalogEntry]:
    return [e for e in CATALOG if e.kind in ("whisper", "parakeet")]


KIND_LABELS = {
    "whisper": "Transkription (Whisper)",
    "parakeet": "Transkription (Parakeet)",
    "diarize": "Sprechererkennung",
    "align": "Wort-Alignment",
}

KIND_COLORS = {
    "whisper": "blue",
    "parakeet": "teal",
    "diarize": "green",
    "align": "purple",
}
