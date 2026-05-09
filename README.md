<div align="center">

<img src="global-assets/icon/transcribeops-256.png" alt="TranscribeOps Logo" width="128" />

# TranscribeOps

**Self-hosted Plattform für Audio-Transkription, Meeting-Protokolle, Diktat und KI-gestützte Textverarbeitung.**

[![License](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)
[![Docker](https://img.shields.io/badge/docker-ready-blue.svg)](https://www.docker.com/)
[![Python](https://img.shields.io/badge/python-3.12-yellow.svg)](https://www.python.org/)

[Features](#-features) · [Schnellstart](#-schnellstart) · [Deployment-Varianten](#-deployment-varianten) · [Konfiguration](#%EF%B8%8F-konfiguration) · [Dokumentation](docs/README.md)

</div>

---

## ✨ Features

- 🎙️ **Transkription** — Audiodateien hochladen und automatisch transkribieren (mit Sprechererkennung)
- 📝 **Meeting-Protokolle** — Aufnahmen mit Sprechertrennung und automatischer Zusammenfassung
- 🎤 **Diktat** — Direktaufnahme im Browser mit sofortiger Transkription
- 🤖 **KI-Textverarbeitung** — Umschreiben, Übersetzen, Grammatik, Zusammenfassen
- 💬 **KI-Chat** — Multi-Turn-Chat über deine Transkriptionen ("Was wurde zu X gesagt?")
- 📚 **Wörterbuch** — Eigene Vokabeln zur Verbesserung der Erkennungsgenauigkeit
- 👥 **Benutzer & Gruppen** — Rollen-basierte Zugriffssteuerung, SSO (Header & OIDC)
- 🔌 **Multi-Provider** — Lokales Whisper, OpenAI, Azure Speech / OpenAI, Ollama
- 🐳 **Docker-First** — Komplettes Deployment mit einer Compose-Datei

---

## 🏗️ Architektur

TranscribeOps besteht aus zwei **unabhängigen** Komponenten, die einzeln oder zusammen betrieben werden können:

```
┌──────────────────────────┐         ┌────────────────────────────┐
│      TranscribeOps       │ ──HTTP──▶  TranscribeOps Modell-API  │
│  (Web-App, Flask+Celery) │         │  (faster-whisper / WhisperX)│
│                          │         │  OpenAI-kompatibel         │
└────────────┬─────────────┘         └────────────────────────────┘
             │
             │ optional auch zu:
             ▼
   OpenAI · Azure · Ollama
```

- **TranscribeOps** (`web-app/`) — Die Web-Anwendung mit UI, Benutzerverwaltung, Job-Queue. Spricht beliebige OpenAI-kompatible Speech- und Text-Endpoints an.
- **TranscribeOps Modell-API** (`whisper-api/`) — Eigenständiger, OpenAI-kompatibler Whisper-Server mit Admin-UI zur Verwaltung mehrerer Modelle/Worker. Kann auch von anderen Anwendungen genutzt werden.

---

## 🚀 Schnellstart

```bash
git clone https://github.com/Janinnho/TranscribeOps.git
cd TranscribeOps

# Konfiguration anlegen
cp docker-compose.example.yml docker-compose.yml
cp .env.example .env

# SECRET_KEY generieren und in .env eintragen
python3 -c "import secrets; print(secrets.token_hex(32))"

# Stack starten (Web-App + Worker + Redis + Whisper-API)
docker compose up -d
```

Im Browser öffnen: **http://localhost:5000**

**Erst-Login:** `admin@transcribeops.local` / `admin` — **bitte sofort ändern!**

---

## 📦 Deployment-Varianten

Du kannst dir aussuchen, was du brauchst. Alle drei Varianten basieren auf der einen `docker-compose.example.yml` — du kommentierst einfach die Services aus, die du nicht brauchst.

### 🟦 Variante 1 — Komplettpaket (empfohlen)

> **TranscribeOps + TranscribeOps Modell-API**, alles selbst gehostet, keine externen API-Calls nötig.

Ideal für: Datenschutz-sensible Umgebungen, isolierte Netze, volle Kontrolle.

```bash
cp docker-compose.example.yml docker-compose.yml
cp .env.example .env
# SECRET_KEY in .env setzen
docker compose up -d
```

Beinhaltet alle Services: `web` + `worker` + `redis` + `whisper`. Standardmäßig ist als Sprachmodell bereits `http://whisper:8000/v1/audio/transcriptions` eingetragen — du musst nichts weiter konfigurieren.

Für **KI-Textverarbeitung** (Zusammenfassung, Chat etc.) zusätzlich [Ollama](https://ollama.com) lokal installieren oder einen externen Provider (OpenAI/Azure) im Admin-Portal konfigurieren.

**Ressourcen:** ~6 GB RAM (für `medium`-Modell), ~10 GB Disk.

---

### 🟨 Variante 2 — Nur die Web-App

> **Nur TranscribeOps**, Spracherkennung läuft über externe Provider (OpenAI/Azure) oder eine bereits vorhandene Whisper-Instanz.

Ideal für: Wenn du bereits einen STT-Endpoint hast oder OpenAI/Azure nutzen willst.

In `docker-compose.yml` den `whisper`-Service entfernen oder auskommentieren:

```yaml
services:
  web: { ... }
  worker: { ... }
  redis: { ... }
  # whisper: ...  ← entfernen
```

```bash
docker compose up -d
```

Dann im Admin-Portal (**Admin → Sprachmodelle**) das Standardmodell anpassen — z. B. auf:
- `https://api.openai.com/v1/audio/transcriptions` (OpenAI)
- `https://<dein-endpoint>.openai.azure.com/...` (Azure)
- Beliebige andere OpenAI-kompatible URL

**Ressourcen:** ~1 GB RAM, ~2 GB Disk.

---

### 🟥 Variante 3 — Nur die Modell-API

> **Nur TranscribeOps Modell-API**, als eigenständiger OpenAI-kompatibler Whisper-Server für andere Anwendungen.

Ideal für: Wenn du nur einen lokalen Whisper-Endpoint brauchst und kein Web-UI willst (z. B. um deinen eigenen Code, n8n, Home-Assistant etc. anzubinden).

```bash
cd whisper-api
docker build -t transcribeops-whisper .

docker run -d \
  --name transcribeops-whisper \
  -p 8000:8000 \
  -v whisper-cache:/root/.cache \
  -e WHISPER_API_KEY=mein-geheimer-schluessel \
  -e WHISPER_MODEL=medium \
  -e WHISPER_DEVICE=cpu \
  -e WHISPER_COMPUTE_TYPE=int8 \
  -e ADMIN_PASSWORD=ein-admin-passwort \
  transcribeops-whisper
```

Test:
```bash
curl http://localhost:8000/health

curl -X POST http://localhost:8000/v1/audio/transcriptions \
  -H "Authorization: Bearer mein-geheimer-schluessel" \
  -F "file=@audio.mp3" \
  -F "model=whisper-1"
```

Admin-UI: **http://localhost:8000/admin** (mit `ADMIN_PASSWORD` einloggen).

Mehr Details: [`docs/whisper-api.md`](docs/whisper-api.md)

**Ressourcen:** je nach Modell 1–6 GB RAM.

---

## ⚙️ Konfiguration

Die wichtigsten Umgebungsvariablen (siehe [`.env.example`](.env.example)):

| Variable | Beschreibung | Erforderlich |
|---|---|---|
| `SECRET_KEY` | Flask Session/CSRF Secret (mind. 32 Zeichen) | ✅ Produktion |
| `WHISPER_API_KEY` | API-Key für Modell-API (leer = kein Auth) | optional |
| `HF_TOKEN` | Hugging Face Token für Speaker-Diarization | optional |
| `WHISPER_ADMIN_PASSWORD` | Aktiviert das Whisper-Admin-UI (leer = deaktiviert) | optional |
| `WHISPER_ADMIN_SESSION_SECRET` | Session-Secret für Admin-UI | optional |

**SECRET_KEY generieren:**
```bash
python3 -c "import secrets; print(secrets.token_hex(32))"
```

**HF_TOKEN für Diarization:** Konto auf [huggingface.co](https://huggingface.co) erstellen, einen Read-Token generieren, und folgende Modelle akzeptieren:
- [pyannote/speaker-diarization-3.1](https://huggingface.co/pyannote/speaker-diarization-3.1)
- [pyannote/segmentation-3.0](https://huggingface.co/pyannote/segmentation-3.0)

Vollständige Konfigurations-Referenz: [`docs/configuration.md`](docs/configuration.md)

---

## 🔒 Produktions-Checkliste

Bevor du TranscribeOps öffentlich erreichbar machst:

- [ ] `SECRET_KEY` auf einen sicheren Zufallswert gesetzt
- [ ] Admin-Passwort geändert (nicht mehr `admin`/`admin`)
- [ ] `WHISPER_API_KEY` gesetzt, falls die Modell-API von außen erreichbar ist
- [ ] HTTPS via Reverse Proxy (nginx / Caddy / Traefik) — siehe [`docs/installation.md`](docs/installation.md)
- [ ] Backup-Strategie für DB-Volume (`transcribeops-db`) und Audio-Storage
- [ ] Optional: SSO/OIDC einrichten ([`docs/sso-setup.md`](docs/sso-setup.md))

---

## 🖥️ GPU-Beschleunigung (optional)

Lokales Whisper läuft per Default auf CPU. Für GPU (NVIDIA):

1. [NVIDIA Container Toolkit](https://docs.nvidia.com/datacenter/cloud-native/container-toolkit/install-guide.html) installieren
2. In `docker-compose.yml` beim `whisper`-Service:
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

## 📚 Dokumentation

| Dokument | Inhalt |
|---|---|
| [Installation & Deployment](docs/installation.md) | Detaillierte Setup-Anleitung |
| [Konfiguration](docs/configuration.md) | Alle Umgebungsvariablen, Settings |
| [Architektur](docs/architecture.md) | Technischer Stack, Datenmodell, Tasks |
| [API-Referenz](docs/api-reference.md) | REST-API-Endpunkte |
| [Admin-Handbuch](docs/admin-guide.md) | Benutzer, Gruppen, Modelle |
| [Benutzerhandbuch](docs/user-guide.md) | Bedienung der Features |
| [Whisper-API](docs/whisper-api.md) | Standalone Modell-API |
| [SSO-Setup](docs/sso-setup.md) | Header-SSO und OIDC |

---

## 🛠️ Entwicklung

```bash
# Web-App (Dev-Server)
cd web-app && python run.py

# Celery Worker
cd web-app && celery -A celery_worker.celery worker --loglevel=info

# Whisper-API
cd whisper-api && python app.py
```

**Tech-Stack:** Python 3.12, Flask 3.1, SQLAlchemy 2.0, Celery 5.4, Redis 7, faster-whisper / WhisperX, Bootstrap 5.3.

---

## 🤝 Beiträge

Issues und Pull Requests sind willkommen. Bitte Code-Style beibehalten (kein `shell=True`, CSRF-geschützte Routen, `current_user.id`-Filter in API-Endpoints).

---

## 📄 Lizenz

[MIT](LICENSE) — Nutzung, Modifikation und kommerzielle Verwendung erlaubt.

---

<div align="center">
Made with ☕ in Germany
</div>
