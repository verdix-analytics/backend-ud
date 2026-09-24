import logging
from functools import lru_cache
from typing import Dict, Any, Optional, List

import yfinance as yf

from app.models.schemas import (
    NewsResponse,
    NewsArticle,
    NewsContent,
    NewsProvider,
    NewsUrl,
    NewsThumbnail,
    NewsResolution,
    NewsMetadata,
    NewsFinance,
    NewsSentiment,
    NewsOverallSentiment,
)

logger = logging.getLogger(__name__)

_FINBERT_MODEL = "ProsusAI/finbert"

# FinBERT label → domain label
_LABEL_MAP = {
    "positive": "bullish",
    "negative": "bearish",
    "neutral": "neutral",
}


@lru_cache(maxsize=1)
def _get_pipeline():
    """Lazily load FinBERT; cached so the model is only downloaded and loaded once."""
    try:
        from transformers import pipeline as hf_pipeline
        return hf_pipeline(
            "text-classification",
            model=_FINBERT_MODEL,
            device=-1,          # CPU; change to 0 for GPU
            truncation=True,
            max_length=512,
        )
    except Exception as exc:
        logger.error(f"Failed to load FinBERT pipeline: {exc}")
        return None


def _analyze_sentiment(text: str) -> NewsSentiment:
    """Run text through FinBERT and return a NewsSentiment."""
    fallback = NewsSentiment(label="neutral", score=0.0, confidence="low")
    if not text or not text.strip():
        return fallback

    pipe = _get_pipeline()
    if pipe is None:
        return fallback

    try:
        result = pipe(text[:512])[0]   # truncate before inference too
        raw_label: str = result["label"].lower()
        confidence_score: float = round(float(result["score"]), 4)

        label = _LABEL_MAP.get(raw_label, "neutral")
        # signed_score: +1 → bullish, -1 → bearish, 0 → neutral
        if label == "bullish":
            signed_score = confidence_score
        elif label == "bearish":
            signed_score = -confidence_score
        else:
            signed_score = 0.0

        confidence = (
            "high" if confidence_score >= 0.85
            else "medium" if confidence_score >= 0.65
            else "low"
        )

        return NewsSentiment(
            label=label,
            score=round(signed_score, 4),
            confidence=confidence,
        )
    except Exception as exc:
        logger.warning(f"FinBERT inference failed: {exc}")
        return fallback


def _compute_overall_sentiment(articles: List[NewsArticle]) -> NewsOverallSentiment:
    """Aggregate per-article sentiments into one overall verdict."""
    scored = [a.sentiment for a in articles if a.sentiment is not None]
    if not scored:
        return NewsOverallSentiment(label="neutral", score=0.0)

    avg_score = round(sum(s.score for s in scored) / len(scored), 4)
    bullish_count = sum(1 for s in scored if s.label == "bullish")
    bearish_count = sum(1 for s in scored if s.label == "bearish")
    neutral_count = sum(1 for s in scored if s.label == "neutral")

    if avg_score > 0.05:
        label = "bullish"
    elif avg_score < -0.05:
        label = "bearish"
    else:
        label = "neutral"

    return NewsOverallSentiment(
        label=label,
        score=avg_score,
        bullish_count=bullish_count,
        bearish_count=bearish_count,
        neutral_count=neutral_count,
    )


def _parse_news_article(article: Dict[str, Any]) -> NewsArticle:
    """Parse a raw news article dict into NewsArticle model."""
    try:
        article_id = article.get("id")
        content_data = article.get("content", {})

        # Parse thumbnail
        thumbnail_data = content_data.get("thumbnail")
        thumbnail = None
        if thumbnail_data:
            resolutions = []
            if thumbnail_data.get("resolutions"):
                for res in thumbnail_data.get("resolutions", []):
                    resolutions.append(
                        NewsResolution(
                            url=res.get("url"),
                            width=res.get("width"),
                            height=res.get("height"),
                            tag=res.get("tag"),
                        )
                    )
            thumbnail = NewsThumbnail(
                originalUrl=thumbnail_data.get("originalUrl"),
                originalWidth=thumbnail_data.get("originalWidth"),
                originalHeight=thumbnail_data.get("originalHeight"),
                caption=thumbnail_data.get("caption"),
                resolutions=resolutions if resolutions else None,
            )

        # Parse provider
        provider_data = content_data.get("provider", {})
        provider = NewsProvider(
            displayName=provider_data.get("displayName"),
            url=provider_data.get("url"),
            sourceId=provider_data.get("sourceId"),
        )

        # Parse URLs
        canonical_url_data = content_data.get("canonicalUrl", {})
        canonical_url = NewsUrl(
            url=canonical_url_data.get("url"),
            site=canonical_url_data.get("site"),
            region=canonical_url_data.get("region"),
            lang=canonical_url_data.get("lang"),
        )

        click_url_data = content_data.get("clickThroughUrl", {})
        click_url = NewsUrl(
            url=click_url_data.get("url"),
            site=click_url_data.get("site"),
            region=click_url_data.get("region"),
            lang=click_url_data.get("lang"),
        )

        # Parse metadata
        metadata_data = content_data.get("metadata", {})
        metadata = NewsMetadata(editorsPick=metadata_data.get("editorsPick"))

        # Parse finance
        finance_data = content_data.get("finance", {})
        finance = NewsFinance(premiumFinance=finance_data.get("premiumFinance"))

        content = NewsContent(
            id=content_data.get("id"),
            contentType=content_data.get("contentType"),
            title=content_data.get("title"),
            description=content_data.get("description"),
            summary=content_data.get("summary"),
            pubDate=content_data.get("pubDate"),
            displayTime=content_data.get("displayTime"),
            isHosted=content_data.get("isHosted"),
            bypassModal=content_data.get("bypassModal"),
            previewUrl=content_data.get("previewUrl"),
            thumbnail=thumbnail,
            provider=provider,
            canonicalUrl=canonical_url,
            clickThroughUrl=click_url,
            metadata=metadata,
            finance=finance,
            storyline=content_data.get("storyline"),
        )

        sentiment_text = " ".join(filter(None, [
            content_data.get("title"),
            content_data.get("description"),
            content_data.get("summary"),
        ]))
        sentiment = _analyze_sentiment(sentiment_text)

        return NewsArticle(id=article_id, content=content, sentiment=sentiment)

    except Exception as exc:
        logger.error(f"Error parsing news article: {exc}")
        return NewsArticle()


def fetch_news(symbol: str, limit: Optional[int] = None) -> NewsResponse:
    """Fetch news articles for a given ticker symbol."""
    try:
        ticker = yf.Ticker(symbol)
        info = ticker.info or {}

        news_list = ticker.news or []

        articles = []
        for article in news_list:
            parsed_article = _parse_news_article(article)
            articles.append(parsed_article)

        if limit:
            articles = articles[:limit]

        overall_sentiment = _compute_overall_sentiment(articles)

        return NewsResponse(
            symbol=symbol.upper(),
            name=info.get("longName"),
            articles=articles,
            total_count=len(articles),
            overall_sentiment=overall_sentiment,
        )

    except Exception as exc:
        logger.error(f"Failed to fetch news for {symbol}: {exc}")
        raise ValueError(f"Unable to fetch news for symbol '{symbol}': {str(exc)}")


def get_news(symbol: str, limit: Optional[int] = None) -> NewsResponse:
    """Get news articles for a stock symbol with validation."""
    if not symbol or not isinstance(symbol, str):
        raise ValueError("Symbol must be a non-empty string")

    symbol_upper = symbol.strip().upper()
    if not symbol_upper:
        raise ValueError("Symbol cannot be empty after trimming")

    if limit is not None and limit < 1:
        raise ValueError("Limit must be at least 1")

    return fetch_news(symbol_upper, limit)
