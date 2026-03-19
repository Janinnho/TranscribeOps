# Whisper API Service

Der Whisper API Service ist ein eigenständiger Flask-Server, der eine **OpenAI-kompatible** Transkriptions-API bereitstellt. Er verwendet [faster-whisper](https://github.com/SYSTRAN/faster-whisper), eine optimierte Implementierung von OpenAI Whisper, für lokale Spracherkennung.

## Inhaltsverzeichnis

- [Übersicht](#übersicht)
- [Installation & Start](#installation--start)
- [API-Endpunkte](#api-endpunkte)
- [Konfiguration](#konfiguration)
- [Modelle](#modelle)
- [Ausgabeformate](#ausgabeformate)
- [Authentifizierung](#authentifizierung)
- [GPU-Unterstützung](#gpu-unterstützung)
- [Performance-Tipps](#performance-tipps)

---

## Übersicht

| Eigenschaft | Wert |
|------------|------|
| **Framework** | Flask + Gunicorn |
| **Engine** | faster-whisper 1.1.1 (CTranslate2) |
| **API-Kompatibilität** | OpenAI Whisper API (`/v1/audio/transcriptions`) |
| **Standard-Port** | 8000 (intern), 8090 (extern) |
| **Standard-Modell** | `medium` |
| **Speicherlimit** | 4 GB (Docker) |

---

## Installation & Start

### Docker (empfohlen)

```bash
# Netzwerk erstellen (einmalig)
docker network create transcribeops-shared

# Service starten
cd whisper-api
docker compose up -d
```

### Health-Check

```bash
curl http://localhost:8090/health
```

Erwartete Antwort:
```json
{
  "status": "ok",
  "default_model": "medium",
  "device": "cpu",
  "compute_type": "int8",
  "models_loaded": ["medium"]
}
```

---

## API-Endpunkte

### `POST /v1/audio/transcriptions`

Transkribiert eine Audiodatei.

**Content-Type:** `multipart/form-data`

**Parameter:**

| Parameter | Typ | Pflicht | Beschreibung | Standard |
|-----------|-----|---------|-------------|----------|
| `file` | File | Ja | Audiodatei (beliebiges Format) | — |
| `model` | String | Nein | Modellgröße oder `whisper-1` | `whisper-1` |
| `language` | String | Nein | Sprach-Code (ISO 639-1) | Auto-Erkennung |
| `response_format` | String | Nein | Ausgabeformat | `json` |

**Beispiel (cURL):**

```bash
curl -X POST http://localhost:8090/v1/audio/transcriptions \
  -H "Authorization: Bearer my-secret-key" \
  -F "file=@interview.mp3" \
  -F "model=whisper-1" \
  -F "language=de" \
  -F "response_format=verbose_json"
```

**Erfolgsantwort (json):**
```json
{
  "text": "Hallo, das ist ein Testtext."
}
```

**Erfolgsantwort (verbose_json):**
```json
{
  "text": "Hallo, das ist ein Testtext.",
  "language": "de",
  "duration": 5.42,
  "segments": [
    {
      "id": 0,
      "start": 0.0,
      "end": 2.5,
      "text": " Hallo, das ist"
    },
    {
      "id": 1,
      "start": 2.5,
      "end": 5.42,
      "text": " ein Testtext."
    }
  ]
}
```

**Fehlerantworten:**

| Code | Beschreibung |
|------|-------------|
| `400` | Keine Audiodatei oder leerer Dateiname |
| `401` | Ungültiger API-Schlüssel |
| `500` | Transkriptionsfehler (z.B. ungültiges Audioformat) |

```json
{
  "error": {
    "message": "Invalid API key.",
    "type": "auth_error"
  }
}
```

---

### `GET /v1/models`

Listet verfügbare Modelle (OpenAI-kompatibel).

**Authentifizierung:** Erforderlich (falls API-Key konfiguriert)

**Antwort:**
```json
{
  "object": "list",
  "data": [
    {"id": "whisper-1", "object": "model", "owned_by": "local", "description": "Default (medium)"},
    {"id": "tiny", "object": "model", "owned_by": "local"},
    {"id": "base", "object": "model", "owned_by": "local"},
    {"id": "small", "object": "model", "owned_by": "local"},
    {"id": "medium", "object": "model", "owned_by": "local"},
    {"id": "large-v3", "object": "model", "owned_by": "local"},
    {"id": "turbo", "object": "model", "owned_by": "local"}
  ]
}
```

---

### `GET /health`

Health-Check-Endpunkt (keine Authentifizierung erforderlich).

**Antwort:**
```json
{
  "status": "ok",
  "default_model": "medium",
  "device": "cpu",
  "compute_type": "int8",
  "models_loaded": ["medium"]
}
```

---

## Konfiguration

### Umgebungsvariablen

| Variable | Beschreibung | Standard |
|----------|-------------|----------|
| `WHISPER_API_KEY` | API-Schlüssel für Bearer-Auth (leer = kein Auth) | `""` |
| `WHISPER_MODEL` | Standard-Modellgröße | `medium` |
| `WHISPER_DEVICE` | Berechnungsgerät | `cpu` |
| `WHISPER_COMPUTE_TYPE` | Berechnungsgenauigkeit | `int8` |

### Docker-Compose

```yaml
services:
  whisper:
    build: .
    ports:
      - "8090:8000"
    environment:
      - WHISPER_API_KEY=${WHISPER_API_KEY:-my-secret-key}
      - WHISPER_MODEL=${WHISPER_MODEL:-medium}
      - WHISPER_DEVICE=cpu
      - WHISPER_COMPUTE_TYPE=int8
    volumes:
      - whisper_cache:/root/.cache     # Hugging Face Modell-Cache
    networks:
      - transcribeops
    restart: unless-stopped
    deploy:
      resources:
        limits:
          memory: 4G
```

### `.env`-Datei (optional)

```env
WHISPER_API_KEY=mein-sicherer-schlüssel
WHISPER_MODEL=large-v3
```

---

## Modelle

### Verfügbare Modelle

| Modell | Parameter | RAM (CPU, int8) | Sprachen | Genauigkeit |
|--------|-----------|----------------|----------|-------------|
| `tiny` | 39 M | ~1 GB | Alle | Gering |
| `base` | 74 M | ~1 GB | Alle | Gering-Mittel |
| `small` | 244 M | ~2 GB | Alle | Mittel |
| `medium` | 769 M | ~4 GB | Alle | Gut |
| `large-v3` | 1.55 B | ~6 GB | Alle | Sehr gut |
| `turbo` | 809 M | ~6 GB | Alle | Sehr gut (schneller als large) |

### Modell-Mapping

| API-Parameter | Tatsächlich verwendetes Modell |
|--------------|-------------------------------|
| `whisper-1` | Konfiguriertes Standard-Modell (`WHISPER_MODEL`) |
| `whisper-large-v3` | Konfiguriertes Standard-Modell |
| Andere Werte | Direkt als Modellgröße verwendet |

### Modell-Caching

- Modelle werden beim ersten Laden von Hugging Face heruntergeladen
- Das Docker-Volume `whisper_cache` speichert geladene Modelle persistent
- Das Standard-Modell wird beim Container-Start vorgeladen
- Weitere Modelle werden bei Bedarf geladen und gecacht

---

## Ausgabeformate

### `json` (Standard)

Einfaches JSON mit dem gesamten Text:

```json
{
  "text": "Der vollständige transkribierte Text."
}
```

### `verbose_json`

Erweitertes JSON mit Metadaten und Zeitstempel-Segmenten:

```json
{
  "text": "Der vollständige transkribierte Text.",
  "language": "de",
  "duration": 45.67,
  "segments": [
    {
      "id": 0,
      "start": 0.0,
      "end": 3.5,
      "text": " Der vollständige"
    },
    {
      "id": 1,
      "start": 3.5,
      "end": 5.2,
      "text": " transkribierte Text."
    }
  ]
}
```

### `text`

Nur der transkribierte Text als Plain-Text:

```
Der vollständige transkribierte Text.
```

### `srt`

SubRip Subtitle Format:

```
1
00:00:00,000 --> 00:00:03,500
Der vollständige

2
00:00:03,500 --> 00:00:05,200
transkribierte Text.
```

### `vtt`

WebVTT Format:

```
WEBVTT

00:00:00.000 --> 00:00:03.500
Der vollständige

00:00:03.500 --> 00:00:05.200
transkribierte Text.
```

---

## Authentifizierung

### Bearer Token

Wenn `WHISPER_API_KEY` gesetzt ist, wird ein Bearer Token erwartet:

```
Authorization: Bearer <api-key>
```

### Ohne Authentifizierung

Wenn `WHISPER_API_KEY` leer ist (`""`), ist keine Authentifizierung erforderlich. Dies ist sinnvoll in isolierten Docker-Netzwerken ohne externen Zugriff.

---

## GPU-Unterstützung

### NVIDIA CUDA

Für GPU-beschleunigte Transkription:

1. **NVIDIA Container Toolkit** installieren:
   ```bash
   # Ubuntu/Debian
   distribution=$(. /etc/os-release;echo $ID$VERSION_ID)
   curl -fsSL https://nvidia.github.io/libnvidia-container/gpgkey | sudo gpg --dearmor -o /usr/share/keyrings/nvidia-container-toolkit-keyring.gpg
   curl -s -L https://nvidia.github.io/libnvidia-container/$distribution/libnvidia-container.list | \
     sed 's#deb https://#deb [signed-by=/usr/share/keyrings/nvidia-container-toolkit-keyring.gpg] https://#g' | \
     sudo tee /etc/apt/sources.list.d/nvidia-container-toolkit.list
   sudo apt-get update && sudo apt-get install -y nvidia-container-toolkit
   sudo nvidia-ctk runtime configure --runtime=docker && sudo systemctl restart docker
   ```

2. **docker-compose.yml anpassen:**

   ```yaml
   services:
     whisper:
       build: .
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

3. **Dockerfile anpassen** (für CUDA-Base-Image):

   ```dockerfile
   FROM nvidia/cuda:12.1-runtime-ubuntu22.04
   # ... Python und Dependencies installieren
   ```

### Compute Types mit GPU

| Typ | Beschreibung | Empfehlung |
|-----|-------------|------------|
| `float16` | Standard für GPU — guter Kompromiss | Empfohlen |
| `int8` | Weniger VRAM, minimal geringere Genauigkeit | Für kleinere GPUs |
| `float32` | Höchste Genauigkeit, mehr VRAM | Selten nötig |

---

## Performance-Tipps

### Modellwahl

- **Für Geschwindigkeit:** `tiny` oder `base` — sehr schnell, aber weniger genau
- **Für Balance:** `medium` — guter Kompromiss (Standard)
- **Für Genauigkeit:** `large-v3` — beste Ergebnisse, langsamer
- **Für Genauigkeit + Geschwindigkeit:** `turbo` — ähnlich wie large, aber schneller

### VAD-Filter

Der Service aktiviert automatisch den **Voice Activity Detection (VAD) Filter** (`vad_filter=True`). Dieser filtert Stille-Abschnitte heraus und verbessert die Verarbeitungsgeschwindigkeit, besonders bei Aufnahmen mit langen Pausen.

### Beam Size

Die Standard-Beam-Size ist `5`. Höhere Werte können die Genauigkeit verbessern, verlangsamen aber die Verarbeitung.

### Speicher

- Stellen Sie sicher, dass genügend RAM/VRAM für das gewählte Modell verfügbar ist
- Das Docker-Speicherlimit (Standard: 4 GB) muss mindestens so groß sein wie der RAM-Bedarf des Modells
- Bei `large-v3` auf CPU wird empfohlen, das Limit auf 8 GB zu erhöhen

### Concurrency

Der Gunicorn-Server ist mit `--workers 1 --threads 4` konfiguriert:
- **1 Worker** — Whisper-Modelle sind speicherintensiv; mehrere Worker würden das Modell mehrfach laden
- **4 Threads** — Ermöglicht parallele Request-Bearbeitung (I/O), die eigentliche Transkription läuft sequenziell

### Sprache angeben

Wenn die Sprache bekannt ist, geben Sie sie explizit an (`language=de`). Dies spart die automatische Spracherkennung und verbessert die Genauigkeit, besonders bei kurzen Aufnahmen.

---

## Integration mit TranscribeOps

In TranscribeOps wird der Whisper API Service als **Sprachmodell** mit Provider `whisper_local` konfiguriert:

```
Name:          whisper-lokal
Anzeigename:   Lokales Whisper
Provider:      whisper_local
Endpunkt-URL:  http://whisper:8000/v1/audio/transcriptions
API-Schlüssel: my-secret-key (falls konfiguriert)
Modell-ID:     whisper-1
```

Die Kommunikation erfolgt über das gemeinsame Docker-Netzwerk `transcribeops-shared`. Der Hostname `whisper` wird automatisch vom Docker DNS aufgelöst.
