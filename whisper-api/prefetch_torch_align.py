"""
Pre-fetch the torchaudio wav2vec2 bundles used by WhisperX for forced alignment.

WhisperX's `DEFAULT_ALIGN_MODELS_TORCH` maps en/fr/de/es/it to torchaudio
pipelines. Calling `<BUNDLE>.get_model()` downloads the checkpoint into
`~/.cache/torch/hub/checkpoints/` — no HuggingFace token required.

Run once at image-build time so the five most common alignment languages are
already on disk when the container first starts. Idempotent: torchaudio skips
the download if the file is already cached.
"""
import sys
import pathlib

# Bundle names mirror whisperx.alignment.DEFAULT_ALIGN_MODELS_TORCH for the
# five languages we ship pre-loaded. If whisperx ever changes these names,
# update this list to stay in sync (or the admin dashboard will flag them
# as missing at runtime).
BUNDLES = [
    ("en", "WAV2VEC2_ASR_BASE_960H"),
    ("fr", "VOXPOPULI_ASR_BASE_10K_FR"),
    ("de", "VOXPOPULI_ASR_BASE_10K_DE"),
    ("es", "VOXPOPULI_ASR_BASE_10K_ES"),
    ("it", "VOXPOPULI_ASR_BASE_10K_IT"),
]


def main() -> int:
    import torchaudio.pipelines as pipelines  # noqa: WPS433 (local import speeds up --help etc.)

    failures: list[str] = []
    for lang, name in BUNDLES:
        bundle = getattr(pipelines, name, None)
        if bundle is None:
            print(f"[prefetch] {lang}: bundle '{name}' not found on torchaudio.pipelines", file=sys.stderr)
            failures.append(name)
            continue
        print(f"[prefetch] {lang}: loading {name} ...", flush=True)
        try:
            bundle.get_model()
        except Exception as e:
            print(f"[prefetch] {lang}: FAILED {name}: {e}", file=sys.stderr)
            failures.append(name)

    cache_dir = pathlib.Path.home() / ".cache" / "torch" / "hub" / "checkpoints"
    if cache_dir.exists():
        files = sorted(p.name for p in cache_dir.iterdir() if p.is_file())
        print(f"[prefetch] {cache_dir} contains: {files}")
    else:
        print(f"[prefetch] WARNING: {cache_dir} does not exist", file=sys.stderr)

    if failures:
        print(f"[prefetch] {len(failures)} bundle(s) failed: {failures}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
