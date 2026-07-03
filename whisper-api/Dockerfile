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
RUN pip install --no-cache-dir -r requirements.txt

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
