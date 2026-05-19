# TranscribeOps Dokumentation

TranscribeOps ist eine Self-Hosted Webanwendung zur automatischen Transkription, Meeting-Protokollierung, Diktat-Erkennung und KI-gestützten Textverarbeitung. Die Anwendung unterstützt mehrere Speech-to-Text- und Text-KI-Provider und lässt sich vollständig über ein Admin-Portal konfigurieren.

---

## Dokumentationsübersicht

| Dokument | Beschreibung |
|----------|-------------|
| [Installation & Deployment](installation.md) | Docker-Setup, Systemvoraussetzungen, erster Start |
| [Update](updating.md) | Update auf die neueste Version (Docker / Podman, rootless / rootful, Standalone Whisper API) |
| [Architektur & Technik](architecture.md) | Technischer Stack, Projektstruktur, Datenmodell, Celery-Tasks |
| [Konfiguration](configuration.md) | Umgebungsvariablen, Datenbank, Redis, Audio-Speicher |
| [API-Referenz](api-reference.md) | Alle REST-API-Endpunkte mit Request/Response-Dokumentation |
| [Admin-Handbuch](admin-guide.md) | Benutzerverwaltung, Gruppen, Modelle, globale Einstellungen |
| [Benutzerhandbuch](user-guide.md) | Transkription, Meetings, Diktat, Text-Tools, Wörterbuch, Chat |
| [Whisper API Service](whisper-api.md) | Lokaler Whisper-Server, Endpunkte, Modellkonfiguration |
| [SSO-Setup](sso-setup.md) | Single Sign-On (Header-basiert & OIDC) |

---

## Schnellstart

```bash
# 1. Docker-Netzwerk erstellen (einmalig)
docker network create transcribeops-shared

# 2. Konfiguration erstellen
cp docker-compose.example.yml docker-compose.yml
cp .env.example .env
# .env anpassen (mindestens SECRET_KEY setzen!)

# 3. Stack starten
docker compose up -d

# 4. Im Browser öffnen
open http://localhost:5000
```

**Standard-Login:**
- E-Mail: `admin@transcribeops.local`
- Passwort: `admin`

---

## Features

### Spracherkennung
- **Transkription** — Audiodateien hochladen und transkribieren (Einzel- oder Mehrsprecher)
- **Meeting-Protokoll** — Meetings aufnehmen oder hochladen mit automatischer Sprechererkennung
- **Diktat** — Direktaufnahme im Browser mit sofortiger Transkription

### KI-Textverarbeitung
- **Zusammenfassung** — Automatische oder manuelle Zusammenfassung von Transkriptionen
- **Text-Tools** — Umschreiben, Grammatikprüfung, Übersetzung, Zusammenfassung beliebiger Texte
- **KI-Chat** — Multi-Turn-Chat mit Transkriptionen (Fragen zum Inhalt stellen)
- **Auto-Titel** — KI-generierte Titel für neue Transkriptionen

### Provider-Unterstützung
- **Speech-to-Text:** Lokales Whisper (faster-whisper), OpenAI Whisper API, Azure Speech
- **Text-KI:** Ollama (lokal), OpenAI Chat API, Azure OpenAI

### Verwaltung
- **Benutzerverwaltung** — Benutzer, Gruppen, Rollen-basierte Zugriffssteuerung
- **Modellverwaltung** — Mehrere Speech- und Text-Modelle konfigurierbar
- **Single Sign-On** — Header-basiertes SSO und OpenID Connect
- **Wörterbuch** — Benutzerdefinierte Vokabeln zur Verbesserung der Erkennungsgenauigkeit
- **Audio-Archivierung** — Optionale permanente Speicherung von Audiodateien
- **Themes** — Hell, Dunkel, Automatisch

---

## Systemarchitektur (Überblick)

```
┌─────────────┐     ┌────────────┐     ┌───────────────┐
│   Browser    │────▶│  Web-App   │────▶│ Celery Worker │
│  (Frontend)  │◀────│  (Flask)   │     │   (Tasks)     │
└─────────────┘     └─────┬──────┘     └───────┬───────┘
                          │                     │
                    ┌─────┴──────┐        ┌─────┴──────┐
                    │   SQLite   │        │   Redis    │
                    │ (Datenbank)│        │  (Broker)  │
                    └────────────┘        └────────────┘
                                                │
                          ┌─────────────────────┼──────────────────┐
                          │                     │                  │
                    ┌─────┴──────┐     ┌────────┴─────┐   ┌───────┴──────┐
                    │ Whisper API│     │  OpenAI API  │   │  Ollama API  │
                    │  (lokal)   │     │  (extern)    │   │   (lokal)    │
                    └────────────┘     └──────────────┘   └──────────────┘
```

---

## Technologien

| Komponente | Technologie |
|-----------|------------|
| Backend | Python 3.12, Flask 3.1 |
| Datenbank | SQLite (SQLAlchemy ORM) |
| Task Queue | Celery 5.4 + Redis 7 |
| Frontend | Bootstrap 5.3, Vanilla JavaScript |
| Speech-to-Text | faster-whisper, OpenAI API, Azure Speech |
| Text-KI | Ollama, OpenAI API, Azure OpenAI |
| Audio-Konvertierung | FFmpeg (libmp3lame) |
| Authentifizierung | Flask-Login, Authlib (OIDC) |
| Deployment | Docker, Docker Compose, Gunicorn |
