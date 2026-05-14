# Whisper API Service

The Whisper API service is a standalone Flask server that provides an **OpenAI-compatible** transcription API. It uses [WhisperX](https://github.com/m-bain/whisperX) (based on faster-whisper) with word-level alignment and optional speaker diarization.

## Table of Contents

- [Overview](#overview)
- [Installation & Start](#installation--start)
- [API Endpoints](#api-endpoints)
- [Configuration](#configuration)
- [Models](#models)
- [Output Formats](#output-formats)
- [Authentication](#authentication)
- [GPU Support](#gpu-support)
- [Performance Tips](#performance-tips)

---

## Overview

| Property | Value |
|----------|-------|
| **Framework** | Flask + Gunicorn |
| **Engine** | WhisperX (faster-whisper + alignment + diarization) |
| **API compatibility** | OpenAI Whisper API (`/v1/audio/transcriptions`) |
| **Default port** | 8000 (internal), 8090 (external) |
| **Default model** | `medium` |
| **Memory limit** | 4 GB (Docker) |

---

## Installation & Start

### Docker (recommended)

```bash
# Create network (one-time)
docker network create transcribeops-shared

# Start service
cd whisper-api
docker compose up -d
```

### Health check

```bash
curl http://localhost:8090/health
```

Expected response:
```json
{
  "status": "ok",
  "default_model": "medium",
  "device": "cpu",
  "compute_type": "int8",
  "models_loaded": ["medium"]
}
```

---

## API Endpoints

### `POST /v1/audio/transcriptions`

Transcribes an audio file.

**Content-Type:** `multipart/form-data`

**Parameters:**

| Parameter | Type | Required | Description | Default |
|-----------|------|----------|-------------|---------|
| `file` | File | Yes | Audio file (any format) | — |
| `model` | String | No | Model size or `whisper-1` | `whisper-1` |
| `language` | String | No | Language code (ISO 639-1) | Auto-detect |
| `response_format` | String | No | Output format | `json` |

**Example (cURL):**

```bash
curl -X POST http://localhost:8090/v1/audio/transcriptions \
  -H "Authorization: Bearer my-secret-key" \
  -F "file=@interview.mp3" \
  -F "model=whisper-1" \
  -F "language=de" \
  -F "response_format=verbose_json"
```

**Success response (json):**
```json
{
  "text": "Hello, this is a test text."
}
```

**Success response (verbose_json):**
```json
{
  "text": "Hello, this is a test text.",
  "language": "en",
  "duration": 5.42,
  "segments": [
    {
      "id": 0,
      "start": 0.0,
      "end": 2.5,
      "text": " Hello, this is"
    },
    {
      "id": 1,
      "start": 2.5,
      "end": 5.42,
      "text": " a test text."
    }
  ]
}
```

**Error responses:**

| Code | Description |
|------|-------------|
| `400` | No audio file or empty filename |
| `401` | Invalid API key |
| `500` | Transcription error (e.g. invalid audio format) |

```json
{
  "error": {
    "message": "Invalid API key.",
    "type": "auth_error"
  }
}
```

---

### `GET /v1/models`

Lists available models (OpenAI-compatible).

**Authentication:** Required (if API key is configured)

**Response:**
```json
{
  "object": "list",
  "data": [
    {"id": "whisper-1", "object": "model", "owned_by": "local", "description": "Default (medium)"},
    {"id": "tiny", "object": "model", "owned_by": "local"},
    {"id": "base", "object": "model", "owned_by": "local"},
    {"id": "small", "object": "model", "owned_by": "local"},
    {"id": "medium", "object": "model", "owned_by": "local"},
    {"id": "large-v3", "object": "model", "owned_by": "local"},
    {"id": "turbo", "object": "model", "owned_by": "local"}
  ]
}
```

---

### `GET /health`

Health check endpoint (no authentication required).

**Response:**
```json
{
  "status": "ok",
  "default_model": "medium",
  "device": "cpu",
  "compute_type": "int8",
  "models_loaded": ["medium"]
}
```

---

## Configuration

### Environment variables

| Variable | Description | Default |
|----------|-------------|---------|
| `WHISPER_API_KEY` | API key for bearer auth (empty = no auth) | `""` |
| `WHISPER_MODEL` | Default model size | `medium` |
| `WHISPER_DEVICE` | Compute device | `cpu` |
| `WHISPER_COMPUTE_TYPE` | Compute precision | `int8` |

### Docker Compose

```yaml
services:
  whisper:
    build: .
    ports:
      - "8090:8000"
    environment:
      - WHISPER_API_KEY=${WHISPER_API_KEY:-my-secret-key}
      - WHISPER_MODEL=${WHISPER_MODEL:-medium}
      - WHISPER_DEVICE=cpu
      - WHISPER_COMPUTE_TYPE=int8
    volumes:
      - whisper_cache:/root/.cache     # Hugging Face model cache
    networks:
      - transcribeops
    restart: unless-stopped
    deploy:
      resources:
        limits:
          memory: 4G
```

### `.env` file (optional)

```env
WHISPER_API_KEY=my-secure-key
WHISPER_MODEL=large-v3
```

---

## Models

### Available models

| Model | Parameters | RAM (CPU, int8) | Languages | Accuracy |
|-------|------------|-----------------|-----------|----------|
| `tiny` | 39 M | ~1 GB | All | Low |
| `base` | 74 M | ~1 GB | All | Low-medium |
| `small` | 244 M | ~2 GB | All | Medium |
| `medium` | 769 M | ~4 GB | All | Good |
| `large-v3` | 1.55 B | ~6 GB | All | Very good |
| `turbo` | 809 M | ~6 GB | All | Very good (faster than large) |

### Model mapping

| API parameter | Actual model used |
|---------------|-------------------|
| `whisper-1` | Configured default model (`WHISPER_MODEL`) |
| `whisper-large-v3` | Configured default model |
| Other values | Used directly as the model size |

### Model caching

- Models are downloaded from Hugging Face on first load
- The Docker volume `whisper_cache` persists loaded models
- The default model is preloaded at container start
- Additional models are loaded and cached on demand

---

## Output Formats

### `json` (default)

Simple JSON with the full text:

```json
{
  "text": "The complete transcribed text."
}
```

### `verbose_json`

Extended JSON with metadata and timestamped segments:

```json
{
  "text": "The complete transcribed text.",
  "language": "en",
  "duration": 45.67,
  "segments": [
    {
      "id": 0,
      "start": 0.0,
      "end": 3.5,
      "text": " The complete"
    },
    {
      "id": 1,
      "start": 3.5,
      "end": 5.2,
      "text": " transcribed text."
    }
  ]
}
```

### `text`

Only the transcribed text as plain text:

```
The complete transcribed text.
```

### `srt`

SubRip Subtitle format:

```
1
00:00:00,000 --> 00:00:03,500
The complete

2
00:00:03,500 --> 00:00:05,200
transcribed text.
```

### `vtt`

WebVTT format:

```
WEBVTT

00:00:00.000 --> 00:00:03.500
The complete

00:00:03.500 --> 00:00:05.200
transcribed text.
```

---

## Authentication

### Bearer Token

If `WHISPER_API_KEY` is set, a bearer token is expected:

```
Authorization: Bearer <api-key>
```

### Without authentication

If `WHISPER_API_KEY` is empty (`""`), no authentication is required. This makes sense in isolated Docker networks without external access.

---

## GPU Support

### NVIDIA CUDA

For GPU-accelerated transcription:

1. **Install the NVIDIA Container Toolkit:**
   ```bash
   # Ubuntu/Debian
   distribution=$(. /etc/os-release;echo $ID$VERSION_ID)
   curl -fsSL https://nvidia.github.io/libnvidia-container/gpgkey | sudo gpg --dearmor -o /usr/share/keyrings/nvidia-container-toolkit-keyring.gpg
   curl -s -L https://nvidia.github.io/libnvidia-container/$distribution/libnvidia-container.list | \
     sed 's#deb https://#deb [signed-by=/usr/share/keyrings/nvidia-container-toolkit-keyring.gpg] https://#g' | \
     sudo tee /etc/apt/sources.list.d/nvidia-container-toolkit.list
   sudo apt-get update && sudo apt-get install -y nvidia-container-toolkit
   sudo nvidia-ctk runtime configure --runtime=docker && sudo systemctl restart docker
   ```

2. **Adjust docker-compose.yml:**

   ```yaml
   services:
     whisper:
       build: .
       environment:
         - WHISPER_DEVICE=cuda
         - WHISPER_COMPUTE_TYPE=float16
       deploy:
         resources:
           reservations:
             devices:
               - driver: nvidia
                 count: 1
                 capabilities: [gpu]
   ```

3. **Adjust the Dockerfile** (for a CUDA base image):

   ```dockerfile
   FROM nvidia/cuda:12.1-runtime-ubuntu22.04
   # ... install Python and dependencies
   ```

### Compute types with GPU

| Type | Description | Recommendation |
|------|-------------|----------------|
| `float16` | Standard for GPU — good tradeoff | Recommended |
| `int8` | Less VRAM, slightly lower accuracy | For smaller GPUs |
| `float32` | Highest accuracy, more VRAM | Rarely needed |

---

## Performance Tips

### Model choice

- **For speed:** `tiny` or `base` — very fast, but less accurate
- **For balance:** `medium` — a good tradeoff (default)
- **For accuracy:** `large-v3` — best results, slower
- **For accuracy + speed:** `turbo` — similar to large, but faster

### VAD filter

The service automatically enables the **Voice Activity Detection (VAD) filter** (`vad_filter=True`). It filters out silent sections and improves processing speed, especially for recordings with long pauses.

### Beam size

The default beam size is `5`. Higher values can improve accuracy but slow down processing.

### Memory

- Make sure enough RAM/VRAM is available for the chosen model
- The Docker memory limit (default: 4 GB) must be at least as large as the model's RAM requirement
- For `large-v3` on CPU it is recommended to raise the limit to 8 GB

### Concurrency

The Gunicorn server is configured with `--workers 1 --threads 4`:
- **1 worker** — Whisper models are memory-intensive; multiple workers would load the model multiple times
- **4 threads** — Allows parallel request handling (I/O); the actual transcription runs sequentially

### Specifying the language

If the language is known, specify it explicitly (`language=de`). This skips automatic language detection and improves accuracy, especially for short recordings.

---

## Integration with TranscribeOps

In TranscribeOps, the Whisper API service is configured as a **speech model** with the provider `whisper_local`:

```
Name:          whisper-local
Display name:  Local Whisper
Provider:      whisper_local
Endpoint URL:  http://whisper:8000/v1/audio/transcriptions
API key:       my-secret-key (if configured)
Model ID:      whisper-1
```

Communication happens over the shared Docker network `transcribeops-shared`. The hostname `whisper` is resolved automatically by Docker DNS.
