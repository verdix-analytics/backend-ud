from __future__ import annotations

from enum import Enum
from typing import Any
from typing import Protocol

from app.models.schemas import PatternSummary, StockAnalysisResponse


class _TranslatorClient(Protocol):
    def translate(self, text: str) -> str: ...


def _build_google_translator(source_language_code: str, target_language_code: str) -> _TranslatorClient:
    """Create a GoogleTranslator client lazily to avoid import-time hard failures."""
    try:
        from deep_translator import GoogleTranslator
    except ModuleNotFoundError as exc:
        raise RuntimeError(
            "deep-translator is not installed. Add it to dependencies before using translation_service"
        ) from exc

    return GoogleTranslator(source=source_language_code, target=target_language_code)


def translate_text(target_language_code: str, text: str, source_language_code: str = "auto") -> str:
    """Translate text to the target language code (for example: 'es', 'fr', 'hi')."""
    normalized_target = target_language_code.strip()
    if not normalized_target:
        raise ValueError("target_language_code must not be empty")

    normalized_source = source_language_code.strip()
    if not normalized_source:
        raise ValueError("source_language_code must not be empty")

    normalized_text = text.strip()
    if not normalized_text:
        raise ValueError("text must not be empty")

    translator = _build_google_translator(
        source_language_code=normalized_source,
        target_language_code=normalized_target,
    )

    try:
        translated = translator.translate(normalized_text)
    except Exception as exc:  # pragma: no cover - provider/network failures
        raise RuntimeError("Failed to translate text") from exc

    normalized_translation = translated.strip()
    if not normalized_translation:
        raise RuntimeError("Translation provider returned an empty response")

    return normalized_translation


_DO_NOT_TRANSLATE_KEYS = {
    "ticker",
    "companyname",
    "exchange",
    "symbol",
    "stock_name",
    "stock_exchange",
    "pre_trend",
    "post_trend",
    "pivots",
}


def _translate_value(
    value: Any,
    *,
    language_code: str,
    cache: dict[str, str],
    parent_key: str | None = None,
) -> Any:
    if value is None:
        return None

    if isinstance(value, Enum):
        return value

    if parent_key and parent_key.lower() in _DO_NOT_TRANSLATE_KEYS:
        return value

    if isinstance(value, str):
        normalized = value.strip()
        if not normalized:
            return value

        translated = cache.get(normalized)
        if translated is None:
            translated = translate_text(language_code, normalized)
            cache[normalized] = translated
        return translated

    if isinstance(value, dict):
        translated_dict: dict[str, Any] = {}
        for key, item in value.items():
            translated_dict[key] = _translate_value(
                item,
                language_code=language_code,
                cache=cache,
                parent_key=str(key),
            )
        return translated_dict

    if isinstance(value, list):
        return [
            _translate_value(item, language_code=language_code, cache=cache, parent_key=parent_key)
            for item in value
        ]

    return value


def _translate_pattern_summary(pattern: PatternSummary, *, language_code: str, cache: dict[str, str]) -> PatternSummary:
    return pattern.model_copy(
        update={
            "name": _translate_value(pattern.name, language_code=language_code, cache=cache, parent_key="name"),
            "contextBias": _translate_value(
                pattern.contextBias,
                language_code=language_code,
                cache=cache,
                parent_key="contextBias",
            ),
            "signal": _translate_value(pattern.signal, language_code=language_code, cache=cache, parent_key="signal"),
            "pre_trend": _translate_value(
                pattern.pre_trend,
                language_code=language_code,
                cache=cache,
                parent_key="pre_trend",
            ),
            "post_trend": _translate_value(
                pattern.post_trend,
                language_code=language_code,
                cache=cache,
                parent_key="post_trend",
            ),
        }
    )


def translate_stock_analysis_response(response: StockAnalysisResponse, language_code: str) -> StockAnalysisResponse:
    """Translate user-facing text in StockAnalysisResponse while preserving identifiers and numeric fields."""
    normalized_language = language_code.strip()
    if not normalized_language:
        raise ValueError("language_code must not be empty")

    if normalized_language in {"en", "en-us", "en-gb"}:
        return response

    cache: dict[str, str] = {}
    return response.model_copy(
        update={
            "patterns": [
                _translate_pattern_summary(pattern, language_code=normalized_language, cache=cache)
                for pattern in response.patterns
            ],
            "patternName": _translate_value(
                response.patternName,
                language_code=normalized_language,
                cache=cache,
                parent_key="patternName",
            ),
            "trend": _translate_value(
                response.trend,
                language_code=normalized_language,
                cache=cache,
                parent_key="trend",
            ),
            "interpretation": _translate_value(
                response.interpretation,
                language_code=normalized_language,
                cache=cache,
                parent_key="interpretation",
            ),
        }
    )


