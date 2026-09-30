# From Idea to Feed

An AI-powered content production pipeline for the Qoneqt Global Feed.
One topic in. A checked, publish-ready vertical video out. Repeatable.

See [`PRD.md`](PRD.md) for the product requirements and phased build plan,
[`TECH.md`](TECH.md) for architecture/stack details, and [`RULES.md`](RULES.md)
for the engineering rules this codebase follows.

## Status

Backend (PRD Phases 0–5) is implemented: Intelligence (script + scene planning),
Generation (images, voice, captions, each with provider fallback chains),
Composition (ffmpeg/Pillow), Validation (ffprobe quality gate), and a thin
FastAPI job-orchestration API. The Gradio frontend (Phase 6) and deployment
scaffolding (Phase 7: Dockerfile, CI, HF Space config) are also in place.

**Verified live end to end, not just mocked**: script generation
(Gemini → Groq → OpenRouter → local template, in that order — all four
providers live-tested, including a real Gemini 503 falling through
correctly), images (NVIDIA-hosted FLUX.1-dev → Pollinations → local
placeholder, all three live-tested), voice (`edge-tts`, keyless),
captions (`faster-whisper`, keyless — CPU, word-level timestamps), and
composition/validation (`ffmpeg`/`ffprobe`, via the `static-ffmpeg` pip
fallback — no admin rights needed). A full real run (`pipeline.run`, the
actual code path) reached `DONE` with the quality gate passing. Still
pending from you: a `FAL_API_KEY` motion-stage integration (not built
yet, optional — Ken Burns is the default and works).

## Requirements

- Python 3.11+
- `ffmpeg`/`ffprobe` — needed for the composition and validation stages (not
  for the unit test suite, which mocks the subprocess boundary). **No admin
  rights needed**: `pip install -r requirements.txt` pulls in `static-ffmpeg`,
  which `backend/utils/ffmpeg_utils.py` uses automatically as a fallback —
  it downloads a static `ffmpeg`/`ffprobe` build into a user-writable cache
  the first time either binary isn't found on `PATH`. A system install
  (`choco install ffmpeg` from an *elevated* shell, `brew install ffmpeg`,
  `apt-get install ffmpeg`) is only needed if you specifically want the
  system binaries instead.
- No API keys are required to boot the pipeline — every stage has a keyless
  fallback (local template script, Pollinations images, edge-tts voice).
  Add `GEMINI_API_KEY` / `GROQ_API_KEY` / `NVIDIA_API_KEY` / `FAL_API_KEY` to
  `.env` whenever you have them to use the higher-quality primary providers
  instead.
- Captions use `faster-whisper` (already in `requirements.txt`) — CPU-only,
  no API key, downloads its model weights on first use via `huggingface_hub`
  (resumable, unlike `openai-whisper`'s downloader, which this project
  doesn't use for exactly that reason — see `TECH.md` §7).

## Run the frontend (Gradio)

```bash
uvicorn backend.api.main:app --reload &   # backend on :8000
python frontend/app.py                    # Gradio UI, polls the backend
```

Or bundle both into one process (no Docker needed) the way a Hugging Face
Space's Gradio SDK runs it — see [`deploy/huggingface/README.md`](deploy/huggingface/README.md):

```bash
python app.py
```

Docker is optional, not required — it's one deployment path among several
(see the deploy doc above for the Docker-free HF Space / plain-VM options).

## Setup

```bash
pip install -r requirements.txt
cp .env.example .env
# fill in GEMINI_API_KEY / GROQ_API_KEY / NVIDIA_API_KEY as available
```

## Run the API

```bash
uvicorn backend.api.main:app --reload
```

- `POST /jobs {"topic": "..."}` — create a job, pipeline runs in the background
- `GET /jobs/{id}` — poll status/progress
- `GET /jobs/{id}/result` — get the final video path once `status == "done"`
- `GET /health` — liveness check

## Tests

```bash
pytest
```

All unit tests run offline: every provider call (Gemini, Groq, NVIDIA,
Pollinations, edge-tts, Whisper) and every `ffmpeg`/`ffprobe` subprocess call is
mocked at the boundary, per [`RULES.md`](RULES.md) §6. No API keys or network
access are required to run the suite.

An opt-in live integration test (`tests/test_integration_live.py`) runs the
whole pipeline for real — local-template script, real Pollinations image, real
edge-tts voice, real Whisper (if installed), real `ffmpeg`/`ffprobe` — with
zero API keys. It's excluded by default (`pytest.ini`); run it explicitly:

```bash
pytest -m integration
```

It auto-skips if `ffmpeg`/`ffprobe` aren't on `PATH`.

## Pipeline stages

```
INPUT → INTELLIGENCE (Gemini→Groq) → GENERATION (images/voice/captions,
each with fallbacks) → COMPOSITION (ffmpeg Ken Burns + captions + ducking)
→ VALIDATION (ffprobe quality gate) → OUTPUT (publish-ready MP4)
```
