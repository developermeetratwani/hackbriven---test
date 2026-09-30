from __future__ import annotations

import json
import logging

import httpx

from backend.config import settings
from backend.core.exceptions import InvalidScriptError
from backend.models.schemas import Script
from backend.services.model_router import Provider, call_with_fallback

logger = logging.getLogger(__name__)

STAGE = "intelligence.story_engine"

_SYSTEM_PROMPT = (
    "You are a short vertical-video scriptwriter. Given a topic, return ONLY "
    "valid JSON (no markdown fences, no prose) matching this shape:\n"
    '{"hook": str, "mood": str, "scenes": ['
    '{"narration": str, "image_prompt": str, "duration_seconds": number, "mood": str}'
    "]}\n"
    "Write 3 to 6 scenes. Each duration_seconds should be between 3 and 8. "
    "narration is what a voiceover reads aloud; image_prompt describes a single "
    "still image for that scene."
)


def _build_user_prompt(topic: str) -> str:
    return f"Topic: {topic}\nReturn the JSON now."


def _parse_script(topic: str, raw_text: str) -> Script:
    text = raw_text.strip()
    if text.startswith("```"):
        text = text.strip("`")
        if text.lower().startswith("json"):
            text = text[4:]
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise InvalidScriptError(STAGE, f"model did not return valid JSON: {exc}") from exc

    scenes = data.get("scenes", [])
    if not scenes:
        raise InvalidScriptError(STAGE, "model returned zero scenes")

    for i, scene in enumerate(scenes):
        scene["index"] = i

    try:
        return Script(
            topic=topic,
            hook=data["hook"],
            mood=data.get("mood", "neutral"),
            scenes=scenes,
        )
    except KeyError as exc:
        raise InvalidScriptError(STAGE, f"missing required field: {exc}") from exc


def _call_gemini(topic: str) -> Script:
    if not settings.gemini_api_key:
        raise RuntimeError("GEMINI_API_KEY not configured")

    url = (
        f"https://generativelanguage.googleapis.com/v1beta/models/"
        f"{settings.gemini_model}:generateContent?key={settings.gemini_api_key}"
    )
    payload = {
        "contents": [{"parts": [{"text": _build_user_prompt(topic)}]}],
        "systemInstruction": {"parts": [{"text": _SYSTEM_PROMPT}]},
        "generationConfig": {"responseMimeType": "application/json"},
    }
    with httpx.Client(timeout=settings.provider_timeout_seconds) as client:
        response = client.post(url, json=payload)
        response.raise_for_status()
        body = response.json()

    raw_text = body["candidates"][0]["content"]["parts"][0]["text"]
    return _parse_script(topic, raw_text)


def _call_groq(topic: str) -> Script:
    if not settings.groq_api_key:
        raise RuntimeError("GROQ_API_KEY not configured")

    url = "https://api.groq.com/openai/v1/chat/completions"
    headers = {"Authorization": f"Bearer {settings.groq_api_key}"}
    payload = {
        "model": settings.groq_model,
        "messages": [
            {"role": "system", "content": _SYSTEM_PROMPT},
            {"role": "user", "content": _build_user_prompt(topic)},
        ],
        "response_format": {"type": "json_object"},
    }
    with httpx.Client(timeout=settings.provider_timeout_seconds) as client:
        response = client.post(url, json=payload, headers=headers)
        response.raise_for_status()
        body = response.json()

    raw_text = body["choices"][0]["message"]["content"]
    return _parse_script(topic, raw_text)


def _call_openrouter(topic: str) -> Script:
    if not settings.openrouter_api_key:
        raise RuntimeError("OPENROUTER_API_KEY not configured")

    url = "https://openrouter.ai/api/v1/chat/completions"
    headers = {"Authorization": f"Bearer {settings.openrouter_api_key}"}
    payload = {
        "model": settings.openrouter_model,
        "messages": [
            {"role": "system", "content": _SYSTEM_PROMPT},
            {"role": "user", "content": _build_user_prompt(topic)},
        ],
        "response_format": {"type": "json_object"},
    }
    with httpx.Client(timeout=settings.provider_timeout_seconds) as client:
        response = client.post(url, json=payload, headers=headers)
        response.raise_for_status()
        body = response.json()

    raw_text = body["choices"][0]["message"]["content"]
    return _parse_script(topic, raw_text)


_TEMPLATE_ANGLES = [
    ("the hook", "Here's something you didn't expect about {topic}.", "a striking establishing shot representing {topic}"),
    ("context", "{topic} matters more than most people realize.", "an informative wide shot related to {topic}"),
    ("key point", "The biggest driver behind {topic} is changing fast.", "a close-up illustrating a key detail of {topic}"),
    ("evidence", "The numbers around {topic} tell their own story.", "a visual metaphor for data or growth tied to {topic}"),
    ("takeaway", "So here's what {topic} means for you.", "a closing shot that ties {topic} together"),
]


def _local_template_script(topic: str) -> Script:
    """Deterministic, offline, no-key script generator.

    Last resort in the fallback chain: guarantees the Intelligence stage can
    always produce a usable Script even with zero LLM providers configured,
    so the rest of the pipeline (which needs no API keys at all) stays fully
    runnable while real keys are pending.
    """
    scenes = [
        {
            "narration": narration.format(topic=topic),
            "image_prompt": image_prompt.format(topic=topic),
            "duration_seconds": 4.0,
            "mood": "neutral",
            "index": i,
        }
        for i, (_label, narration, image_prompt) in enumerate(_TEMPLATE_ANGLES)
    ]
    return Script(
        topic=topic,
        hook=f"{topic}. Here's what's really going on.",
        mood="neutral",
        scenes=scenes,
    )


def generate_script(topic: str) -> Script:
    providers = [
        Provider(name="gemini", call=lambda: _call_gemini(topic)),
        Provider(name="groq", call=lambda: _call_groq(topic)),
        Provider(name="openrouter", call=lambda: _call_openrouter(topic)),
        Provider(name="local_template", call=lambda: _local_template_script(topic)),
    ]
    return call_with_fallback(providers, stage=STAGE)
