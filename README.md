# Nova Clip

Nova Clip is a modular AI video studio for generating clips, arranging and trimming a multi-clip sequence, and exporting a normalized master with hard-cut or crossfade transitions.

## What is implemented

- Next.js App Router studio with a responsive source monitor, drag-and-drop timeline, clip uploads, trimming, queue telemetry, and master downloads.
- FastAPI + Pydantic v2 API with async SQLAlchemy persistence and strict request validation.
- Celery queues for isolated GPU generation and media export, backed by Redis.
- WebSocket job telemetry with cached last-known state, heartbeats, step/speed/ETA reporting, and terminal events.
- Ollama prompt expansion and Wan 2.1 T2V 14B inference with FP8 transformer storage, BF16 compute, group offloading, VAE slicing/tiling, a distributed Redis GPU mutex, worker concurrency `1`, and CUDA cache cleanup in every success/failure path.
- FFmpeg probing, trim validation, aspect-preserving scale/pad, FPS/audio/pixel-format normalization, NVENC auto-detection, concat-demuxer hard cuts, and filter-complex A/V crossfades.

## Run on an NVIDIA host

Prerequisites are Docker Engine, Docker Compose v2, a current NVIDIA driver, NVIDIA Container Toolkit, and OpenSSL. The included Nginx gateway redirects HTTP to HTTPS and protects the UI, API, media, API docs, and WebSocket upgrades with HTTP Basic authentication. Backend and frontend container ports are private.

```bash
cp .env.example .env
# Set a strong POSTGRES_PASSWORD and the public browser-visible gateway URL.
# For a remote host, also set CORS_ORIGINS to a JSON array containing that URL.

# Create an IP-address development certificate. Replace it with a public-CA
# certificate for a domain-backed production deployment.
PUBLIC_HOST=203.0.113.10
mkdir -p tls
openssl req -x509 -nodes -days 365 -newkey rsa:4096 \
  -keyout tls/nova-clip.key -out tls/nova-clip.crt \
  -subj "/CN=${PUBLIC_HOST}" -addext "subjectAltName=IP:${PUBLIC_HOST}"
chmod 600 tls/nova-clip.key

# Replace novaadmin if desired. OpenSSL prompts without storing plaintext.
printf 'novaadmin:%s\n' "$(openssl passwd -apr1)" > .htpasswd
chmod 600 .htpasswd
# The stock Nginx image uses numeric UID/GID 101 for its workers.
sudo chown 101:101 .htpasswd

docker compose up --build -d
docker compose logs -f api gpu-worker media-worker
```

Open `https://<host>` and enter the gateway credentials. A self-signed IP certificate produces a browser trust warning until it is replaced by a public-CA certificate. The first generation downloads the configured Hugging Face model into the persistent `model-cache` volume. If the model is gated, add `HF_TOKEN` to the shared backend environment.

To rotate the login, recreate `.htpasswd`, restore ownership/mode, and run `docker compose restart gateway`. For trusted HTTPS, point a domain at the host, install its public-CA certificate in `tls/`, and set `NEXT_PUBLIC_API_URL` and `CORS_ORIGINS` to the resulting `https://` origin.

For an L4 with 24 GB VRAM, the default is `Wan-AI/Wan2.1-T2V-14B-Diffusers` with the Comfy-Org FP8 E4M3FN transformer, BF16 compute, leaf-level group offloading, a float32 tiled VAE, and one-process GPU queue. Prompt expansion asks Ollama to unload Qwen immediately after each response so Wan receives the full GPU. The cached components consume roughly 35 GB. A full 81-frame 720p denoising step measured about four minutes on the deployed L4, so the 10/20/30-step tiers prioritize quality over speed and the GPU lock allows up to six hours.

To exercise the UI and media pipeline without loading a diffusion model:

```bash
GENERATION_BACKEND=mock docker compose up --build
```

## Development

Backend (Python 3.11+ and FFmpeg required):

```bash
cd backend
python -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
GENERATION_BACKEND=mock LLM_PROVIDER=disabled uvicorn app.main:app --reload
pytest
```

Frontend:

```bash
cd frontend
npm install
npm run dev
npm run typecheck
npm run build
```

API documentation is at `http://localhost/docs` through the authenticated gateway. Generated media is stored under `/media/projects/<project-id>`. In production, enable TLS so browser WebSockets use `wss`.

## Operational notes

- The Redis mutex prevents overlapping generation even if more GPU workers are accidentally started. Celery late acknowledgements allow an interrupted render to be redelivered.
- Job, clip, and project failures are persisted with bounded diagnostics. Failed generation always releases the Redis lock and runs `torch.cuda.empty_cache()` plus IPC cleanup.
- Media URLs are emitted only for paths inside `MEDIA_ROOT`; uploaded filenames never become filesystem paths.
- For multiple API replicas, add Alembic migrations before evolving the schema.

