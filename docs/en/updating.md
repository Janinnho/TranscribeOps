# Updating TranscribeOps

This guide covers updating an existing TranscribeOps deployment to the latest version from GitHub. Your local configuration (`docker-compose.yml`, `.env`) and named volumes (database, uploads, model cache) are preserved.

Database migrations run automatically on app start (`_apply_migrations()` in `app/__init__.py`) — no manual schema steps required.

---

## Before You Update

1. **Note your deployment mode** — rootless (no `sudo`) or rootful (with `sudo`). The container engine keeps **completely separate** storage for both modes; running the update without `sudo` when you deployed with `sudo` will update a different instance and leave your production untouched.
2. **Back up the database** (recommended):

   ```bash
   # Rootless
   docker run --rm -v transcribeops-db:/data -v "$(pwd)":/backup \
     alpine tar czf /backup/db-backup-$(date +%Y%m%d).tar.gz /data

   # Rootful — prepend sudo
   sudo docker run --rm -v transcribeops-db:/data -v "$(pwd)":/backup \
     alpine tar czf /backup/db-backup-$(date +%Y%m%d).tar.gz /data
   ```

   Replace `docker` with `podman` if you use Podman.
3. **Check disk space** — a full rebuild with `--no-cache` can temporarily need 5–10 GB extra.

---

## Variant 1 — Full Stack (Compose)

This covers Option 1 and Option 2 from the [main README](../../README.md#-deployment-options): the web app together with worker, Redis, and optionally Whisper, all started via `docker compose` / `podman compose`.

### Docker (rootless)

```bash
cd /path/to/TranscribeOps && \
git fetch origin && \
git reset --hard origin/main && \
docker compose build --pull --no-cache && \
docker compose up -d --force-recreate && \
docker image prune -f
```

### Docker (rootful)

```bash
cd /path/to/TranscribeOps && \
sudo git fetch origin && \
sudo git reset --hard origin/main && \
sudo docker compose build --pull --no-cache && \
sudo docker compose up -d --force-recreate && \
sudo docker image prune -f
```

### Podman (rootless)

```bash
cd /path/to/TranscribeOps && \
git fetch origin && \
git reset --hard origin/main && \
podman compose build --pull --no-cache && \
podman compose up -d --force-recreate && \
podman image prune -f
```

### Podman (rootful)

```bash
cd /path/to/TranscribeOps && \
sudo git fetch origin && \
sudo git reset --hard origin/main && \
sudo podman compose build --pull --no-cache && \
sudo podman compose up -d --force-recreate && \
sudo podman image prune -f
```

### What each step does

1. `git fetch origin` — downloads the latest commits from GitHub.
2. `git reset --hard origin/main` — moves the working copy to the latest commit. `docker-compose.yml` and `.env` are gitignored, so they are not touched. **Local edits to tracked source files are discarded** — commit them to a fork or branch first if you have customizations.
3. `compose build --pull --no-cache` — rebuilds all images from scratch and pulls newer base images.
4. `compose up -d --force-recreate` — recreates containers with the new images even if Compose thinks nothing changed.
5. `image prune -f` — frees disk space by removing the now-unused old images.

---

## Variant 2 — Standalone Whisper API only

For Option 3 (the standalone Model API, started with `docker run` / `podman run` without Compose):

### Docker

```bash
cd /path/to/TranscribeOps/whisper-api && \
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
cd /path/to/TranscribeOps/whisper-api && \
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

Prepend `sudo` to all commands if you deployed in rootful mode. Adjust the `podman run` / `docker run` arguments (env vars, port mapping, volume names) to match the flags you used for your original deployment — see [Option 3 in the main README](../../README.md#-option-3--model-api-only) for reference.

---

## After the Update

1. **Verify all containers are running** and on the new image:

   ```bash
   docker compose ps          # or: podman compose ps  (add sudo if rootful)
   ```

2. **Check the version in the UI** — the version number is shown in the navbar header. If you still see the old version after a successful update, it is almost always **browser cache** — do a hard refresh (`Ctrl + Shift + R` on Linux/Windows, `Cmd + Shift + R` on macOS).

3. **Tail the logs** for the first minute to catch migration errors or startup issues:

   ```bash
   docker compose logs -f --tail=100 web worker
   ```

---

## Rolling Back

If the new version misbehaves, restore the database backup and check out the previous commit:

```bash
cd /path/to/TranscribeOps && \
git log --oneline -10            # find the commit hash you want to return to
git reset --hard <commit-hash> && \
docker compose build --pull --no-cache && \
docker compose up -d --force-recreate
```

---

## Troubleshooting

**"Already up to date" but the new version isn't running**
`git pull` succeeded but the containers were not recreated. Make sure you ran `compose build` *and* `compose up -d --force-recreate`. `up -d` alone may skip the rebuild if the image tag is unchanged.

**Update ran but the UI still shows the old version**
Almost certainly browser cache — hard refresh with `Ctrl + Shift + R`. The version is rendered server-side from the `VERSION` file at app startup; if `/app/VERSION` inside the container shows the new version, the deployment is correct.

**You deployed with `sudo` but ran the update without**
The container engine keeps rootless and rootful storage separate. You just updated a different, parallel instance. Run the same commands again with `sudo`.

**`git reset --hard` fails with merge conflicts**
You have local changes to tracked files. Stash them first (`git stash`) or commit them to a branch. Files in `.gitignore` (such as `docker-compose.yml` and `.env`) are not affected by `git reset`.

**Disk full during build**
Run `docker image prune -af` (or `podman image prune -af`) to remove all dangling and unused images, then retry.
