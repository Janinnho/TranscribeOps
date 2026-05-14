# Benutzerhandbuch

## Inhaltsverzeichnis

- [Erste Schritte](#erste-schritte)
- [Transkription](#transkription)
- [Meetings](#meetings)
- [Diktat](#diktat)
- [Detailansicht](#detailansicht)
- [Zusammenfassung](#zusammenfassung)
- [KI-Chat](#ki-chat)
- [Text-Tools](#text-tools)
- [Wörterbuch](#wörterbuch)
- [Einstellungen](#einstellungen)

---

## Erste Schritte

### Anmelden

1. Öffne TranscribeOps im Browser (z.B. `http://localhost:5000`)
2. Gib deine E-Mail-Adresse und dein Passwort ein
3. Klicke auf **Anmelden**

> Bei aktiviertem SSO wirst du automatisch über deinen Identity Provider angemeldet. Der manuelle Login ist weiterhin unter `/manuell-login` erreichbar.

### Navigation

Die Sidebar-Navigation enthält folgende Bereiche (je nach Gruppenberechtigungen):

| Symbol | Bereich | Beschreibung |
|--------|---------|-------------|
| Mikrofon | **Transkription** | Audio-Dateien transkribieren |
| Personen | **Meetings** | Meeting-Aufnahmen mit Sprechertrennung |
| Aufnahme | **Diktat** | Sprachaufnahme direkt im Browser |
| Werkzeug | **Text-Tools** | KI-Textverarbeitung |
| Buch | **Wörterbuch** | Benutzerdefinierte Vokabeln |
| Zahnrad | **Einstellungen** | Persönliche Einstellungen |
| Shield | **Admin** | Admin-Portal (nur für Admins) |

### Responsive Design

TranscribeOps ist vollständig responsive:
- **Desktop:** Sidebar permanent sichtbar
- **Mobile:** Sidebar als ausklappbares Menü (Hamburger-Icon)

---

## Transkription

### Datei hochladen

1. Navigiere zu **Transkription**
2. Wähle eine Audiodatei aus (Drag & Drop oder Dateiauswahl)
3. Konfiguriere die Optionen:

| Option | Beschreibung |
|--------|-------------|
| **Sprachmodell** | Wähle das zu verwendende Speech-to-Text-Modell |
| **Sprache** | Sprache des Audios (leer = automatische Erkennung) |
| **Mehrsprecher** | Aktiviere Sprechererkennung für mehrere Sprecher |
| **Audio speichern** | Audio-Datei dauerhaft archivieren |

4. Klicke auf **Transkribieren**

### Unterstützte Dateiformate

`MP3`, `WAV`, `OGG`, `WebM`, `FLAC`, `M4A`, `MP4`, `MPEG`, `MPGA`

**Maximale Dateigröße:** 500 MB

### Verlauf

Unterhalb des Upload-Bereichs wird der Verlauf der letzten Transkriptionen angezeigt. Der Zeitraum ist über die Einstellungen konfigurierbar (Standard: 30 Tage).

### Status-Anzeige

| Status | Bedeutung |
|--------|-----------|
| **Ausstehend** | Job in der Warteschlange |
| **Verarbeitung** | Transkription läuft |
| **Abgeschlossen** | Transkription erfolgreich |
| **Fehlgeschlagen** | Fehler bei der Verarbeitung |

> Die Seite aktualisiert sich automatisch, solange ein Job läuft.

---

## Meetings

### Meeting aufnehmen oder hochladen

Meetings funktionieren wie Transkriptionen, aber mit aktivierter **Sprechertrennung** (Diarization):

1. **Datei hochladen** — Lade eine vorhandene Meeting-Aufnahme hoch
2. **Live aufnehmen** — Nimm ein Meeting direkt im Browser auf (Mikrofon-Button)

### Sprechererkennung

Bei Meetings wird automatisch versucht, verschiedene Sprecher zu erkennen und deren Beiträge zu trennen. Dies funktioniert am besten mit:
- Klarer Audioqualität
- Deutlichen Sprecherwechseln
- Sprachmodellen, die Diarization unterstützen

---

## Diktat

### Aufnahme starten

1. Navigiere zu **Diktat**
2. Klicke auf den **Aufnahme-Button** (Mikrofon-Symbol)
3. Sprich deinen Text
4. Klicke erneut auf den Button, um die Aufnahme zu beenden
5. Die Aufnahme wird automatisch transkribiert

### Optionen

| Option | Beschreibung |
|--------|-------------|
| **Sprachmodell** | Wähle das zu verwendende Modell |
| **Sprache** | Sprache des Diktats |
| **Audio speichern** | Aufnahme dauerhaft archivieren |

---

## Detailansicht

Nach Abschluss einer Transkription, eines Meetings oder Diktats gelangst du zur **Detailansicht**. Diese bietet:

### Titel bearbeiten

- Klicke auf den Titel, um ihn zu bearbeiten
- Der Titel wird automatisch generiert, wenn Auto-Titel in deiner Gruppe aktiviert ist
- Bestätige mit Enter oder klicke auf das Häkchen

### Transkriptionstext

Der transkribierte Text wird angezeigt mit:
- **Zeitstempeln** — Falls vom Sprachmodell unterstützt (Klickbar für Sprung im Audio-Player)
- **Sprechertrennung** — Bei Mehrsprecher-Modus oder Meetings

### Segmente bearbeiten

Jedes Segment kann einzeln bearbeitet werden:
1. Klicke auf den Text eines Segments
2. Bearbeite den Text
3. Bestätige die Änderung

### Sprecher umbenennen

Bei diarisierten Aufnahmen können Sprecher-Labels umbenannt werden:
1. Klicke auf einen Sprechernamen (z.B. „Speaker 1")
2. Gib den echten Namen ein (z.B. „Max Mustermann")
3. Alle Segmente dieses Sprechers werden aktualisiert

### Audio-Player

Wenn die Audio-Datei archiviert wurde, wird ein Audio-Player angezeigt:
- **Play/Pause** — Wiedergabe starten/stoppen
- **Seeking** — In der Aufnahme springen
- **Zeitstempel-Klick** — Segment anklicken, um zur entsprechenden Stelle zu springen

### Download

Klicke auf **Herunterladen**, um die Transkription als Textdatei (`.txt`) zu exportieren. Die Datei enthält:
- Zeitstempel (falls vorhanden)
- Sprecherzuordnung (falls vorhanden)
- Zusammenfassung (falls vorhanden, am Ende angehängt)

### Löschen

Klicke auf **Löschen**, um den Eintrag zu entfernen. Dabei werden auch die Audiodatei und der Chat-Verlauf gelöscht.

---

## Zusammenfassung

### Manuelle Zusammenfassung

1. Öffne die Detailansicht einer Transkription oder eines Meetings
2. Wähle ein **Textmodell** für die Zusammenfassung
3. Klicke auf **Zusammenfassen**
4. Die Zusammenfassung wird asynchron generiert und automatisch angezeigt

### Automatische Zusammenfassung

Wenn in deiner Benutzergruppe die **Auto-Zusammenfassung** aktiviert ist, wird nach Abschluss jeder Transkription/jedes Meetings automatisch eine Zusammenfassung erstellt.

> Auto-Zusammenfassung ist nur für Transkriptionen und Meetings verfügbar, nicht für Diktate.

---

## KI-Chat

Der KI-Chat ermöglicht Multi-Turn-Gespräche mit dem Inhalt einer Transkription oder eines Meetings.

### Chat starten

1. Öffne die Detailansicht eines Jobs oder Meetings
2. Scrolle zum **Chat-Bereich**
3. Wähle ein Textmodell
4. Stelle eine Frage zum Transkriptionsinhalt

### Beispiel-Fragen

- „Was sind die wichtigsten Punkte?"
- „Fasse die Diskussion über das Budget zusammen"
- „Welche Aufgaben wurden verteilt?"
- „Was hat Sprecher 1 zum Thema X gesagt?"

### Kontext

Der Chat erhält automatisch den Transkriptionstext als Kontext (bis zu 8.000 Zeichen). Der KI-Assistent antwortet basierend auf diesem Text und dem bisherigen Gesprächsverlauf.

### Chat löschen

Klicke auf **Chat löschen**, um den gesamten Verlauf zu entfernen und ein neues Gespräch zu starten.

---

## Text-Tools

Die Text-Tools ermöglichen KI-gestützte Textverarbeitung unabhängig von Transkriptionen.

### Verfügbare Aktionen

| Aktion | Beschreibung |
|--------|-------------|
| **Umschreiben** | Text stilistisch überarbeiten und verbessern |
| **Grammatik** | Grammatik- und Rechtschreibprüfung mit Korrekturen |
| **Übersetzen** | Text in eine andere Sprache übersetzen |
| **Zusammenfassen** | Text zusammenfassen |

### Verwendung

1. Navigiere zu **Text-Tools**
2. Wähle eine Aktion
3. Wähle ein Textmodell
4. Gib den zu verarbeitenden Text ein
5. Bei „Übersetzen": Wähle die Zielsprache
6. Klicke auf **Ausführen**

### Verlauf

Die letzten 20 Text-Tasks werden im Verlauf angezeigt und können erneut eingesehen werden.

---

## Wörterbuch

Das Wörterbuch ermöglicht die Definition eigener Vokabeln, die die Erkennungsgenauigkeit der Spracherkennung verbessern.

### Funktionsweise

Wörterbucheinträge werden als **Prompt** an die Speech-to-Text-API übergeben. Das Sprachmodell berücksichtigt diese Begriffe bei der Erkennung, was besonders bei Fachbegriffen, Eigennamen oder ungewöhnlichen Wörtern die Genauigkeit verbessert.

> Das Sprachmodell muss **Prompt-Unterstützung** (`supports_prompt`) aktiviert haben, damit das Wörterbuch wirkt.

### Einträge verwalten

1. Navigiere zu **Wörterbuch**
2. Klicke auf **Neues Wort hinzufügen**
3. Gib das Wort und optional eine Beschreibung ein
4. Speichere den Eintrag

### Beispiele

| Wort | Beschreibung |
|------|-------------|
| TranscribeOps | Name der Anwendung |
| Kubernetes | Container-Orchestrierungsplattform |
| Dr. Müller | Gesprächspartner im Interview |

---

## Einstellungen

Persönliche Einstellungen sind unter **Einstellungen** (`/settings`) erreichbar.

### Design-Theme

| Option | Beschreibung |
|--------|-------------|
| **Hell** | Helles Farbschema |
| **Dunkel** | Dunkles Farbschema |
| **Automatisch** | Folgt der Betriebssystem-Einstellung |

### Verlaufszeitraum

Konfiguriert, wie viele Tage an Jobs/Meetings/Diktaten in den Übersichten angezeigt werden.

**Standard:** 30 Tage

| Wert | Beschreibung |
|------|-------------|
| 7 | Letzte Woche |
| 30 | Letzter Monat |
| 90 | Letzte 3 Monate |
| 365 | Letztes Jahr |

---

## Tipps & Tricks

### Bessere Transkriptionsergebnisse

1. **Sprache angeben** — Wenn die Sprache bekannt ist, gib sie explizit an. Automatische Erkennung kann bei kurzen Aufnahmen oder Mischsprachen ungenau sein.
2. **Wörterbuch nutzen** — Trage Fachbegriffe und Eigennamen ins Wörterbuch ein.
3. **Audio-Qualität** — Bessere Audio-Qualität führt zu besseren Ergebnissen. Reduziere Hintergrundgeräusche wenn möglich.
4. **Richtiges Modell wählen** — Größere Modelle (medium, large) liefern bessere Ergebnisse, sind aber langsamer.

### Mehrsprecher-Aufnahmen

1. Aktiviere den **Mehrsprecher-Modus** oder nutze die **Meeting**-Funktion.
2. Verwende ein Sprachmodell mit **Diarization-Unterstützung** für automatische Sprechertrennung.
3. Benenne die erkannten Sprecher über die **Sprecher umbenennen**-Funktion.

### Keyboard-Shortcuts

| Taste | Funktion |
|-------|----------|
| `Enter` | Titeländerung bestätigen |
| `Escape` | Bearbeitung abbrechen |
