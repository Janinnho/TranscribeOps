# TranscribeOps aktualisieren

Diese Anleitung beschreibt das Update einer bestehenden TranscribeOps-Installation auf die neueste Version von GitHub. Deine lokale Konfiguration (`docker-compose.yml`, `.env`) und Named Volumes (Datenbank, Uploads, Modell-Cache) bleiben erhalten.

Datenbank-Migrationen laufen automatisch beim App-Start — sowohl für die Web-App (`_apply_migrations()` in `app/__init__.py`) als auch für die Admin-DB der Modell-API (`init_db()` in `whisper-api/admin/db.py`). Keine manuellen Schema-Schritte nötig.

---

## Versionshinweise 1.2.2

Die Modell-API (whisper-api) wurde umgebaut: **Port 8000 ist jetzt der einzige Einstiegspunkt**, das Modell wird über den `model`-Parameter gewählt (Instanz-Name = Alias). Details in der [Modell-API-Doku](whisper-api.md). Für bestehende Installationen bedeutet das:

1. **Instanz-Ports (8100–8120) sind nur noch intern.** Die Worker binden an localhost; von außen sind sie nicht mehr erreichbar. Clients, die bisher direkt einen Instanz-Port ansprachen, auf `http://<host>:8000` + `model=<Instanz-Name>` umstellen. Innerhalb desselben Pods/Compose-Netzwerks funktionieren die alten URLs übergangsweise weiter. Ein Port-Publishing der Range (z.B. `-p 8100-8120:8100-8120`) kann ersatzlos entfallen.
2. **Unbekannte `model`-Werte geben jetzt `404`** statt stillschweigend mit dem geladenen Modell zu transkribieren. Gültig bleiben `whisper-1` (Main-Engine), der Modellname der Main-Engine sowie alle Instanz-Namen. Externe Clients ggf. prüfen.
3. **Admin-DB wird automatisch migriert** (neue Spalten `timeout_secs`, `idle_unload_secs`, `last_used_at` in der Instanz-Tabelle). Bestehende Instanzen erhalten das Standard-Timeout von 600 s — das entspricht dem bisherigen Verhalten (gunicorn-Timeout). Die Web-App-Datenbank hat in 1.2.2 keine Schema-Änderungen.
4. **Empfohlene Nacharbeit:** Sprachmodell-Einträge in der Web-App, die auf Instanz-Ports zeigen (z.B. `http://localhost:8110/...`), auf `http://localhost:8000/v1/audio/transcriptions` mit `model_id` = Instanz-Name umstellen.
5. **Neu und ohne Migrationsbedarf:** Timeout + RAM-Freigabe pro Modell im Admin-UI, Wörterbuch-Korrektur auch für die Main-Engine (WhisperX) und NeMo ≥ 2.x, Ersetzungsregeln (`Quelle=Ziel`) im Wörterbuch, Modell „Parakeet Primeline (Deutsch)" im Katalog.

---

## Vor dem Update

1. **Deployment-Modus prüfen** — rootless (ohne `sudo`) oder rootful (mit `sudo`). Die Container-Engine hält für beide Modi **komplett getrennte** Storage-Bereiche; ein Update ohne `sudo` bei einer rootful-Installation aktualisiert eine andere Instanz und lässt die Produktion unverändert.
2. **Datenbank-Backup** (empfohlen):

   ```bash
   # Rootless
   docker run --rm -v transcribeops-db:/data -v "$(pwd)":/backup \
     alpine tar czf /backup/db-backup-$(date +%Y%m%d).tar.gz /data

   # Rootful — sudo voranstellen
   sudo docker run --rm -v transcribeops-db:/data -v "$(pwd)":/backup \
     alpine tar czf /backup/db-backup-$(date +%Y%m%d).tar.gz /data
   ```

   `docker` mit `podman` ersetzen, falls du Podman nutzt.
3. **Speicherplatz prüfen** — ein voller Rebuild mit `--no-cache` braucht temporär 5–10 GB extra.

---

## Variante 1 — Full Stack (Compose)

Deckt Option 1 und Option 2 aus der [Haupt-README](../../README.md#-deployment-options) ab: Web-App zusammen mit Worker, Redis und optional Whisper, alles via `docker compose` / `podman compose` gestartet.

### Docker (rootless)

```bash
cd /pfad/zu/TranscribeOps && \
git fetch origin && \
git reset --hard origin/main && \
docker compose build --pull --no-cache && \
docker compose up -d --force-recreate && \
docker image prune -f
```

### Docker (rootful)

```bash
cd /pfad/zu/TranscribeOps && \
sudo git fetch origin && \
sudo git reset --hard origin/main && \
sudo docker compose build --pull --no-cache && \
sudo docker compose up -d --force-recreate && \
sudo docker image prune -f
```

### Podman (rootless)

```bash
cd /pfad/zu/TranscribeOps && \
git fetch origin && \
git reset --hard origin/main && \
podman compose build --pull --no-cache && \
podman compose up -d --force-recreate && \
podman image prune -f
```

### Podman (rootful)

```bash
cd /pfad/zu/TranscribeOps && \
sudo git fetch origin && \
sudo git reset --hard origin/main && \
sudo podman compose build --pull --no-cache && \
sudo podman compose up -d --force-recreate && \
sudo podman image prune -f
```

### Was jeder Schritt macht

1. `git fetch origin` — lädt die neuesten Commits von GitHub.
2. `git reset --hard origin/main` — setzt die Working Copy auf den neuesten Commit. `docker-compose.yml` und `.env` sind gitignored und werden nicht angefasst. **Lokale Änderungen an versionierten Source-Dateien werden verworfen** — vorher in einen Branch oder Fork committen, falls du Anpassungen hast.
3. `compose build --pull --no-cache` — baut alle Images von Grund auf neu und pullt neue Base-Images.
4. `compose up -d --force-recreate` — recreated die Container mit den neuen Images, auch wenn Compose denkt es hat sich nichts geändert.
5. `image prune -f` — gibt Speicherplatz frei, indem die jetzt unbenutzten alten Images entfernt werden.

---

## Variante 2 — Nur Standalone Whisper API

Für Option 3 (Standalone Model API, gestartet mit `docker run` / `podman run` ohne Compose):

### Docker

```bash
cd /pfad/zu/TranscribeOps/whisper-api && \
git -C .. fetch origin && \
git -C .. reset --hard origin/main && \
docker stop transcribeops-whisper && \
docker rm transcribeops-whisper && \
docker build --pull --no-cache -t transcribeops-whisper . && \
docker run -d \
  --name transcribeops-whisper \
  -p 8000:8000 \
  -v whisper-cache:/root/.cache \
  --env-file ../.env \
  transcribeops-whisper && \
docker image prune -f
```

### Podman

```bash
cd /pfad/zu/TranscribeOps/whisper-api && \
git -C .. fetch origin && \
git -C .. reset --hard origin/main && \
podman stop transcribeops-whisper && \
podman rm transcribeops-whisper && \
podman build --pull --no-cache -t transcribeops-whisper . && \
podman run -d \
  --name transcribeops-whisper \
  -p 8000:8000 \
  -v whisper-cache:/root/.cache \
  --env-file ../.env \
  transcribeops-whisper && \
podman image prune -f
```

Bei rootful-Deployment allen Befehlen `sudo` voranstellen. Die Argumente für `podman run` / `docker run` (Env-Variablen, Port-Mapping, Volume-Namen) so anpassen, dass sie mit den Flags deines ursprünglichen Deployments übereinstimmen — siehe [Option 3 in der Haupt-README](../../README.md#-option-3--model-api-only).

---

## Nach dem Update

1. **Container-Status prüfen** und ob sie auf dem neuen Image laufen:

   ```bash
   docker compose ps          # oder: podman compose ps  (sudo bei rootful)
   ```

2. **Versionsnummer in der UI prüfen** — die Version steht in der Navbar. Wenn nach einem erfolgreichen Update noch die alte Version angezeigt wird, ist das fast immer **Browser-Cache** — Hard-Refresh mit `Strg + Shift + R` (Linux/Windows) bzw. `Cmd + Shift + R` (macOS).

3. **Logs für die erste Minute beobachten**, um Migrations- oder Startup-Fehler zu erkennen:

   ```bash
   docker compose logs -f --tail=100 web worker
   ```

---

## Rollback

Falls die neue Version Probleme macht, Datenbank-Backup wiederherstellen und auf den vorherigen Commit zurückwechseln:

```bash
cd /pfad/zu/TranscribeOps && \
git log --oneline -10            # Commit-Hash für den Rollback finden
git reset --hard <commit-hash> && \
docker compose build --pull --no-cache && \
docker compose up -d --force-recreate
```

---

## Troubleshooting

**"Already up to date", aber die neue Version läuft nicht**
`git pull` war erfolgreich, aber die Container wurden nicht recreated. `compose build` *und* `compose up -d --force-recreate` müssen beide ausgeführt werden. `up -d` allein überspringt den Rebuild möglicherweise, wenn der Image-Tag gleich bleibt.

**Update lief durch, UI zeigt aber alte Version**
Mit hoher Wahrscheinlichkeit Browser-Cache — Hard-Refresh mit `Strg + Shift + R`. Die Version wird server-seitig aus der `VERSION`-Datei beim App-Start gerendert; wenn `/app/VERSION` im Container die neue Version zeigt, ist das Deployment korrekt.

**Mit `sudo` deployt, aber Update ohne `sudo` ausgeführt**
Die Container-Engine hält rootless und rootful komplett getrennt. Du hast gerade eine andere, parallele Instanz aktualisiert. Die gleichen Befehle nochmal mit `sudo` ausführen.

**`git reset --hard` schlägt mit Merge-Konflikten fehl**
Du hast lokale Änderungen an versionierten Dateien. Vorher stashen (`git stash`) oder in einen Branch committen. Dateien in `.gitignore` (z.B. `docker-compose.yml` und `.env`) sind von `git reset` nicht betroffen.

**Speicherplatz voll während Build**
`docker image prune -af` (oder `podman image prune -af`) entfernt alle dangling und unused Images. Danach erneut versuchen.
