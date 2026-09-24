from __future__ import annotations

from langchain_core.messages import AIMessage
from langchain_core.runnables import RunnableLambda

from app.services import llm_service


def test_generate_llm_response_returns_string(monkeypatch):
    monkeypatch.setattr(llm_service.settings, "google_api_key", "test-key")
    monkeypatch.setattr(llm_service, "_build_llm", lambda: RunnableLambda(lambda _: AIMessage(content="mock response")))

    result = llm_service.generate_llm_response("  Hello Gemini  ")

    assert result == "mock response"


def test_generate_llm_response_rejects_empty_prompt():
    try:
        llm_service.generate_llm_response("   ")
    except ValueError as exc:
        assert str(exc) == "prompt must not be empty"
    else:  # pragma: no cover - defensive guard
        raise AssertionError("Expected ValueError for empty prompt")


def test_generate_llm_response_requires_google_api_key(monkeypatch):
    monkeypatch.setattr(llm_service.settings, "google_api_key", None)

    try:
        llm_service.generate_llm_response("Give me a summary")
    except RuntimeError as exc:
        assert str(exc) == "GOOGLE_API_KEY is not configured"
    else:  # pragma: no cover - defensive guard
        raise AssertionError("Expected RuntimeError when GOOGLE_API_KEY is missing")

