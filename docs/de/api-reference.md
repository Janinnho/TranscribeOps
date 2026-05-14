# API-Referenz

Alle API-Endpunkte sind unter dem Präfix `/api` erreichbar und erfordern eine authentifizierte Session (`@login_required`). Antworten erfolgen im JSON-Format.

## Inhaltsverzeichnis

- [Authentifizierung](#authentifizierung)
- [Datei-Upload](#datei-upload)
- [Transkriptions-Jobs](#transkriptions-jobs)
- [Meetings](#meetings)
- [Diktate](#diktate)
- [Text-Tasks](#text-tasks)
- [Wörterbuch](#wörterbuch)
- [KI-Chat](#ki-chat)
- [Fehlerbehandlung](#fehlerbehandlung)

---

## Authentifizierung

Alle API-Endpunkte verwenden Session-basierte Authentifizierung (Flask-Login). Ein gültiger Session-Cookie ist erforderlich. Dieser wird automatisch beim Login über `/login` oder `/manuell-login` gesetzt.

### Login-Routes

| Route | Methode | Beschreibung |
|-------|---------|-------------|
| `/login` | GET, POST | Haupt-Login (SSO-aware) |
| `/manuell-login` | GET, POST | Manueller Login mit E-Mail/Passwort |
| `/oidc/callback` | GET | OIDC Provider Callback |
| `/logout` | GET | Logout |

---

## Datei-Upload

### `POST /api/upload`

Lädt eine Audiodatei hoch und startet die Transkription.

**Content-Type:** `multipart/form-data`

**Parameter:**

| Parameter | Typ | Pflicht | Beschreibung |
|-----------|-----|---------|-------------|
| `file` | File | Ja | Audiodatei |
| `job_type` | String | Nein | `transcription` (Standard) oder `meeting` |
| `speech_model_id` | Integer | Nein | ID des Sprachmodells |
| `language` | String | Nein | Sprach-Code (z.B. `de`, `en`) |
| `multi_speaker` | String | Nein | `true` für Mehrsprecher-Modus |
| `save_audio` | String | Nein | `1` für Audio-Archivierung |

**Erlaubte Dateitypen:** `mp3`, `wav`, `ogg`, `webm`, `flac`, `m4a`, `mp4`, `mpeg`, `mpga`

**Erfolgsantwort (200):**
```json
{
  "job_id": "a1b2c3d4e5f6...",
  "status": "pending"
}
```

**Fehlerantworten:**
- `400` — Keine Datei, leerer Dateiname oder nicht erlaubter Dateityp

---

### `POST /api/upload-audio`

Lädt eine Browser-Aufnahme (WebM) hoch und startet die Verarbeitung.

**Content-Type:** `multipart/form-data`

**Parameter:**

| Parameter | Typ | Pflicht | Beschreibung |
|-----------|-----|---------|-------------|
| `audio` | File | Ja | Audio-Aufnahme (WebM) |
| `job_type` | String | Nein | `dictation` (Standard) oder `meeting` |
| `speech_model_id` | Integer | Nein | ID des Sprachmodells |
| `language` | String | Nein | Sprach-Code |
| `save_audio` | String | Nein | `1` für Audio-Archivierung |

**Erfolgsantwort (200):**
```json
{
  "job_id": "a1b2c3d4e5f6...",
  "status": "pending"
}
```

---

## Transkriptions-Jobs

### `GET /api/jobs/<job_type>`

Listet alle Jobs eines Typs für den aktuellen Benutzer.

**URL-Parameter:**

| Parameter | Werte | Beschreibung |
|-----------|-------|-------------|
| `job_type` | `transcription` | Job-Typ |

**Filterung:** Nur Jobs innerhalb des konfigurierten Verlaufszeitraums (`history_days`) des Benutzers, maximal 50 Einträge.

**Antwort (200):**
```json
[
  {
    "id": "a1b2c3d4...",
    "title": "Interview.mp3",
    "status": "completed",
    "created_at": "23.02.2026 14:30",
    "result_text": "Transkribierter Text...",
    "diarized_segments": [...],
    "has_speakers": false,
    "summary_text": "Zusammenfassung...",
    "summary_status": "completed",
    "error_message": null,
    "tool_action": null,
    "multi_speaker": false,
    "audio_available": true
  }
]
```

---

### `GET /api/job/<public_id>`

Gibt Details eines einzelnen Jobs zurück.

**Antwort (200):**
```json
{
  "id": "a1b2c3d4...",
  "title": "Interview.mp3",
  "status": "completed",
  "created_at": "23.02.2026 14:30",
  "result_text": "Transkribierter Text...",
  "diarized_segments": [
    {
      "text": " Segment-Text",
      "start": 0.0,
      "end": 5.2,
      "speaker": "Speaker 1"
    }
  ],
  "has_speakers": true,
  "summary_text": null,
  "summary_status": null,
  "error_message": null,
  "tool_action": null,
  "multi_speaker": true,
  "audio_available": true
}
```

**Fehler:**
- `404` — Job nicht gefunden oder gehört nicht dem Benutzer

---

### `PATCH /api/job/<public_id>/title`

Aktualisiert den Titel eines Jobs.

**Content-Type:** `application/json`

**Body:**
```json
{
  "title": "Neuer Titel"
}
```

**Antwort (200):**
```json
{
  "status": "ok",
  "title": "Neuer Titel"
}
```

---

### `PATCH /api/job/<public_id>/segment`

Aktualisiert den Text eines einzelnen Segments.

**Body:**
```json
{
  "segment_index": 0,
  "text": "Korrigierter Segment-Text"
}
```

**Antwort (200):** Vollständiges Job-Objekt (wie `GET /api/job/<id>`)

---

### `POST /api/job/<public_id>/speakers`

Benennt Sprecher in diarisierten Segmenten um.

**Body:**
```json
{
  "renames": {
    "Speaker 1": "Max Mustermann",
    "Speaker 2": "Erika Musterfrau"
  }
}
```

**Antwort (200):** Vollständiges Job-Objekt

---

### `POST /api/summarize/<public_id>`

Startet die Zusammenfassung eines Jobs.

**Body:**
```json
{
  "text_model_id": 1
}
```

**Antwort (200):**
```json
{
  "status": "processing"
}
```

---

### `GET /api/job/<public_id>/download`

Lädt die Transkription als Textdatei herunter.

**Antwort:** `text/plain` Datei mit Zeitstempeln und Sprecherzuordnung (falls vorhanden). Bei vorhandener Zusammenfassung wird diese an den Text angehängt.

---

### `GET /api/job/<public_id>/audio`

Streamt die archivierte Audiodatei mit HTTP Range Support (Seeking).

**Query-Parameter:**

| Parameter | Beschreibung |
|-----------|-------------|
| `download=1` | Als Datei-Download statt Streaming |

**Antwort:** Audiodatei mit korrektem MIME-Type

**Fehler:**
- `404` — Keine Audiodatei verfügbar (nicht archiviert oder Datei gelöscht)

---

### `DELETE /api/job/<public_id>`

Löscht einen Job inkl. Audio-Datei und Chat-Verlauf.

**Antwort (200):**
```json
{
  "status": "deleted"
}
```

---

## Meetings

Meeting-Endpunkte funktionieren analog zu den Job-Endpunkten. Meetings haben immer `multi_speaker: true`.

### Endpunkte

| Route | Methode | Beschreibung |
|-------|---------|-------------|
| `GET /api/meetings` | GET | Alle Meetings auflisten |
| `GET /api/meeting/<id>` | GET | Meeting-Details |
| `PATCH /api/meeting/<id>/title` | PATCH | Titel aktualisieren |
| `PATCH /api/meeting/<id>/segment` | PATCH | Segment-Text bearbeiten |
| `POST /api/meeting/<id>/speakers` | POST | Sprecher umbenennen |
| `POST /api/summarize-meeting/<id>` | POST | Zusammenfassung starten |
| `GET /api/meeting/<id>/download` | GET | Als Text herunterladen |
| `GET /api/meeting/<id>/audio` | GET | Audio streamen |
| `DELETE /api/meeting/<id>` | DELETE | Meeting löschen |

### Meeting-Objekt

```json
{
  "id": "a1b2c3d4...",
  "title": "Teammeeting 23.02.2026",
  "status": "completed",
  "created_at": "23.02.2026 10:00",
  "result_text": "[Speaker 1]: Hallo zusammen...",
  "diarized_segments": [...],
  "has_speakers": true,
  "summary_text": "Zusammenfassung...",
  "summary_status": "completed",
  "error_message": null,
  "multi_speaker": true,
  "audio_available": true
}
```

---

## Diktate

Diktat-Endpunkte für Sprachaufnahmen. Diktate haben kein Zusammenfassungs-Feature und immer `multi_speaker: false`.

### Endpunkte

| Route | Methode | Beschreibung |
|-------|---------|-------------|
| `GET /api/dictations` | GET | Alle Diktate auflisten |
| `GET /api/dictation/<id>` | GET | Diktat-Details |
| `PATCH /api/dictation/<id>/title` | PATCH | Titel aktualisieren |
| `PATCH /api/dictation/<id>/segment` | PATCH | Segment-Text bearbeiten |
| `GET /api/dictation/<id>/download` | GET | Als Text herunterladen |
| `GET /api/dictation/<id>/audio` | GET | Audio streamen |
| `DELETE /api/dictation/<id>` | DELETE | Diktat löschen |

### Diktat-Objekt

```json
{
  "id": "a1b2c3d4...",
  "title": "Aufnahme 23.02.2026 14:30",
  "status": "completed",
  "created_at": "23.02.2026 14:30",
  "result_text": "Diktierter Text...",
  "diarized_segments": [...],
  "has_speakers": false,
  "error_message": null,
  "multi_speaker": false,
  "audio_available": false
}
```

---

## Text-Tasks

### `POST /api/text-task`

Erstellt eine neue Textverarbeitungs-Aufgabe.

**Content-Type:** `application/json`

**Body:**
```json
{
  "action": "translate",
  "text": "Der zu verarbeitende Text",
  "text_model_id": 1,
  "target_language": "Englisch"
}
```

**Aktionen:**

| Aktion | Beschreibung |
|--------|-------------|
| `rewrite` | Text umschreiben und stilistisch verbessern |
| `grammar` | Grammatik- und Rechtschreibprüfung |
| `translate` | Übersetzen in Zielsprache |
| `summarize` | Zusammenfassen |

**Antwort (200):**
```json
{
  "id": "a1b2c3d4...",
  "status": "pending"
}
```

---

### `GET /api/text-task/<public_id>`

Gibt Details einer Text-Task zurück.

**Antwort (200):**
```json
{
  "id": "a1b2c3d4...",
  "action": "translate",
  "action_label": "Übersetzen",
  "status": "completed",
  "input_text": "Originaltext...",
  "result_text": "Translated text...",
  "error_message": null,
  "created_at": "23.02.2026 14:30"
}
```

---

### `GET /api/text-tasks`

Listet die letzten 20 Text-Tasks des Benutzers.

**Antwort (200):** Array von Text-Task-Objekten.

---

### `DELETE /api/text-task/<public_id>`

Löscht eine Text-Task.

**Antwort (200):**
```json
{
  "status": "deleted"
}
```

---

## Wörterbuch

Das Wörterbuch ermöglicht benutzerdefinierte Vokabeln, die als Prompt an die Speech-to-Text-API übergeben werden.

> Zugriff erfordert, dass `dictionary_enabled` in mindestens einer Gruppe des Benutzers aktiviert ist.

### `GET /api/dictionary`

Listet alle Wörterbucheinträge des Benutzers.

**Antwort (200):**
```json
[
  {
    "id": 1,
    "word": "TranscribeOps",
    "description": "Name der Anwendung",
    "created_at": "23.02.2026 14:30"
  }
]
```

---

### `POST /api/dictionary`

Erstellt einen neuen Wörterbucheintrag.

**Body:**
```json
{
  "word": "TranscribeOps",
  "description": "Name der Anwendung"
}
```

**Antwort (201):** Wörterbucheintrag-Objekt.

**Fehler:**
- `400` — Wort ist leer
- `409` — Wort existiert bereits

---

### `PUT /api/dictionary/<entry_id>`

Aktualisiert einen Wörterbucheintrag.

**Body:**
```json
{
  "word": "TranscribeOps",
  "description": "Aktualisierte Beschreibung"
}
```

**Antwort (200):** Aktualisiertes Wörterbucheintrag-Objekt.

---

### `DELETE /api/dictionary/<entry_id>`

Löscht einen Wörterbucheintrag.

**Antwort (200):**
```json
{
  "status": "deleted"
}
```

---

## KI-Chat

Multi-Turn-Chat mit Transkriptionen. Verfügbar für Jobs und Meetings.

### `GET /api/chat/<record_type>/<public_id>`

Gibt den Chat-Verlauf für eine Transkription zurück.

**URL-Parameter:**

| Parameter | Werte | Beschreibung |
|-----------|-------|-------------|
| `record_type` | `job`, `meeting` | Typ des Records |
| `public_id` | String | Public-ID des Records |

**Antwort (200):**
```json
{
  "messages": [
    {
      "id": "abc123...",
      "role": "user",
      "content": "Was ist das Hauptthema?",
      "status": "completed",
      "created_at": "23.02.2026 14:30"
    },
    {
      "id": "def456...",
      "role": "assistant",
      "content": "Das Hauptthema ist...",
      "status": "completed",
      "created_at": "23.02.2026 14:30"
    }
  ],
  "has_pending": false
}
```

---

### `POST /api/chat/<record_type>/<public_id>`

Sendet eine Nachricht und queut eine KI-Antwort.

**Body:**
```json
{
  "content": "Was sind die wichtigsten Punkte?",
  "text_model_id": 1
}
```

**Antwort (200):**
```json
{
  "user_message": {
    "id": "abc123...",
    "role": "user",
    "content": "Was sind die wichtigsten Punkte?",
    "status": "completed",
    "created_at": "23.02.2026 14:31"
  },
  "assistant_message": {
    "id": "def456...",
    "role": "assistant",
    "content": "",
    "status": "processing",
    "created_at": "23.02.2026 14:31"
  }
}
```

> Die KI-Antwort wird asynchron generiert. Pollen Sie `GET /api/chat/<type>/<id>`, bis `status` des Assistant-Messages `completed` ist.

### Kontext

Der KI-Chat erhält als Kontext:
- Einen System-Prompt mit den ersten 8.000 Zeichen der Transkription
- Den vollständigen bisherigen Chat-Verlauf
- Die neue Benutzer-Nachricht

---

### `DELETE /api/chat/<record_type>/<public_id>`

Löscht den gesamten Chat-Verlauf für ein Record.

**Antwort (200):**
```json
{
  "status": "cleared"
}
```

---

## Fehlerbehandlung

### Standard-Fehlerformat

```json
{
  "error": "Fehlerbeschreibung"
}
```

### HTTP-Statuscodes

| Code | Bedeutung |
|------|-----------|
| `200` | Erfolgreich |
| `201` | Erstellt (nur `POST /api/dictionary`) |
| `400` | Ungültige Anfrage (fehlende Parameter, falscher Typ) |
| `403` | Zugriff verweigert (Feature nicht aktiviert) |
| `404` | Ressource nicht gefunden |
| `409` | Konflikt (z.B. doppelter Wörterbucheintrag) |

### Häufige Fehlermeldungen

| Meldung | Ursache |
|---------|---------|
| `Keine Datei ausgewählt` | Upload ohne `file`-Feld |
| `Dateityp nicht erlaubt` | Ungültige Dateiendung |
| `Nicht gefunden` | Job/Meeting/Diktat gehört nicht dem Benutzer |
| `Kein Textmodell ausgewählt` | `text_model_id` fehlt oder ungültig |
| `Kein Zugriff auf das Wörterbuch` | Benutzergruppe hat Dictionary nicht aktiviert |
| `Dieses Wort existiert bereits` | Doppelter Wörterbucheintrag |

---

## Admin-Routes

Die Admin-Endpunkte sind unter `/admin` erreichbar und erfordern Admin-Rechte. Sie verwenden Standard-HTML-Formulare (POST) statt JSON-API.

| Route | Methode | Beschreibung |
|-------|---------|-------------|
| `GET /admin/` | GET | Dashboard |
| `POST /admin/user` | POST | Benutzer erstellen |
| `POST /admin/user/<id>` | POST | Benutzer bearbeiten |
| `POST /admin/user/<id>/delete` | POST | Benutzer löschen |
| `POST /admin/group` | POST | Gruppe erstellen |
| `POST /admin/group/<id>` | POST | Gruppe bearbeiten |
| `POST /admin/group/<id>/delete` | POST | Gruppe löschen |
| `POST /admin/speech-model` | POST | Sprachmodell erstellen |
| `POST /admin/speech-model/<id>` | POST | Sprachmodell bearbeiten |
| `POST /admin/speech-model/<id>/delete` | POST | Sprachmodell löschen |
| `POST /admin/text-model` | POST | Textmodell erstellen |
| `POST /admin/text-model/<id>` | POST | Textmodell bearbeiten |
| `POST /admin/text-model/<id>/delete` | POST | Textmodell löschen |
| `POST /admin/global` | POST | Globale Einstellungen speichern |
| `POST /admin/sso` | POST | SSO-Einstellungen speichern |

---

## Seiten-Routes

| Route | Methode | Beschreibung |
|-------|---------|-------------|
| `GET /` | GET | Weiterleitung zur Transkription |
| `GET /transcription` | GET | Transkriptions-Seite |
| `GET /meeting` | GET | Meeting-Seite |
| `GET /dictation` | GET | Diktat-Seite |
| `GET /text-tools` | GET | Text-Tools-Seite |
| `GET /dictionary` | GET | Wörterbuch-Seite |
| `GET /settings` | GET, POST | Benutzereinstellungen |
| `GET /transcription-job/<id>` | GET | Job-Detailseite |
| `GET /meeting-job/<id>` | GET | Meeting-Detailseite |
| `GET /dictation-job/<id>` | GET | Diktat-Detailseite |
| `GET /job/<id>` | GET | Legacy-Weiterleitung |
