# Installation & Deployment

## Inhaltsverzeichnis

- [Systemvoraussetzungen](#systemvoraussetzungen)
- [Docker-Netzwerk erstellen](#docker-netzwerk-erstellen)
- [Whisper API Service starten](#whisper-api-service-starten)
- [Web-App starten](#web-app-starten)
- [Erster Login](#erster-login)
- [Produktions-Deployment](#produktions-deployment)
- [Updates](#updates)
- [Deinstallation](#deinstallation)

---

## Systemvoraussetzungen

| Komponente | Mindestanforderung | Empfohlen |
|-----------|-------------------|-----------|
| Docker | 20.10+ | 24.0+ |
| Docker Compose | v2.0+ | v2.20+ |
| RAM | 4 GB | 8 GB+ (für lokales Whisper) |
| Speicher | 5 GB | 20 GB+ (Modelle + Audio-Archiv) |
| CPU | 2 Kerne | 4+ Kerne |
| GPU (optional) | — | NVIDIA CUDA-fähig |

### Softwareabhängigkeiten

Die folgenden Abhängigkeiten werden **automatisch** in den Docker-Containern installiert:

- **Python 3.12** — Laufzeitumgebung
- **FFmpeg** — Audio-Konvertierung (MP3-Encoding mit libmp3lame)
- **Redis 7** — Message Broker für Celery
- **faster-whisper** — Lokale Spracherkennung (nur im Whisper-API-Container)

---

## Docker-Netzwerk erstellen

TranscribeOps verwendet ein gemeinsames Docker-Netzwerk, über das die Web-App und der Whisper-API-Service kommunizieren.

```bash
docker network create transcribeops-shared
```

> Dieses Netzwerk muss nur **einmalig** erstellt werden und bleibt über Container-Neustarts hinweg bestehen.

---

## Alle Services starten

```bash
# 1. Konfiguration erstellen
cp docker-compose.example.yml docker-compose.yml
cp .env.example .env

# 2. .env anpassen (mindestens SECRET_KEY setzen!)
# SECRET_KEY generieren: python3 -c "import secrets; print(secrets.token_hex(32))"

# 3. Stack starten
docker compose up -d
```

### Konfiguration

Die Konfiguration erfolgt über Umgebungsvariablen in `docker-compose.yml`:

```yaml
environment:
  - WHISPER_API_KEY=${WHISPER_API_KEY:-my-secret-key}  # API-Schlüssel (optional)
  - WHISPER_MODEL=${WHISPER_MODEL:-medium}              # Modellgröße
  - WHISPER_DEVICE=cpu                                  # cpu oder cuda
  - WHISPER_COMPUTE_TYPE=int8                           # Rechengenauigkeit
```

### Verfügbare Modelle

| Modell | RAM-Bedarf | Genauigkeit | Geschwindigkeit |
|--------|-----------|-------------|-----------------|
| `tiny` | ~1 GB | Niedrig | Sehr schnell |
| `base` | ~1 GB | Niedrig-Mittel | Schnell |
| `small` | ~2 GB | Mittel | Mittel |
| `medium` | ~4 GB | Gut | Langsamer |
| `large-v3` | ~6 GB | Sehr gut | Langsam |
| `turbo` | ~6 GB | Sehr gut | Schneller als large |

### GPU-Unterstützung (NVIDIA)

Für GPU-beschleunigte Transkription:

1. Installiere [NVIDIA Container Toolkit](https://docs.nvidia.com/datacenter/cloud-native/container-toolkit/install-guide.html)
2. Ändere die `docker-compose.yml`:

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

### Überprüfung

```bash
# Health-Check
curl http://localhost:8090/health

# Erwartete Antwort:
# {"status":"ok","default_model":"medium","device":"cpu","compute_type":"int8","models_loaded":["medium"]}
```

---

## Erster Start

Beim ersten Start passiert Folgendes automatisch:

1. **Datenbank wird erstellt** — SQLite-Datei unter `/app/data/transcribeops.db`
2. **Migrationen werden ausgeführt** — Fehlende Spalten/Tabellen werden automatisch angelegt
3. **Standarddaten werden angelegt:**
   - Admin-Benutzer: `admin@transcribeops.local` / `admin`
   - Standard-Sprachmodell: Lokales Whisper unter `http://whisper:8000/v1/audio/transcriptions`
   - Standard-Textmodell: Lokales Ollama unter `http://ollama:11434`
   - Standardgruppe: „Standard"
   - Zeitzone: `Europe/Berlin`

### Docker-Services

| Service | Funktion | Port |
|---------|---------|------|
| `web` | Flask-Webserver (Gunicorn) | 5050 → 5000 |
| `worker` | Celery Worker (Async Tasks) | — |
| `redis` | Message Broker | — (intern) |

### Volumes

| Volume | Pfad im Container | Beschreibung |
|--------|-------------------|-------------|
| `db_data` | `/app/data` | SQLite-Datenbank |
| `upload_data` | `/app/app/static/uploads` | Temporäre Uploads |
| Audio-Mount | `/app/audio_storage` | Permanente Audio-Archivierung |

---

## Erster Login

1. Öffne http://localhost:5050 im Browser
2. Melde dich mit den Standard-Zugangsdaten an:
   - **E-Mail:** `admin@transcribeops.local`
   - **Passwort:** `admin`
3. **Wichtig:** Ändere sofort das Admin-Passwort unter **Admin > Benutzer**

### Erstkonfiguration

Nach dem Login empfehlen sich folgende Schritte:

1. **Admin-Passwort ändern** — Im Admin-Portal unter Benutzer
2. **Sprachmodell prüfen** — Das Standard-Whisper-Modell zeigt auf `http://whisper:8000/v1/audio/transcriptions`. Falls der Whisper-Service auf einem anderen Port läuft, die URL anpassen.
3. **Textmodell konfigurieren** — Falls Ollama nicht verfügbar ist, ein alternatives Textmodell einrichten (OpenAI, Azure)
4. **Zeitzone einstellen** — Unter Admin > Global die gewünschte Zeitzone auswählen
5. **Benutzer anlegen** — Weitere Benutzer im Admin-Portal erstellen

---

## Produktions-Deployment

### SECRET_KEY setzen

**Zwingend für Produktion:** Setze einen sicheren, zufälligen `SECRET_KEY` in der `.env`-Datei:

```bash
# .env
SECRET_KEY=dein-sicherer-zufälliger-schlüssel-hier
```

Generiere einen sicheren Schlüssel:
```bash
python3 -c "import secrets; print(secrets.token_hex(32))"
```

### HTTPS / Reverse Proxy

Für den Produktionsbetrieb wird ein Reverse Proxy mit HTTPS empfohlen:

**nginx-Beispiel:**
```nginx
server {
    listen 443 ssl;
    server_name transcribeops.example.com;

    ssl_certificate     /path/to/cert.pem;
    ssl_certificate_key /path/to/key.pem;

    client_max_body_size 500M;  # Für große Audiodateien

    location / {
        proxy_pass http://localhost:5050;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
```

### Audio-Speicher konfigurieren

Standardmäßig werden Audio-Dateien unter `./audio_storage` gemountet. Passe den Pfad in `docker-compose.yml` an:

```yaml
volumes:
  - /pfad/zum/audio-archiv:/app/audio_storage
```

### Datensicherung

Sichern Sie regelmäßig:

1. **Datenbank** — Das Docker-Volume `db_data` (enthält die SQLite-Datei)
2. **Audio-Archiv** — Das gemountete Audio-Verzeichnis
3. **docker-compose.yml** und **.env** — Ihre Konfiguration

```bash
# Beispiel: Datenbank-Backup
docker compose exec web cp /app/data/transcribeops.db /app/data/backup_$(date +%Y%m%d).db
```

---

## Updates

```bash
# Neueste Version herunterladen
git pull

# Container neu bauen und starten
docker compose up -d --build
```

> Migrationen werden automatisch beim Start der Web-App ausgeführt. Ein manuelles Eingreifen ist nicht erforderlich.

---

## Deinstallation

```bash
# Container stoppen und entfernen
docker compose down

# Optional: Volumes löschen (ACHTUNG: Daten gehen verloren!)
docker compose down -v

# Netzwerk entfernen
docker network rm transcribeops-shared
```
