# TranscribeOps Model API (Whisper API Service)

The Model API service is a standalone Flask server providing an **OpenAI-compatible** transcription API. It supports two engines — **WhisperX** (faster-whisper with word alignment) and **NeMo** (NVIDIA Parakeet) — and can serve multiple models at once. Everything is managed through a built-in **admin UI**.

## Table of contents

- [Overview](#overview)
- [Architecture: main engine and instances](#architecture-main-engine-and-instances)
- [Model routing via the model parameter](#model-routing-via-the-model-parameter)
- [Admin UI](#admin-ui)
- [API endpoints](#api-endpoints)
- [Dictionary and replacement rules (prompt)](#dictionary-and-replacement-rules-prompt)
- [Timeout and RAM unloading](#timeout-and-ram-unloading)
- [Model catalog](#model-catalog)
- [Configuration](#configuration)
- [Authentication](#authentication)
- [Integration with TranscribeOps](#integration-with-transcribeops)

---

## Overview

| Property | Value |
|----------|-------|
| **Framework** | Flask + Gunicorn (main process), Werkzeug (instance workers) |
| **Engines** | WhisperX (faster-whisper + alignment + diarization), NeMo (Parakeet TDT) |
| **API compatibility** | OpenAI Whisper API (`/v1/audio/transcriptions`) |
| **External port** | 8000 — single entry point for the API **and** the admin UI |
| **Admin UI** | `http://<host>:8000/admin` |
| **Default model** | `medium` (WhisperX), changeable via the admin UI |

---

## Architecture: main engine and instances

The service consists of a **main process** and optional **instance workers**:

- **Main process (port 8000):** loads the main engine (alias `whisper-1`), hosts the admin UI and the **model router** that dispatches requests based on the `model` parameter.
- **Instance workers:** separate processes each loading one additional model (e.g. a fast `tiny` for dictation and a German Parakeet for meetings). They are created in the admin UI and managed by the main process (start/stop/respawn). Their internal ports (default 8100–8120) bind to **localhost only** — externally everything goes through port 8000.

Process isolation means a crash or memory issue in one instance takes down neither the main process nor other models, and instances can be started, stopped, or unloaded from RAM individually.

---

## Model routing via the `model` parameter

The API's `model` parameter decides which process handles a request:

| `model` value | Target |
|---------------|--------|
| empty or `whisper-1` | Main engine (recommended default) |
| main engine's model name (e.g. `medium`) | Main engine |
| instance name (e.g. `express`) | That instance |
| unknown value | `404` with the list of available models |

The **instance name is the alias**: an instance called `dictation-fast` is addressed with `model=dictation-fast`. `GET /v1/models` lists all available aliases, so clients can discover models automatically.

Sleeping instances (see [RAM unloading](#timeout-and-ram-unloading)) are started automatically on request; the request then waits for the model to load. Explicitly stopped instances are **not** auto-started.

---

## Admin UI

Available at `http://<host>:8000/admin` (password: `ADMIN_PASSWORD`). Three areas:

1. **Models** — curated download catalog (Whisper sizes, Parakeet variants, the German-optimized Parakeet Primeline). Custom **HuggingFace repos** can be added by `repo_id`; NeMo models also work as bare `.nemo` checkpoint files (community fine-tunes).
2. **Instances** — create instances (name = API alias, engine, model, device, compute type, timeout, RAM unloading), start/stop them, change settings. The main engine appears as the first row and can be reconfigured here (triggers a reload; timeout/RAM-only changes do not).
3. **API keys** — create and revoke bearer keys (stored hashed).

---

## API endpoints

### `POST /v1/audio/transcriptions`

**Content-Type:** `multipart/form-data`

| Parameter | Type | Required | Description | Default |
|-----------|------|----------|-------------|---------|
| `file` | File | Yes | Audio file (any ffmpeg-readable format) | — |
| `model` | String | No | Model alias, see [routing](#model-routing-via-the-model-parameter) | `whisper-1` |
| `language` | String | No | Language code (ISO 639-1), e.g. `de` | auto-detect |
| `prompt` | String | No | Dictionary + replacement rules, see [below](#dictionary-and-replacement-rules-prompt) | — |
| `response_format` | String | No | `json`, `verbose_json`, `text`, `srt`, `vtt` | `json` |
| `diarize` | Bool | No | Speaker diarization (requires `HF_TOKEN`) | `false` |
| `async` | Bool | No | Async mode: immediate `202` + `task_id` | `false` |

**Example:**

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

**Error codes:** `400` (no file), `401` (invalid key), `404` (unknown model), `500` (transcription error), `503` (engine loading / instance not startable, with `Retry-After`), `504` (timeout exceeded).

### `GET /v1/audio/transcriptions/<task_id>`

Status polling for async tasks. The response contains `status` (`processing` / `completed` / `failed`), `progress` (0–100), `progress_step`, and on completion `result` or `error`. Results are discarded after delivery or after 1 hour. The main process forwards polls to the owning instance automatically.

### `GET /v1/models`

Lists all usable models: `whisper-1` + the main engine's model + all instance aliases (running or sleeping), with `description` = engine/model.

### `GET /health`

No authentication. Returns engine, model, device, compute type, `main_engine_loaded`, `active_requests`, plus diarization/alignment capabilities.

---

## Dictionary and replacement rules (`prompt`)

The `prompt` parameter carries a comma-separated dictionary. Both local engines apply it as a word-level post-correction (timestamps are preserved):

- **`Proper Name`** — words in the transcript that sound similar are corrected to the exact spelling (fuzzy): `Janik Bader` → `Jannik Baader`. Multi-word entries and hyphenated compounds (`IOK-Abteilung` → `IuK-Abteilung`) are corrected too. Short entries (2–3 characters, e.g. acronyms like `IuK`) match strictly: exactly, or with at most one character difference given identical first/last characters.
- **`source=target`** — replacement rule: when the source is recognized (fuzzy included), it is replaced entirely by the target, e.g. `Doppelpunkt=:` or `mfg=mit freundlichen Grüßen`. If the target is punctuation only, it is attached to the preceding word, dictation-style ("ist denn Doppelpunkt" → "ist denn:"). A comma cannot be used as a target (commas separate entries).

```
prompt=Jannik Baader, IuK, Erika Mustermann, Doppelpunkt=:, mfg=mit freundlichen Grüßen
```

---

## Timeout and RAM unloading

Both are configurable per model in the admin UI (instance settings or the main engine dialog); changes apply immediately without a restart:

- **Timeout** (default: 600s, `0` = unlimited): maximum processing time per request. Synchronous requests get `504` after expiry; async tasks flip to `failed` on the next poll.
- **RAM unloading / idle unload** (default: off, `0` = keep loaded): after X seconds without a request the model is unloaded — for instances the whole worker process is stopped (status "Sleeping"), for the main engine the model is released in-process. The next request reloads automatically and waits for it. Running transcriptions block the unload.

---

## Model catalog

| Model | Engine | Size | Description |
|-------|--------|------|-------------|
| `tiny` / `base` / `small` | WhisperX | 75 MB – 465 MB | Fast, CPU-friendly |
| `medium` | WhisperX | ~1.5 GB | Default recommendation |
| `large-v3` / `large-v3-turbo` | WhisperX | ~3 GB / ~1.5 GB | Best Whisper quality |
| `parakeet-tdt-0.6b-v2/v3`, `parakeet-tdt-1.1b` | NeMo | 1.2 – 2.2 GB | NVIDIA Parakeet, very fast ASR |
| `parakeet-primeline` | NeMo | ~2.5 GB | **German-optimized** Parakeet fine-tune (CC-BY-4.0) |

Alignment models (wav2vec2 for en/fr/de/es/it) are baked into the image; pyannote diarization is fetched automatically on first start given an `HF_TOKEN`. All models and the admin database live in the volume under `/root/.cache` and survive container restarts.

---

## Configuration

| Variable | Description | Default |
|----------|-------------|---------|
| `WHISPER_API_KEY` | Static API key (in addition to admin-UI keys) | `""` |
| `WHISPER_MODEL` | Initial main engine model | `medium` |
| `WHISPER_DEVICE` | `cpu`, `cuda`, or `mps` | `cpu` |
| `WHISPER_COMPUTE_TYPE` | `int8`, `int16`, `float16`, `float32` | `int8` |
| `WHISPER_BATCH_SIZE` | Transcription batch size | `16` |
| `HF_TOKEN` | HuggingFace token (needed for diarization/pyannote) | `""` |
| `ADMIN_PASSWORD` | Admin UI password (empty = admin UI disabled) | `""` |
| `ADMIN_SESSION_SECRET` | Admin UI session secret | derived |
| `ADMIN_DB_PATH` | Path of the admin SQLite DB | `/root/.cache/transcribeops/admin.db` |
| `INSTANCE_PORT_RANGE` | Internal port range for instance workers | `8100-8120` |
| `DISABLE_MAIN_ENGINE` | `1` = main process loads no model (router + admin only) | `0` |
| `ROUTER_READ_TIMEOUT` | Proxy timeout when no model timeout is set (seconds) | `3600` |
| `ROUTER_STARTUP_TIMEOUT` | Max wait when auto-starting sleeping instances | `300` |

Engine/model changes made in the admin UI are persisted in the admin DB and override the env defaults. Admin DB schema migrations run automatically on startup.

---

## Authentication

Bearer token in the `Authorization` header. Valid tokens are the static `WHISPER_API_KEY` (if set) and all active keys created in the admin UI. If neither env key nor DB keys are configured, the API is open — only sensible on isolated networks.

---

## Integration with TranscribeOps

Each model is registered in the web app as its own **speech model** with provider `whisper_local` — all sharing the same endpoint URL, distinguished only by the model ID:

```
Provider:      whisper_local
Endpoint URL:  http://localhost:8000/v1/audio/transcriptions   (pod/compose-internal)
API key:       <key from the admin UI>
Model ID:      whisper-1        (main engine)  or  <instance name>
```

Offering a new model therefore only takes: download the model in the admin UI → create an instance → add a speech-model entry in the web app with `model_id` = instance name. No new port, no new container.
