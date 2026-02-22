FROM python:3.12-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

ENV WHISPER_API_KEY=""
ENV WHISPER_MODEL="medium"
ENV WHISPER_DEVICE="cpu"
ENV WHISPER_COMPUTE_TYPE="int8"
ENV PYTHONUNBUFFERED=1
ENV XDG_CACHE_HOME=/app/.cache

# Pre-download default model during build for faster startup
RUN python -c "from faster_whisper import WhisperModel; WhisperModel('medium', device='cpu', compute_type='int8')"

# Create non-root user and assign ownership
RUN groupadd -r whisperuser && useradd -r -g whisperuser whisperuser \
    && chown -R whisperuser:whisperuser /app

EXPOSE 8000

USER whisperuser

CMD ["gunicorn", "--bind", "0.0.0.0:8000", "--workers", "1", "--threads", "4", "--timeout", "600", "app:app"]
