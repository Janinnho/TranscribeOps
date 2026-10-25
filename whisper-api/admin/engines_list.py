"""Simple registry wrapper for the admin UI (avoid importing heavy engine code on boot)."""

def engines_choices() -> list[dict]:
    # ``short_label`` is the instance-form dropdown. ``label`` stays the
    # longer string the /admin/api/engines payload already exposed.
    return [
        {
            "id": "whisperx",
            "label": "WhisperX (faster-whisper + Alignment + pyannote)",
            "short_label": "WhisperX",
        },
        {
            "id": "nemo",
            "label": "NeMo (Parakeet)",
            "short_label": "NeMo (Parakeet)",
        },
        {
            "id": "parakeet_onnx",
            "label": "Parakeet ONNX (sherpa-onnx, Ultra/Redux)",
            "short_label": "Parakeet ONNX (Ultra/Redux)",
        },
    ]
