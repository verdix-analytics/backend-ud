from __future__ import annotations

import logging
from typing import Callable, Any

from pybreaker import CircuitBreaker

logger = logging.getLogger(__name__)

# Circuit breaker for LLM service
llm_circuit_breaker = CircuitBreaker(
    fail_max=3,
    reset_timeout=60,
    name="LLM Circuit Breaker",
)


def call_with_circuit_breaker(func: Callable[..., Any], *args, **kwargs) -> Any:
    try:
        return llm_circuit_breaker.call(func, *args, **kwargs)
    except Exception as exc:
        logger.warning("Circuit breaker triggered or function failed: %s", exc)
        raise
