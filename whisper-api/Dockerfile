FROM python:3.12-slim

WORKDIR /app

# System-Deps:
#   ffmpeg     — Audio-I/O (whisperx + nemo)
#   git        — für pip git-Installs (whisperx)
#   libsndfile1 — von NeMo zum Einlesen von Audio benötigt
#   build-essential — NeMo-/Torch-Builds
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    git \
    libsndfile1 \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
# sherpa-onnx (Parakeet Ultra/Redux) is in requirements.txt. Its wheel
# bundles ONNX Runtime and does not replace the torch build below.
RUN pip install --no-cache-dir -r requirements.txt

# Torch flavour. Empty (the default) means "leave whatever pip resolved from
# PyPI alone" — on linux/amd64 that is the CUDA build, i.e. exactly what this
# image shipped before this argument existed. Existing CPU and NVIDIA builds
# are therefore unaffected. Set it to a PyTorch wheel index to swap the build:
#   --build-arg TORCH_INDEX=https://download.pytorch.org/whl/rocm6.3  (AMD/ROCm)
#   --build-arg TORCH_INDEX=https://download.pytorch.org/whl/cpu      (slim, CPU-only)
# See docker-compose.rocm.yml for the AMD setup.
ARG TORCH_INDEX=""
# Swaps the torch *backend* without disturbing anything else:
#
#   * versions are pinned to what requirements.txt just resolved. Unpinned,
#     pip takes the newest wheel the index offers and breaks whisperx's
#     `torch~=2.8.0`. A version the index lacks fails the build loudly, which
#     is the right outcome.
#   * everything already installed is frozen into a constraints file, so the
#     reinstall cannot drag shared dependencies along. Without it, --force-
#     reinstall pulls fsspec and setuptools from the torch index and breaks
#     the pins of lightning, datasets and nv-one-logger.
#   * PyPI stays available as an extra index so the constrained dependencies
#     remain resolvable. This cannot pull the CUDA wheel back in: PEP 440
#     ranks the local version `2.8.0+rocm6.3` above a plain `2.8.0`, so the
#     backend-specific wheel always wins for the pinned version.
RUN if [ -n "$TORCH_INDEX" ]; then \
      TORCH_VER="$(python -c 'import torch; print(torch.__version__.split("+")[0])')" && \
      TA_VER="$(python -c 'import torchaudio; print(torchaudio.__version__.split("+")[0])')" && \
      echo "Reinstalling torch==$TORCH_VER torchaudio==$TA_VER from $TORCH_INDEX" && \
      pip freeze | grep -viE '^(torch|torchaudio|pytorch-triton)' > /tmp/torch-constraints.txt && \
      pip install --no-cache-dir --force-reinstall -c /tmp/torch-constraints.txt \
          "torch==$TORCH_VER" "torchaudio==$TA_VER" \
          --index-url "$TORCH_INDEX" --extra-index-url https://pypi.org/simple && \
      rm -f /tmp/torch-constraints.txt && \
      python -c "import torch, torchaudio; print('torch', torch.__version__, '| torchaudio', torchaudio.__version__)" && \
      pip check; \
    else \
      echo "TORCH_INDEX unset — keeping the torch build resolved from PyPI"; \
    fi

# NumPy 2.0 removed `np.sctypes`, but NeMo 2.0.0 still references it in
# preprocessing/segment.py. Patch it in-place to use explicit dtype lists.
COPY patch_nemo_numpy2.py /tmp/patch_nemo_numpy2.py
RUN python /tmp/patch_nemo_numpy2.py && rm /tmp/patch_nemo_numpy2.py

# Pre-fetch the 5 torchaudio wav2vec2 bundles used by WhisperX for forced
# alignment (en/fr/de/es/it). Baked into the image so transcriptions with
# word-timestamps never stall on a first-use download. No HF token needed.
COPY prefetch_torch_align.py /tmp/prefetch_torch_align.py
RUN python /tmp/prefetch_torch_align.py && rm /tmp/prefetch_torch_align.py

COPY . .

# Default environment — per-instance settings werden ab jetzt über das Admin-UI verwaltet.
ENV WHISPER_API_KEY=""
ENV WHISPER_MODEL="medium"
# Unchanged default: "cpu". "auto" picks the best available device (CUDA,
# ROCm or MPS) — opt-in, so existing deployments keep behaving as before.
ENV WHISPER_DEVICE="cpu"
ENV WHISPER_COMPUTE_TYPE="int8"
ENV WHISPER_BATCH_SIZE="16"
ENV HF_TOKEN=""

# Admin-UI
ENV ADMIN_PASSWORD=""
ENV ADMIN_SESSION_SECRET=""
ENV ADMIN_DB_PATH="/root/.cache/transcribeops/admin.db"
ENV INSTANCE_PORT_RANGE="8100-8120"

ENV PYTHONUNBUFFERED=1

# Port 8000 = Admin-UI + Haupt-API + Model-Router.
# Instanz-Ports (Standard 8100-8120) sind an 127.0.0.1 gebunden und nur noch
# intern erreichbar — Requests laufen über den model-Parameter auf Port 8000.
EXPOSE 8000

# Threads großzügig: Proxy-Threads für Instanz-Routing warten fast nur auf I/O.
CMD ["gunicorn", "--bind", "0.0.0.0:8000", "--workers", "1", "--threads", "8", "--timeout", "600", "app:app"]
