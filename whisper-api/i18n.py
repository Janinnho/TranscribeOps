"""Whisper-API admin UI i18n.

Mirror of the web-app pattern: a Python dict holds English→German pairs and
``compile_translations()`` writes Babel ``.mo`` files on app startup. English
is the source language so wrapping a new string with ``_()`` only requires
adding a German row to ``TRANSLATIONS['de']``.
"""
import os
from babel.messages.catalog import Catalog
from babel.messages.mofile import write_mo


TRANSLATIONS: dict[str, dict[str, str]] = {
    "de": {
        # === Branding / nav ===
        "TranscribeOps Model API": "TranscribeOps Modell API",
        "Dashboard": "Dashboard",
        "Models": "Modelle",
        "Instances": "Instanzen",
        "API Keys": "API-Keys",
        "Sign out": "Abmelden",
        "Logout": "Abmelden",
        "Language": "Sprache",
        "English": "Englisch",
        "German": "Deutsch",

        # === Login ===
        "Admin Login": "Admin-Anmeldung",
        "Password": "Passwort",
        "Sign in": "Anmelden",
        "Wrong password.": "Falsches Passwort.",
        "Too many failed attempts. Please try again later.": "Zu viele Fehlversuche. Bitte später erneut versuchen.",

        # === Disabled state ===
        "Admin UI disabled": "Admin-UI deaktiviert",
        "The admin interface is disabled because no ADMIN_PASSWORD has been set.": "Das Admin-Interface ist deaktiviert, weil kein ADMIN_PASSWORD gesetzt wurde.",

        # === Dashboard / models / instances ===
        "Main engine": "Haupt-Engine",
        "Engine": "Engine",
        "Model": "Modell",
        "Device": "Gerät",
        "Compute type": "Compute-Typ",
        "Port": "Port",
        "Status": "Status",
        "Loaded": "Geladen",
        "Loading…": "Wird geladen…",
        "Failed": "Fehlgeschlagen",
        "Idle": "Bereit",
        "Disabled": "Deaktiviert",
        "Stopped": "Gestoppt",
        "Running": "Läuft",
        "Reload": "Neu laden",
        "Edit": "Bearbeiten",
        "Save": "Speichern",
        "Cancel": "Abbrechen",
        "Delete": "Löschen",
        "Add": "Hinzufügen",
        "Start": "Starten",
        "Stop": "Stoppen",
        "Restart": "Neu starten",
        "Create instance": "Instanz erstellen",
        "Name": "Name",
        "Purpose": "Zweck",
        "Transcription": "Transkription",
        "Diarization": "Sprechertrennung",
        "Alignment": "Alignment",
        "Download": "Herunterladen",
        "Downloaded": "Heruntergeladen",
        "Not downloaded": "Nicht heruntergeladen",
        "Bundled": "Mitgeliefert",
        "Catalog": "Katalog",
        "Whisper models": "Whisper-Modelle",
        "Parakeet models": "Parakeet-Modelle",
        "Diarization models": "Diarization-Modelle",
        "Alignment models": "Alignment-Modelle",
        "System info": "Systeminfo",
        "Default model": "Standard-Modell",
        "Default device": "Standard-Gerät",
        "Default compute type": "Standard-Compute-Typ",
        "Batch size": "Batch-Größe",
        "Port range": "Port-Bereich",
        "HF token set": "HF-Token gesetzt",
        "API key set": "API-Key gesetzt",
        "Yes": "Ja",
        "No": "Nein",

        # === API keys page ===
        "Create new key": "Neuen Key erstellen",
        "Label": "Label",
        "Created at": "Erstellt am",
        "Last used": "Zuletzt verwendet",
        "Revoke": "Widerrufen",
        "Never": "Nie",
        "This key is shown only once — save it now!": "Dieser Key wird nur ein Mal angezeigt — jetzt speichern!",
        "No keys yet.": "Noch keine Keys.",

        # === Validation / errors (server) ===
        "Unknown engine '{engine}'. Allowed: {allowed}": "Unbekannte Engine '{engine}'. Erlaubt: {allowed}",
        "Model must not be empty.": "Modell darf nicht leer sein.",
        "A reload is already in progress. Please wait and try again.": "Ein Reload läuft bereits. Bitte abwarten und erneut versuchen.",
        "Main engine is reloading.": "Main-Engine wird gerade neu geladen.",
        "Main engine not loaded (last reload failed or invalid configuration).": "Main-Engine nicht geladen (letzter Reload fehlgeschlagen oder Konfiguration ungültig).",
        "Main engine is disabled via DISABLE_MAIN_ENGINE.": "Main engine ist via DISABLE_MAIN_ENGINE deaktiviert.",
        "Reload failed — see server log for details.": "Reload fehlgeschlagen — Details siehe Server-Log.",

        # === Client toasts ===
        "Loading…": "Lädt…",
        "Saved.": "Gespeichert.",
        "Saving…": "Speichert…",
        "Error": "Fehler",
        "Success": "Erfolg",
        "Confirm deletion?": "Löschen bestätigen?",
        "Are you sure?": "Sind Sie sicher?",
        "Network error.": "Netzwerkfehler.",
        "Copied to clipboard.": "In Zwischenablage kopiert.",
        "Copy": "Kopieren",

        # === Dashboard additions ===
        "Overview of all models by purpose.": "Überblick aller Modelle nach Zweck.",
        "System (main process)": "System (Hauptprozess)",
        "Engine, model and device can be edited under %(link_start)sInstances%(link_end)s.": "Engine, Modell und Device können unter %(link_start)sInstanzen%(link_end)s bearbeitet werden.",
        "Initial values come from Docker env vars (%(vars)s); changes are persisted in the admin DB. Diarization and alignment run inside the same process.": "Initialwerte kommen aus den Docker-Env-Vars (%(vars)s); Änderungen werden in der Admin-DB persistiert. Diarisierung und Alignment laufen innerhalb desselben Prozesses.",
        "disabled (DISABLE_MAIN_ENGINE=1)": "deaktiviert (DISABLE_MAIN_ENGINE=1)",
        "reloading…": "lädt neu…",
        "Reload failed": "Reload fehlgeschlagen",
        "Engine loaded": "Engine geladen",
        "Engine not loaded": "Engine nicht geladen",
        "Instance ports": "Instanz-Ports",
        "set (required for diarization)": "gesetzt (erforderlich für Diarisierung)",
        "not set — pyannote unavailable": "nicht gesetzt — pyannote nicht nutzbar",
        "set (env)": "gesetzt (Env)",
        "empty — only DB keys active": "leer — nur DB-Keys aktiv",
        "Shipped with the container": "Mit Container ausgeliefert",
        "Alignment and diarization models are not downloaded individually — they are either bundled in the image or auto-downloaded on first start. No UI configuration needed.": "Alignment- und Diarisierungs-Modelle werden nicht einzeln heruntergeladen — sie sind entweder direkt im Image enthalten oder werden beim ersten Start automatisch nachgeladen. Keine UI-Konfiguration nötig.",
        "Word alignment (wav2vec2)": "Wort-Alignment (wav2vec2)",
        "bundled": "bundled",
        "Torchaudio bundles for English, French, German, Spanish and Italian — preloaded into the image at build time. They provide millisecond-accurate word timestamps and are used in-process by WhisperX.": "Torchaudio-Bundles für Englisch, Französisch, Deutsch, Spanisch und Italienisch — im Image beim Build vorgeladen. Liefern millisekundengenaue Wort-Timestamps, werden in-process von WhisperX verwendet.",
        "Source": "Quelle",
        "Cache": "Cache",
        "%(count)s checkpoints present": "%(count)s Checkpoints vorhanden",
        "only %(count)s checkpoints (expected: 5) — maybe overridden by a volume mount?": "nur %(count)s Checkpoints (erwartet: 5) — evtl. Volume-Mount überlagert?",
        "no checkpoints — check the image build": "keine Checkpoints — Image-Build prüfen",
        "Speaker recognition (pyannote)": "Sprechererkennung (pyannote)",
        "auto-download": "auto-download",
        "pyannote/segmentation-3.0 + pyannote/speaker-diarization-3.1 are downloaded on first container start using the runtime %(token)s and then stored permanently in the volume.": "pyannote/segmentation-3.0 + pyannote/speaker-diarization-3.1 werden beim ersten Containerstart mit dem Runtime-%(token)s heruntergeladen und anschließend dauerhaft im Volume abgelegt.",
        "cached": "im Cache",
        "will be loaded on next start": "wird beim nächsten Start geladen",
        "missing — HF_TOKEN not set": "fehlt — HF_TOKEN nicht gesetzt",
        "Size": "Größe",
        "not loaded": "nicht geladen",
        "Manage models": "Modelle verwalten",
        "Curated catalog — download models from HuggingFace as needed.": "Kuratierter Katalog — Modelle bei Bedarf aus HuggingFace herunterladen.",
        "Download a custom HuggingFace repo": "Eigenes HuggingFace-Repo herunterladen",
        "e.g. user/custom-model": "z.B. user/custom-model",
        "Transcription (Whisper)": "Transkription (Whisper)",
        "Transcription (Parakeet)": "Transkription (Parakeet)",
        "requires HF token": "benötigt HF-Token",
        "Each instance loads its own model in its own process — multiple instances run in parallel.": "Jede Instanz lädt ihr eigenes Modell in einem eigenen Prozess — mehrere Instanzen laufen parallel.",
        "All requests go through the main API port: pass the instance name as the %(param)s parameter and it is routed to the right instance automatically.": "Alle Requests laufen über den Haupt-API-Port: den Instanz-Namen als %(param)s-Parameter übergeben, das Routing zur richtigen Instanz passiert automatisch.",
        "New instance": "Neue Instanz",
        "Name (used as model parameter)": "Name (wird als model-Parameter verwendet)",
        "Letters, digits, dots, hyphens and underscores": "Buchstaben, Ziffern, Punkte, Binde- und Unterstriche",
        "API model": "API-Modell",
        "e.g. express": "z.B. express",
        "Timeout": "Timeout",
        "Idle unload": "RAM-Freigabe",
        "Timeout in seconds (0 = unlimited)": "Timeout in Sekunden (0 = unbegrenzt)",
        "Unload from RAM after idle seconds (0 = keep loaded)": "Aus RAM entladen nach Leerlauf-Sekunden (0 = dauerhaft geladen)",
        "Sleeping": "Schläft",
        "Unloaded after idle time — starts automatically on the next request.": "Nach Leerlaufzeit entladen — startet automatisch bei der nächsten Anfrage.",
        "Settings": "Einstellungen",
        "Instance settings": "Instanz-Einstellungen",
        "Applies immediately, no restart needed. A sleeping instance is started automatically on the next request — that request then waits for the model to load.": "Gilt sofort, kein Neustart nötig. Eine schlafende Instanz startet automatisch bei der nächsten Anfrage — diese Anfrage wartet dann auf das Laden des Modells.",
        "Timeout and idle unload apply immediately without a reload. Engine/model changes trigger a reload.": "Timeout und RAM-Freigabe gelten sofort ohne Reload. Engine-/Modell-Änderungen lösen einen Reload aus.",
        "Note: instances are always transcription services. Diarization (pyannote) and alignment (wav2vec2) run as components %(em_start)sinside%(em_end)s the WhisperX engine when a transcription request asks for %(diarize_code)s or word timestamps — not as separate instances.": "Hinweis: Instanzen sind immer Transkriptionsdienste. Diarisierung (pyannote) und Alignment (wav2vec2) laufen als Komponenten %(em_start)sinnerhalb%(em_end)s der WhisperX-Engine, wenn ein Transkriptions-Request %(diarize_code)s oder Wort-Timestamps anfordert — nicht als eigene Instanzen.",
        "No transcription models downloaded yet. Please download one under \"Models\" first.": "Noch keine Transkriptionsmodelle heruntergeladen. Bitte erst unter „Modelle\" herunterladen.",
        "Engine / Model": "Engine / Modell",
        "Actions": "Aktionen",
        "Main process on port 8000 — managed by Gunicorn": "Hauptprozess auf Port 8000 — durch Gunicorn verwaltet",
        "Default": "Default",
        "crashed": "abgestürzt",
        "disabled via %(var)s": "via %(var)s deaktiviert",
        "No instances created yet.": "Noch keine Instanzen angelegt.",
        "Edit main engine": "Main Engine bearbeiten",
        "Changes are persisted (they survive container restarts) and reload the model immediately. While reloading, port 8000 will not answer transcriptions — pending requests will fail.": "Änderungen werden persistiert (überleben Container-Neustarts) und laden das Modell sofort neu. Während des Reloads beantwortet Port 8000 keine Transkriptionen — bestehende Anfragen schlagen fehl.",
        "No models downloaded yet — please load one under \"Models\" first.": "Noch keine Modelle heruntergeladen — bitte erst unter „Modelle\" eines laden.",
        "Save & reload": "Speichern & neu laden",
        "Generate keys for the %(header)s header of the transcription API.": "Generiere Keys für den %(header)s-Header der Transkriptions-API.",
        "Label (e.g. 'Production')": "Beschriftung (z.B. 'Produktion')",
        "Generate": "Generieren",
        "Important:": "Wichtig:",
        "Prefix": "Prefix",
        "revoked": "widerrufen",
        "active": "aktiv",
        "Set the %(var)s environment variable in your Docker config and restart the container.": "Setze die Umgebungsvariable %(var)s im Docker-Config und starte den Container neu.",
        "Really revoke this key?": "Diesen Key wirklich widerrufen?",
        "Starting…": "Starte…",
        "Download failed: {msg}": "Download fehlgeschlagen: {msg}",
        "Error: {msg}": "Fehler: {msg}",
        "Really delete this instance?": "Instanz wirklich löschen?",
        "Reload main engine now? Transcriptions on port 8000 will be unavailable during the reload.": "Main Engine jetzt neu laden? Transkriptionen auf Port 8000 sind währenddessen nicht verfügbar.",
    },
}


# Client-side keys (mirrored in admin.js via window.I18N).
CLIENT_STRING_KEYS = [
    "Loading…",
    "Saved.",
    "Saving…",
    "Error",
    "Success",
    "Confirm deletion?",
    "Are you sure?",
    "Network error.",
    "Copied to clipboard.",
    "Copy",
    "Start",
    "Stop",
    "Restart",
    "Reload",
    "Delete",
    "Cancel",
    "Save",
    "Edit",
    "Add",
    "Idle",
    "Loading…",
    "Failed",
    "Running",
    "Stopped",
    "Disabled",
    "Download",
    "Download failed: {msg}",
    "Error: {msg}",
    "Really delete this instance?",
    "Really revoke this key?",
    "Reload main engine now? Transcriptions on port 8000 will be unavailable during the reload.",
    "Starting…",
]


def compile_translations(translations_dir: str) -> None:
    for locale, mapping in TRANSLATIONS.items():
        catalog = Catalog(locale=locale, domain="messages")
        catalog.add("", "")
        for msg_id, translated in mapping.items():
            if translated:
                catalog.add(msg_id, translated)
        out_dir = os.path.join(translations_dir, locale, "LC_MESSAGES")
        os.makedirs(out_dir, exist_ok=True)
        with open(os.path.join(out_dir, "messages.mo"), "wb") as f:
            write_mo(f, catalog)


def client_strings_for(locale: str) -> dict:
    out = {}
    mapping = TRANSLATIONS.get(locale, {})
    for key in CLIENT_STRING_KEYS:
        out[key] = mapping.get(key, key)
    return out
