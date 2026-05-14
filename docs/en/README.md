# TranscribeOps Documentation

TranscribeOps is a self-hosted web application for automated transcription, meeting minutes, dictation recognition, and AI-powered text processing. The application supports multiple Speech-to-Text and Text-AI providers and can be configured entirely through an admin portal.

---

## Documentation Overview

| Document | Description |
|----------|-------------|
| [Installation & Deployment](installation.md) | Docker setup, system requirements, first start |
| [Architecture & Technology](architecture.md) | Technical stack, project structure, data model, Celery tasks |
| [Configuration](configuration.md) | Environment variables, database, Redis, audio storage |
| [API Reference](api-reference.md) | All REST API endpoints with request/response documentation |
| [Admin Guide](admin-guide.md) | User management, groups, models, global settings |
| [User Guide](user-guide.md) | Transcription, meetings, dictation, text tools, dictionary, chat |
| [Whisper API Service](whisper-api.md) | Local Whisper server, endpoints, model configuration |
| [SSO Setup](sso-setup.md) | Single Sign-On (header-based & OIDC) |

---

## Quick Start

```bash
# 1. Create Docker network (one-time)
docker network create transcribeops-shared

# 2. Create configuration
cp docker-compose.example.yml docker-compose.yml
cp .env.example .env
# Adjust .env (at minimum, set SECRET_KEY!)

# 3. Start the stack
docker compose up -d

# 4. Open in browser
open http://localhost:5000
```

**Default login:**
- Email: `admin@transcribeops.local`
- Password: `admin`

---

## Features

### Speech Recognition
- **Transcription** — Upload and transcribe audio files (single or multi-speaker)
- **Meeting Minutes** — Record or upload meetings with automatic speaker recognition
- **Dictation** — Record directly in the browser with instant transcription

### AI Text Processing
- **Summarization** — Automatic or manual summarization of transcriptions
- **Text Tools** — Rewriting, grammar checking, translation, summarization of arbitrary text
- **AI Chat** — Multi-turn chat with transcriptions (ask questions about the content)
- **Auto Title** — AI-generated titles for new transcriptions

### Provider Support
- **Speech-to-Text:** Local Whisper (faster-whisper), OpenAI Whisper API, Azure Speech
- **Text AI:** Ollama (local), OpenAI Chat API, Azure OpenAI

### Administration
- **User management** — Users, groups, role-based access control
- **Model management** — Multiple speech and text models configurable
- **Single Sign-On** — Header-based SSO and OpenID Connect
- **Dictionary** — Custom vocabulary to improve recognition accuracy
- **Audio archiving** — Optional permanent storage of audio files
- **Themes** — Light, Dark, Automatic

---

## System Architecture (Overview)

```
┌─────────────┐     ┌────────────┐     ┌───────────────┐
│   Browser    │────▶│  Web-App   │────▶│ Celery Worker │
│  (Frontend)  │◀────│  (Flask)   │     │   (Tasks)     │
└─────────────┘     └─────┬──────┘     └───────┬───────┘
                          │                     │
                    ┌─────┴──────┐        ┌─────┴──────┐
                    │   SQLite   │        │   Redis    │
                    │ (Database) │        │  (Broker)  │
                    └────────────┘        └────────────┘
                                                │
                          ┌─────────────────────┼──────────────────┐
                          │                     │                  │
                    ┌─────┴──────┐     ┌────────┴─────┐   ┌───────┴──────┐
                    │ Whisper API│     │  OpenAI API  │   │  Ollama API  │
                    │   (local)  │     │  (external)  │   │   (local)    │
                    └────────────┘     └──────────────┘   └──────────────┘
```

---

## Technologies

| Component | Technology |
|-----------|------------|
| Backend | Python 3.12, Flask 3.1 |
| Database | SQLite (SQLAlchemy ORM) |
| Task Queue | Celery 5.4 + Redis 7 |
| Frontend | Bootstrap 5.3, Vanilla JavaScript |
| Speech-to-Text | faster-whisper, OpenAI API, Azure Speech |
| Text AI | Ollama, OpenAI API, Azure OpenAI |
| Audio conversion | FFmpeg (libmp3lame) |
| Authentication | Flask-Login, Authlib (OIDC) |
| Deployment | Docker, Docker Compose, Gunicorn |
