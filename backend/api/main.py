from __future__ import annotations

from fastapi import FastAPI

from backend.api.routes import router
from backend.utils.logger import setup_logging


def create_app() -> FastAPI:
    setup_logging()
    app = FastAPI(
        title="From Idea to Feed",
        description="AI-powered content production pipeline for the Qoneqt Global Feed",
        version="0.1.0",
    )
    app.include_router(router)

    @app.get("/health")
    def health() -> dict:
        return {"status": "ok"}

    return app


app = create_app()
