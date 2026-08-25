# TranscribeOps auf einer AMD-GPU (ROCm)

Diese Anleitung beschreibt Schritt für Schritt, wie du die Modell-API auf einer AMD-Grafikkarte betreibst. Sie gilt ab Version **1.3.5**.

## Inhaltsverzeichnis

- [Was auf einer AMD-GPU läuft — und was nicht](#was-auf-einer-amd-gpu-läuft--und-was-nicht)
- [Kompatible Karten](#kompatible-karten)
- [Schritt 1 — Host prüfen](#schritt-1--host-prüfen)
- [Schritt 2 — Treiber sicherstellen](#schritt-2--treiber-sicherstellen)
- [Schritt 3 — Konfiguration anlegen](#schritt-3--konfiguration-anlegen)
- [Schritt 4 — Bauen und starten](#schritt-4--bauen-und-starten)
- [Schritt 5 — Überprüfen](#schritt-5--überprüfen)
- [Schritt 6 — Parakeet-Instanz anlegen](#schritt-6--parakeet-instanz-anlegen)
- [Tuning](#tuning)
- [Fehlerbehebung](#fehlerbehebung)
- [Zurück auf CPU oder NVIDIA](#zurück-auf-cpu-oder-nvidia)
- [Hintergrund: Warum laufen Whisper-Modelle nicht?](#hintergrund-warum-laufen-whisper-modelle-nicht)

---

## Was auf einer AMD-GPU läuft — und was nicht

Lies das zuerst — es entscheidet, ob sich der Aufwand für dich lohnt.

| Komponente | AMD-GPU? | Begründung |
|---|---|---|
| **NeMo / Parakeet** (Transkription) | ✅ ja | Reines PyTorch, läuft über ROCm |
| **Word-Alignment** (wav2vec2) | ✅ ja | PyTorch |
| **Sprechererkennung** (pyannote) | ✅ ja | PyTorch |
| **WhisperX / Whisper-Modelle** | ❌ nein | faster-whisper nutzt **CTranslate2**, das kein ROCm-Backend besitzt |

Die Whisper-Modelle (`tiny` bis `large-v3-turbo`) bleiben also auf der CPU — unabhängig davon, was du als Gerät einstellst. Das Admin-Dashboard weist explizit darauf hin, statt so zu tun, als liefe es.

> **Für deutsche Transkription ist das kaum ein Verlust:** `parakeet-primeline` ist ein deutsch-optimiertes Parakeet-Finetune mit 2,95 % WER auf Tuda-De und damit ohnehin das stärkste Modell im Katalog. Es läuft auf der GPU.

---

## Kompatible Karten

PyTorch bringt die ROCm-Laufzeitbibliotheken im Wheel mit. Auf dem Host brauchst du deshalb **keine vollständige ROCm-Installation**, sondern nur den Kernel-Treiber und die Gerätedateien.

| Karte / Serie | gfx-Arch | `HSA_OVERRIDE_GFX_VERSION` |
|---|---|---|
| RX 7900 XT / XTX, W7900 | gfx1100 | nicht nötig (offiziell unterstützt) |
| MI-Serie (MI210, MI250, MI300) | gfx90a / gfx942 | nicht nötig (offiziell unterstützt) |
| RX 7700 / 7800 | gfx1101 | `11.0.0` |
| RX 7600 | gfx1102 | `11.0.0` |
| Ryzen-APUs (Radeon 780M, Phoenix) | gfx1103 | `11.0.0` |
| RX 6800 / 6900 | gfx1030 | meist nicht nötig |
| RX 6700 | gfx1031 | `10.3.0` |
| RX 6600 | gfx1032 | `10.3.0` |

`HSA_OVERRIDE_GFX_VERSION` gibt einer nicht offiziell unterstützten Karte die Arch-Kennung einer verwandten, unterstützten aus. Das funktioniert in der Praxis gut, ist aber von AMD nicht zugesichert.

> **Setze die Variable nur, wenn deine Karte sie braucht.** Ein falscher Wert ist schlimmer als gar keiner — er führt zu Abstürzen tief im Kernel-Treiber statt zu einer klaren Fehlermeldung. Die offizielle Kompatibilitätsliste steht in der [ROCm-Dokumentation](https://rocm.docs.amd.com/projects/install-on-linux/en/latest/reference/system-requirements.html).

---

## Schritt 1 — Host prüfen

Die beiden Gerätedateien müssen existieren — `/dev/kfd` ist die Compute-Schnittstelle des Treibers, `/dev/dri/renderD*` der Render-Node:

```bash
ls -l /dev/kfd /dev/dri/renderD*
```

Erwartete Ausgabe (Gruppen können abweichen):

```
crw-rw---- 1 root render 234, 0 /dev/kfd
crw-rw---- 1 root render 226, 128 /dev/dri/renderD128
```

Die Karte identifizieren:

```bash
lspci | grep -iE "vga|display"
```

Fehlt `/dev/kfd`, ist der `amdgpu`-Kerneltreiber nicht geladen oder deine Karte wird von ihm nicht bedient — weiter mit Schritt 2.

---

## Schritt 2 — Treiber sicherstellen

Bei aktuellen Distributionen (Ubuntu 22.04+, Debian 12+, Fedora 38+) ist der `amdgpu`-Treiber im Kernel enthalten und `/dev/kfd` existiert bereits. Dann kannst du diesen Schritt überspringen.

Falls nicht — oder bei sehr neuen Karten auf älteren Kerneln — installierst du das DKMS-Modul von AMD:

```bash
sudo apt install "linux-headers-$(uname -r)" "linux-modules-extra-$(uname -r)"
```

Danach das `amdgpu-install`-Paket für deine Distribution von der [AMD-Downloadseite](https://www.amd.com/en/support/download/linux-drivers.html) laden und ausführen:

```bash
sudo amdgpu-install --usecase=dkms
```

Ein Neustart ist danach nötig. `--usecase=rocm` (die vollständige ROCm-Userspace-Installation, ~30 GB) brauchst du **nicht** — die Bibliotheken kommen im Container mit.

### Gruppenzugehörigkeit (nur rootless)

Wenn du Container **ohne** `sudo` betreibst, muss dein Benutzer die Gerätedateien lesen dürfen:

```bash
sudo usermod -aG video,render $USER
```

Danach neu anmelden (oder `newgrp render`). Bei rootful-Deployment (`sudo podman` / `sudo docker`) entfällt das.

---

## Schritt 3 — Konfiguration anlegen

In der `.env` im Projektverzeichnis:

```bash
# PyTorch-Wheel-Index für AMD. Muss zur ROCm-Version passen, die dein
# Treiber bereitstellt — 6.3 ist ein guter Standard.
TORCH_INDEX=https://download.pytorch.org/whl/rocm6.3
```

`TORCH_INDEX` wird von `docker-compose.rocm.yml` automatisch übernommen. `HSA_OVERRIDE_GFX_VERSION` dagegen **nicht** — die Zeile liegt dort bewusst auskommentiert, damit sie niemand versehentlich mit einem falschen Wert aktiviert. Braucht deine Karte einen Override, entferne in `docker-compose.rocm.yml` das Kommentarzeichen und trage den Wert aus der Tabelle ein:

```yaml
    environment:
      - WHISPER_DEVICE=auto
      - HSA_OVERRIDE_GFX_VERSION=11.0.0
```

---

## Schritt 4 — Bauen und starten

Die AMD-Konfiguration liegt als **Override-Datei** vor. Du übergibst immer beide Compose-Dateien, die ROCm-Datei als zweite — dann gewinnen deren Werte:

### Docker Compose

```bash
docker compose -f docker-compose.yml -f docker-compose.rocm.yml up -d --build
```

### Podman Compose

```bash
podman compose -f docker-compose.yml -f docker-compose.rocm.yml up -d --build
```

Bei rootful-Deployment `sudo` voranstellen.

### Podman ohne Compose

Wenn du die Modell-API einzeln betreibst (Option 3 der [Haupt-README](../../README.md)):

```bash
podman build --build-arg TORCH_INDEX=https://download.pytorch.org/whl/rocm6.3 -t transcribeops-whisper ./whisper-api
```

```bash
podman run -d --name transcribeops-whisper \
  --device /dev/kfd --device /dev/dri \
  --group-add keep-groups --security-opt seccomp=unconfined --ipc=host \
  -e WHISPER_DEVICE=auto -e ADMIN_PASSWORD=dein-passwort \
  -p 8000:8000 -v transcribeops-whisper-cache:/root/.cache \
  transcribeops-whisper
```

> Der Build lädt rund 3 GB ROCm-Wheels und dauert deutlich länger als der CPU-Build. Plane 10–20 Minuten ein.

---

## Schritt 5 — Überprüfen

Drei Kontrollpunkte, vom schnellsten zum aussagekräftigsten.

### 1. Container-Log

```bash
docker compose logs whisper | grep "Detected compute hardware"
```

Erwartet:

```
INFO:whisper-api:Detected compute hardware: AMD Radeon RX 7900 XTX · 24.0 GB · ROCm 6.3.42133 (WHISPER_DEVICE=auto)
```

Steht dort `CPU`, wird die Karte nicht erkannt — weiter bei [Fehlerbehebung](#fehlerbehebung).

### 2. Admin-Dashboard

Öffne `http://<host>:8000/admin` und sieh im Block **System (Hauptprozess)** nach:

- **Erkannte Hardware** — grüner Punkt mit Kartenname, VRAM und ROCm-Version
- **Gerät** — das Gerät, auf dem die Engine **tatsächlich** läuft (steht dort `cpu` bei `konfiguriert: auto`, hat die Erkennung nichts gefunden)
- Ein Hinweisblock erklärt, dass Whisper-Modelle trotz erkannter GPU auf der CPU bleiben

### 3. Health-Endpunkt

```bash
curl -s http://localhost:8000/health
```

Die Felder `requested_device`, `device` und `device_note` zeigen angefordertes Gerät, tatsächliches Gerät und gegebenenfalls den Grund für einen Rückfall auf die CPU.

---

## Schritt 6 — Parakeet-Instanz anlegen

Erst jetzt kommt der eigentliche Nutzen. Die Main-Engine ist standardmäßig WhisperX und damit CPU-gebunden — für die GPU legst du eine NeMo-Instanz an.

1. Im Admin-UI auf **Modelle** gehen und **Parakeet Primeline (Deutsch)** herunterladen (~2,5 GB). Für Englisch stattdessen **Parakeet TDT 0.6B v3**.
2. Auf **Instanzen** wechseln und eine neue anlegen:
   - **Name:** z.B. `parakeet` — dieser Name ist gleichzeitig der `model`-Parameter der API
   - **Engine:** NeMo (Parakeet)
   - **Modell:** das eben geladene
   - **Gerät:** `Automatisch` (zeigt hinter dem Pfeil an, was erkannt wurde)
3. Nach dem Start zeigt die Device-Spalte der Tabelle `cuda` an. Steht dort `cuda` mit rotem **CPU-Fallback**-Pill, hat das Laden auf der GPU nicht geklappt — der Tooltip nennt den Grund.
4. In der Web-App unter **Admin → Sprachmodelle** ein Modell anlegen, das auf `http://<host>:8000/v1/audio/transcriptions` zeigt, mit `model_id` = `parakeet`.

---

## Tuning

**VRAM statt RAM.** Parakeets Encoder skaliert quadratisch mit der Audiolänge, deshalb schneidet die Engine lange Aufnahmen in Stücke. Auf der GPU begrenzt das den VRAM-Bedarf. Standard sind 300 Sekunden; bei knappem Speicher verkleinern:

```bash
NEMO_CHUNK_SECS=180
```

Als Anhaltspunkt (auf CPU gemessen, 900 s Sprache): 300-s-Stücke → 7,6 GB Spitze, 450 s → 11,5 GB, ungeschnitten → 32,6 GB.

**Compute-Typ ignorieren.** `WHISPER_COMPUTE_TYPE` (`int8`, `float16`, …) ist ein reiner CTranslate2-Parameter. Die NeMo-Engine liest ihn nicht aus — der Wert hat für Parakeet keinerlei Wirkung.

**RAM-Freigabe.** Pro Instanz lässt sich einstellen, dass ein Modell nach einer Leerlaufzeit entladen wird. Auf einer GPU mit wenig VRAM lohnt sich das, wenn mehrere Modelle parallel konfiguriert sind.

---

## Fehlerbehebung

| Symptom | Ursache und Abhilfe |
|---|---|
| Log sagt `Detected compute hardware: CPU` | Gerätedateien fehlen im Container. Prüfen, ob `docker-compose.rocm.yml` wirklich mit `-f` übergeben wurde. |
| `Hardware probe reported: GPU probe failed: …` | ROCm sieht die Karte, kann sie aber nicht initialisieren — meist eine nicht unterstützte gfx-Arch. `HSA_OVERRIDE_GFX_VERSION` gemäß Tabelle setzen. |
| `hipErrorNoBinaryForGpu` | Der Override fehlt oder ist falsch. Arch mit `rocminfo \| grep gfx` ermitteln, falls ROCm auf dem Host installiert ist. |
| Instanz zeigt rotes **CPU-Fallback** | Tooltip lesen. Bei einer NeMo-Instanz nennt er die Original-Fehlermeldung von PyTorch. |
| Whisper-Instanz bleibt auf CPU | Erwartetes Verhalten, kein Fehler — siehe [Hintergrund](#hintergrund-warum-laufen-whisper-modelle-nicht). |
| `Permission denied` auf `/dev/kfd` (rootless) | Benutzer nicht in der Gruppe `render`. Schritt 2 nachholen und neu anmelden. |
| Build bricht mit „No matching distribution" ab | Die ROCm-Version im `TORCH_INDEX` gibt es nicht (mehr). Verfügbare Indizes auf [pytorch.org](https://pytorch.org/get-started/locally/) prüfen. |
| Out-of-Memory auf der GPU | `NEMO_CHUNK_SECS` verkleinern, siehe [Tuning](#tuning). |

---

## Zurück auf CPU oder NVIDIA

Der ROCm-Weg ist vollständig opt-in. Zum Zurückrollen genügt es, die Override-Datei wegzulassen und ohne `TORCH_INDEX` neu zu bauen:

```bash
docker compose build --no-cache whisper && docker compose up -d
```

Ohne gesetztes `TORCH_INDEX` installiert der Build exakt den PyTorch-Build, den TranscribeOps immer verwendet hat. Bestehende CPU- und NVIDIA-Installationen sind von dieser Funktion also nicht betroffen — auch nicht nach einem Update.

---

## Hintergrund: Warum laufen Whisper-Modelle nicht?

WhisperX nutzt intern **faster-whisper**, und das setzt auf **CTranslate2** — eine eigene Inferenz-Engine mit Backends für CPU und CUDA. Ein HIP/ROCm-Backend existiert dort nicht.

Erschwerend kommt hinzu, dass PyTorch AMD-Karten über die **CUDA-API** anspricht: `torch.cuda.is_available()` liefert auf einer ROCm-Maschine `True`, und der Gerätestring lautet `cuda`. Ein naiv geschriebenes Programm hält die AMD-Karte damit für eine NVIDIA-Karte und reicht `cuda` an CTranslate2 weiter, das daran scheitert.

TranscribeOps prüft deshalb getrennt, ob CTranslate2 überhaupt eine GPU ansprechen kann (`ctranslate2.get_cuda_device_count()`). Fällt die Antwort negativ aus, während PyTorch eine GPU meldet, läuft **nur die Transkription** auf der CPU — Alignment und Sprechererkennung sind reines PyTorch und behalten die GPU. Der Grund wird als Notiz an `/health` und ins Admin-UI durchgereicht.

Wer Whisper-Modelle zwingend auf einer AMD-Karte braucht, kommt an einer anderen Engine nicht vorbei (whisper.cpp mit Vulkan-Backend oder Whisper über `transformers`). Beides ist derzeit nicht Teil von TranscribeOps.
