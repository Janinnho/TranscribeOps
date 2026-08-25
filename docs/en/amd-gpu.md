# TranscribeOps on an AMD GPU (ROCm)

This guide walks through running the Model API on an AMD graphics card, step by step. It applies from version **1.3.5** onwards.

## Table of contents

- [What runs on an AMD GPU — and what does not](#what-runs-on-an-amd-gpu--and-what-does-not)
- [Compatible cards](#compatible-cards)
- [Step 1 — Check the host](#step-1--check-the-host)
- [Step 2 — Make sure the driver is there](#step-2--make-sure-the-driver-is-there)
- [Step 3 — Create the configuration](#step-3--create-the-configuration)
- [Step 4 — Build and start](#step-4--build-and-start)
- [Step 5 — Verify](#step-5--verify)
- [Step 6 — Create a Parakeet instance](#step-6--create-a-parakeet-instance)
- [Tuning](#tuning)
- [Troubleshooting](#troubleshooting)
- [Going back to CPU or NVIDIA](#going-back-to-cpu-or-nvidia)
- [Background: why do Whisper models not run?](#background-why-do-whisper-models-not-run)

---

## What runs on an AMD GPU — and what does not

Read this first — it decides whether the effort is worth it for you.

| Component | AMD GPU? | Reason |
|---|---|---|
| **NeMo / Parakeet** (transcription) | ✅ yes | Plain PyTorch, runs through ROCm |
| **Word alignment** (wav2vec2) | ✅ yes | PyTorch |
| **Speaker diarization** (pyannote) | ✅ yes | PyTorch |
| **WhisperX / Whisper models** | ❌ no | faster-whisper runs on **CTranslate2**, which has no ROCm backend |

The Whisper models (`tiny` through `large-v3-turbo`) therefore stay on the CPU no matter what device you configure. The admin dashboard says so explicitly rather than pretending otherwise.

> **For German transcription this is barely a loss:** `parakeet-primeline` is a German-optimised Parakeet finetune at 2.95 % WER on Tuda-De and the strongest model in the catalog anyway. It runs on the GPU.

---

## Compatible cards

PyTorch ships the ROCm runtime libraries inside its wheel. You therefore do **not** need a full ROCm installation on the host — only the kernel driver and the device nodes.

| Card / series | gfx arch | `HSA_OVERRIDE_GFX_VERSION` |
|---|---|---|
| RX 7900 XT / XTX, W7900 | gfx1100 | not needed (officially supported) |
| MI series (MI210, MI250, MI300) | gfx90a / gfx942 | not needed (officially supported) |
| RX 7700 / 7800 | gfx1101 | `11.0.0` |
| RX 7600 | gfx1102 | `11.0.0` |
| Ryzen APUs (Radeon 780M, Phoenix) | gfx1103 | `11.0.0` |
| RX 6800 / 6900 | gfx1030 | usually not needed |
| RX 6700 | gfx1031 | `10.3.0` |
| RX 6600 | gfx1032 | `10.3.0` |

`HSA_OVERRIDE_GFX_VERSION` makes an unsupported card report the arch of a closely related supported one. It works well in practice but carries no guarantee from AMD.

> **Only set the variable if your card needs it.** A wrong value is worse than none — it produces crashes deep inside the kernel driver instead of a clear error message. The official compatibility list lives in the [ROCm documentation](https://rocm.docs.amd.com/projects/install-on-linux/en/latest/reference/system-requirements.html).

---

## Step 1 — Check the host

Both device nodes must exist — `/dev/kfd` is the driver's compute interface, `/dev/dri/renderD*` the render node:

```bash
ls -l /dev/kfd /dev/dri/renderD*
```

Expected output (groups may differ):

```
crw-rw---- 1 root render 234, 0 /dev/kfd
crw-rw---- 1 root render 226, 128 /dev/dri/renderD128
```

Identify the card:

```bash
lspci | grep -iE "vga|display"
```

If `/dev/kfd` is missing, the `amdgpu` kernel driver is not loaded or does not serve your card — continue with step 2.

---

## Step 2 — Make sure the driver is there

On current distributions (Ubuntu 22.04+, Debian 12+, Fedora 38+) the `amdgpu` driver is in the kernel and `/dev/kfd` already exists. You can skip this step then.

If not — or with very new cards on older kernels — install AMD's DKMS module:

```bash
sudo apt install "linux-headers-$(uname -r)" "linux-modules-extra-$(uname -r)"
```

Then download the `amdgpu-install` package for your distribution from the [AMD download page](https://www.amd.com/en/support/download/linux-drivers.html) and run:

```bash
sudo amdgpu-install --usecase=dkms
```

A reboot is required afterwards. You do **not** need `--usecase=rocm` (the full ROCm userspace, ~30 GB) — those libraries come with the container.

### Group membership (rootless only)

If you run containers **without** `sudo`, your user needs read access to the device nodes:

```bash
sudo usermod -aG video,render $USER
```

Log out and back in afterwards (or run `newgrp render`). Rootful deployments (`sudo podman` / `sudo docker`) do not need this.

---

## Step 3 — Create the configuration

In the project's `.env`:

```bash
# PyTorch wheel index for AMD. Must match the ROCm version your driver
# provides — 6.3 is a good default.
TORCH_INDEX=https://download.pytorch.org/whl/rocm6.3
```

`TORCH_INDEX` is picked up by `docker-compose.rocm.yml` automatically. `HSA_OVERRIDE_GFX_VERSION` is **not** — that line sits commented out on purpose so nobody enables it with a wrong value by accident. If your card needs an override, uncomment the line in `docker-compose.rocm.yml` and set the value from the table:

```yaml
    environment:
      - WHISPER_DEVICE=auto
      - HSA_OVERRIDE_GFX_VERSION=11.0.0
```

---

## Step 4 — Build and start

The AMD configuration ships as an **override file**. Always pass both compose files, the ROCm one second — its values then win:

### Docker Compose

```bash
docker compose -f docker-compose.yml -f docker-compose.rocm.yml up -d --build
```

### Podman Compose

```bash
podman compose -f docker-compose.yml -f docker-compose.rocm.yml up -d --build
```

Prefix with `sudo` for rootful deployments.

### Podman without Compose

If you run the Model API standalone (option 3 in the [main README](../../README.md)):

```bash
podman build --build-arg TORCH_INDEX=https://download.pytorch.org/whl/rocm6.3 -t transcribeops-whisper ./whisper-api
```

```bash
podman run -d --name transcribeops-whisper \
  --device /dev/kfd --device /dev/dri \
  --group-add keep-groups --security-opt seccomp=unconfined --ipc=host \
  -e WHISPER_DEVICE=auto -e ADMIN_PASSWORD=your-password \
  -p 8000:8000 -v transcribeops-whisper-cache:/root/.cache \
  transcribeops-whisper
```

> The build downloads roughly 3 GB of ROCm wheels and takes considerably longer than the CPU build. Budget 10–20 minutes.

---

## Step 5 — Verify

Three checkpoints, fastest first.

### 1. Container log

```bash
docker compose logs whisper | grep "Detected compute hardware"
```

Expected:

```
INFO:whisper-api:Detected compute hardware: AMD Radeon RX 7900 XTX · 24.0 GB · ROCm 6.3.42133 (WHISPER_DEVICE=auto)
```

If it says `CPU`, the card is not being detected — see [Troubleshooting](#troubleshooting).

### 2. Admin dashboard

Open `http://<host>:8000/admin` and look at the **System (main process)** block:

- **Detected hardware** — green dot with card name, VRAM and ROCm version
- **Device** — the device the engine is **actually** running on (if it says `cpu` next to `configured: auto`, detection found nothing)
- A note explains that Whisper models stay on the CPU despite the detected GPU

### 3. Health endpoint

```bash
curl -s http://localhost:8000/health
```

The fields `requested_device`, `device` and `device_note` show the requested device, the actual device, and the reason for a CPU fallback if there was one.

---

## Step 6 — Create a Parakeet instance

This is where the payoff arrives. The main engine defaults to WhisperX and is therefore CPU-bound — for the GPU you create a NeMo instance.

1. In the admin UI go to **Models** and download **Parakeet Primeline (German)** (~2.5 GB). For English, pick **Parakeet TDT 0.6B v3** instead.
2. Switch to **Instances** and create a new one:
   - **Name:** e.g. `parakeet` — this name doubles as the API's `model` parameter
   - **Engine:** NeMo (Parakeet)
   - **Model:** the one you just downloaded
   - **Device:** `Automatic` (the arrow shows what was detected)
3. Once started, the table's device column shows `cuda`. If it shows `cuda` with a red **CPU fallback** pill, loading onto the GPU failed — the tooltip names the reason.
4. In the web app under **Admin → Speech models**, add a model pointing at `http://<host>:8000/v1/audio/transcriptions` with `model_id` = `parakeet`.

---

## Tuning

**VRAM instead of RAM.** Parakeet's encoder scales quadratically with audio length, so the engine slices long recordings. On a GPU this caps VRAM usage. The default is 300 seconds; lower it when memory is tight:

```bash
NEMO_CHUNK_SECS=180
```

For reference (measured on CPU, 900 s of speech): 300 s slices → 7.6 GB peak, 450 s → 11.5 GB, unsliced → 32.6 GB.

**Ignore compute type.** `WHISPER_COMPUTE_TYPE` (`int8`, `float16`, …) is a CTranslate2-only parameter. The NeMo engine never reads it — the value has no effect on Parakeet whatsoever.

**Idle unload.** Each instance can unload its model after an idle period. On a GPU with little VRAM this pays off when several models are configured in parallel.

---

## Troubleshooting

| Symptom | Cause and fix |
|---|---|
| Log says `Detected compute hardware: CPU` | Device nodes missing inside the container. Check that `docker-compose.rocm.yml` was actually passed with `-f`. |
| `Hardware probe reported: GPU probe failed: …` | ROCm sees the card but cannot initialise it — usually an unsupported gfx arch. Set `HSA_OVERRIDE_GFX_VERSION` per the table. |
| `hipErrorNoBinaryForGpu` | The override is missing or wrong. Determine the arch with `rocminfo \| grep gfx` if ROCm is installed on the host. |
| Instance shows a red **CPU fallback** | Read the tooltip. For a NeMo instance it carries PyTorch's original error message. |
| Whisper instance stays on CPU | Expected behaviour, not a bug — see [Background](#background-why-do-whisper-models-not-run). |
| `Permission denied` on `/dev/kfd` (rootless) | User is not in the `render` group. Complete step 2 and log in again. |
| Build fails with "No matching distribution" | The ROCm version in `TORCH_INDEX` does not (or no longer) exist. Check the available indexes on [pytorch.org](https://pytorch.org/get-started/locally/). |
| Out of memory on the GPU | Lower `NEMO_CHUNK_SECS`, see [Tuning](#tuning). |

---

## Going back to CPU or NVIDIA

The ROCm path is entirely opt-in. To roll back, leave out the override file and rebuild without `TORCH_INDEX`:

```bash
docker compose build --no-cache whisper && docker compose up -d
```

With `TORCH_INDEX` unset, the build installs exactly the PyTorch build TranscribeOps has always used. Existing CPU and NVIDIA installations are therefore unaffected by this feature — including after an update.

---

## Background: why do Whisper models not run?

WhisperX uses **faster-whisper** internally, which builds on **CTranslate2** — a dedicated inference engine with backends for CPU and CUDA. No HIP/ROCm backend exists there.

What makes this trickier is that PyTorch addresses AMD cards through the **CUDA API**: on a ROCm machine `torch.cuda.is_available()` returns `True` and the device string is `cuda`. A naively written program therefore mistakes the AMD card for an NVIDIA one and hands `cuda` to CTranslate2, which then fails.

TranscribeOps therefore checks separately whether CTranslate2 can address a GPU at all (`ctranslate2.get_cuda_device_count()`). If the answer is no while PyTorch reports a GPU, **only transcription** falls back to the CPU — alignment and diarization are plain PyTorch and keep the GPU. The reason is passed through to `/health` and into the admin UI.

If you absolutely need Whisper models on an AMD card, a different engine is unavoidable (whisper.cpp with the Vulkan backend, or Whisper via `transformers`). Neither is currently part of TranscribeOps.
