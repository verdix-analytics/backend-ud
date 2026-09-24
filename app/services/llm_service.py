from __future__ import annotations

from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import ChatPromptTemplate
from langchain_google_genai import ChatGoogleGenerativeAI

from app.core.config import settings

_PROMPT_TEMPLATE = ChatPromptTemplate.from_messages([
    ("human", "{prompt}"),
])


def _build_llm() -> ChatGoogleGenerativeAI:
    if not settings.google_api_key:
        raise RuntimeError("GOOGLE_API_KEY is not configured")

    return ChatGoogleGenerativeAI(
        model=settings.gemini_model,
        temperature=settings.gemini_temperature,
        google_api_key=settings.google_api_key,
    )


def generate_llm_response(prompt: str) -> str:
    """Generate a Gemini-backed response for the provided prompt."""
    normalized_prompt = prompt.strip()
    if not normalized_prompt:
        raise ValueError("prompt must not be empty")

    chain = _PROMPT_TEMPLATE | _build_llm() | StrOutputParser()

    try:
        response = chain.invoke({"prompt": normalized_prompt})
    except Exception as exc:  # pragma: no cover - provider/network failures
        raise RuntimeError("Failed to generate an LLM response") from exc

    return response.strip()

