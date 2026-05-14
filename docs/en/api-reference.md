# API Reference

All API endpoints are available under the `/api` prefix and require an authenticated session (`@login_required`). Responses are returned in JSON format.

## Table of Contents

- [Authentication](#authentication)
- [File Upload](#file-upload)
- [Transcription Jobs](#transcription-jobs)
- [Meetings](#meetings)
- [Dictations](#dictations)
- [Text Tasks](#text-tasks)
- [Dictionary](#dictionary)
- [AI Chat](#ai-chat)
- [Error Handling](#error-handling)

---

## Authentication

All API endpoints use session-based authentication (Flask-Login). A valid session cookie is required. It is set automatically when logging in via `/login` or `/manuell-login`.

### Login routes

| Route | Method | Description |
|-------|--------|-------------|
| `/login` | GET, POST | Main login (SSO-aware) |
| `/manuell-login` | GET, POST | Manual login with email/password |
| `/oidc/callback` | GET | OIDC provider callback |
| `/logout` | GET | Logout |

---

## File Upload

### `POST /api/upload`

Uploads an audio file and starts the transcription.

**Content-Type:** `multipart/form-data`

**Parameters:**

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `file` | File | Yes | Audio file |
| `job_type` | String | No | `transcription` (default) or `meeting` |
| `speech_model_id` | Integer | No | ID of the speech model |
| `language` | String | No | Language code (e.g. `de`, `en`) |
| `multi_speaker` | String | No | `true` for multi-speaker mode |
| `save_audio` | String | No | `1` for audio archiving |

**Allowed file types:** `mp3`, `wav`, `ogg`, `webm`, `flac`, `m4a`, `mp4`, `mpeg`, `mpga`

**Success response (200):**
```json
{
  "job_id": "a1b2c3d4e5f6...",
  "status": "pending"
}
```

**Error responses:**
- `400` — No file, empty filename, or disallowed file type

---

### `POST /api/upload-audio`

Uploads a browser recording (WebM) and starts processing.

**Content-Type:** `multipart/form-data`

**Parameters:**

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `audio` | File | Yes | Audio recording (WebM) |
| `job_type` | String | No | `dictation` (default) or `meeting` |
| `speech_model_id` | Integer | No | ID of the speech model |
| `language` | String | No | Language code |
| `save_audio` | String | No | `1` for audio archiving |

**Success response (200):**
```json
{
  "job_id": "a1b2c3d4e5f6...",
  "status": "pending"
}
```

---

## Transcription Jobs

### `GET /api/jobs/<job_type>`

Lists all jobs of a given type for the current user.

**URL parameters:**

| Parameter | Values | Description |
|-----------|--------|-------------|
| `job_type` | `transcription` | Job type |

**Filtering:** Only jobs within the user's configured history window (`history_days`), up to 50 entries.

**Response (200):**
```json
[
  {
    "id": "a1b2c3d4...",
    "title": "Interview.mp3",
    "status": "completed",
    "created_at": "23.02.2026 14:30",
    "result_text": "Transcribed text...",
    "diarized_segments": [...],
    "has_speakers": false,
    "summary_text": "Summary...",
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

Returns details for a single job.

**Response (200):**
```json
{
  "id": "a1b2c3d4...",
  "title": "Interview.mp3",
  "status": "completed",
  "created_at": "23.02.2026 14:30",
  "result_text": "Transcribed text...",
  "diarized_segments": [
    {
      "text": " Segment text",
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

**Errors:**
- `404` — Job not found or does not belong to the user

---

### `PATCH /api/job/<public_id>/title`

Updates a job's title.

**Content-Type:** `application/json`

**Body:**
```json
{
  "title": "New title"
}
```

**Response (200):**
```json
{
  "status": "ok",
  "title": "New title"
}
```

---

### `PATCH /api/job/<public_id>/segment`

Updates the text of a single segment.

**Body:**
```json
{
  "segment_index": 0,
  "text": "Corrected segment text"
}
```

**Response (200):** Full job object (same as `GET /api/job/<id>`)

---

### `POST /api/job/<public_id>/speakers`

Renames speakers in diarized segments.

**Body:**
```json
{
  "renames": {
    "Speaker 1": "Max Mustermann",
    "Speaker 2": "Erika Musterfrau"
  }
}
```

**Response (200):** Full job object

---

### `POST /api/summarize/<public_id>`

Starts summarization for a job.

**Body:**
```json
{
  "text_model_id": 1
}
```

**Response (200):**
```json
{
  "status": "processing"
}
```

---

### `GET /api/job/<public_id>/download`

Downloads the transcription as a text file.

**Response:** `text/plain` file with timestamps and speaker assignment (if available). If a summary exists, it is appended to the text.

---

### `GET /api/job/<public_id>/audio`

Streams the archived audio file with HTTP Range support (seeking).

**Query parameters:**

| Parameter | Description |
|-----------|-------------|
| `download=1` | Return as a file download instead of streaming |

**Response:** Audio file with the correct MIME type

**Errors:**
- `404` — No audio file available (not archived or file deleted)

---

### `DELETE /api/job/<public_id>`

Deletes a job including its audio file and chat history.

**Response (200):**
```json
{
  "status": "deleted"
}
```

---

## Meetings

Meeting endpoints work analogously to the job endpoints. Meetings always have `multi_speaker: true`.

### Endpoints

| Route | Method | Description |
|-------|--------|-------------|
| `GET /api/meetings` | GET | List all meetings |
| `GET /api/meeting/<id>` | GET | Meeting details |
| `PATCH /api/meeting/<id>/title` | PATCH | Update title |
| `PATCH /api/meeting/<id>/segment` | PATCH | Edit segment text |
| `POST /api/meeting/<id>/speakers` | POST | Rename speakers |
| `POST /api/summarize-meeting/<id>` | POST | Start summarization |
| `GET /api/meeting/<id>/download` | GET | Download as text |
| `GET /api/meeting/<id>/audio` | GET | Stream audio |
| `DELETE /api/meeting/<id>` | DELETE | Delete meeting |

### Meeting object

```json
{
  "id": "a1b2c3d4...",
  "title": "Team meeting 23.02.2026",
  "status": "completed",
  "created_at": "23.02.2026 10:00",
  "result_text": "[Speaker 1]: Hello everyone...",
  "diarized_segments": [...],
  "has_speakers": true,
  "summary_text": "Summary...",
  "summary_status": "completed",
  "error_message": null,
  "multi_speaker": true,
  "audio_available": true
}
```

---

## Dictations

Dictation endpoints for voice recordings. Dictations have no summarization feature and always have `multi_speaker: false`.

### Endpoints

| Route | Method | Description |
|-------|--------|-------------|
| `GET /api/dictations` | GET | List all dictations |
| `GET /api/dictation/<id>` | GET | Dictation details |
| `PATCH /api/dictation/<id>/title` | PATCH | Update title |
| `PATCH /api/dictation/<id>/segment` | PATCH | Edit segment text |
| `GET /api/dictation/<id>/download` | GET | Download as text |
| `GET /api/dictation/<id>/audio` | GET | Stream audio |
| `DELETE /api/dictation/<id>` | DELETE | Delete dictation |

### Dictation object

```json
{
  "id": "a1b2c3d4...",
  "title": "Recording 23.02.2026 14:30",
  "status": "completed",
  "created_at": "23.02.2026 14:30",
  "result_text": "Dictated text...",
  "diarized_segments": [...],
  "has_speakers": false,
  "error_message": null,
  "multi_speaker": false,
  "audio_available": false
}
```

---

## Text Tasks

### `POST /api/text-task`

Creates a new text processing task.

**Content-Type:** `application/json`

**Body:**
```json
{
  "action": "translate",
  "text": "The text to process",
  "text_model_id": 1,
  "target_language": "English"
}
```

**Actions:**

| Action | Description |
|--------|-------------|
| `rewrite` | Rewrite text and improve style |
| `grammar` | Grammar and spelling check |
| `translate` | Translate into target language |
| `summarize` | Summarize |

**Response (200):**
```json
{
  "id": "a1b2c3d4...",
  "status": "pending"
}
```

---

### `GET /api/text-task/<public_id>`

Returns details of a text task.

**Response (200):**
```json
{
  "id": "a1b2c3d4...",
  "action": "translate",
  "action_label": "Translate",
  "status": "completed",
  "input_text": "Original text...",
  "result_text": "Translated text...",
  "error_message": null,
  "created_at": "23.02.2026 14:30"
}
```

---

### `GET /api/text-tasks`

Lists the user's most recent 20 text tasks.

**Response (200):** Array of text task objects.

---

### `DELETE /api/text-task/<public_id>`

Deletes a text task.

**Response (200):**
```json
{
  "status": "deleted"
}
```

---

## Dictionary

The dictionary allows custom vocabulary that is passed as a prompt to the speech-to-text API.

> Access requires `dictionary_enabled` to be set in at least one of the user's groups.

### `GET /api/dictionary`

Lists all of the user's dictionary entries.

**Response (200):**
```json
[
  {
    "id": 1,
    "word": "TranscribeOps",
    "description": "Name of the application",
    "created_at": "23.02.2026 14:30"
  }
]
```

---

### `POST /api/dictionary`

Creates a new dictionary entry.

**Body:**
```json
{
  "word": "TranscribeOps",
  "description": "Name of the application"
}
```

**Response (201):** Dictionary entry object.

**Errors:**
- `400` — Word is empty
- `409` — Word already exists

---

### `PUT /api/dictionary/<entry_id>`

Updates a dictionary entry.

**Body:**
```json
{
  "word": "TranscribeOps",
  "description": "Updated description"
}
```

**Response (200):** Updated dictionary entry object.

---

### `DELETE /api/dictionary/<entry_id>`

Deletes a dictionary entry.

**Response (200):**
```json
{
  "status": "deleted"
}
```

---

## AI Chat

Multi-turn chat with transcriptions. Available for jobs and meetings.

### `GET /api/chat/<record_type>/<public_id>`

Returns the chat history for a transcription.

**URL parameters:**

| Parameter | Values | Description |
|-----------|--------|-------------|
| `record_type` | `job`, `meeting` | Record type |
| `public_id` | String | Public ID of the record |

**Response (200):**
```json
{
  "messages": [
    {
      "id": "abc123...",
      "role": "user",
      "content": "What is the main topic?",
      "status": "completed",
      "created_at": "23.02.2026 14:30"
    },
    {
      "id": "def456...",
      "role": "assistant",
      "content": "The main topic is...",
      "status": "completed",
      "created_at": "23.02.2026 14:30"
    }
  ],
  "has_pending": false
}
```

---

### `POST /api/chat/<record_type>/<public_id>`

Sends a message and queues an AI response.

**Body:**
```json
{
  "content": "What are the most important points?",
  "text_model_id": 1
}
```

**Response (200):**
```json
{
  "user_message": {
    "id": "abc123...",
    "role": "user",
    "content": "What are the most important points?",
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

> The AI response is generated asynchronously. Poll `GET /api/chat/<type>/<id>` until the assistant message's `status` is `completed`.

### Context

The AI chat receives the following context:
- A system prompt with the first 8,000 characters of the transcription
- The complete existing chat history
- The new user message

---

### `DELETE /api/chat/<record_type>/<public_id>`

Deletes the entire chat history for a record.

**Response (200):**
```json
{
  "status": "cleared"
}
```

---

## Error Handling

### Standard error format

```json
{
  "error": "Error description"
}
```

### HTTP status codes

| Code | Meaning |
|------|---------|
| `200` | Success |
| `201` | Created (only `POST /api/dictionary`) |
| `400` | Invalid request (missing parameters, wrong type) |
| `403` | Access denied (feature not enabled) |
| `404` | Resource not found |
| `409` | Conflict (e.g. duplicate dictionary entry) |

### Common error messages

| Message | Cause |
|---------|-------|
| `Keine Datei ausgewählt` | Upload without `file` field |
| `Dateityp nicht erlaubt` | Invalid file extension |
| `Nicht gefunden` | Job/meeting/dictation does not belong to the user |
| `Kein Textmodell ausgewählt` | `text_model_id` missing or invalid |
| `Kein Zugriff auf das Wörterbuch` | User group does not have dictionary enabled |
| `Dieses Wort existiert bereits` | Duplicate dictionary entry |

---

## Admin Routes

The admin endpoints are available under `/admin` and require admin privileges. They use standard HTML forms (POST) instead of a JSON API.

| Route | Method | Description |
|-------|--------|-------------|
| `GET /admin/` | GET | Dashboard |
| `POST /admin/user` | POST | Create user |
| `POST /admin/user/<id>` | POST | Edit user |
| `POST /admin/user/<id>/delete` | POST | Delete user |
| `POST /admin/group` | POST | Create group |
| `POST /admin/group/<id>` | POST | Edit group |
| `POST /admin/group/<id>/delete` | POST | Delete group |
| `POST /admin/speech-model` | POST | Create speech model |
| `POST /admin/speech-model/<id>` | POST | Edit speech model |
| `POST /admin/speech-model/<id>/delete` | POST | Delete speech model |
| `POST /admin/text-model` | POST | Create text model |
| `POST /admin/text-model/<id>` | POST | Edit text model |
| `POST /admin/text-model/<id>/delete` | POST | Delete text model |
| `POST /admin/global` | POST | Save global settings |
| `POST /admin/sso` | POST | Save SSO settings |

---

## Page Routes

| Route | Method | Description |
|-------|--------|-------------|
| `GET /` | GET | Redirect to transcription |
| `GET /transcription` | GET | Transcription page |
| `GET /meeting` | GET | Meeting page |
| `GET /dictation` | GET | Dictation page |
| `GET /text-tools` | GET | Text tools page |
| `GET /dictionary` | GET | Dictionary page |
| `GET /settings` | GET, POST | User settings |
| `GET /transcription-job/<id>` | GET | Job detail page |
| `GET /meeting-job/<id>` | GET | Meeting detail page |
| `GET /dictation-job/<id>` | GET | Dictation detail page |
| `GET /job/<id>` | GET | Legacy redirect |
