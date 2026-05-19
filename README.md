<div align="center">

<img src="global-assets/icon/transcribeops-256.png" alt="TranscribeOps Logo" width="128" />

# TranscribeOps

**Self-hosted platform for audio transcription, meeting minutes, dictation, and AI-powered text processing.**

[![License](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)
[![Docker](https://img.shields.io/badge/docker-ready-blue.svg)](https://www.docker.com/)
[![Python](https://img.shields.io/badge/python-3.12-yellow.svg)](https://www.python.org/)

[Features](#-features) · [Quick Start](#-quick-start) · [Deployment Options](#-deployment-options) · [Configuration](#%EF%B8%8F-configuration) · [Documentation](docs/README.md)

> **Note:** The user interface is currently in German. English UI translation is on the roadmap. The API and configuration are language-neutral.

</div>

---

## ✨ Features

- 🎙️ **Transcription** — Upload audio files and transcribe them automatically (with speaker diarization)
- 📝 **Meeting Minutes** — Recordings with speaker separation and automatic summarization
- 🎤 **Dictation** — Record directly in the browser with instant transcription
- 🤖 **AI Text Processing** — Rewrite, translate, grammar check, summarize
- 💬 **AI Chat** — Multi-turn chat over your transcriptions ("What was said about X?")
- 📚 **Custom Dictionary** — Add your own vocabulary to improve recognition accuracy
- 👥 **Users & Groups** — Role-based access control, SSO (header-based & OIDC)
- 🔌 **Multi-Provider** — Local Whisper, OpenAI, Azure Speech / OpenAI, Ollama
- 🐳 **Docker-First** — Full deployment with a single Compose file

---

## 🏗️ Architecture

TranscribeOps consists of two **independent** components that can be run separately or together:

```
┌──────────────────────────┐         ┌────────────────────────────┐
│      TranscribeOps       │ ──HTTP──▶  TranscribeOps Model API   │
│  (Web app, Flask+Celery) │         │ (faster-whisper / WhisperX)│
│                          │         │  OpenAI-compatible         │
└────────────┬─────────────┘         └────────────────────────────┘
             │
             │ optionally also to:
             ▼
   OpenAI · Azure · Ollama
```

- **TranscribeOps** (`web-app/`) — The web application with UI, user management, and job queue. Talks to any OpenAI-compatible speech and text endpoints.
- **TranscribeOps Model API** (`whisper-api/`) — Standalone, OpenAI-compatible Whisper server with an admin UI for managing multiple models/workers. Can also be used by other applications.

---

## 🚀 Quick Start

```bash
git clone https://github.com/Janinnho/TranscribeOps.git
cd TranscribeOps

# Create configuration
cp docker-compose.example.yml docker-compose.yml
cp .env.example .env

# Generate a SECRET_KEY and put it in .env
python3 -c "import secrets; print(secrets.token_hex(32))"

# Start the stack (web app + worker + Redis + Whisper API)
docker compose up -d
```

Open in your browser: **http://localhost:5000**

**Initial login:** `admin@transcribeops.local` / `admin` — **change this immediately!**

---

## 📦 Deployment Options

Pick what you need. All three options share the same `docker-compose.example.yml` — you simply remove the services you don't want.

### 🟦 Option 1 — Full Stack (recommended)

> **TranscribeOps + TranscribeOps Model API**, fully self-hosted, no external API calls required.

Best for: privacy-sensitive environments, isolated networks, full control.

```bash
cp docker-compose.example.yml docker-compose.yml
cp .env.example .env
# Set SECRET_KEY in .env
docker compose up -d
```

Includes all services: `web` + `worker` + `redis` + `whisper`. The default speech model is preconfigured to `http://whisper:8000/v1/audio/transcriptions` — no further setup needed.

For **AI text processing** (summaries, chat, etc.) install [Ollama](https://ollama.com) locally as well, or configure an external provider (OpenAI/Azure) in the admin portal.

**Resources:** ~6 GB RAM (for the `medium` model), ~10 GB disk.

---

### 🟨 Option 2 — Web App only

> **Just TranscribeOps**, with speech recognition handled by external providers (OpenAI/Azure) or an existing Whisper instance.

Best for: when you already have an STT endpoint or want to use OpenAI/Azure.

In `docker-compose.yml`, remove or comment out the `whisper` service:

```yaml
services:
  web: { ... }
  worker: { ... }
  redis: { ... }
  # whisper: ...  ← remove
```

```bash
docker compose up -d
```

Then in the admin portal (**Admin → Speech Models**) point the default model to e.g.:
- `https://api.openai.com/v1/audio/transcriptions` (OpenAI)
- `https://<your-endpoint>.openai.azure.com/...` (Azure)
- Any other OpenAI-compatible URL

**Resources:** ~1 GB RAM, ~2 GB disk.

---

### 🟥 Option 3 — Model API only

> **Just the TranscribeOps Model API**, as a standalone OpenAI-compatible Whisper server for other applications.

Best for: when you only need a local Whisper endpoint and don't want a web UI (e.g. to integrate with your own code, n8n, Home Assistant, etc.).

```bash
cd whisper-api
docker build -t transcribeops-whisper .

docker run -d \
  --name transcribeops-whisper \
  -p 8000:8000 \
  -v whisper-cache:/root/.cache \
  -e WHISPER_API_KEY=my-secret-key \
  -e WHISPER_MODEL=medium \
  -e WHISPER_DEVICE=cpu \
  -e WHISPER_COMPUTE_TYPE=int8 \
  -e ADMIN_PASSWORD=an-admin-password \
  transcribeops-whisper
```

Test:
```bash
curl http://localhost:8000/health

curl -X POST http://localhost:8000/v1/audio/transcriptions \
  -H "Authorization: Bearer my-secret-key" \
  -F "file=@audio.mp3" \
  -F "model=whisper-1"
```

Admin UI: **http://localhost:8000/admin** (sign in with `ADMIN_PASSWORD`).

More details: [`docs/whisper-api.md`](docs/whisper-api.md)

**Resources:** 1–6 GB RAM depending on the model.

---

## 🔄 Updating to the Latest Version

Pull the latest code from GitHub, rebuild the images, and restart the containers. Your local `docker-compose.yml`, `.env`, and named volumes (database, uploads, model cache) are **not** touched.

> **Tip:** Back up the database volume before updating:
> ```bash
> docker run --rm -v transcribeops-db:/data -v "$(pwd)":/backup alpine \
>   tar czf /backup/db-backup-$(date +%Y%m%d).tar.gz /data
> ```

### 🐳 Docker

```bash
cd /path/to/TranscribeOps && \
git stash push -u -m "pre-update-$(date +%Y%m%d_%H%M%S)" -- docker-compose.yml .env 2>/dev/null; \
git fetch origin && \
git pull origin main && \
git stash pop 2>/dev/null; \
docker compose build --pull && \
docker compose up -d && \
docker image prune -f
```

### 🦭 Podman

```bash
cd /path/to/TranscribeOps && \
git stash push -u -m "pre-update-$(date +%Y%m%d_%H%M%S)" -- docker-compose.yml .env 2>/dev/null; \
git fetch origin && \
git pull origin main && \
git stash pop 2>/dev/null; \
podman compose build --pull && \
podman compose up -d && \
podman image prune -f
```

**What happens:**

1. `git stash` temporarily saves any local changes to `docker-compose.yml` / `.env`
2. `git pull` fetches the latest code from `main`
3. `git stash pop` restores your local config files
4. `build --pull` rebuilds the images and also pulls newer base images
5. `up -d` recreates the containers with the new images
6. `image prune -f` removes the now-unused old images to free disk space

Database migrations run automatically on app start (`_apply_migrations()` in `app/__init__.py`) — no manual DB steps required.

---

## ⚙️ Configuration

The most important environment variables (see [`.env.example`](.env.example)):

| Variable | Description | Required |
|---|---|---|
| `SECRET_KEY` | Flask session/CSRF secret (≥ 32 chars) | ✅ Production |
| `WHISPER_API_KEY` | API key for the Model API (empty = no auth) | optional |
| `HF_TOKEN` | Hugging Face token for speaker diarization | optional |
| `WHISPER_ADMIN_PASSWORD` | Enables the Whisper admin UI (empty = disabled) | optional |
| `WHISPER_ADMIN_SESSION_SECRET` | Session secret for the admin UI | optional |

**Generate a SECRET_KEY:**
```bash
python3 -c "import secrets; print(secrets.token_hex(32))"
```

**HF_TOKEN for diarization:** Create an account at [huggingface.co](https://huggingface.co), generate a read token, and accept the terms for these models:
- [pyannote/speaker-diarization-3.1](https://huggingface.co/pyannote/speaker-diarization-3.1)
- [pyannote/segmentation-3.0](https://huggingface.co/pyannote/segmentation-3.0)

Full configuration reference: [`docs/configuration.md`](docs/configuration.md)

---

## 🔒 Production Checklist

Before exposing TranscribeOps publicly:

- [ ] `SECRET_KEY` set to a secure random value
- [ ] Admin password changed (no longer `admin`/`admin`)
- [ ] `WHISPER_API_KEY` set if the Model API is reachable from the outside
- [ ] HTTPS via reverse proxy (nginx / Caddy / Traefik) — see [`docs/installation.md`](docs/installation.md)
- [ ] Backup strategy for the DB volume (`transcribeops-db`) and audio storage
- [ ] Optional: configure SSO/OIDC ([`docs/sso-setup.md`](docs/sso-setup.md))

---

## 🖥️ GPU Acceleration (optional)

Local Whisper runs on CPU by default. For GPU (NVIDIA):

1. Install the [NVIDIA Container Toolkit](https://docs.nvidia.com/datacenter/cloud-native/container-toolkit/install-guide.html)
2. In `docker-compose.yml` under the `whisper` service:
   ```yaml
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

---

## 📚 Documentation

> Documentation is currently in German.

| Document | Contents |
|---|---|
| [Installation & Deployment](docs/installation.md) | Detailed setup guide |
| [Configuration](docs/configuration.md) | All environment variables and settings |
| [Architecture](docs/architecture.md) | Tech stack, data model, tasks |
| [API Reference](docs/api-reference.md) | REST API endpoints |
| [Admin Guide](docs/admin-guide.md) | Users, groups, models |
| [User Guide](docs/user-guide.md) | How to use the features |
| [Whisper API](docs/whisper-api.md) | Standalone Model API |
| [SSO Setup](docs/sso-setup.md) | Header-based SSO and OIDC |

---

## 🛠️ Development

```bash
# Web app (dev server)
cd web-app && python run.py

# Celery worker
cd web-app && celery -A celery_worker.celery worker --loglevel=info

# Whisper API
cd whisper-api && python app.py
```

**Tech stack:** Python 3.12, Flask 3.1, SQLAlchemy 2.0, Celery 5.4, Redis 7, faster-whisper / WhisperX, Bootstrap 5.3.

---

## 🤝 Contributing

Issues and pull requests are welcome. Please follow the existing code style (no `shell=True`, CSRF-protected routes, `current_user.id` filter on API endpoints).

---

## 📄 License

[MIT](LICENSE) — use, modification and commercial use are all permitted.

---
