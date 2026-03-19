FROM python:3.12-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    git \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Environment variables (can be overridden at runtime)
ENV WHISPER_API_KEY=""
ENV WHISPER_MODEL="medium"
ENV WHISPER_DEVICE="cpu"
ENV WHISPER_COMPUTE_TYPE="int8"
ENV WHISPER_BATCH_SIZE="16"
ENV HF_TOKEN=""
ENV PYTHONUNBUFFERED=1

# Pre-download default model during build for faster startup
RUN python -c "import whisperx; whisperx.load_model('medium', device='cpu', compute_type='int8')"

EXPOSE 8000

CMD ["gunicorn", "--bind", "0.0.0.0:8000", "--workers", "1", "--threads", "4", "--timeout", "600", "app:app"]
