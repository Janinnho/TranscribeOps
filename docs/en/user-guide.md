# User Guide

## Table of Contents

- [Getting Started](#getting-started)
- [Transcription](#transcription)
- [Meetings](#meetings)
- [Dictation](#dictation)
- [Detail View](#detail-view)
- [Summary](#summary)
- [AI Chat](#ai-chat)
- [Text Tools](#text-tools)
- [Dictionary](#dictionary)
- [Settings](#settings)

---

## Getting Started

### Signing In

1. Open TranscribeOps in your browser (e.g. `http://localhost:5000`)
2. Enter your email address and password
3. Click **Sign in**

> When SSO is enabled, you are automatically signed in via your identity provider. Manual login is still available at `/manuell-login`.

### Navigation

The sidebar navigation contains the following sections (depending on group permissions):

| Icon | Section | Description |
|--------|---------|-------------|
| Microphone | **Transcription** | Transcribe audio files |
| People | **Meetings** | Meeting recordings with speaker separation |
| Recording | **Dictation** | Voice recording directly in the browser |
| Tool | **Text Tools** | AI-powered text processing |
| Book | **Dictionary** | Custom vocabulary |
| Gear | **Settings** | Personal settings |
| Shield | **Admin** | Admin portal (admins only) |

### Responsive Design

TranscribeOps is fully responsive:
- **Desktop:** Sidebar permanently visible
- **Mobile:** Sidebar as a collapsible menu (hamburger icon)

---

## Transcription

### Uploading a File

1. Navigate to **Transcription**
2. Select an audio file (drag & drop or file picker)
3. Configure the options:

| Option | Description |
|--------|-------------|
| **Speech model** | Choose the speech-to-text model to use |
| **Language** | Audio language (empty = automatic detection) |
| **Multi-speaker** | Enable speaker recognition for multiple speakers |
| **Save audio** | Permanently archive the audio file |

4. Click **Transcribe**

### Supported File Formats

`MP3`, `WAV`, `OGG`, `WebM`, `FLAC`, `M4A`, `MP4`, `MPEG`, `MPGA`

**Maximum file size:** 500 MB

### History

Below the upload area, the history of recent transcriptions is shown. The time range is configurable via the settings (default: 30 days).

### Status Indicator

| Status | Meaning |
|--------|-----------|
| **Pending** | Job in the queue |
| **Processing** | Transcription in progress |
| **Completed** | Transcription successful |
| **Failed** | Error during processing |

> The page refreshes automatically while a job is running.

---

## Meetings

### Recording or Uploading a Meeting

Meetings work like transcriptions, but with **speaker separation** (diarization) enabled:

1. **Upload file** — Upload an existing meeting recording
2. **Record live** — Record a meeting directly in the browser (microphone button)

### Speaker Recognition

For meetings, the system automatically tries to recognize different speakers and separate their contributions. This works best with:
- Clear audio quality
- Distinct speaker changes
- Speech models that support diarization

---

## Dictation

### Starting a Recording

1. Navigate to **Dictation**
2. Click the **record button** (microphone icon)
3. Speak your text
4. Click the button again to stop the recording
5. The recording is transcribed automatically

### Options

| Option | Description |
|--------|-------------|
| **Speech model** | Choose the model to use |
| **Language** | Dictation language |
| **Save audio** | Permanently archive the recording |

---

## Detail View

After a transcription, meeting or dictation finishes, you are taken to the **detail view**. It offers:

### Editing the Title

- Click the title to edit it
- The title is generated automatically if auto-title is enabled for your group
- Confirm with Enter or click the checkmark

### Transcription Text

The transcribed text is shown with:
- **Timestamps** — If supported by the speech model (clickable to jump within the audio player)
- **Speaker separation** — In multi-speaker mode or for meetings

### Editing Segments

Each segment can be edited individually:
1. Click the text of a segment
2. Edit the text
3. Confirm the change

### Renaming Speakers

For diarized recordings, speaker labels can be renamed:
1. Click a speaker name (e.g. "Speaker 1")
2. Enter the real name (e.g. "John Doe")
3. All segments from this speaker are updated

### Audio Player

If the audio file was archived, an audio player is displayed:
- **Play/Pause** — Start/stop playback
- **Seeking** — Jump within the recording
- **Timestamp click** — Click a segment to jump to the corresponding position

### Download

Click **Download** to export the transcription as a text file (`.txt`). The file contains:
- Timestamps (if available)
- Speaker assignment (if available)
- Summary (if available, appended at the end)

### Deleting

Click **Delete** to remove the entry. This also deletes the audio file and chat history.

---

## Summary

### Manual Summary

1. Open the detail view of a transcription or a meeting
2. Choose a **text model** for the summary
3. Click **Summarize**
4. The summary is generated asynchronously and displayed automatically

### Automatic Summary

If **auto summary** is enabled in your user group, a summary is automatically created after every transcription/meeting completes.

> Auto summary is only available for transcriptions and meetings, not for dictations.

---

## AI Chat

The AI chat enables multi-turn conversations about the contents of a transcription or meeting.

### Starting a Chat

1. Open the detail view of a job or meeting
2. Scroll to the **chat area**
3. Choose a text model
4. Ask a question about the transcription content

### Example Questions

- "What are the most important points?"
- "Summarize the discussion about the budget"
- "Which tasks were assigned?"
- "What did Speaker 1 say about topic X?"

### Context

The chat automatically receives the transcription text as context (up to 8,000 characters). The AI assistant answers based on this text and the conversation history so far.

### Clearing the Chat

Click **Clear chat** to remove the entire history and start a new conversation.

---

## Text Tools

Text Tools enable AI-powered text processing independent of transcriptions.

### Available Actions

| Action | Description |
|--------|-------------|
| **Rewrite** | Stylistically revise and improve the text |
| **Grammar** | Grammar and spelling check with corrections |
| **Translate** | Translate text into another language |
| **Summarize** | Summarize the text |

### Usage

1. Navigate to **Text Tools**
2. Choose an action
3. Choose a text model
4. Enter the text to be processed
5. For "Translate": choose the target language
6. Click **Run**

### History

The last 20 text tasks are shown in the history and can be reviewed.

---

## Dictionary

The dictionary lets you define your own vocabulary that improves the recognition accuracy of speech recognition.

### How it works

Dictionary entries are passed as a **prompt** to the speech-to-text API. The speech model takes these terms into account during recognition, which particularly improves accuracy for technical terms, proper names or unusual words.

> The speech model must have **prompt support** (`supports_prompt`) enabled for the dictionary to take effect.

### Managing Entries

1. Navigate to **Dictionary**
2. Click **Add new word**
3. Enter the word and optionally a description
4. Save the entry

### Examples

| Word | Description |
|------|-------------|
| TranscribeOps | Name of the application |
| Kubernetes | Container orchestration platform |
| Dr. Müller | Interview participant |

---

## Settings

Personal settings are available under **Settings** (`/settings`).

### Design Theme

| Option | Description |
|--------|-------------|
| **Light** | Light color scheme |
| **Dark** | Dark color scheme |
| **Automatic** | Follows the operating system setting |

### History Period

Configures how many days of jobs/meetings/dictations are shown in the overviews.

**Default:** 30 days

| Value | Description |
|------|-------------|
| 7 | Last week |
| 30 | Last month |
| 90 | Last 3 months |
| 365 | Last year |

---

## Tips & Tricks

### Better Transcription Results

1. **Specify the language** — If the language is known, specify it explicitly. Automatic detection can be inaccurate for short recordings or mixed languages.
2. **Use the dictionary** — Add technical terms and proper names to the dictionary.
3. **Audio quality** — Better audio quality leads to better results. Reduce background noise if possible.
4. **Choose the right model** — Larger models (medium, large) deliver better results but are slower.

### Multi-Speaker Recordings

1. Enable **multi-speaker mode** or use the **Meeting** feature.
2. Use a speech model with **diarization support** for automatic speaker separation.
3. Rename the recognized speakers via the **rename speakers** feature.

### Keyboard Shortcuts

| Key | Function |
|-------|----------|
| `Enter` | Confirm title change |
| `Escape` | Cancel editing |
