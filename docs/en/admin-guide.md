# Admin Guide

## Table of Contents

- [Overview](#overview)
- [Dashboard](#dashboard)
- [User Management](#user-management)
- [Group Management](#group-management)
- [Speech Models (Speech-to-Text)](#speech-models-speech-to-text)
- [Text Models (AI)](#text-models-ai)
- [Global Settings](#global-settings)
- [Single Sign-On](#single-sign-on)
- [Default Seed Data](#default-seed-data)

---

## Overview

The admin portal is available at `/admin` and is only visible to users with `is_admin=True`. It includes the following sections:

1. **Users** — Create, edit, delete, assign groups
2. **Groups** — Feature access, model assignment, auto features
3. **Speech models** — Configure speech-to-text providers
4. **Text models** — Configure AI text processing providers
5. **Global** — Time zone, system information
6. **Single Sign-On** — SSO configuration (header-based / OIDC)

---

## Dashboard

The dashboard shows a summary of the system:

- **Number of users** — Total and active users
- **Number of groups** — Configured groups
- **Speech models** — Configured speech-to-text models
- **Text models** — Configured AI models
- **Storage** — Total storage consumption of audio files

---

## User Management

### Creating a User

| Field | Description | Required |
|------|-------------|---------|
| Display name | User's name | Yes |
| Email | Login email address (unique) | Yes |
| Password | Initial password | Yes |
| Admin | Grant admin rights | No |
| Groups | Group membership | No |

### Editing a User

- **Change group assignment** — Select/deselect groups
- **Active/Inactive** — Deactivated users cannot sign in
- **Reset password** — Set a new password (only when filled in)
- **Admin status** — Grant/revoke admin rights

### Deleting a User

When a user is deleted, all related data is removed:
- Jobs, meetings, dictations
- Text tasks
- Dictionary entries
- Chat histories

### Source Column

In the user overview, the "Source" column shows how the account was created:

| Badge | Meaning |
|-------|-----------|
| **Local** (gray) | Manually created account with local credentials |
| **Header SSO** (yellow) | Created via header-based SSO |
| **OIDC** (blue) | Created via OpenID Connect |

> SSO users that were created with `password_hash=None` cannot sign in via the manual login form.

---

## Group Management

Groups control which features and models are available to a user. A user can belong to multiple groups — access is combined across all groups (OR logic).

### Creating/Editing a Group

#### Feature Access

| Feature | Description |
|---------|-------------|
| Transcription | Access to audio transcription |
| Meeting | Access to meeting recording |
| Dictation | Access to voice recording/dictation |
| Text Tools | Access to rewrite, grammar, translate, summarize |
| Dictionary | Access to custom vocabulary |

#### Model Assignment

- **Speech models** — Which speech-to-text models group members may use
- **Text models** — Which AI text models group members may use

> Admins always have access to **all active** models, regardless of group assignment.

#### Auto Features

| Feature | Description |
|----------|-------------|
| **Auto title** | Automatic title generation after the transcription completes. Uses the first 500 characters of the result. Requires an assigned text model. |
| **Auto summary** | Automatic summary after the transcription completes (jobs and meetings only). Requires an assigned text model. |

#### Audio Archiving

| Setting | Description |
|-------------|-------------|
| **Audio archiving allowed** | Users can permanently save audio files |
| **Enabled by default** | Audio archiving is checked by default on upload |

#### UI Settings

| Setting | Description |
|-------------|-------------|
| **Hide model selection** | If enabled and only one model is available, the model selection is hidden in the UI |

#### Default Group

If a group is marked as the **default group**, new SSO users are automatically assigned to this group.

---

## Speech Models (Speech-to-Text)

### Providers

| Provider | Internal name | Description |
|----------|--------------|-------------|
| Local Whisper | `whisper_local` | Self-hosted Whisper server (OpenAI-compatible API) |
| OpenAI | `openai` | OpenAI Whisper API (cloud) |
| Azure | `azure` | Azure Speech-to-Text |

### Creating a Model

| Field | Description | Example |
|------|-------------|---------|
| Name | Internal identifier | `whisper-lokal` |
| Display name | Name in the UI | `Lokales Whisper (Medium)` |
| Provider | `whisper_local`, `openai`, `azure` | `whisper_local` |
| Endpoint URL | API URL | `http://whisper:8000/v1/audio/transcriptions` |
| API key | Authentication (optional for local Whisper) | `my-secret-key` |
| Model ID | Model identifier | `whisper-1` |
| Speaker mode | `single`, `multi`, `both` | `both` |

### Azure-specific Fields

| Field | Description | Example |
|------|-------------|---------|
| Azure Deployment | Deployment name | `whisper` |
| Azure API Version | API version | `2024-06-01` |

### Capabilities

| Capability | Description |
|-----------|-------------|
| **Supports prompt** | Pass dictionary entries as prompt |
| **Supports timestamps** | Segment timestamps in the result (verbose_json) |
| **Supports speaker separation** | Diarization (speaker recognition) |

### Speaker Mode

| Mode | Description |
|-------|-------------|
| `single` | Available only for single-speaker transcription |
| `multi` | Available only for multi-speaker transcription/meetings |
| `both` | Available for both modes |

### Example Configurations

#### Local Whisper
```
Provider:      whisper_local
Endpoint URL:  http://whisper:8000/v1/audio/transcriptions
API key:       my-secret-key
Model ID:      whisper-1
Speaker mode:  both
Timestamps:    ✓
Prompt:        ✓
Diarization:   ✗
```

#### OpenAI Whisper
```
Provider:      openai
API key:       sk-...
Model ID:      whisper-1
Speaker mode:  both
Timestamps:    ✓
Prompt:        ✓
Diarization:   ✓ (gpt-4o-transcribe)
```

#### Azure Speech
```
Provider:          azure
Endpoint URL:      https://your-resource.openai.azure.com
API key:           your-api-key
Azure Deployment:  whisper
Azure API Version: 2024-06-01
Speaker mode:      both
Timestamps:        ✓
Diarization:       ✓
```

---

## Text Models (AI)

### Providers

| Provider | Internal name | Description |
|----------|--------------|-------------|
| Ollama | `ollama` | Local LLM (e.g. Llama, Mistral) |
| OpenAI | `openai` | OpenAI Chat API (e.g. GPT-4) |
| Azure | `azure` | Azure OpenAI Service |

### Creating a Model

| Field | Description | Example |
|------|-------------|---------|
| Name | Internal identifier | `gpt-4o` |
| Display name | Name in the UI | `GPT-4o` |
| Provider | `ollama`, `openai`, `azure` | `openai` |
| Endpoint URL | API URL (Ollama/Azure only) | `http://ollama:11434` |
| API key | Authentication | `sk-...` |
| Model ID | Model identifier | `gpt-4o` |

### Azure-specific Fields

| Field | Description | Example |
|------|-------------|---------|
| Azure Deployment | Deployment name | `gpt-4o` |
| Azure API Version | API version | `2024-06-01` |

### Example Configurations

#### Ollama (local)
```
Provider:     ollama
Endpoint URL: http://ollama:11434
Model ID:     llama3.2
```

#### OpenAI
```
Provider: openai
API key:  sk-...
Model ID: gpt-4o
```

#### Azure OpenAI
```
Provider:          azure
Endpoint URL:      https://your-resource.openai.azure.com
API key:           your-api-key
Model ID:          gpt-4o
Azure Deployment:  gpt-4o
Azure API Version: 2024-06-01
```

### Use of Text Models

Text models are used for the following functions:

| Function | Description |
|----------|-------------|
| Text Tools | Rewrite, grammar, translate, summarize |
| Summary | Manual and automatic summaries |
| Auto title | Automatic title generation |
| AI Chat | Multi-turn chat with transcriptions |

---

## Global Settings

### Time Zone

The system time zone is used to display all date and time values. Time values are stored internally in UTC and converted to the configured time zone on display.

**Default:** `Europe/Berlin`

Available time zones follow the IANA format (e.g. `Europe/Berlin`, `America/New_York`, `Asia/Tokyo`).

### System Information

The dashboard shows information about the system:
- Version and build
- Number of users, groups, models
- Storage consumption of audio files

---

## Single Sign-On

The detailed SSO documentation is in the separate file [sso-setup.md](sso-setup.md).

### Quick Overview

| Method | Description |
|---------|-------------|
| **Header-based** | Reverse proxy sets HTTP headers with user data |
| **OIDC** | OpenID Connect Authorization Code Flow |

### Configuration in the Admin Portal

1. Open the **Admin > Single-Sign-On** tab
2. Enable SSO and choose a method
3. Fill in the configuration fields
4. Optional: enable automatic user creation
5. Save

### Important Notes

- **Manual login** is always available at `/manuell-login`
- For **header-based SSO**, the app must be reachable **only** through the reverse proxy
- **OIDC callback URL:** `https://your-domain.com/oidc/callback`
- The **OIDC client secret** is no longer displayed after saving

---

## Default Seed Data

On first startup, the following data is created automatically:

### Admin User

| Field | Value |
|------|------|
| Display name | `Admin` |
| Email | `admin@transcribeops.local` |
| Password | `admin` |
| Admin | Yes |

> **Change the password immediately after the first login!**

### Default Speech Model

| Field | Value |
|------|------|
| Name | `whisper-lokal` |
| Display name | `Lokales Whisper` |
| Provider | `whisper_local` |
| Endpoint URL | `http://whisper:8000/v1/audio/transcriptions` |
| Model ID | `whisper-1` |
| Speaker mode | `both` |
| Timestamps | Yes |
| Prompt | Yes |

### Default Text Model

| Field | Value |
|------|------|
| Name | `ollama-lokal` |
| Display name | `Lokales Ollama` |
| Provider | `ollama` |
| Endpoint URL | `http://ollama:11434` |
| Model ID | `llama3.2` |

### Default Group

| Field | Value |
|------|------|
| Name | `Standard` |
| Description | `Standardgruppe` |
| Default group | Yes |
| All features | Enabled |
| Models assigned | All available models |
| Audio archiving | Enabled (default on) |
| Hide model selection | Yes |
