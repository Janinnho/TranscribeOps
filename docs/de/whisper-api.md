# TranscribeOps Modell API (Whisper API Service)

Der Modell-API-Service ist ein eigenständiger Flask-Server, der eine **OpenAI-kompatible** Transkriptions-API bereitstellt. Er unterstützt zwei Engines — **WhisperX** (faster-whisper mit Word-Alignment) und **NeMo** (NVIDIA Parakeet) — und kann mehrere Modelle gleichzeitig betreiben. Verwaltet wird alles über ein integriertes **Admin-UI**.

## Inhaltsverzeichnis

- [Übersicht](#übersicht)
- [Architektur: Main-Engine und Instanzen](#architektur-main-engine-und-instanzen)
- [Modell-Routing über den model-Parameter](#modell-routing-über-den-model-parameter)
- [Admin-UI](#admin-ui)
- [API-Endpunkte](#api-endpunkte)
- [Wörterbuch und Ersetzungsregeln (prompt)](#wörterbuch-und-ersetzungsregeln-prompt)
- [Timeout und RAM-Freigabe](#timeout-und-ram-freigabe)
- [Modellkatalog](#modellkatalog)
- [Konfiguration](#konfiguration)
- [Authentifizierung](#authentifizierung)
- [Integration mit TranscribeOps](#integration-mit-transcribeops)

---

## Übersicht

| Eigenschaft | Wert |
|------------|------|
| **Framework** | Flask + Gunicorn (Hauptprozess), Werkzeug (Instanz-Worker) |
| **Engines** | WhisperX (faster-whisper + Alignment + Diarization), NeMo (Parakeet TDT) |
| **API-Kompatibilität** | OpenAI Whisper API (`/v1/audio/transcriptions`) |
| **Externer Port** | 8000 — einziger Einstiegspunkt für API **und** Admin-UI |
| **Admin-UI** | `http://<host>:8000/admin` |
| **Standard-Modell** | `medium` (WhisperX), per Admin-UI änderbar |

---

## Architektur: Main-Engine und Instanzen

Der Service besteht aus einem **Hauptprozess** und optionalen **Instanz-Workern**:

- **Hauptprozess (Port 8000):** Lädt die Main-Engine (Alias `whisper-1`), beherbergt das Admin-UI und den **Model-Router**, der Anfragen anhand des `model`-Parameters verteilt.
- **Instanz-Worker:** Eigenständige Prozesse, die je ein weiteres Modell laden (z.B. ein schnelles `tiny` für Diktate und ein deutsches Parakeet für Meetings). Sie werden im Admin-UI angelegt und vom Hauptprozess verwaltet (Start/Stop/Respawn). Ihre internen Ports (Standard 8100–8120) binden **nur an localhost** — von außen läuft alles über Port 8000.

Prozess-Trennung bedeutet: Ein Absturz oder Speicherproblem einer Instanz reißt weder den Hauptprozess noch andere Modelle mit, und Instanzen können einzeln gestartet, gestoppt oder aus dem RAM entladen werden.

---

## Modell-Routing über den `model`-Parameter

Der `model`-Parameter der API entscheidet, welcher Prozess die Anfrage bearbeitet:

| `model`-Wert | Ziel |
|--------------|------|
| leer oder `whisper-1` | Main-Engine (empfohlen für den Standardfall) |
| Name der Main-Engine (z.B. `medium`) | Main-Engine |
| Instanz-Name (z.B. `express`) | Die entsprechende Instanz |
| unbekannter Wert | `404` mit Liste der verfügbaren Modelle |

Der **Instanz-Name ist der Alias**: Eine Instanz namens `diktat-schnell` wird mit `model=diktat-schnell` angesprochen. `GET /v1/models` listet alle verfügbaren Aliase — Clients können die Modelle also automatisch entdecken.

Schlafende Instanzen (siehe [RAM-Freigabe](#timeout-und-ram-freigabe)) werden bei einer Anfrage automatisch gestartet; die Anfrage wartet dann auf das Laden des Modells. Explizit gestoppte Instanzen werden **nicht** automatisch gestartet.

---

## Admin-UI

Erreichbar unter `http://<host>:8000/admin` (Passwort: `ADMIN_PASSWORD`). Drei Bereiche:

1. **Modelle** — Kuratierter Katalog zum Herunterladen (Whisper-Größen, Parakeet-Varianten, deutsch-optimiertes Parakeet Primeline). Zusätzlich lassen sich **eigene HuggingFace-Repos** per `repo_id` laden; NeMo-Modelle funktionieren auch als einzelne `.nemo`-Checkpoint-Datei (Community-Finetunes).
2. **Instanzen** — Instanzen anlegen (Name = API-Alias, Engine, Modell, Device, Compute-Type, Timeout, RAM-Freigabe), starten/stoppen, Einstellungen ändern. Die Main-Engine erscheint als erste Zeile und kann hier umkonfiguriert werden (löst einen Reload aus; reine Timeout-/RAM-Änderungen nicht).
3. **API-Keys** — Bearer-Keys erzeugen und widerrufen (gehasht gespeichert).

---

## API-Endpunkte

### `POST /v1/audio/transcriptions`

**Content-Type:** `multipart/form-data`

| Parameter | Typ | Pflicht | Beschreibung | Standard |
|-----------|-----|---------|-------------|----------|
| `file` | File | Ja | Audiodatei (beliebiges Format, ffmpeg-lesbar) | — |
| `model` | String | Nein | Modell-Alias, siehe [Routing](#modell-routing-über-den-model-parameter) | `whisper-1` |
| `language` | String | Nein | Sprach-Code (ISO 639-1), z.B. `de` | Auto-Erkennung |
| `prompt` | String | Nein | Wörterbuch + Ersetzungsregeln, siehe [unten](#wörterbuch-und-ersetzungsregeln-prompt) | — |
| `response_format` | String | Nein | `json`, `verbose_json`, `text`, `srt`, `vtt` | `json` |
| `diarize` | Bool | Nein | Sprechererkennung (benötigt `HF_TOKEN`) | `false` |
| `async` | Bool | Nein | Asynchroner Modus: sofort `202` + `task_id` | `false` |

**Beispiel:**

```bash
curl -X POST http://localhost:8000/v1/audio/transcriptions \
  -H "Authorization: Bearer wsk_..." \
  -F "file=@meeting.mp3" \
  -F "model=express2" \
  -F "language=de" \
  -F "prompt=Jannik Baader, IuK" \
  -F "diarize=true" \
  -F "response_format=verbose_json"
```

**Fehlercodes:** `400` (keine Datei), `401` (ungültiger Key), `404` (unbekanntes Modell), `500` (Transkriptionsfehler), `503` (Engine lädt gerade / Instanz nicht startbar, mit `Retry-After`), `504` (Timeout überschritten).

### `GET /v1/audio/transcriptions/<task_id>`

Status-Polling für asynchrone Tasks. Antwort enthält `status` (`processing` / `completed` / `failed`), `progress` (0–100), `progress_step` und bei Abschluss `result` bzw. `error`. Ergebnisse werden nach Abholung bzw. nach 1 Stunde verworfen. Der Hauptprozess leitet Polls automatisch an die zuständige Instanz weiter.

### `GET /v1/models`

Listet alle nutzbaren Modelle: `whisper-1` + Modell der Main-Engine + alle Instanz-Aliase (laufend oder schlafend), mit `description` = Engine/Modell.

### `GET /health`

Ohne Authentifizierung. Liefert Engine, Modell, Device, Compute-Type, `main_engine_loaded`, `active_requests` sowie Diarization-/Alignment-Fähigkeiten.

---

## Wörterbuch und Ersetzungsregeln (`prompt`)

Der `prompt`-Parameter transportiert ein kommagetrenntes Wörterbuch. Beide lokalen Engines wenden es als Nachkorrektur auf Wortebene an (Timestamps bleiben erhalten):

- **`Eigenname`** — ähnlich klingende Wörter im Transkript werden auf die exakte Schreibweise gezogen (fuzzy): `Janik Bader` → `Jannik Baader`. Auch Mehrwort-Einträge und Bindestrich-Komposita (`IOK-Abteilung` → `IuK-Abteilung`) werden korrigiert. Kurze Einträge (2–3 Zeichen, z.B. Akronyme wie `IuK`) matchen streng: exakt oder mit maximal einem Buchstaben Unterschied bei gleichem Anfangs-/Endbuchstaben.
- **`Quelle=Ziel`** — Ersetzungsregel: Wird die Quelle erkannt (auch fuzzy), wird sie komplett durch das Ziel ersetzt, z.B. `Doppelpunkt=:` oder `mfg=mit freundlichen Grüßen`. Besteht das Ziel nur aus Satzzeichen, wird es diktat-typisch an das vorherige Wort angehängt („ist denn Doppelpunkt“ → „ist denn:“). Ein Komma kann bauartbedingt nicht als Ziel dienen (Kommas trennen die Einträge).

```
prompt=Jannik Baader, IuK, Erika Mustermann, Doppelpunkt=:, mfg=mit freundlichen Grüßen
```

---

## Timeout und RAM-Freigabe

Beides pro Modell im Admin-UI einstellbar (Instanz-Einstellungen bzw. Main-Engine-Dialog), Änderungen gelten sofort ohne Neustart:

- **Timeout** (Standard: 600s, `0` = unbegrenzt): Maximale Verarbeitungszeit pro Anfrage. Synchrone Anfragen erhalten nach Ablauf `504`, asynchrone Tasks werden beim Polling als `failed` markiert.
- **RAM-Freigabe / Idle-Unload** (Standard: aus, `0` = dauerhaft geladen): Nach X Sekunden ohne Anfrage wird das Modell entladen — bei Instanzen wird der ganze Worker-Prozess gestoppt (Status „Schläft“), bei der Main-Engine das Modell im Prozess freigegeben. Die nächste Anfrage lädt automatisch nach und wartet solange. Laufende Transkriptionen verhindern die Entladung.

---

## Modellkatalog

| Modell | Engine | Größe | Beschreibung |
|--------|--------|-------|-------------|
| `tiny` / `base` / `small` | WhisperX | 75 MB – 465 MB | Schnell, CPU-freundlich |
| `medium` | WhisperX | ~1,5 GB | Standard-Empfehlung |
| `large-v3` / `large-v3-turbo` | WhisperX | ~3 GB / ~1,5 GB | Beste Whisper-Qualität |
| `parakeet-tdt-0.6b-v2/v3`, `parakeet-tdt-1.1b` | NeMo | 1,2 – 2,2 GB | NVIDIA Parakeet, sehr schnelles ASR |
| `parakeet-primeline` | NeMo | ~2,5 GB | **Deutsch-optimiertes** Parakeet-Finetune (CC-BY-4.0) |

Alignment-Modelle (wav2vec2 für en/fr/de/es/it) sind ins Image eingebacken; pyannote-Diarization wird beim ersten Start mit `HF_TOKEN` automatisch geladen. Alle Modelle und die Admin-Datenbank liegen im Volume unter `/root/.cache` und überleben Container-Neustarts.

---

## Konfiguration

| Variable | Beschreibung | Standard |
|----------|-------------|----------|
| `WHISPER_API_KEY` | Statischer API-Key (zusätzlich zu Admin-UI-Keys) | `""` |
| `WHISPER_MODEL` | Initiales Main-Engine-Modell | `medium` |
| `WHISPER_DEVICE` | `cpu`, `cuda` oder `mps` | `cpu` |
| `WHISPER_COMPUTE_TYPE` | `int8`, `int16`, `float16`, `float32` | `int8` |
| `WHISPER_BATCH_SIZE` | Batch-Größe der Transkription | `16` |
| `HF_TOKEN` | HuggingFace-Token (nötig für Diarization/pyannote) | `""` |
| `ADMIN_PASSWORD` | Admin-UI-Passwort (leer = Admin-UI deaktiviert) | `""` |
| `ADMIN_SESSION_SECRET` | Session-Secret des Admin-UI | abgeleitet |
| `ADMIN_DB_PATH` | Pfad der Admin-SQLite-DB | `/root/.cache/transcribeops/admin.db` |
| `INSTANCE_PORT_RANGE` | Interne Portrange der Instanz-Worker | `8100-8120` |
| `DISABLE_MAIN_ENGINE` | `1` = Hauptprozess lädt kein Modell (nur Router + Admin) | `0` |
| `ROUTER_READ_TIMEOUT` | Proxy-Timeout ohne Modell-Timeout (Sekunden) | `3600` |
| `ROUTER_STARTUP_TIMEOUT` | Max. Wartezeit beim Auto-Start schlafender Instanzen | `300` |

Engine-/Modell-Änderungen über das Admin-UI werden in der Admin-DB persistiert und überschreiben die Env-Defaults. Schema-Migrationen der Admin-DB laufen automatisch beim Start.

---

## Authentifizierung

Bearer-Token im `Authorization`-Header. Gültig sind der statische `WHISPER_API_KEY` (falls gesetzt) und alle aktiven, im Admin-UI erzeugten Keys. Sind weder Env-Key noch DB-Keys konfiguriert, ist die API offen — nur sinnvoll in isolierten Netzwerken.

---

## Integration mit TranscribeOps

Jedes Modell wird in der Web-App als eigenes **Sprachmodell** mit Provider `whisper_local` angelegt — alle mit derselben Endpunkt-URL, unterschieden nur durch die Modell-ID:

```
Provider:      whisper_local
Endpunkt-URL:  http://localhost:8000/v1/audio/transcriptions   (Pod/Compose-intern)
API-Schlüssel: <Key aus dem Admin-UI>
Modell-ID:     whisper-1        (Main-Engine)  bzw.  <Instanz-Name>
```

Ein neues Modell anbieten heißt also nur: Modell im Admin-UI herunterladen → Instanz anlegen → Sprachmodell-Eintrag in der Web-App mit `model_id` = Instanz-Name. Kein neuer Port, kein neuer Container.
