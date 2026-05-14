# Installation & Deployment

## Table of Contents

- [System Requirements](#system-requirements)
- [Create Docker Network](#create-docker-network)
- [Start the Whisper API Service](#start-the-whisper-api-service)
- [Start the Web App](#start-the-web-app)
- [First Login](#first-login)
- [Production Deployment](#production-deployment)
- [Updates](#updates)
- [Uninstallation](#uninstallation)

---

## System Requirements

| Component | Minimum | Recommended |
|-----------|---------|-------------|
| Docker | 20.10+ | 24.0+ |
| Docker Compose | v2.0+ | v2.20+ |
| RAM | 4 GB | 8 GB+ (for local Whisper) |
| Storage | 5 GB | 20 GB+ (models + audio archive) |
| CPU | 2 cores | 4+ cores |
| GPU (optional) | — | NVIDIA CUDA-capable |

### Software Dependencies

The following dependencies are installed **automatically** inside the Docker containers:

- **Python 3.12** — Runtime environment
- **FFmpeg** — Audio conversion (MP3 encoding with libmp3lame)
- **Redis 7** — Message broker for Celery
- **faster-whisper** — Local speech recognition (only inside the Whisper API container)

---

## Create Docker Network

TranscribeOps uses a shared Docker network through which the web app and the Whisper API service communicate.

```bash
docker network create transcribeops-shared
```

> This network only needs to be created **once** and persists across container restarts.

---

## Start All Services

```bash
# 1. Create configuration
cp docker-compose.example.yml docker-compose.yml
cp .env.example .env

# 2. Adjust .env (at minimum, set SECRET_KEY!)
# Generate SECRET_KEY: python3 -c "import secrets; print(secrets.token_hex(32))"

# 3. Start the stack
docker compose up -d
```

### Configuration

Configuration is done via environment variables in `docker-compose.yml`:

```yaml
environment:
  - WHISPER_API_KEY=${WHISPER_API_KEY:-my-secret-key}  # API key (optional)
  - WHISPER_MODEL=${WHISPER_MODEL:-medium}              # Model size
  - WHISPER_DEVICE=cpu                                  # cpu or cuda
  - WHISPER_COMPUTE_TYPE=int8                           # Compute precision
```

### Available Models

| Model | RAM Requirement | Accuracy | Speed |
|-------|-----------------|----------|-------|
| `tiny` | ~1 GB | Low | Very fast |
| `base` | ~1 GB | Low-Medium | Fast |
| `small` | ~2 GB | Medium | Medium |
| `medium` | ~4 GB | Good | Slower |
| `large-v3` | ~6 GB | Very good | Slow |
| `turbo` | ~6 GB | Very good | Faster than large |

### GPU Support (NVIDIA)

For GPU-accelerated transcription:

1. Install the [NVIDIA Container Toolkit](https://docs.nvidia.com/datacenter/cloud-native/container-toolkit/install-guide.html)
2. Modify `docker-compose.yml`:

```yaml
services:
  whisper:
    # ...
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

### Verification

```bash
# Health check
curl http://localhost:8090/health

# Expected response:
# {"status":"ok","default_model":"medium","device":"cpu","compute_type":"int8","models_loaded":["medium"]}
```

---

## First Start

On the first start, the following happens automatically:

1. **Database is created** — SQLite file at `/app/data/transcribeops.db`
2. **Migrations are applied** — Missing columns/tables are created automatically
3. **Default data is seeded:**
   - Admin user: `admin@transcribeops.local` / `admin`
   - Default speech model: Local Whisper at `http://whisper:8000/v1/audio/transcriptions`
   - Default text model: Local Ollama at `http://ollama:11434`
   - Default group: "Standard"
   - Timezone: `Europe/Berlin`

### Docker Services

| Service | Function | Port |
|---------|----------|------|
| `web` | Flask web server (Gunicorn) | 5000 |
| `worker` | Celery worker (async tasks) | — |
| `redis` | Message broker | — (internal) |

### Volumes

| Volume | Path in container | Description |
|--------|-------------------|-------------|
| `db_data` | `/app/data` | SQLite database |
| `upload_data` | `/app/app/static/uploads` | Temporary uploads |
| Audio mount | `/app/audio_storage` | Permanent audio archive |

---

## First Login

1. Open http://localhost:5000 in your browser
2. Log in with the default credentials:
   - **Email:** `admin@transcribeops.local`
   - **Password:** `admin`
3. **Important:** Change the admin password immediately under **Admin > Users**

### Initial Configuration

After logging in, the following steps are recommended:

1. **Change the admin password** — In the admin portal under Users
2. **Verify the speech model** — The default Whisper model points to `http://whisper:8000/v1/audio/transcriptions`. If the Whisper service runs on a different port, adjust the URL.
3. **Configure a text model** — If Ollama is not available, set up an alternative text model (OpenAI, Azure)
4. **Set the timezone** — Under Admin > Global, select the desired timezone
5. **Create users** — Add more users in the admin portal

---

## Production Deployment

### Set SECRET_KEY

**Mandatory for production:** Set a secure, random `SECRET_KEY` in the `.env` file:

```bash
# .env
SECRET_KEY=your-secure-random-key-here
```

Generate a secure key:
```bash
python3 -c "import secrets; print(secrets.token_hex(32))"
```

### HTTPS / Reverse Proxy

A reverse proxy with HTTPS is recommended for production:

**nginx example:**
```nginx
server {
    listen 443 ssl;
    server_name transcribeops.example.com;

    ssl_certificate     /path/to/cert.pem;
    ssl_certificate_key /path/to/key.pem;

    client_max_body_size 500M;  # For large audio files

    location / {
        proxy_pass http://localhost:5000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
```

### Configure Audio Storage

By default, audio files are mounted under `./audio_storage`. Adjust the path in `docker-compose.yml`:

```yaml
volumes:
  - /path/to/audio-archive:/app/audio_storage
```

### Backups

Back up the following regularly:

1. **Database** — The Docker volume `db_data` (contains the SQLite file)
2. **Audio archive** — The mounted audio directory
3. **docker-compose.yml** and **.env** — Your configuration

```bash
# Example: database backup
docker compose exec web cp /app/data/transcribeops.db /app/data/backup_$(date +%Y%m%d).db
```

---

## Updates

```bash
# Pull the latest version
git pull

# Rebuild and start containers
docker compose up -d --build
```

> Migrations are applied automatically when the web app starts. No manual intervention is required.

---

## Uninstallation

```bash
# Stop and remove containers
docker compose down

# Optional: delete volumes (WARNING: data will be lost!)
docker compose down -v

# Remove the network
docker network rm transcribeops-shared
```
