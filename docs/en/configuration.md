# Configuration

## Table of Contents

- [Environment Variables](#environment-variables)
- [Docker Compose Configuration](#docker-compose-configuration)
- [Flask Configuration](#flask-configuration)
- [Whisper API Configuration](#whisper-api-configuration)
- [System Settings (Database)](#system-settings-database)
- [Network Configuration](#network-configuration)

---

## Environment Variables

### Web App

| Variable | Description | Default | Required |
|----------|-------------|---------|----------|
| `SECRET_KEY` | Flask session secret (CSRF, cookie signing) | `dev-secret-key` | **Yes (production)** |
| `DATABASE_URL` | SQLAlchemy connection string | `sqlite:///data/transcribeops.db` | No |
| `REDIS_URL` | Redis connection URL | `redis://localhost:6379/0` | No |
| `AUDIO_STORAGE_PATH` | Path to permanent audio archive | Upload folder | No |
| `FLASK_APP` | Flask entry point | `run.py` | No |
| `PYTHONUNBUFFERED` | Disables output buffering | `1` | No |

### Whisper API

| Variable | Description | Default |
|----------|-------------|---------|
| `WHISPER_API_KEY` | API key for authentication (empty = no auth) | `my-secret-key` |
| `WHISPER_MODEL` | Default model size | `medium` |
| `WHISPER_DEVICE` | Compute device (`cpu` or `cuda`) | `cpu` |
| `WHISPER_COMPUTE_TYPE` | Compute precision (`int8`, `float16`, `float32`) | `int8` |

---

## Docker Compose Configuration

### Full Stack (`docker-compose.example.yml`)

The entire configuration is done through a single compose file in the root directory. Secrets are read from the `.env` file.

```bash
# Setup
cp docker-compose.example.yml docker-compose.yml
cp .env.example .env
# Adjust .env (SECRET_KEY, HF_TOKEN, etc.)
```

> **Important:** `web` and `worker` must use **identical** volumes and environment variables, since both access the same database and the same files. See `docker-compose.example.yml` for the full reference.

---

## Flask Configuration

The Flask configuration lives in `web-app/config.py`:

```python
class Config:
    SECRET_KEY = os.environ.get('SECRET_KEY', 'dev-secret-key')
    SQLALCHEMY_DATABASE_URI = os.environ.get('DATABASE_URL',
        f'sqlite:///{os.path.join(basedir, "data", "transcribeops.db")}')
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    UPLOAD_FOLDER = os.path.join(basedir, 'app', 'static', 'uploads')
    AUDIO_STORAGE_PATH = os.environ.get('AUDIO_STORAGE_PATH',
        os.path.join(basedir, 'app', 'static', 'uploads'))
    MAX_CONTENT_LENGTH = 500 * 1024 * 1024  # 500 MB
    CELERY_BROKER_URL = os.environ.get('REDIS_URL', 'redis://localhost:6379/0')
    CELERY_RESULT_BACKEND = os.environ.get('REDIS_URL', 'redis://localhost:6379/0')
```

### Explanation

| Setting | Description |
|---------|-------------|
| `SECRET_KEY` | Used for session cookies, CSRF tokens, and OIDC state. **Must be set to a secure random value in production.** |
| `SQLALCHEMY_DATABASE_URI` | Database connection. Defaults to SQLite. |
| `SQLALCHEMY_TRACK_MODIFICATIONS` | Disabled (for performance). |
| `UPLOAD_FOLDER` | Directory for temporary audio uploads. |
| `AUDIO_STORAGE_PATH` | Directory for permanent audio archiving. |
| `MAX_CONTENT_LENGTH` | Maximum upload size (500 MB). |
| `CELERY_BROKER_URL` | Redis URL for the Celery message broker. |
| `CELERY_RESULT_BACKEND` | Redis URL for Celery task results. |

---

## Whisper API Configuration

### Model Sizes

| Model | Parameters | RAM (CPU) | Accuracy |
|-------|-----------|-----------|----------|
| `tiny` | 39 M | ~1 GB | Low |
| `base` | 74 M | ~1 GB | Low-Medium |
| `small` | 244 M | ~2 GB | Medium |
| `medium` | 769 M | ~4 GB | Good |
| `large-v3` | 1.55 B | ~6 GB | Very good |
| `turbo` | 809 M | ~6 GB | Very good |

### Compute Types

| Type | Description | GPU/CPU |
|------|-------------|---------|
| `int8` | 8-bit integer quantization — less RAM, slightly less accurate | CPU/GPU |
| `float16` | 16-bit floating point — default for GPU | GPU recommended |
| `float32` | 32-bit floating point — highest accuracy, more RAM | CPU/GPU |

### Model Mapping

If `model=whisper-1` or `model=whisper-large-v3` is passed as a parameter, the server uses the configured default model (`WHISPER_MODEL`). All other values are interpreted directly as a model size.

---

## System Settings (Database)

The following settings are stored as key-value pairs in the `system_settings` table and managed through the admin portal:

### Global Settings

| Key | Description | Default | Managed in |
|-----|-------------|---------|------------|
| `timezone` | System timezone (IANA format) | `Europe/Berlin` | Admin > Global |

### SSO Settings

| Key | Description | Default | Managed in |
|-----|-------------|---------|------------|
| `sso_enabled` | SSO enabled | `false` | Admin > SSO |
| `sso_method` | SSO method | `header` | Admin > SSO |
| `sso_header_email` | Email header (header SSO) | — | Admin > SSO |
| `sso_header_name` | Name header (header SSO) | — | Admin > SSO |
| `sso_auto_create` | Auto-create users | `false` | Admin > SSO |
| `sso_default_admin` | Auto-created users as admin | `false` | Admin > SSO |
| `oidc_discovery_url` | OIDC discovery URL | — | Admin > SSO |
| `oidc_client_id` | OIDC client ID | — | Admin > SSO |
| `oidc_client_secret` | OIDC client secret | — | Admin > SSO |
| `oidc_scopes` | OIDC scopes | `openid email profile` | Admin > SSO |
| `oidc_email_claim` | OIDC email claim | `email` | Admin > SSO |
| `oidc_name_claim` | OIDC name claim | `name` | Admin > SSO |

---

## Network Configuration

### Docker Networks

| Network | Type | Purpose |
|---------|------|---------|
| `default` | Bridge (internal) | Communication between web, worker, redis |
| `transcribeops-shared` | External bridge | Communication between web-app and whisper-api |

### Port Overview

| Service | Internal Port | External Port | Description |
|---------|--------------|---------------|-------------|
| Web App | 5000 | 5000 | Web UI |
| Whisper API | 8000 | 8090 | Speech-to-Text API |
| Redis | 6379 | — (internal only) | Message broker |

### Service Communication

| From | To | URL |
|------|----|----|
| Web/Worker | Whisper | `http://whisper:8000/v1/audio/transcriptions` |
| Web/Worker | Redis | `redis://redis:6379/0` |
| Web/Worker | Ollama | `http://ollama:11434` (configured externally) |
| Web/Worker | OpenAI | `https://api.openai.com/v1/...` |
| Web/Worker | Azure | `https://{endpoint}.openai.azure.com/...` |

> **Note:** The hostname `whisper` is resolved via the Docker network `transcribeops-shared`. If the Whisper service runs on a different host, the URL in the speech model must be adjusted accordingly.

---

## Adjusting Ports

### Change the Web App Port

```yaml
# docker-compose.yml
services:
  web:
    ports:
      - "8080:5000"  # Web app reachable on port 8080
```

### Change the Whisper API Port

```yaml
# docker-compose.yml
services:
  whisper:
    ports:
      - "9000:8000"  # Whisper API reachable on port 9000
```

> **Important:** The internal ports (5000 for web, 8000 for whisper) should not be changed. Only the external (host) port is relevant.
