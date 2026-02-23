# Architektur & Technik

## Inhaltsverzeichnis

- [Systemarchitektur](#systemarchitektur)
- [Technologie-Stack](#technologie-stack)
- [Projektstruktur](#projektstruktur)
- [Datenmodell](#datenmodell)
- [Authentifizierung & Autorisierung](#authentifizierung--autorisierung)
- [Celery Task-System](#celery-task-system)
- [Speech-Provider](#speech-provider)
- [Text-Provider](#text-provider)
- [Audio-Verarbeitung](#audio-verarbeitung)
- [Frontend-Architektur](#frontend-architektur)
- [Datenbank-Migrationen](#datenbank-migrationen)

---

## Systemarchitektur

TranscribeOps besteht aus mehreren Docker-Services, die über ein gemeinsames Netzwerk kommunizieren:

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
          │   (extern)      │  │   (extern/lokal)│
          └─────────────────┘  └─────────────────┘
```

### Request-Flow (Transkription)

```
1. Browser  ──POST /api/upload──▶  Flask (web)
2. Flask    ──speichert Datei──▶   /app/static/uploads/
3. Flask    ──erstellt Job-Record──▶  SQLite
4. Flask    ──task.delay()──▶      Redis (Broker)
5. Celery   ──liest Task──▶       Redis
6. Celery   ──konvertiert Audio──▶ FFmpeg → MP3
7. Celery   ──API-Call──▶          Whisper API / OpenAI / Azure
8. Celery   ──speichert Ergebnis──▶ SQLite
9. Browser  ──GET /api/job/{id}──▶ Flask → SQLite → JSON
```

---

## Technologie-Stack

### Backend

| Paket | Version | Funktion |
|-------|---------|----------|
| Flask | 3.1.0 | Web-Framework |
| Flask-SQLAlchemy | 3.1.1 | ORM (Datenbankabstraktion) |
| Flask-Login | 0.6.3 | Session-Management / Authentifizierung |
| Flask-Migrate | 4.1.0 | Datenbank-Migrationen |
| Flask-WTF | 1.2.2 | CSRF-Schutz |
| SQLAlchemy | 2.0.36 | SQL-Toolkit & ORM |
| Werkzeug | 3.1.3 | WSGI-Utilities |
| Celery | 5.4.0 | Asynchrone Task Queue |
| Redis | 5.2.1 | Redis-Client |
| requests | 2.32.3 | HTTP-Client für API-Calls |
| openai | 1.58.1 | OpenAI Python SDK |
| Authlib | 1.4.1 | OAuth2/OIDC-Client (SSO) |
| Gunicorn | 23.0.0 | WSGI Production Server |

### Whisper API

| Paket | Version | Funktion |
|-------|---------|----------|
| Flask | 3.1.0 | API-Server |
| faster-whisper | 1.1.1 | Optimierte Whisper-Implementierung |
| Gunicorn | 23.0.0 | Production Server |

### Frontend

| Technologie | Version | Funktion |
|------------|---------|----------|
| Bootstrap | 5.3.3 | UI-Framework & Responsive Design |
| Bootstrap Icons | 1.11.3 | Icon-Set |
| JavaScript | ES6+ | Frontend-Logik (Vanilla, kein Framework) |

### Infrastruktur

| Technologie | Funktion |
|------------|----------|
| Docker | Containerisierung |
| Docker Compose | Multi-Container Orchestrierung |
| FFmpeg | Audio-Konvertierung (libmp3lame) |
| SQLite | Eingebettete Datenbank |
| Redis 7 Alpine | Message Broker & Task Result Backend |

---

## Projektstruktur

```
TranscribeOps/
├── docs/                              # Dokumentation
│   ├── README.md                      # Übersicht
│   ├── installation.md                # Installationsanleitung
│   ├── architecture.md                # Architektur (diese Datei)
│   ├── configuration.md               # Konfiguration
│   ├── api-reference.md               # API-Referenz
│   ├── admin-guide.md                 # Admin-Handbuch
│   ├── user-guide.md                  # Benutzerhandbuch
│   ├── whisper-api.md                 # Whisper API Doku
│   └── sso-setup.md                   # SSO-Setup
│
├── web-app/                           # Haupt-Webanwendung
│   ├── Dockerfile                     # Container-Definition
│   ├── docker-compose.yml             # Service-Orchestrierung
│   ├── requirements.txt               # Python-Abhängigkeiten
│   ├── config.py                      # Flask-Konfiguration
│   ├── run.py                         # Anwendungs-Einstiegspunkt
│   ├── celery_worker.py               # Celery-Worker-Setup
│   │
│   └── app/
│       ├── __init__.py                # App Factory, Migrationen, Seeds
│       ├── models.py                  # SQLAlchemy-Datenmodelle
│       ├── tasks.py                   # Celery-Tasks (Speech, Text, Chat)
│       ├── celery_app.py              # Celery-Instanz-Konfiguration
│       ├── sso.py                     # SSO-Helpermodul
│       ├── utils.py                   # Hilfsfunktionen (Zeitzone, Format)
│       │
│       ├── routes/
│       │   ├── auth.py                # Login, Logout, SSO, OIDC
│       │   ├── main.py                # Seiten-Routes (Transkription, etc.)
│       │   ├── api.py                 # REST-API-Endpunkte
│       │   └── admin.py               # Admin-Portal-Routes
│       │
│       ├── static/
│       │   ├── css/style.css          # Stylesheet
│       │   ├── js/app.js              # Frontend-JavaScript
│       │   ├── img/                   # Favicon, Logo
│       │   └── uploads/               # Temporäre Datei-Uploads
│       │
│       └── templates/
│           ├── base.html              # Basis-Layout mit Sidebar
│           ├── auth/                  # Login-Templates
│           ├── main/                  # Feature-Seiten
│           └── admin/                 # Admin-Portal
│
├── whisper-api/                       # Lokaler Whisper-Service
│   ├── Dockerfile
│   ├── docker-compose.yml
│   ├── requirements.txt
│   └── app.py                         # OpenAI-kompatibler API-Server
│
└── global-assets/                     # Gemeinsame Assets
    └── icon/                          # App-Icons
```

---

## Datenmodell

### Entity-Relationship-Diagramm

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

### Tabellen im Detail

#### `users`

| Spalte | Typ | Beschreibung |
|--------|-----|-------------|
| `id` | Integer | Primärschlüssel |
| `display_name` | String(80) | Anzeigename |
| `email` | String(120) | E-Mail (unique) |
| `password_hash` | String(256) | Gehashtes Passwort (nullable für SSO) |
| `is_admin` | Boolean | Admin-Rechte |
| `is_active_user` | Boolean | Account aktiv |
| `theme` | String(20) | `light`, `dark`, `auto` |
| `history_days` | Integer | Verlaufsfilter (Tage, Standard: 30) |
| `auth_source` | String(20) | `local`, `header_sso`, `oidc` |
| `external_id` | String(255) | OIDC `sub`-Claim |
| `created_at` | DateTime | Erstellungszeitpunkt (UTC) |

#### `groups`

| Spalte | Typ | Beschreibung |
|--------|-----|-------------|
| `id` | Integer | Primärschlüssel |
| `name` | String(80) | Gruppenname (unique) |
| `description` | String(255) | Beschreibung |
| `is_default` | Boolean | Standardgruppe für neue Benutzer |
| `transcription_enabled` | Boolean | Zugriff auf Transkription |
| `meeting_enabled` | Boolean | Zugriff auf Meetings |
| `dictation_enabled` | Boolean | Zugriff auf Diktat |
| `text_tools_enabled` | Boolean | Zugriff auf Text-Tools |
| `dictionary_enabled` | Boolean | Zugriff auf Wörterbuch |
| `auto_title_enabled` | Boolean | Automatische Titelgenerierung |
| `auto_title_model_id` | FK(TextModel) | Textmodell für Auto-Titel |
| `auto_summary_enabled` | Boolean | Automatische Zusammenfassung |
| `auto_summary_model_id` | FK(TextModel) | Textmodell für Auto-Summary |
| `audio_save_enabled` | Boolean | Audio-Archivierung erlaubt |
| `audio_save_default` | Boolean | Audio-Archivierung als Standard |
| `hide_single_model` | Boolean | Modellauswahl ausblenden bei nur einem Modell |

#### `speech_models`

| Spalte | Typ | Beschreibung |
|--------|-----|-------------|
| `id` | Integer | Primärschlüssel |
| `name` | String(100) | Interner Name |
| `display_name` | String(100) | Anzeigename |
| `provider` | String(50) | `whisper_local`, `openai`, `azure` |
| `endpoint_url` | String(500) | API-Endpunkt-URL |
| `api_key` | String(500) | API-Schlüssel |
| `model_id` | String(100) | Modell-Bezeichnung |
| `azure_deployment` | String(100) | Azure Deployment Name |
| `azure_api_version` | String(50) | Azure API Version |
| `speaker_mode` | String(10) | `single`, `multi`, `both` |
| `supports_prompt` | Boolean | Unterstützt Custom Prompt |
| `supports_timestamps` | Boolean | Unterstützt Zeitstempel |
| `supports_diarize` | Boolean | Unterstützt Sprechertrennung |
| `is_active` | Boolean | Modell aktiv |

#### `text_models`

| Spalte | Typ | Beschreibung |
|--------|-----|-------------|
| `id` | Integer | Primärschlüssel |
| `name` | String(100) | Interner Name |
| `display_name` | String(100) | Anzeigename |
| `provider` | String(50) | `ollama`, `openai`, `azure` |
| `endpoint_url` | String(500) | API-Endpunkt-URL |
| `api_key` | String(500) | API-Schlüssel |
| `model_id` | String(100) | Modell-Bezeichnung |
| `azure_deployment` | String(100) | Azure Deployment Name |
| `azure_api_version` | String(50) | Azure API Version |
| `is_active` | Boolean | Modell aktiv |

#### `jobs`

| Spalte | Typ | Beschreibung |
|--------|-----|-------------|
| `id` | Integer | Primärschlüssel |
| `public_id` | String(32) | UUID für externe Referenzen |
| `user_id` | FK(User) | Besitzer |
| `job_type` | String(30) | Immer `transcription` |
| `status` | String(20) | `pending`, `processing`, `completed`, `failed` |
| `title` | String(255) | Titel (initial = Dateiname) |
| `original_filename` | String(255) | Originaler Dateiname |
| `file_path` | String(500) | Pfad zur Audio-Datei |
| `speech_model_id` | FK(SpeechModel) | Verwendetes Sprachmodell |
| `text_model_id` | FK(TextModel) | Textmodell (für Tools) |
| `language` | String(10) | Sprach-Code (z.B. `de`, `en`) |
| `multi_speaker` | Boolean | Mehrsprecher-Modus |
| `result_text` | Text | Transkriptionsergebnis |
| `diarized_segments` | Text | JSON-Array mit Segmenten |
| `summary_text` | Text | Zusammenfassung |
| `summary_status` | String(20) | Status der Zusammenfassung |
| `tool_action` | String(30) | Text-Tool-Aktion |
| `target_language` | String(50) | Zielsprache für Übersetzung |
| `error_message` | Text | Fehlermeldung |
| `audio_saved` | Boolean | Audio-Datei archiviert |
| `celery_task_id` | String(155) | Celery Task ID |
| `created_at` | DateTime | Erstellungszeitpunkt (UTC) |
| `completed_at` | DateTime | Abschlusszeitpunkt |

#### `meetings`

Identisch zu `jobs`, aber ohne `job_type`, `multi_speaker` (immer true), `tool_action`, `target_language`, `input_text`.

#### `dictations`

Wie `jobs`, aber ohne `text_model_id`, `summary_text`, `summary_status`, `tool_action`, `target_language`, `input_text`.

#### `text_tasks`

| Spalte | Typ | Beschreibung |
|--------|-----|-------------|
| `id` | Integer | Primärschlüssel |
| `public_id` | String(32) | UUID |
| `user_id` | FK(User) | Besitzer |
| `action` | String(30) | `rewrite`, `grammar`, `translate`, `summarize` |
| `status` | String(20) | `pending`, `processing`, `completed`, `failed` |
| `input_text` | Text | Eingabetext |
| `result_text` | Text | Ergebnis |
| `target_language` | String(50) | Zielsprache (für Übersetzung) |
| `text_model_id` | FK(TextModel) | Verwendetes Textmodell |
| `error_message` | Text | Fehlermeldung |

#### `dictionary_entries`

| Spalte | Typ | Beschreibung |
|--------|-----|-------------|
| `id` | Integer | Primärschlüssel |
| `user_id` | FK(User) | Besitzer |
| `word` | String(200) | Wort/Begriff |
| `description` | String(500) | Beschreibung |

#### `chat_messages`

| Spalte | Typ | Beschreibung |
|--------|-----|-------------|
| `id` | Integer | Primärschlüssel |
| `public_id` | String(32) | UUID |
| `record_type` | String(20) | `job` oder `meeting` |
| `record_id` | Integer | Referenz auf Job/Meeting ID |
| `user_id` | FK(User) | Besitzer |
| `role` | String(20) | `user` oder `assistant` |
| `content` | Text | Nachrichteninhalt |
| `status` | String(20) | `completed`, `processing`, `failed` |
| `text_model_id` | FK(TextModel) | Verwendetes Textmodell |

#### `system_settings`

| Spalte | Typ | Beschreibung |
|--------|-----|-------------|
| `key` | String(100) | Schlüssel (Primärschlüssel) |
| `value` | String(500) | Wert |

Gespeicherte Einstellungen: `timezone`, `sso_enabled`, `sso_method`, `sso_header_email`, `sso_header_name`, `sso_auto_create`, `sso_default_admin`, `oidc_discovery_url`, `oidc_client_id`, `oidc_client_secret`, `oidc_scopes`, `oidc_email_claim`, `oidc_name_claim`.

### Assoziationstabellen

| Tabelle | Beziehung |
|---------|-----------|
| `user_groups` | User ↔ Group (M:N) |
| `group_speech_models` | Group ↔ SpeechModel (M:N) |
| `group_text_models` | Group ↔ TextModel (M:N) |

---

## Authentifizierung & Autorisierung

### Login-Methoden

1. **Lokaler Login** — E-Mail + Passwort (Werkzeug `generate_password_hash` / `check_password_hash`)
2. **Header-basiertes SSO** — Reverse Proxy setzt HTTP-Header mit E-Mail/Name
3. **OIDC** — OpenID Connect Authorization Code Flow (Authlib)

### Autorisierung

Die Zugriffssteuerung erfolgt über **Gruppen**:

- Jeder Benutzer gehört zu einer oder mehreren Gruppen
- Jede Gruppe definiert, welche **Features** aktiviert sind (Transkription, Meetings, Diktat, Text-Tools, Wörterbuch)
- Jede Gruppe definiert, welche **Modelle** verfügbar sind (Speech + Text)
- Gruppen steuern auch Auto-Funktionen (Auto-Titel, Auto-Zusammenfassung, Audio-Archivierung)
- **Admins** haben automatisch Zugriff auf alle Features und Modelle

### Session-Management

- Flask-Login mit `remember=True` (persistente Sessions)
- CSRF-Schutz über Flask-WTF für alle Formulare
- API-Endpunkte sind über `@login_required` geschützt

---

## Celery Task-System

### Task-Übersicht

| Task | Trigger | Funktion |
|------|---------|----------|
| `process_transcription` | Upload (Job) | Audio → Transkription |
| `process_meeting` | Upload (Meeting) | Audio → Meeting-Protokoll |
| `process_dictation` | Upload (Dictation) | Audio → Diktat-Text |
| `process_text_tool` | Text-Tool Formular | Text-Verarbeitung |
| `process_summary` | Manuell / Auto | Zusammenfassung generieren |
| `process_auto_title` | Auto (nach Transkription) | KI-Titel generieren |
| `process_chat_message` | Chat senden | Multi-Turn KI-Antwort |

### Task-Flow (Transkription)

```python
# 1. API erhält Upload
record = Job(status='pending', ...)
db.session.commit()
process_transcription.delay(record.id)

# 2. Worker verarbeitet
job.status = 'processing'
_persist_audio_file(job, app)       # MP3-Konvertierung + permanente Speicherung
_run_speech_processing(job, ...)    # API-Call an Speech Provider
_cleanup_temp_file(job, temp_path)  # Upload-Datei entfernen
_trigger_auto_tasks(...)            # Auto-Titel + Auto-Zusammenfassung

# 3. Frontend pollt Status
# GET /api/job/{id} → { status: 'completed', result_text: '...' }
```

### Auto-Tasks

Nach erfolgreicher Transkription werden automatisch weitere Tasks ausgelöst (falls in der Benutzergruppe aktiviert):

1. **Auto-Titel** — Generiert einen kurzen Titel (5-8 Wörter) basierend auf den ersten 500 Zeichen der Transkription
2. **Auto-Zusammenfassung** — Erstellt eine strukturierte Zusammenfassung (nur für Jobs und Meetings)

### Konfiguration

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

**Worker-Start:**
```bash
celery -A celery_worker.celery worker --loglevel=info --concurrency=2
```

---

## Speech-Provider

### Lokales Whisper (`whisper_local`)

- **API:** OpenAI-kompatibel (`POST /v1/audio/transcriptions`)
- **Formate:** `json`, `verbose_json` (mit Zeitstempeln)
- **Features:** Sprach-Prompt (Wörterbuch), Zeitstempel-Segmente
- **Diarization:** Nicht unterstützt

### OpenAI Whisper (`openai`)

- **API:** `https://api.openai.com/v1/audio/transcriptions`
- **Formate:** `json`, `verbose_json`, `diarized_json`
- **Features:** Sprach-Prompt, Zeitstempel, Sprechererkennung
- **Authentifizierung:** Bearer Token

### Azure Speech (`azure`)

- **API:** `{endpoint}/openai/deployments/{deployment}/audio/transcriptions?api-version={version}`
- **Formate:** `json`, `verbose_json`, `diarized_json`
- **Features:** Sprach-Prompt, Zeitstempel, Sprechererkennung
- **Authentifizierung:** `api-key` Header

### Diarization-Response-Parsing

Für OpenAI und Azure wird die Diarization-Antwort geparst — entweder als:
- **SSE (Server-Sent Events):** Zeilenweises Parsing von `transcript.text.segment` Events
- **JSON:** Direktes `segments`-Array mit `speaker`, `text`, `start`, `end`

---

## Text-Provider

### Ollama (`ollama`)

- **API:** `{endpoint}/api/chat`
- **Payload:** `{ model, messages: [{role, content}], stream: false }`
- **Beispiel:** `http://ollama:11434/api/chat`

### OpenAI (`openai`)

- **API:** `https://api.openai.com/v1/chat/completions`
- **Payload:** `{ model, messages: [{role, content}] }`
- **Authentifizierung:** Bearer Token

### Azure OpenAI (`azure`)

- **API:** `{endpoint}/openai/deployments/{deployment}/chat/completions?api-version={version}`
- **Payload:** `{ messages: [{role, content}] }`
- **Authentifizierung:** `api-key` Header

### Text-Aktionen und Prompts

| Aktion | System-Prompt |
|--------|-------------|
| `rewrite` | Text umschreiben und stilistisch verbessern |
| `grammar` | Grammatik/Rechtschreibung prüfen, Fehler korrigieren |
| `translate` | Text in Zielsprache übersetzen |
| `summarize` | Text zusammenfassen |

---

## Audio-Verarbeitung

### Konvertierung

Audio-Dateien werden vor der Archivierung mit **FFmpeg** zu MP3 konvertiert:

```bash
ffmpeg -i <input> -codec:a libmp3lame -q:a 4 -y <output>.mp3
```

- **Codec:** LAME MP3 (`libmp3lame`)
- **Qualität:** VBR Stufe 4 (~165 kbps)
- **Timeout:** 600 Sekunden (10 Minuten)

### Unterstützte Upload-Formate

| Format | MIME-Type |
|--------|----------|
| `.mp3` | `audio/mpeg` |
| `.wav` | `audio/wav` |
| `.ogg` | `audio/ogg` |
| `.webm` | `audio/webm` |
| `.flac` | `audio/flac` |
| `.m4a` | `audio/mp4` |
| `.mp4` | `audio/mp4` |
| `.mpeg` | `audio/mpeg` |
| `.mpga` | `audio/mpeg` |

### Dateigröße

Maximale Upload-Größe: **500 MB** (konfiguriert über `MAX_CONTENT_LENGTH`).

### Speicher-Strategie

1. **Upload** — Datei wird in `/app/static/uploads/` mit UUID-Präfix gespeichert
2. **Archivierung** — Falls aktiviert: MP3-Konvertierung + Kopie nach `/app/audio_storage/`
3. **Cleanup** — Original-Upload wird nach Transkription gelöscht
4. **Streaming** — Archivierte Dateien werden über API-Endpunkte mit HTTP Range Support bereitgestellt

---

## Frontend-Architektur

### Template-System

- **Jinja2-Templates** mit Vererbung (`base.html` → Feature-Templates)
- **Bootstrap 5.3** für Responsive Layout
- **Bootstrap Icons** für Icon-Set

### Basis-Layout (`base.html`)

- Responsive Sidebar-Navigation mit Feature-Links
- Theme-Umschalter (Hell/Dunkel/Auto) im Footer
- Flash-Messages für Benachrichtigungen
- Offcanvas-Sidebar für Mobile

### JavaScript (`app.js`)

- **Polling-Mechanismus** — Regelmäßige Status-Abfragen für laufende Tasks
- **Datei-Upload** — `FormData` mit Progress-Tracking
- **Audio-Player** — Integrierter Player mit Seeking-Support
- **Inline-Editing** — Titel und Segment-Texte direkt bearbeitbar
- **KI-Chat** — Real-time Chat-Interface mit Auto-Scroll

### Theme-Unterstützung

- `light` — Helles Theme
- `dark` — Dunkles Theme (Bootstrap Dark Mode)
- `auto` — Folgt Betriebssystem-Einstellung (`prefers-color-scheme`)

Gespeichert in `User.theme`, angewendet über `data-bs-theme` Attribut.

---

## Datenbank-Migrationen

TranscribeOps verwendet ein **leichtgewichtiges Auto-Migrations-System** (kein Alembic). Beim App-Start prüft `_apply_migrations()` die Datenbankstruktur und fügt fehlende Spalten/Tabellen hinzu:

```python
def _apply_migrations(app, db):
    with db.engine.connect() as conn:
        # Prüft ob Tabelle/Spalte existiert
        if _has_table('users') and not _has_column('users', 'theme'):
            _safe_execute(conn, "ALTER TABLE users ADD COLUMN theme VARCHAR(20) DEFAULT 'auto'")
        # ...weitere Migrationen
```

### Migrierte Features

- User: `theme`, `history_days`, `auth_source`, `external_id`
- Group: `auto_title_*`, `auto_summary_*`, `audio_save_*`, `hide_single_model`
- SpeechModel: `supports_diarize`, `azure_*`
- TextModel: `azure_*`
- Jobs: `summary_text`, `summary_status`, `audio_saved`, `celery_task_id`
- Neue Tabellen: `system_settings`, `chat_messages`, `dictations`, `text_tasks`
