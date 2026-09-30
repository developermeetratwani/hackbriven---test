from __future__ import annotations

import os
import time

import gradio as gr
import httpx

API_BASE_URL = os.environ.get("API_BASE_URL", "http://localhost:8000")

_STAGE_ORDER = [
    "queued",
    "running_intelligence",
    "running_generation",
    "running_composition",
    "running_validation",
    "done",
]

_STAGE_LABELS = {
    "queued": "Queued",
    "running_intelligence": "Script",
    "running_generation": "Visuals & Voice",
    "running_composition": "Composition",
    "running_validation": "Quality Check",
    "done": "Done",
    "failed": "Failed",
}


def _render_status(status: str) -> str:
    if status == "failed":
        return "\n".join(f"- {label}" for label in _STAGE_LABELS.values() if label != "Failed") + "\n\n**Failed**"

    reached = _STAGE_ORDER.index(status) if status in _STAGE_ORDER else -1
    lines = []
    for i, stage in enumerate(_STAGE_ORDER):
        label = _STAGE_LABELS[stage]
        if i < reached:
            lines.append(f"- [x] {label}")
        elif i == reached:
            lines.append(f"- [ ] **{label} (running)**" if stage != "done" else f"- [x] {label}")
        else:
            lines.append(f"- [ ] {label}")
    return "\n".join(lines)


def generate(topic: str):
    topic = (topic or "").strip()
    if not topic:
        yield "Enter a topic first.", None, gr.update(interactive=True)
        return

    yield "Submitting job...", None, gr.update(interactive=False)

    with httpx.Client(timeout=30.0) as client:
        try:
            response = client.post(f"{API_BASE_URL}/jobs", json={"topic": topic})
            response.raise_for_status()
        except httpx.HTTPError as exc:
            yield f"Could not reach the backend at {API_BASE_URL}: {exc}", None, gr.update(interactive=True)
            return

        job = response.json()
        job_id = job["id"]

        while True:
            time.sleep(1.5)
            try:
                response = client.get(f"{API_BASE_URL}/jobs/{job_id}")
                response.raise_for_status()
            except httpx.HTTPError as exc:
                yield f"Lost connection to backend: {exc}", None, gr.update(interactive=True)
                return

            job = response.json()
            status = job["status"]

            if status == "failed":
                reason = job.get("error_reason", "unknown error")
                stage = job.get("error_stage", "unknown stage")
                yield f"{_render_status(status)}\n\n**Reason ({stage}):** {reason}", None, gr.update(interactive=True)
                return

            if status == "done":
                yield _render_status(status), job.get("result_path"), gr.update(interactive=True)
                return

            yield _render_status(status), None, gr.update(interactive=False)


with gr.Blocks(title="Qoneqt Content Engine") as demo:
    gr.Markdown(
        "# Qoneqt Content Engine\n"
        "One topic in. A checked, publish-ready video out."
    )

    with gr.Row():
        topic_input = gr.Textbox(
            label="Topic, prompt, idea or trend",
            placeholder="Why electric vehicles are becoming popular",
            scale=4,
        )
        generate_button = gr.Button("Generate", variant="primary", scale=1)

    with gr.Row():
        stage_status = gr.Markdown(label="Pipeline stages")
        video_output = gr.Video(label="Result")

    generate_button.click(
        fn=generate,
        inputs=[topic_input],
        outputs=[stage_status, video_output, generate_button],
    )

if __name__ == "__main__":
    demo.queue().launch()
