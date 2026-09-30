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

**Working right now with zero API keys** (verified live, not just mocked):
the Intelligence stage falls back to a deterministic local template when no
LLM key is configured, images fall back to the keyless Pollinations API, and
voice uses `edge-tts` (no key ever required). Only the NVIDIA/Gemini/Groq
*primary* providers and the Whisper caption stage (needs `openai-whisper` +
`torch`, not installed by default — heavy, keyless but large) are still
pending your keys / an explicit install. `ffmpeg`/`ffprobe` are also not
installed on this machine — see **Requirements** below — so composition and
the quality gate are implemented and unit-tested but not yet exercised live
here.

## Requirements

- Python 3.11+
- `ffmpeg` and `ffprobe` on `PATH` (system install, not pip) — required for the
  composition and validation stages; not required to run the unit test suite,
  which mocks the subprocess boundary. Install with `choco install ffmpeg`
  (Windows, needs an elevated/admin shell), `brew install ffmpeg` (macOS), or
  `apt-get install ffmpeg` (Debian/Ubuntu — this is also what the `Dockerfile`
  does automatically).
- No API keys are required to boot the pipeline — every stage has a keyless
  fallback (local template script, Pollinations images, edge-tts voice).
  Add `GEMINI_API_KEY` / `GROQ_API_KEY` / `NVIDIA_API_KEY` / `FAL_API_KEY` to
  `.env` whenever you have them to use the higher-quality primary providers
  instead.
- `pip install openai-whisper torch` for real captions — large download, not
  in the default install path above; the caption stage will otherwise be the
  one piece needing that explicit opt-in.

## Run the frontend (Gradio)

```bash
uvicorn backend.api.main:app --reload &   # backend on :8000
python frontend/app.py                    # Gradio UI, polls the backend
```

Or bundle both into one process the way a Hugging Face Space runs it:

```bash
python app.py
```

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
