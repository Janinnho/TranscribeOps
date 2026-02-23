# Konfiguration

## Inhaltsverzeichnis

- [Umgebungsvariablen](#umgebungsvariablen)
- [Docker-Compose-Konfiguration](#docker-compose-konfiguration)
- [Flask-Konfiguration](#flask-konfiguration)
- [Whisper API Konfiguration](#whisper-api-konfiguration)
- [Systemeinstellungen (Datenbank)](#systemeinstellungen-datenbank)
- [Netzwerk-Konfiguration](#netzwerk-konfiguration)

---

## Umgebungsvariablen

### Web-App

| Variable | Beschreibung | Standard | Erforderlich |
|----------|-------------|----------|--------------|
| `SECRET_KEY` | Flask Session Secret (CSRF, Cookie-Signierung) | `dev-secret-key` | **Ja (Produktion)** |
| `DATABASE_URL` | SQLAlchemy-Verbindungsstring | `sqlite:///data/transcribeops.db` | Nein |
| `REDIS_URL` | Redis-Verbindungs-URL | `redis://localhost:6379/0` | Nein |
| `AUDIO_STORAGE_PATH` | Pfad zur permanenten Audio-Archivierung | Upload-Ordner | Nein |
| `FLASK_APP` | Flask-Einstiegspunkt | `run.py` | Nein |
| `PYTHONUNBUFFERED` | Deaktiviert Output-Buffering | `1` | Nein |

### Whisper API

| Variable | Beschreibung | Standard |
|----------|-------------|----------|
| `WHISPER_API_KEY` | API-Schlüssel für Authentifizierung (leer = kein Auth) | `my-secret-key` |
| `WHISPER_MODEL` | Standard-Modellgröße | `medium` |
| `WHISPER_DEVICE` | Berechnungsgerät (`cpu` oder `cuda`) | `cpu` |
| `WHISPER_COMPUTE_TYPE` | Berechnungsgenauigkeit (`int8`, `float16`, `float32`) | `int8` |

---

## Docker-Compose-Konfiguration

### Web-App (`web-app/docker-compose.yml`)

```yaml
services:
  web:
    build: .
    ports:
      - "5050:5000"                    # Host:Container Port-Mapping
    volumes:
      - db_data:/app/data              # SQLite-Datenbank (persistent)
      - upload_data:/app/app/static/uploads  # Temporäre Uploads
      - ~/Downloads/TranscribeOps-Audio:/app/audio_storage  # Audio-Archiv
    environment:
      - SECRET_KEY=change-me-in-production-abc123
      - DATABASE_URL=sqlite:////app/data/transcribeops.db
      - REDIS_URL=redis://redis:6379/0
      - AUDIO_STORAGE_PATH=/app/audio_storage
    depends_on:
      - redis
    networks:
      - default                        # Internes Netzwerk
      - transcribeops                  # Gemeinsames Netzwerk für Whisper
    restart: unless-stopped

  worker:
    build: .
    command: celery -A celery_worker.celery worker --loglevel=info --concurrency=2
    volumes:                           # Gleiche Volumes wie web!
      - db_data:/app/data
      - upload_data:/app/app/static/uploads
      - ~/Downloads/TranscribeOps-Audio:/app/audio_storage
    environment:                       # Gleiche Umgebungsvariablen wie web!
      - SECRET_KEY=change-me-in-production-abc123
      - DATABASE_URL=sqlite:////app/data/transcribeops.db
      - REDIS_URL=redis://redis:6379/0
      - AUDIO_STORAGE_PATH=/app/audio_storage
    depends_on:
      - redis
    networks:
      - default
      - transcribeops
    restart: unless-stopped

  redis:
    image: redis:7-alpine
    volumes:
      - redis_data:/data               # Redis-Persistenz
    restart: unless-stopped

volumes:
  db_data:          # SQLite-Datenbank
  upload_data:      # Temporäre Uploads
  audio_data:       # (ungenutzt, reserved)
  redis_data:       # Redis-Daten

networks:
  transcribeops:
    external: true
    name: transcribeops-shared
```

> **Wichtig:** `web` und `worker` müssen **identische** Volumes und Umgebungsvariablen haben, da beide auf die gleiche Datenbank und die gleichen Dateien zugreifen.

### Whisper API (`whisper-api/docker-compose.yml`)

```yaml
services:
  whisper:
    build: .
    ports:
      - "8090:8000"                    # Host:Container Port-Mapping
    environment:
      - WHISPER_API_KEY=${WHISPER_API_KEY:-my-secret-key}
      - WHISPER_MODEL=${WHISPER_MODEL:-medium}
      - WHISPER_DEVICE=cpu
      - WHISPER_COMPUTE_TYPE=int8
    volumes:
      - whisper_cache:/root/.cache     # Modell-Cache (Hugging Face)
    networks:
      - transcribeops                  # Gemeinsames Netzwerk
    restart: unless-stopped
    deploy:
      resources:
        limits:
          memory: 4G                   # Speicherlimit

volumes:
  whisper_cache:

networks:
  transcribeops:
    external: true
    name: transcribeops-shared
```

---

## Flask-Konfiguration

Die Flask-Konfiguration befindet sich in `web-app/config.py`:

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

### Erklärung

| Setting | Beschreibung |
|---------|-------------|
| `SECRET_KEY` | Wird für Session-Cookies, CSRF-Tokens und OIDC-State verwendet. **Muss in Produktion auf einen sicheren Zufallswert gesetzt werden.** |
| `SQLALCHEMY_DATABASE_URI` | Datenbankverbindung. Standard ist SQLite. |
| `SQLALCHEMY_TRACK_MODIFICATIONS` | Deaktiviert (Performance-Grund). |
| `UPLOAD_FOLDER` | Verzeichnis für temporäre Audio-Uploads. |
| `AUDIO_STORAGE_PATH` | Verzeichnis für permanente Audio-Archivierung. |
| `MAX_CONTENT_LENGTH` | Maximale Upload-Größe (500 MB). |
| `CELERY_BROKER_URL` | Redis-URL für Celery Message Broker. |
| `CELERY_RESULT_BACKEND` | Redis-URL für Celery Task Results. |

---

## Whisper API Konfiguration

### Modellgrößen

| Modell | Parameter | RAM (CPU) | Genauigkeit |
|--------|-----------|-----------|-------------|
| `tiny` | 39 M | ~1 GB | Gering |
| `base` | 74 M | ~1 GB | Gering-Mittel |
| `small` | 244 M | ~2 GB | Mittel |
| `medium` | 769 M | ~4 GB | Gut |
| `large-v3` | 1.55 B | ~6 GB | Sehr gut |
| `turbo` | 809 M | ~6 GB | Sehr gut |

### Compute Types

| Typ | Beschreibung | GPU/CPU |
|-----|-------------|---------|
| `int8` | 8-Bit Integer Quantisierung — weniger RAM, etwas weniger genau | CPU/GPU |
| `float16` | 16-Bit Floating Point — Standard für GPU | GPU empfohlen |
| `float32` | 32-Bit Floating Point — höchste Genauigkeit, mehr RAM | CPU/GPU |

### Modell-Mapping

Wenn `model=whisper-1` oder `model=whisper-large-v3` als Parameter übergeben wird, verwendet der Server das konfigurierte Standardmodell (`WHISPER_MODEL`). Alle anderen Werte werden direkt als Modellgröße interpretiert.

---

## Systemeinstellungen (Datenbank)

Folgende Einstellungen werden in der Tabelle `system_settings` als Key-Value-Paare gespeichert und über das Admin-Portal verwaltet:

### Globale Einstellungen

| Key | Beschreibung | Standard | Verwaltet in |
|-----|-------------|----------|-------------|
| `timezone` | System-Zeitzone (IANA-Format) | `Europe/Berlin` | Admin > Global |

### SSO-Einstellungen

| Key | Beschreibung | Standard | Verwaltet in |
|-----|-------------|----------|-------------|
| `sso_enabled` | SSO aktiviert | `false` | Admin > SSO |
| `sso_method` | SSO-Methode | `header` | Admin > SSO |
| `sso_header_email` | E-Mail-Header (Header-SSO) | — | Admin > SSO |
| `sso_header_name` | Name-Header (Header-SSO) | — | Admin > SSO |
| `sso_auto_create` | Benutzer automatisch erstellen | `false` | Admin > SSO |
| `sso_default_admin` | Auto-erstellte User als Admin | `false` | Admin > SSO |
| `oidc_discovery_url` | OIDC Discovery URL | — | Admin > SSO |
| `oidc_client_id` | OIDC Client ID | — | Admin > SSO |
| `oidc_client_secret` | OIDC Client Secret | — | Admin > SSO |
| `oidc_scopes` | OIDC Scopes | `openid email profile` | Admin > SSO |
| `oidc_email_claim` | OIDC E-Mail Claim | `email` | Admin > SSO |
| `oidc_name_claim` | OIDC Name Claim | `name` | Admin > SSO |

---

## Netzwerk-Konfiguration

### Docker-Netzwerke

| Netzwerk | Typ | Zweck |
|----------|-----|-------|
| `default` | Bridge (intern) | Kommunikation zwischen web, worker, redis |
| `transcribeops-shared` | External Bridge | Kommunikation zwischen web-app und whisper-api |

### Port-Übersicht

| Service | Interner Port | Externer Port | Beschreibung |
|---------|--------------|---------------|-------------|
| Web-App | 5000 | 5050 | Weboberfläche |
| Whisper API | 8000 | 8090 | Speech-to-Text API |
| Redis | 6379 | — (nur intern) | Message Broker |

### Service-Kommunikation

| Von | Nach | URL |
|----|------|-----|
| Web/Worker | Whisper | `http://whisper:8000/v1/audio/transcriptions` |
| Web/Worker | Redis | `redis://redis:6379/0` |
| Web/Worker | Ollama | `http://ollama:11434` (extern konfiguriert) |
| Web/Worker | OpenAI | `https://api.openai.com/v1/...` |
| Web/Worker | Azure | `https://{endpoint}.openai.azure.com/...` |

> **Hinweis:** Der Hostname `whisper` wird über das Docker-Netzwerk `transcribeops-shared` aufgelöst. Falls der Whisper-Service auf einem anderen Host läuft, muss die URL im Sprachmodell entsprechend angepasst werden.

---

## Ports anpassen

### Web-App Port ändern

```yaml
# docker-compose.yml
services:
  web:
    ports:
      - "8080:5000"  # Web-App auf Port 8080 erreichbar
```

### Whisper API Port ändern

```yaml
# docker-compose.yml
services:
  whisper:
    ports:
      - "9000:8000"  # Whisper API auf Port 9000 erreichbar
```

> **Wichtig:** Die internen Ports (5000 für web, 8000 für whisper) sollten nicht geändert werden. Nur der externe (Host-)Port ist relevant.
