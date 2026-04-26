from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Optional, Callable


@dataclass
class TranscriptionResult:
    text: str
    language: str
    segments: list[dict] = field(default_factory=list)


class Engine(ABC):
    name: str = "abstract"
    supports_alignment: bool = False
    supports_diarization: bool = False

    def __init__(self, model: str, device: str, compute_type: str, hf_token: str = "", batch_size: int = 16):
        self.model = model
        self.device = device
        self.compute_type = compute_type
        self.hf_token = hf_token
        self.batch_size = batch_size

    @abstractmethod
    def load(self) -> None:
        """Load model(s) into memory. Called once at startup."""

    @abstractmethod
    def transcribe(
        self,
        audio_path: str,
        language: Optional[str] = None,
        enable_diarize: bool = False,
        prompt: Optional[str] = None,
        progress_cb: Optional[Callable[[int, str], None]] = None,
    ) -> TranscriptionResult:
        """Run transcription. progress_cb(percent, step) is optional.
        `prompt` is a comma-separated list of dictionary terms; engines that
        don't support prompting may ignore it."""
