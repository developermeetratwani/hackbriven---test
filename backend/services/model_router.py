from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Callable, TypeVar

from backend.core.exceptions import AllProvidersFailedError

logger = logging.getLogger(__name__)

T = TypeVar("T")


@dataclass(frozen=True)
class Provider:
    name: str
    call: Callable[[], T]


def call_with_fallback(providers: list[Provider], *, stage: str) -> T:
    """Try each provider in order; return the first success.

    Raises AllProvidersFailedError with every collected error if the whole
    chain is exhausted. This is the single implementation of the
    Gemini->Groq / NVIDIA->Pollinations / fal.ai->Ken-Burns pattern; stage
    services must never call a provider SDK directly (see RULES.md #2).
    """
    if not providers:
        raise AllProvidersFailedError(stage, [("<none>", "no providers configured")])

    errors: list[tuple[str, str]] = []
    for provider in providers:
        try:
            logger.info("stage=%s trying provider=%s", stage, provider.name)
            return provider.call()
        except Exception as exc:  # noqa: BLE001 - intentional: any provider failure falls through
            logger.warning(
                "stage=%s provider=%s failed: %s", stage, provider.name, exc
            )
            errors.append((provider.name, str(exc)))

    raise AllProvidersFailedError(stage, errors)
