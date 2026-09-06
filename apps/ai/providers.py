from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Protocol


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
