from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Protocol

from .exceptions import AiProviderError


@dataclass(frozen=True, slots=True)
class AiProviderRequest:
    model: str
    system_instructions: str
    user_data: dict[str, Any]
    output_schema: dict[str, Any]


@dataclass(frozen=True, slots=True)
class AiProviderResult:
    output: dict[str, Any]
    input_tokens: int
    output_tokens: int
    cost_usd: Decimal
    model: str


class AiProvider(Protocol):
    def generate(
        self,
        request: AiProviderRequest,
        *,
        timeout_seconds: int,
        cancellation_check: Callable[[], bool],
    ) -> AiProviderResult: ...


class UnconfiguredAiProvider:
    """Default provider: common infrastructure never calls an external model by accident."""

    def generate(self, request, *, timeout_seconds, cancellation_check):
        raise AiProviderError(
            "AI provider is not configured.",
            code="provider_not_configured",
            retryable=False,
        )
