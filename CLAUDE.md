# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

TranscribeOps is a self-hosted Flask web application for audio transcription, meeting protocols, dictation, and AI-powered text processing. It supports multiple Speech-to-Text and Text-AI providers (OpenAI, Azure, local Whisper, Ollama). The UI and documentation are in German.

## Architecture

Two independent services:

- **web-app/**: Flask app with Celery workers (the main application)
- **whisper-api/**: Standalone Flask API wrapping faster-whisper, OpenAI-compatible endpoints

### Web-App Structure

- `run.py` — App entrypoint (gunicorn runs `run:app`)
- `celery_worker.py` — Celery worker entrypoint, imports tasks for discovery
- `config.py` — Config class, reads from environment variables
- `app/__init__.py` — App factory (`create_app`), lightweight auto-migrations (`_apply_migrations`), seed defaults (`_seed_defaults`)
- `app/models.py` — SQLAlchemy models: User, Group, SpeechModel, TextModel, Job, Meeting, Dictation, TextTask, DictionaryEntry, ChatMessage, SystemSetting
- `app/tasks.py` — Celery tasks for speech processing, text tasks, summaries, auto-title, chat
- `app/sso.py` — SSO helpers (header-based and OIDC via Authlib)
- `app/utils.py` — Timezone helpers
- `app/routes/` — Blueprints: `auth` (`/`), `main` (`/`), `admin` (`/admin`), `api` (`/api`)

### Key Patterns

- **DB migrations**: No Alembic migration files. `_apply_migrations()` in `__init__.py` does `ALTER TABLE ADD COLUMN` with `_safe_execute` (ignores errors if column exists). New tables created via `__table__.create()`.
- **Auth model**: Users belong to Groups. Groups control feature access (transcription, meeting, dictation, text tools, dictionary) and model visibility. Admins bypass all group checks.
- **Record types**: Job (transcription), Meeting, Dictation share similar patterns — each has `public_id` (UUID hex), `user_id`, `status`, `diarized_segments` (JSON text). API endpoints filter by `user_id=current_user.id`.
- **CSRF**: Enabled globally via `CSRFProtect`. API calls from frontend include CSRF token.
- **Task processing**: Upload creates a record, queues a Celery task. Task calls provider API, stores result, updates status to `completed`/`failed`.

## Development Commands

### Run locally (without Docker)

```bash
# Web app (dev server)
cd web-app && python run.py

# Celery worker
cd web-app && celery -A celery_worker.celery worker --loglevel=info

# Whisper API
cd whisper-api && python app.py
```

### Run with Docker/Podman

```bash
# Full stack
docker compose up --build

# Rebuild only web and worker (preserving redis/whisper)
docker compose build web worker
```

### Deployment Notes

- Copy `docker-compose.example.yml` → `docker-compose.yml` and configure secrets in `.env`
- Named volumes: `transcribeops-db` (SQLite), `transcribeops-uploads`, `transcribeops-redis`, `transcribeops-whisper-cache`
- Port 5050 external → 5000 internal (gunicorn)
- Redis runs inside the pod, accessible via `localhost:6379` (pod networking)
- `SECRET_KEY` must be set via environment variable; falls back to a random key if unset

## Important Conventions

- All user-facing strings are in German
- Records use `public_id` (UUID hex) in URLs/API, never internal `id`
- API endpoints always filter by `current_user.id` for authorization
- Admin routes use `@admin_required` decorator (defined in `routes/admin.py`)
- File uploads use `secure_filename()` + UUID prefix
- Subprocess calls (ffmpeg) use list args, never `shell=True`
