"""Hugging Face Space entrypoint: bundles the FastAPI backend and the Gradio
frontend into one process, since a free Space only runs a single app.

Runs uvicorn (backend.api.main:app) on a background thread, points the
Gradio frontend at it via API_BASE_URL, then launches the Gradio UI in the
foreground, which is what the Space's health check expects.
"""

from __future__ import annotations

import os
import threading
import time

import httpx
import uvicorn

_HOST = "127.0.0.1"
_PORT = int(os.environ.get("BACKEND_PORT", "8000"))

os.environ.setdefault("API_BASE_URL", f"http://{_HOST}:{_PORT}")


def _run_backend() -> None:
    uvicorn.run("backend.api.main:app", host=_HOST, port=_PORT, log_level="info")


def _wait_for_backend(timeout_seconds: float = 30.0) -> None:
    deadline = time.monotonic() + timeout_seconds
    url = f"http://{_HOST}:{_PORT}/health"
    while time.monotonic() < deadline:
        try:
            if httpx.get(url, timeout=2.0).status_code == 200:
                return
        except httpx.HTTPError:
            pass
        time.sleep(0.5)
    raise RuntimeError("backend did not become healthy in time")


if __name__ == "__main__":
    threading.Thread(target=_run_backend, daemon=True).start()
    _wait_for_backend()

    from frontend.app import demo

    demo.queue().launch(server_name="0.0.0.0")
