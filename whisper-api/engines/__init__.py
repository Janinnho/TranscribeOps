from .base import Engine, TranscriptionResult, EngineUnavailable, EngineBusy
from .whisperx_engine import WhisperXEngine
from .nemo_engine import NeMoEngine


_REGISTRY = {
    "whisperx": WhisperXEngine,
    "nemo": NeMoEngine,
}


def get_engine(name: str) -> type[Engine]:
    try:
        return _REGISTRY[name]
    except KeyError:
        raise ValueError(f"Unknown engine '{name}'. Available: {list(_REGISTRY)}")


def available_engines() -> list[str]:
    return list(_REGISTRY.keys())
