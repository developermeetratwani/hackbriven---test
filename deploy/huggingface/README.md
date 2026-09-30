---
title: Qoneqt Content Engine
emoji: 🎬
colorFrom: indigo
colorTo: pink
sdk: docker
app_port: 7860
pinned: false
---

# Qoneqt Content Engine — From Idea to Feed

Deploy this repository as-is to a Hugging Face Space using the **Docker** SDK:

1. Create a new Space, choose SDK = Docker.
2. Push this repository's contents to the Space's git remote (the root
   `Dockerfile` and `app.py` are the entrypoint; this `README.md`'s frontmatter
   is the Space card — copy it to the repo root `README.md` if the Space
   requires it there, or point `app_file`/SDK config at this file per HF's
   current docs).
3. In the Space's **Settings → Repository secrets**, set whichever of these
   you have: `GEMINI_API_KEY`, `GROQ_API_KEY`, `NVIDIA_API_KEY`, `FAL_API_KEY`.
   None are required to boot — the pipeline falls back to keyless providers
   (Pollinations images, edge-tts voice, a local template script) when a key
   is missing, per `TECH.md`.
4. Free Spaces sleep when idle — wake it before a live demo.

Measured in the original prototype on 1 CPU: ~45s to produce a ~23s video.
