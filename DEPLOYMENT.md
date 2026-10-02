# DEPLOYMENT.md — IdeaFeed AI / Qoneqt Content Engine

One command to run it, one page to understand it. This is the deployable
reference for the backend built against `PRD.md` (original) and the
IdeaFeed AI MVP spec (Qoneqt × CTRL FREAK Challenge).

---

## 1. What this is

A Python/FastAPI backend (kept intentionally, not rewritten to Node — see
§8 "Architecture decisions") that turns one topic into a reviewed,
approved, publish-ready vertical video:

```
topic -> script+hooks -> scenes -> images+voice+captions -> composed MP4
      -> quality gate -> approve -> Qoneqt manual handoff
```

Every external AI call (script, image, voice, captions, motion) goes
through a **provider fallback chain** ("AI orchestra") — if one provider is
rate-limited or down, the next one in the chain is tried automatically, so
a live demo degrades gracefully instead of failing outright. Check what's
live right now at `GET /providers/status`.

---

## 2. Run it locally (fastest path)

```bash
git clone <this repo>
cd HACKBRIVEN-1
pip install -r requirements.txt
# Windows only, if ffmpeg isn't already on PATH: the app fetches a static
# build automatically on first run via the static-ffmpeg package — no
# admin rights needed. On Linux/Mac: apt-get install ffmpeg / brew install ffmpeg
cp .env.example .env        # fill in whichever keys you have, or leave blank
python app.py                # backend (FastAPI) + Gradio UI, one process, port 7860
```

Open `http://localhost:7860`. Every optional provider has a keyless
fallback, so this boots and produces a real (if lower-quality) video with
**zero API keys configured** — Pollinations for images, edge-tts/gTTS for
voice, a local Whisper model for captions, a hand-written template for
script generation, and Ken Burns pan/zoom instead of real AI motion.

## 3. Run the backend API alone (no UI)

```bash
uvicorn backend.api.main:app --reload --port 8000
```

Interactive API docs at `http://localhost:8000/docs`.

## 4. Docker

```bash
docker build -t ideafeed-ai .
docker run -p 7860:7860 --env-file .env ideafeed-ai
```

## 5. Hugging Face Spaces (no Docker needed)

See `deploy/huggingface/README.md` for the full walkthrough. Short version:
create a Gradio-SDK Space, push this repo, set whichever secrets you have
under **Settings → Repository secrets**, done. Free Spaces sleep when idle
— wake one before a live demo.

---

## 6. Environment variables

Full reference lives in `.env.example` (comments explain the fallback
behavior for each). Summary by category:

| Category | Vars | Required? |
|---|---|---|
| Script (LLM) | `GEMINI_API_KEY`, `GROQ_API_KEY`, `OPENROUTER_API_KEY` | No — falls back to a local template |
| Images | `NVIDIA_API_KEY` | No — falls back to Pollinations (keyless), then a generated placeholder |
| Voice | *(none)* | No — edge-tts then gTTS, both keyless |
| Captions | `GROQ_API_KEY` (reused) | No — falls back to local faster-whisper |
| Real AI motion | `EIGHTSCALE_API_KEY`, `MAGIC_HOUR_API_KEY` | No — falls back to Ken Burns pan/zoom (always available) |
| Credits ledger | `MONGODB_URI` | No — falls back to a local SQLite file (won't survive an ephemeral host restart) |
| Payments | `RAZORPAY_KEY_ID`, `RAZORPAY_KEY_SECRET` | No — credit top-up endpoints return 503 until set |
| Auth | `BACKEND_API_KEY` | **No, but should be set before any public deployment** — empty disables auth entirely |

Nothing is ever required to boot. `GET /providers/status` shows exactly
what's configured right now, without leaking any secret value.

---

## 7. API reference (current, as implemented)

Base path: none versioned yet (flat `/jobs`, `/credits`, etc. — the PRD's
`/api/v1/...` Node-style paths were not adopted 1:1, see §8).

### Jobs (generation lifecycle)
- `POST /jobs` — create + queue a job. Body: `{topic, language, motion_tier}`.
  Accepts an `Idempotency-Key` header; a repeated key returns the original
  job instead of creating a duplicate or charging credits twice.
- `GET /jobs` — list all jobs.
- `GET /jobs/{id}` — status, stage history, script, quality report summary.
- `GET /jobs/{id}/result` — result file path once done (409 before that).
- `GET /jobs/{id}/quality-report` — technical QA report (409 before `done`).
- `POST /jobs/{id}/cancel` — cooperative cancellation between pipeline stages.
- `POST /jobs/{id}/approve` — body `{approver}`. Only legal from `done`;
  records `approved_by` + `approved_at`. **Required before publish.**
- `POST /jobs/{id}/publish` — only legal from `approved`. Always performs
  the honest **manual Qoneqt handoff** (see §9) — never claims `published`,
  because no Qoneqt publishing API exists to actually confirm one.

### Credits / payments
- `GET /credits` — balance + per-tier cost.
- `POST /credits/create-order` — creates a Razorpay test-mode order.
- `POST /credits/verify-payment` — verifies a Razorpay signature, credits the account.

### Meta / observability
- `GET /health` — liveness.
- `GET /ready` — readiness: checks ffmpeg resolves and (if configured) Mongo answers a ping.
- `GET /providers/status` — the "AI orchestra" view: every stage's fallback chain and what's live, no secrets.
- `GET /analytics/overview` — internal job counts by status. No Qoneqt viewership data exists or is fabricated here.

### Auth
Every mutating endpoint above (`POST /jobs`, `/approve`, `/cancel`,
`/publish`) requires `Authorization: Bearer <BACKEND_API_KEY>` **once that
env var is set**. Unset, auth is off (local/demo default).

---

## 8. Architecture decisions (why this isn't the PRD's Node/Mongo stack verbatim)

The IdeaFeed AI PRD specifies Node.js + Express + MongoDB + a Project/
GenerationJob/Asset/Approval/PublishJob data model. This build **keeps the
already-working Python/FastAPI pipeline** instead of a from-scratch Node
rewrite, for one reason: under hackathon time pressure, a rewrite risks a
broken demo; retrofitting the PRD's *guarantees* onto proven code does not.
What was retrofitted:

- **Job lifecycle states** (`queued → ... → done → approved → publishing →
  published/publish_failed/manual_handoff`, plus `cancelled`) — additive to
  the existing `JobStatus` enum, so nothing that worked before changed
  behavior; `done` plays the PRD's `needs_review` role.
- **Idempotency keys** on job creation.
- **MongoDB persistence** for jobs and the credits ledger (survives a
  process restart — the PRD's "persistent status survives API/worker
  restarts" requirement), SQLite/in-memory fallback for local dev.
- **Honest manual Qoneqt handoff** instead of a fake "published" state —
  see §9.
- **Minimal shared-secret auth**, not a full user/session system — see §10
  for exactly what this does and does not cover.

What was **not** attempted, and is out of scope for this build:
- A separate Project entity distinct from a Job (no script editing/
  versioning before render, no project library/reuse).
- Configurable aspect ratio / duration presets / visual themes (fixed at
  1080x1920 vertical, duration driven by the generated script).
- File upload / reference-image ingestion.
- A React frontend (the Gradio UI in `frontend/app.py` is the full UI).
- Multi-user accounts, OAuth, or per-user ownership checks.
- Real Qoneqt analytics (none are fetched or fabricated — `GET
  /analytics/overview` only ever shows internal job counts).

---

## 9. Why publishing is always a "manual handoff"

Qoneqt has no public API for posting to a creator's feed. This was
confirmed directly from the client-provided "Content Creators Main.xlsx":
it is a manually maintained creator roster plus a hand-typed daily
engagement tracker — not an API integration, and no credentials or docs
for one exist. Per the PRD's own explicit rule ("do not claim successful
publishing until the platform confirms success" / "never fake... a
successful publish"), `POST /jobs/{id}/publish` **never** sets a job to
`published`. It always writes a `qoneqt_handoff.txt` next to the final
video (job id, suggested title/caption, language, motion tier, and a clear
"NOT automatically published" banner) and sets status to `manual_handoff` —
an explicit signal that a human still has to hand the video to a creator
from the roster and post it themselves.

If Qoneqt ever provides real API access, swap the implementation inside
`backend/services/qoneqt_handoff.py` / `backend/api/routes.py::publish_job`
for a real call, and only then introduce a genuine `published` transition.

---

## 10. Auth: what's actually implemented

`BACKEND_API_KEY` is a single shared secret, checked via `Authorization:
Bearer <key>` on every mutating endpoint. This satisfies the PRD's P0
"apply request limits and authenticated access to project/publishing
endpoints" at MVP scope — it is **not** multi-user, has no roles beyond
"has the key or doesn't," and there is no session/token issuance flow.
Treat it as a deployment gate ("don't let a stranger hit this API"), not
as user-level authorization. A real multi-operator deployment needs a
proper identity provider in front of this.

---

## 11. The "AI orchestra" — provider fallback chains

Every stage below is implemented as an ordered `Provider` list passed to
`backend/services/model_router.py::call_with_fallback`, which tries each in
order and only raises if every single one fails. This is what makes a live
judge demo resilient to one provider having a bad moment.

| Stage | Chain (in order) | All keyless? |
|---|---|---|
| Script + hooks | Gemini → Groq → OpenRouter → local template | Local template always works |
| Images | NVIDIA (FLUX.1-dev) → Pollinations → generated placeholder | Pollinations + placeholder are keyless |
| Voice | edge-tts → gTTS | Both keyless |
| Captions | Groq-hosted Whisper → local faster-whisper | Local Whisper is keyless |
| Motion | 8Scale → Magic Hour → Ken Burns pan/zoom | Ken Burns is keyless and always available |

Live view: `GET /providers/status` (no secrets exposed, just booleans).

---

## 12. Testing

```bash
python -m pytest -q
```

Runs the full suite excluding `@pytest.mark.integration` tests (those hit
real third-party APIs and are opt-in: `pytest -m integration`). A
`conftest.py` autouse fixture forces Mongo off by default so the suite
never silently writes to a real deployed database — see the fixture's own
docstring for the real incident that made this necessary.

---

## 13. Known gaps vs. the full IdeaFeed AI PRD

Listed plainly, not buried, per this project's own "never fake a result"
rule:

- No React frontend — Gradio only.
- No reference-image upload / script-upload intake path.
- No configurable aspect ratio, duration preset, or visual theme.
- No per-scene regeneration without rerunning the whole job.
- No background music, auto-thumbnail, or SRT/VTT export yet.
- No multi-user ownership/authorization, only a single shared API key.
- No real Qoneqt analytics (none exist to fetch).
- Stage-level resume-from-failure is not implemented; a failed job must be
  re-submitted from the start (it does not silently reuse completed-stage
  outputs from a prior attempt).
