# Architecture & Technology

## Table of Contents

- [System Architecture](#system-architecture)
- [Technology Stack](#technology-stack)
- [Project Structure](#project-structure)
- [Data model](#data-model)
- [Authentication & Authorization](#authentication--authorization)
- [Celery Task System](#celery-task-system)
- [Speech Providers](#speech-providers)
- [Text Providers](#text-providers)
- [Audio Processing](#audio-processing)
- [Frontend Architecture](#frontend-architecture)
- [Database Migrations](#database-migrations)

---

## System Architecture

TranscribeOps consists of multiple Docker services that communicate over a shared network:

```
┌────────────────────────────────────────────────────────────────────┐
│                        Docker Host                                 │
│                                                                    │
│  ┌──────────────────── web-app (docker-compose) ──────────────┐   │
│  │                                                             │   │
│  │  ┌─────────┐    ┌──────────┐    ┌─────────────────────┐   │   │
│  │  │   web   │    │  worker  │    │       redis         │   │   │
│  │  │ (Flask/ │    │ (Celery) │    │ (Message Broker)    │   │   │
│  │  │Gunicorn)│    │          │    │                     │   │   │
│  │  │ :5000   │    │          │    │ :6379               │   │   │
│  │  └────┬────┘    └────┬─────┘    └──────────┬──────────┘   │   │
│  │       │              │                      │              │   │
│  │       └──────────────┼──────────────────────┘              │   │
│  │                      │                                     │   │
│  │              ┌───────┴────────┐                            │   │
│  │              │    SQLite DB   │                            │   │
│  │              │ /app/data/*.db │                            │   │
│  │              └────────────────┘                            │   │
│  └─────────────────────────────────────────────────────────────┘   │
│                         │                                          │
│              transcribeops-shared (Docker Network)                 │
│                         │                                          │
│  ┌──────────────────────┴──────────────────────────────────────┐  │
│  │              whisper-api (docker-compose)                    │  │
│  │  ┌──────────────────────────────────┐                       │  │
│  │  │         whisper                  │                       │  │
│  │  │  (faster-whisper / Flask)        │                       │  │
│  │  │  :8000                           │                       │  │
│  │  └──────────────────────────────────┘                       │  │
│  └─────────────────────────────────────────────────────────────┘  │
│                                                                    │
└────────────────────────────────────────────────────────────────────┘
                    │                    │
          ┌────────┴────────┐  ┌────────┴────────┐
          │   OpenAI API    │  │   Ollama API    │
          │   (external)    │  │ (external/local)│
          └─────────────────┘  └─────────────────┘
```

### Request flow (Transcription)

```
1. Browser  ──POST /api/upload──▶  Flask (web)
2. Flask    ──saves file──▶        /app/static/uploads/
3. Flask    ──creates Job record──▶  SQLite
4. Flask    ──task.delay()──▶      Redis (Broker)
5. Celery   ──reads task──▶        Redis
6. Celery   ──converts audio──▶    FFmpeg → MP3
7. Celery   ──API call──▶          Whisper API / OpenAI / Azure
8. Celery   ──stores result──▶     SQLite
9. Browser  ──GET /api/job/{id}──▶ Flask → SQLite → JSON
```

---

## Technology Stack

### Backend

| Package | Version | Function |
|---------|---------|----------|
| Flask | 3.1.0 | Web framework |
| Flask-SQLAlchemy | 3.1.1 | ORM (database abstraction) |
| Flask-Login | 0.6.3 | Session management / authentication |
| Flask-Migrate | 4.1.0 | Database migrations |
| Flask-WTF | 1.2.2 | CSRF protection |
| SQLAlchemy | 2.0.36 | SQL toolkit & ORM |
| Werkzeug | 3.1.3 | WSGI utilities |
| Celery | 5.4.0 | Asynchronous task queue |
| Redis | 5.2.1 | Redis client |
| requests | 2.32.3 | HTTP client for API calls |
| openai | 1.58.1 | OpenAI Python SDK |
| Authlib | 1.4.1 | OAuth2/OIDC client (SSO) |
| Gunicorn | 23.0.0 | WSGI production server |

### Whisper API

| Package | Version | Function |
|---------|---------|----------|
| Flask | 3.1.0 | API server |
| faster-whisper | 1.1.1 | Optimized Whisper implementation |
| Gunicorn | 23.0.0 | Production server |

### Frontend

| Technology | Version | Function |
|------------|---------|----------|
| Bootstrap | 5.3.3 | UI framework & responsive design |
| Bootstrap Icons | 1.11.3 | Icon set |
| JavaScript | ES6+ | Frontend logic (vanilla, no framework) |

### Infrastructure

| Technology | Function |
|------------|----------|
| Docker | Containerization |
| Docker Compose | Multi-container orchestration |
| FFmpeg | Audio conversion (libmp3lame) |
| SQLite | Embedded database |
| Redis 7 Alpine | Message broker & task result backend |

---

## Project Structure

```
TranscribeOps/
├── docs/                              # Documentation
│   ├── README.md                      # Overview
│   ├── installation.md                # Installation guide
│   ├── architecture.md                # Architecture (this file)
│   ├── configuration.md               # Configuration
│   ├── api-reference.md               # API reference
│   ├── admin-guide.md                 # Admin guide
│   ├── user-guide.md                  # User guide
│   ├── whisper-api.md                 # Whisper API docs
│   └── sso-setup.md                   # SSO setup
│
├── web-app/                           # Main web application
│   ├── Dockerfile                     # Container definition
│   ├── requirements.txt               # Python dependencies
│   ├── config.py                      # Flask configuration
│   ├── run.py                         # Application entrypoint
│   ├── celery_worker.py               # Celery worker setup
│   │
│   └── app/
│       ├── __init__.py                # App factory, migrations, seeds
│       ├── models.py                  # SQLAlchemy data models
│       ├── tasks.py                   # Celery tasks (speech, text, chat)
│       ├── celery_app.py              # Celery instance configuration
│       ├── sso.py                     # SSO helper module
│       ├── utils.py                   # Utility functions (timezone, format)
│       │
│       ├── routes/
│       │   ├── auth.py                # Login, logout, SSO, OIDC
│       │   ├── main.py                # Page routes (transcription, etc.)
│       │   ├── api.py                 # REST API endpoints
│       │   └── admin.py               # Admin portal routes
│       │
│       ├── static/
│       │   ├── css/style.css          # Stylesheet
│       │   ├── js/app.js              # Frontend JavaScript
│       │   ├── img/                   # Favicon, logo
│       │   └── uploads/               # Temporary file uploads
│       │
│       └── templates/
│           ├── base.html              # Base layout with sidebar
│           ├── auth/                  # Login templates
│           ├── main/                  # Feature pages
│           └── admin/                 # Admin portal
│
├── whisper-api/                       # Local Whisper service
│   ├── Dockerfile
│   ├── requirements.txt
│   └── app.py                         # OpenAI-compatible API server
│
└── global-assets/                     # Shared assets
    └── icon/                          # App icons
```

---

## Data model

### Entity-Relationship Diagram

```
┌──────────┐  M:N  ┌──────────┐  M:N  ┌─────────────┐
│   User   │◄─────▶│  Group   │◄─────▶│ SpeechModel │
│          │       │          │       └─────────────┘
│          │       │          │  M:N  ┌─────────────┐
│          │       │          │◄─────▶│  TextModel  │
└────┬─────┘       └──────────┘       └─────────────┘
     │ 1:N
     ├──────────────▶ Job
     ├──────────────▶ Meeting
     ├──────────────▶ Dictation
     ├──────────────▶ TextTask
     ├──────────────▶ DictionaryEntry
     └──────────────▶ ChatMessage

┌──────────────┐
│SystemSetting │  (Key-Value Store)
└──────────────┘
```

### Tables in detail

#### `users`

| Column | Type | Description |
|--------|------|-------------|
| `id` | Integer | Primary key |
| `display_name` | String(80) | Display name |
| `email` | String(120) | Email (unique) |
| `password_hash` | String(256) | Hashed password (nullable for SSO) |
| `is_admin` | Boolean | Admin privileges |
| `is_active_user` | Boolean | Account active |
| `theme` | String(20) | `light`, `dark`, `auto` |
| `history_days` | Integer | History filter (days, default: 30) |
| `auth_source` | String(20) | `local`, `header_sso`, `oidc` |
| `external_id` | String(255) | OIDC `sub` claim |
| `created_at` | DateTime | Creation timestamp (UTC) |

#### `groups`

| Column | Type | Description |
|--------|------|-------------|
| `id` | Integer | Primary key |
| `name` | String(80) | Group name (unique) |
| `description` | String(255) | Description |
| `is_default` | Boolean | Default group for new users |
| `transcription_enabled` | Boolean | Access to transcription |
| `meeting_enabled` | Boolean | Access to meetings |
| `dictation_enabled` | Boolean | Access to dictation |
| `text_tools_enabled` | Boolean | Access to text tools |
| `dictionary_enabled` | Boolean | Access to dictionary |
| `auto_title_enabled` | Boolean | Automatic title generation |
| `auto_title_model_id` | FK(TextModel) | Text model for auto-title |
| `auto_summary_enabled` | Boolean | Automatic summarization |
| `auto_summary_model_id` | FK(TextModel) | Text model for auto-summary |
| `audio_save_enabled` | Boolean | Audio archiving allowed |
| `audio_save_default` | Boolean | Audio archiving as default |
| `hide_single_model` | Boolean | Hide model selector when only one model is available |

#### `speech_models`

| Column | Type | Description |
|--------|------|-------------|
| `id` | Integer | Primary key |
| `name` | String(100) | Internal name |
| `display_name` | String(100) | Display name |
| `provider` | String(50) | `whisper_local`, `openai`, `azure` |
| `endpoint_url` | String(500) | API endpoint URL |
| `api_key` | String(500) | API key |
| `model_id` | String(100) | Model identifier |
| `azure_deployment` | String(100) | Azure deployment name |
| `azure_api_version` | String(50) | Azure API version |
| `speaker_mode` | String(10) | `single`, `multi`, `both` |
| `supports_prompt` | Boolean | Supports custom prompt |
| `supports_timestamps` | Boolean | Supports timestamps |
| `supports_diarize` | Boolean | Supports speaker diarization |
| `is_active` | Boolean | Model active |

#### `text_models`

| Column | Type | Description |
|--------|------|-------------|
| `id` | Integer | Primary key |
| `name` | String(100) | Internal name |
| `display_name` | String(100) | Display name |
| `provider` | String(50) | `ollama`, `openai`, `azure` |
| `endpoint_url` | String(500) | API endpoint URL |
| `api_key` | String(500) | API key |
| `model_id` | String(100) | Model identifier |
| `azure_deployment` | String(100) | Azure deployment name |
| `azure_api_version` | String(50) | Azure API version |
| `is_active` | Boolean | Model active |

#### `jobs`

| Column | Type | Description |
|--------|------|-------------|
| `id` | Integer | Primary key |
| `public_id` | String(32) | UUID for external references |
| `user_id` | FK(User) | Owner |
| `job_type` | String(30) | Always `transcription` |
| `status` | String(20) | `pending`, `processing`, `completed`, `failed` |
| `title` | String(255) | Title (initially = filename) |
| `original_filename` | String(255) | Original filename |
| `file_path` | String(500) | Path to audio file |
| `speech_model_id` | FK(SpeechModel) | Speech model used |
| `text_model_id` | FK(TextModel) | Text model (for tools) |
| `language` | String(10) | Language code (e.g. `de`, `en`) |
| `multi_speaker` | Boolean | Multi-speaker mode |
| `result_text` | Text | Transcription result |
| `diarized_segments` | Text | JSON array of segments |
| `summary_text` | Text | Summary |
| `summary_status` | String(20) | Summary status |
| `tool_action` | String(30) | Text tool action |
| `target_language` | String(50) | Target language for translation |
| `error_message` | Text | Error message |
| `audio_saved` | Boolean | Audio file archived |
| `celery_task_id` | String(155) | Celery task ID |
| `created_at` | DateTime | Creation timestamp (UTC) |
| `completed_at` | DateTime | Completion timestamp |

#### `meetings`

Identical to `jobs`, but without `job_type`, `multi_speaker` (always true), `tool_action`, `target_language`, `input_text`.

#### `dictations`

Like `jobs`, but without `text_model_id`, `summary_text`, `summary_status`, `tool_action`, `target_language`, `input_text`.

#### `text_tasks`

| Column | Type | Description |
|--------|------|-------------|
| `id` | Integer | Primary key |
| `public_id` | String(32) | UUID |
| `user_id` | FK(User) | Owner |
| `action` | String(30) | `rewrite`, `grammar`, `translate`, `summarize` |
| `status` | String(20) | `pending`, `processing`, `completed`, `failed` |
| `input_text` | Text | Input text |
| `result_text` | Text | Result |
| `target_language` | String(50) | Target language (for translation) |
| `text_model_id` | FK(TextModel) | Text model used |
| `error_message` | Text | Error message |

#### `dictionary_entries`

| Column | Type | Description |
|--------|------|-------------|
| `id` | Integer | Primary key |
| `user_id` | FK(User) | Owner |
| `word` | String(200) | Word/term |
| `description` | String(500) | Description |

#### `chat_messages`

| Column | Type | Description |
|--------|------|-------------|
| `id` | Integer | Primary key |
| `public_id` | String(32) | UUID |
| `record_type` | String(20) | `job` or `meeting` |
| `record_id` | Integer | Reference to Job/Meeting ID |
| `user_id` | FK(User) | Owner |
| `role` | String(20) | `user` or `assistant` |
| `content` | Text | Message content |
| `status` | String(20) | `completed`, `processing`, `failed` |
| `text_model_id` | FK(TextModel) | Text model used |

#### `system_settings`

| Column | Type | Description |
|--------|------|-------------|
| `key` | String(100) | Key (primary key) |
| `value` | String(500) | Value |

Stored settings: `timezone`, `sso_enabled`, `sso_method`, `sso_header_email`, `sso_header_name`, `sso_auto_create`, `sso_default_admin`, `oidc_discovery_url`, `oidc_client_id`, `oidc_client_secret`, `oidc_scopes`, `oidc_email_claim`, `oidc_name_claim`.

### Association tables

| Table | Relationship |
|-------|--------------|
| `user_groups` | User ↔ Group (M:N) |
| `group_speech_models` | Group ↔ SpeechModel (M:N) |
| `group_text_models` | Group ↔ TextModel (M:N) |

---

## Authentication & Authorization

### Login methods

1. **Local login** — Email + password (Werkzeug `generate_password_hash` / `check_password_hash`)
2. **Header-based SSO** — Reverse proxy sets HTTP headers with email/name
3. **OIDC** — OpenID Connect Authorization Code Flow (Authlib)

### Authorization

Access control is handled through **groups**:

- Each user belongs to one or more groups
- Each group defines which **features** are enabled (transcription, meetings, dictation, text tools, dictionary)
- Each group defines which **models** are available (speech + text)
- Groups also control auto features (auto-title, auto-summary, audio archiving)
- **Admins** automatically have access to all features and models

### Session management

- Flask-Login with `remember=True` (persistent sessions)
- CSRF protection via Flask-WTF for all forms
- API endpoints are protected with `@login_required`

---

## Celery Task System

### Task overview

| Task | Trigger | Function |
|------|---------|----------|
| `process_transcription` | Upload (Job) | Audio → Transcription |
| `process_meeting` | Upload (Meeting) | Audio → Meeting protocol |
| `process_dictation` | Upload (Dictation) | Audio → Dictation text |
| `process_text_tool` | Text tool form | Text processing |
| `process_summary` | Manual / Auto | Generate summary |
| `process_auto_title` | Auto (after transcription) | Generate AI title |
| `process_chat_message` | Send chat | Multi-turn AI response |

### Task flow (Transcription)

```python
# 1. API receives upload
record = Job(status='pending', ...)
db.session.commit()
process_transcription.delay(record.id)

# 2. Worker processes
job.status = 'processing'
_persist_audio_file(job, app)       # MP3 conversion + permanent storage
_run_speech_processing(job, ...)    # API call to speech provider
_cleanup_temp_file(job, temp_path)  # Remove upload file
_trigger_auto_tasks(...)            # Auto-title + auto-summary

# 3. Frontend polls status
# GET /api/job/{id} → { status: 'completed', result_text: '...' }
```

### Auto tasks

After a successful transcription, additional tasks are triggered automatically (if enabled in the user's group):

1. **Auto-title** — Generates a short title (5-8 words) based on the first 500 characters of the transcription
2. **Auto-summary** — Creates a structured summary (only for jobs and meetings)

### Configuration

```python
# celery_app.py
celery = Celery('transcribeops',
    broker='redis://redis:6379/0',
    backend='redis://redis:6379/0')

celery.conf.update(
    task_serializer='json',
    accept_content=['json'],
    result_serializer='json',
    timezone='UTC',
    enable_utc=True,
)
```

**Worker start:**
```bash
celery -A celery_worker.celery worker --loglevel=info --concurrency=2
```

---

## Speech Providers

### Local Whisper (`whisper_local`)

- **API:** OpenAI-compatible (`POST /v1/audio/transcriptions`)
- **Formats:** `json`, `verbose_json` (with timestamps)
- **Features:** Language prompt (dictionary), timestamped segments
- **Diarization:** Not supported

### OpenAI Whisper (`openai`)

- **API:** `https://api.openai.com/v1/audio/transcriptions`
- **Formats:** `json`, `verbose_json`, `diarized_json`
- **Features:** Language prompt, timestamps, speaker recognition
- **Authentication:** Bearer token

### Azure Speech (`azure`)

- **API:** `{endpoint}/openai/deployments/{deployment}/audio/transcriptions?api-version={version}`
- **Formats:** `json`, `verbose_json`, `diarized_json`
- **Features:** Language prompt, timestamps, speaker recognition
- **Authentication:** `api-key` header

### Diarization response parsing

For OpenAI and Azure, the diarization response is parsed either as:
- **SSE (Server-Sent Events):** Line-by-line parsing of `transcript.text.segment` events
- **JSON:** Direct `segments` array with `speaker`, `text`, `start`, `end`

---

## Text Providers

### Ollama (`ollama`)

- **API:** `{endpoint}/api/chat`
- **Payload:** `{ model, messages: [{role, content}], stream: false }`
- **Example:** `http://ollama:11434/api/chat`

### OpenAI (`openai`)

- **API:** `https://api.openai.com/v1/chat/completions`
- **Payload:** `{ model, messages: [{role, content}] }`
- **Authentication:** Bearer token

### Azure OpenAI (`azure`)

- **API:** `{endpoint}/openai/deployments/{deployment}/chat/completions?api-version={version}`
- **Payload:** `{ messages: [{role, content}] }`
- **Authentication:** `api-key` header

### Text actions and prompts

| Action | System prompt |
|--------|---------------|
| `rewrite` | Rewrite text and improve style |
| `grammar` | Check grammar/spelling, correct errors |
| `translate` | Translate text into target language |
| `summarize` | Summarize text |

---

## Audio Processing

### Conversion

Audio files are converted to MP3 with **FFmpeg** before archiving:

```bash
ffmpeg -i <input> -codec:a libmp3lame -q:a 4 -y <output>.mp3
```

- **Codec:** LAME MP3 (`libmp3lame`)
- **Quality:** VBR level 4 (~165 kbps)
- **Timeout:** 600 seconds (10 minutes)

### Supported upload formats

| Format | MIME type |
|--------|-----------|
| `.mp3` | `audio/mpeg` |
| `.wav` | `audio/wav` |
| `.ogg` | `audio/ogg` |
| `.webm` | `audio/webm` |
| `.flac` | `audio/flac` |
| `.m4a` | `audio/mp4` |
| `.mp4` | `audio/mp4` |
| `.mpeg` | `audio/mpeg` |
| `.mpga` | `audio/mpeg` |

### File size

Maximum upload size: **500 MB** (configured via `MAX_CONTENT_LENGTH`).

### Storage strategy

1. **Upload** — File is saved to `/app/static/uploads/` with a UUID prefix
2. **Archiving** — If enabled: MP3 conversion + copy to `/app/audio_storage/`
3. **Cleanup** — Original upload is deleted after transcription
4. **Streaming** — Archived files are served through API endpoints with HTTP Range support

---

## Frontend Architecture

### Template system

- **Jinja2 templates** with inheritance (`base.html` → feature templates)
- **Bootstrap 5.3** for responsive layout
- **Bootstrap Icons** for the icon set

### Base layout (`base.html`)

- Responsive sidebar navigation with feature links
- Theme toggle (light/dark/auto) in the footer
- Flash messages for notifications
- Offcanvas sidebar for mobile

### JavaScript (`app.js`)

- **Polling mechanism** — Periodic status queries for running tasks
- **File upload** — `FormData` with progress tracking
- **Audio player** — Integrated player with seeking support
- **Inline editing** — Titles and segment texts editable directly
- **AI chat** — Real-time chat interface with auto-scroll

### Theme support

- `light` — Light theme
- `dark` — Dark theme (Bootstrap dark mode)
- `auto` — Follows operating system setting (`prefers-color-scheme`)

Stored in `User.theme`, applied via the `data-bs-theme` attribute.

---

## Database Migrations

TranscribeOps uses a **lightweight auto-migration system** (no Alembic). At app start, `_apply_migrations()` inspects the database structure and adds missing columns/tables:

```python
def _apply_migrations(app, db):
    with db.engine.connect() as conn:
        # Check whether table/column exists
        if _has_table('users') and not _has_column('users', 'theme'):
            _safe_execute(conn, "ALTER TABLE users ADD COLUMN theme VARCHAR(20) DEFAULT 'auto'")
        # ...further migrations
```

### Migrated features

- User: `theme`, `history_days`, `auth_source`, `external_id`
- Group: `auto_title_*`, `auto_summary_*`, `audio_save_*`, `hide_single_model`
- SpeechModel: `supports_diarize`, `azure_*`
- TextModel: `azure_*`
- Jobs: `summary_text`, `summary_status`, `audio_saved`, `celery_task_id`
- New tables: `system_settings`, `chat_messages`, `dictations`, `text_tasks`
