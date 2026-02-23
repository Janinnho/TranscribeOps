# Admin-Handbuch

## Inhaltsverzeichnis

- [Übersicht](#übersicht)
- [Dashboard](#dashboard)
- [Benutzerverwaltung](#benutzerverwaltung)
- [Gruppenverwaltung](#gruppenverwaltung)
- [Sprachmodelle (Speech-to-Text)](#sprachmodelle-speech-to-text)
- [Textmodelle (KI)](#textmodelle-ki)
- [Globale Einstellungen](#globale-einstellungen)
- [Single Sign-On](#single-sign-on)
- [Standard-Seed-Daten](#standard-seed-daten)

---

## Übersicht

Das Admin-Portal ist unter `/admin` erreichbar und nur für Benutzer mit `is_admin=True` sichtbar. Es umfasst folgende Bereiche:

1. **Benutzer** — Erstellen, Bearbeiten, Löschen, Gruppenzuweisung
2. **Gruppen** — Feature-Zugriff, Modellzuweisung, Auto-Funktionen
3. **Sprachmodelle** — Speech-to-Text-Provider konfigurieren
4. **Textmodelle** — KI-Textverarbeitungs-Provider konfigurieren
5. **Global** — Zeitzone, Systeminformationen
6. **Single-Sign-On** — SSO-Konfiguration (Header-basiert / OIDC)

---

## Dashboard

Das Dashboard zeigt eine Zusammenfassung des Systems:

- **Anzahl Benutzer** — Gesamt und aktive Benutzer
- **Anzahl Gruppen** — Konfigurierte Gruppen
- **Sprachmodelle** — Konfigurierte Speech-to-Text-Modelle
- **Textmodelle** — Konfigurierte KI-Modelle
- **Speicherplatz** — Gesamter Speicherverbrauch der Audio-Dateien

---

## Benutzerverwaltung

### Benutzer erstellen

| Feld | Beschreibung | Pflicht |
|------|-------------|---------|
| Anzeigename | Name des Benutzers | Ja |
| E-Mail | Login-E-Mail-Adresse (unique) | Ja |
| Passwort | Initiales Passwort | Ja |
| Admin | Admin-Rechte vergeben | Nein |
| Gruppen | Gruppenzugehörigkeit | Nein |

### Benutzer bearbeiten

- **Gruppenzuweisung ändern** — Gruppen an-/abwählen
- **Aktiv/Inaktiv** — Deaktivierte Benutzer können sich nicht einloggen
- **Passwort zurücksetzen** — Neues Passwort setzen (nur wenn ausgefüllt)
- **Admin-Status** — Admin-Rechte vergeben/entziehen

### Benutzer löschen

Beim Löschen eines Benutzers werden alle zugehörigen Daten entfernt:
- Jobs, Meetings, Diktate
- Text-Tasks
- Wörterbucheinträge
- Chat-Verläufe

### Quelle-Spalte

In der Benutzer-Übersicht zeigt die Spalte „Quelle" an, wie der Account erstellt wurde:

| Badge | Bedeutung |
|-------|-----------|
| **Lokal** (grau) | Manuell erstellter Account mit lokalen Zugangsdaten |
| **Header SSO** (gelb) | Über Header-basiertes SSO erstellt |
| **OIDC** (blau) | Über OpenID Connect erstellt |

> SSO-Benutzer, die mit `password_hash=None` erstellt wurden, können sich nicht über das manuelle Login-Formular anmelden.

---

## Gruppenverwaltung

Gruppen steuern, welche Features und Modelle einem Benutzer zur Verfügung stehen. Ein Benutzer kann mehreren Gruppen angehören — der Zugriff wird über alle Gruppen hinweg vereint (OR-Logik).

### Gruppe erstellen/bearbeiten

#### Feature-Zugriff

| Feature | Beschreibung |
|---------|-------------|
| Transkription | Zugriff auf Audio-Transkription |
| Meeting | Zugriff auf Meeting-Protokollierung |
| Diktat | Zugriff auf Sprachaufnahme/Diktat |
| Text-Tools | Zugriff auf Umschreiben, Grammatik, Übersetzen, Zusammenfassen |
| Wörterbuch | Zugriff auf benutzerdefiniertes Vokabular |

#### Modellzuweisung

- **Sprachmodelle** — Welche Speech-to-Text-Modelle die Gruppenmitglieder nutzen dürfen
- **Textmodelle** — Welche KI-Textmodelle die Gruppenmitglieder nutzen dürfen

> Admins haben immer Zugriff auf **alle aktiven** Modelle, unabhängig von der Gruppenzuweisung.

#### Auto-Funktionen

| Funktion | Beschreibung |
|----------|-------------|
| **Auto-Titel** | Automatische Titelgenerierung nach Abschluss der Transkription. Verwendet die ersten 500 Zeichen des Ergebnis. Benötigt ein zugewiesenes Textmodell. |
| **Auto-Zusammenfassung** | Automatische Zusammenfassung nach Abschluss der Transkription (nur Jobs und Meetings). Benötigt ein zugewiesenes Textmodell. |

#### Audio-Archivierung

| Einstellung | Beschreibung |
|-------------|-------------|
| **Audio-Archivierung erlaubt** | Benutzer können Audio-Dateien permanent speichern |
| **Standard aktiviert** | Audio-Archivierung ist standardmäßig angehakt beim Upload |

#### UI-Einstellungen

| Einstellung | Beschreibung |
|-------------|-------------|
| **Modellauswahl ausblenden** | Wenn aktiviert und nur ein Modell verfügbar, wird die Modellauswahl in der UI ausgeblendet |

#### Standardgruppe

Wenn eine Gruppe als **Standardgruppe** markiert ist, werden neue SSO-Benutzer automatisch dieser Gruppe zugewiesen.

---

## Sprachmodelle (Speech-to-Text)

### Provider

| Provider | Interner Name | Beschreibung |
|----------|--------------|-------------|
| Lokales Whisper | `whisper_local` | Eigener Whisper-Server (OpenAI-kompatible API) |
| OpenAI | `openai` | OpenAI Whisper API (Cloud) |
| Azure | `azure` | Azure Speech-to-Text |

### Modell erstellen

| Feld | Beschreibung | Beispiel |
|------|-------------|---------|
| Name | Interner Bezeichner | `whisper-lokal` |
| Anzeigename | Name in der UI | `Lokales Whisper (Medium)` |
| Provider | `whisper_local`, `openai`, `azure` | `whisper_local` |
| Endpunkt-URL | API-URL | `http://whisper:8000/v1/audio/transcriptions` |
| API-Schlüssel | Authentifizierung (optional bei lokalem Whisper) | `my-secret-key` |
| Modell-ID | Modellbezeichnung | `whisper-1` |
| Sprecher-Modus | `single`, `multi`, `both` | `both` |

### Azure-spezifische Felder

| Feld | Beschreibung | Beispiel |
|------|-------------|---------|
| Azure Deployment | Deployment-Name | `whisper` |
| Azure API Version | API-Version | `2024-06-01` |

### Fähigkeiten

| Fähigkeit | Beschreibung |
|-----------|-------------|
| **Unterstützt Prompt** | Wörterbuch-Einträge als Prompt übergeben |
| **Unterstützt Zeitstempel** | Segment-Zeitstempel im Ergebnis (verbose_json) |
| **Unterstützt Sprechertrennung** | Diarization (Sprechererkennung) |

### Sprecher-Modus

| Modus | Beschreibung |
|-------|-------------|
| `single` | Nur für Einzelsprecher-Transkription verfügbar |
| `multi` | Nur für Mehrsprecher-Transkription/Meetings verfügbar |
| `both` | Für beide Modi verfügbar |

### Beispielkonfigurationen

#### Lokales Whisper
```
Provider:      whisper_local
Endpunkt-URL:  http://whisper:8000/v1/audio/transcriptions
API-Schlüssel: my-secret-key
Modell-ID:     whisper-1
Sprecher-Modus: both
Zeitstempel:   ✓
Prompt:        ✓
Diarization:   ✗
```

#### OpenAI Whisper
```
Provider:      openai
API-Schlüssel: sk-...
Modell-ID:     whisper-1
Sprecher-Modus: both
Zeitstempel:   ✓
Prompt:        ✓
Diarization:   ✓ (gpt-4o-transcribe)
```

#### Azure Speech
```
Provider:         azure
Endpunkt-URL:     https://your-resource.openai.azure.com
API-Schlüssel:    your-api-key
Azure Deployment: whisper
Azure API Version: 2024-06-01
Sprecher-Modus:   both
Zeitstempel:      ✓
Diarization:      ✓
```

---

## Textmodelle (KI)

### Provider

| Provider | Interner Name | Beschreibung |
|----------|--------------|-------------|
| Ollama | `ollama` | Lokales LLM (z.B. Llama, Mistral) |
| OpenAI | `openai` | OpenAI Chat API (z.B. GPT-4) |
| Azure | `azure` | Azure OpenAI Service |

### Modell erstellen

| Feld | Beschreibung | Beispiel |
|------|-------------|---------|
| Name | Interner Bezeichner | `gpt-4o` |
| Anzeigename | Name in der UI | `GPT-4o` |
| Provider | `ollama`, `openai`, `azure` | `openai` |
| Endpunkt-URL | API-URL (nur für Ollama/Azure) | `http://ollama:11434` |
| API-Schlüssel | Authentifizierung | `sk-...` |
| Modell-ID | Modellbezeichnung | `gpt-4o` |

### Azure-spezifische Felder

| Feld | Beschreibung | Beispiel |
|------|-------------|---------|
| Azure Deployment | Deployment-Name | `gpt-4o` |
| Azure API Version | API-Version | `2024-06-01` |

### Beispielkonfigurationen

#### Ollama (lokal)
```
Provider:      ollama
Endpunkt-URL:  http://ollama:11434
Modell-ID:     llama3.2
```

#### OpenAI
```
Provider:      openai
API-Schlüssel: sk-...
Modell-ID:     gpt-4o
```

#### Azure OpenAI
```
Provider:         azure
Endpunkt-URL:     https://your-resource.openai.azure.com
API-Schlüssel:    your-api-key
Modell-ID:        gpt-4o
Azure Deployment: gpt-4o
Azure API Version: 2024-06-01
```

### Verwendung von Textmodellen

Textmodelle werden für folgende Funktionen verwendet:

| Funktion | Beschreibung |
|----------|-------------|
| Text-Tools | Umschreiben, Grammatik, Übersetzen, Zusammenfassen |
| Zusammenfassung | Manuelle und automatische Zusammenfassungen |
| Auto-Titel | Automatische Titelgenerierung |
| KI-Chat | Multi-Turn-Chat mit Transkriptionen |

---

## Globale Einstellungen

### Zeitzone

Die Systemzeitzone wird für die Anzeige aller Datums- und Zeitangaben verwendet. Zeitwerte werden intern in UTC gespeichert und bei der Anzeige in die konfigurierte Zeitzone konvertiert.

**Standard:** `Europe/Berlin`

Verfügbare Zeitzonen folgen dem IANA-Format (z.B. `Europe/Berlin`, `America/New_York`, `Asia/Tokyo`).

### Systeminformationen

Das Dashboard zeigt Informationen über das System an:
- Version und Build
- Anzahl Benutzer, Gruppen, Modelle
- Speicherplatz-Verbrauch für Audio-Dateien

---

## Single Sign-On

Die ausführliche SSO-Dokumentation befindet sich in der separaten Datei [sso-setup.md](sso-setup.md).

### Kurzübersicht

| Methode | Beschreibung |
|---------|-------------|
| **Header-basiert** | Reverse Proxy setzt HTTP-Header mit Benutzerdaten |
| **OIDC** | OpenID Connect Authorization Code Flow |

### Konfiguration im Admin-Portal

1. **Admin > Single-Sign-On** Tab öffnen
2. SSO aktivieren und Methode wählen
3. Konfigurationsfelder ausfüllen
4. Optional: Automatische Benutzererstellung aktivieren
5. Speichern

### Wichtige Hinweise

- **Manueller Login** ist immer unter `/manuell-login` erreichbar
- Bei **Header-basiertem SSO** muss die App **nur** über den Reverse Proxy erreichbar sein
- **OIDC Callback URL:** `https://your-domain.com/oidc/callback`
- Das **OIDC Client Secret** wird nach dem Speichern nicht mehr angezeigt

---

## Standard-Seed-Daten

Beim ersten Start werden automatisch folgende Daten angelegt:

### Admin-Benutzer

| Feld | Wert |
|------|------|
| Anzeigename | `Admin` |
| E-Mail | `admin@transcribeops.local` |
| Passwort | `admin` |
| Admin | Ja |

> **Ändern Sie das Passwort sofort nach dem ersten Login!**

### Standard-Sprachmodell

| Feld | Wert |
|------|------|
| Name | `whisper-lokal` |
| Anzeigename | `Lokales Whisper` |
| Provider | `whisper_local` |
| Endpunkt-URL | `http://whisper:8080/v1/audio/transcriptions` |
| Modell-ID | `whisper-1` |
| Sprecher-Modus | `both` |
| Zeitstempel | Ja |
| Prompt | Ja |

### Standard-Textmodell

| Feld | Wert |
|------|------|
| Name | `ollama-lokal` |
| Anzeigename | `Lokales Ollama` |
| Provider | `ollama` |
| Endpunkt-URL | `http://ollama:11434` |
| Modell-ID | `llama3.2` |

### Standardgruppe

| Feld | Wert |
|------|------|
| Name | `Standard` |
| Beschreibung | `Standardgruppe` |
| Standardgruppe | Ja |
| Alle Features | Aktiviert |
| Modelle zugewiesen | Alle verfügbaren Modelle |
| Audio-Archivierung | Aktiviert (Standard an) |
| Modellauswahl ausblenden | Ja |
