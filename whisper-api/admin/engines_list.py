"""Simple registry wrapper for the admin UI (avoid importing heavy engine code on boot)."""

def engines_choices() -> list[dict]:
    return [
        {"id": "whisperx", "label": "WhisperX (faster-whisper + Alignment + pyannote)"},
        {"id": "nemo", "label": "NeMo (Parakeet)"},
    ]
