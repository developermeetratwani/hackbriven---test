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
scripts (Phase 7) are not part of this pass.

## Requirements

- Python 3.11+
- `ffmpeg` and `ffprobe` on `PATH` (system install, not pip) — required for the
  composition and validation stages; not required to run the unit test suite,
  which mocks the subprocess boundary.
- API keys for at least one story-engine provider (Gemini or Groq) and one
  image provider (NVIDIA, or rely on the keyless Pollinations fallback) to run
  the pipeline against live services.

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

## Pipeline stages

```
INPUT → INTELLIGENCE (Gemini→Groq) → GENERATION (images/voice/captions,
each with fallbacks) → COMPOSITION (ffmpeg Ken Burns + captions + ducking)
→ VALIDATION (ffprobe quality gate) → OUTPUT (publish-ready MP4)
```
