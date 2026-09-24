from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional, Union
from uuid import UUID

from pydantic import BaseModel, Field


class PatternType(str, Enum):
    CANDLESTICK = "candlestick"
    CHART = "chart"
    HARMONIC = "harmonic"


class TechnicalContext(str, Enum):
    POSITIVE = "positive"
    NEUTRAL = "neutral"
    NEGATIVE = "negative"


class TrendDirection(str, Enum):
    UPTREND = "uptrend"
    DOWNTREND = "downtrend"
    SIDEWAYS = "sideways"


class Candle(BaseModel):
    timestamp: datetime
    open: float
    high: float
    low: float
    close: float
    volume: Optional[float] = None


class Pattern(BaseModel):
    name: str
    type: PatternType
    confidence: float = Field(ge=0, le=100)
    start_time: datetime
    end_time: datetime
    trend_alignment: int = Field(ge=-1, le=1)
    metadata: Dict[str, Any] = Field(default_factory=dict)


class TrendAnalysis(BaseModel):
    pre_pattern: TrendDirection
    post_pattern: TrendDirection


class AnalyzeRequest(BaseModel):
    instrument: str = Field(min_length=1)
    timeframe: str = "1H"
    candles: List[Candle] = Field(default_factory=list)
    use_sample_data: bool = False
    sample_count: int = Field(default=50, ge=20, le=500)


class AnalysisResult(BaseModel):
    analysis_id: str
    instrument: str
    timestamp: datetime
    timeframe: str
    technical_context: TechnicalContext
    confidence: float = Field(ge=0, le=100)
    patterns_detected: List[Pattern]
    interpretation: str
    trend_analysis: TrendAnalysis


class BatchAnalyzeRequest(BaseModel):
    analyses: List[AnalyzeRequest] = Field(min_length=1, max_length=100)


class BatchAnalyzeResponse(BaseModel):
    results: List[AnalysisResult]


class TrendInfo(BaseModel):
    label: str = "sideways"
    strength: Optional[float] = None
    realized_move_pct: Optional[float] = None


class SignalInfo(BaseModel):
    confirmed: bool = False
    structure_detected: Optional[bool] = None
    confidence: float = 0.0
    confidence_breakdown: Dict[str, Any] = Field(default_factory=dict)
    confidence_metadata: Dict[str, Any] = Field(default_factory=dict)
    pivots: Optional[Any] = None
    direction: Optional[str] = None


class DetectedPatternResponse(BaseModel):
    id: Optional[UUID] = None
    analysis_id: Optional[str] = None
    instrument: Optional[str] = None
    timeframe: Optional[str] = None
    detected_at: Optional[datetime] = None
    pattern: str
    category: str
    pattern_type: Optional[str] = None
    window_start: Optional[int] = None
    window_end: Optional[int] = None
    confidence: float
    confirmed: bool
    structure_detected: Optional[bool] = None
    signal: SignalInfo
    pre_trend: TrendInfo
    post_trend: TrendInfo


class DetectedPatternsListResponse(BaseModel):
    instrument: str
    category: str
    lookback_days: int
    count: int
    patterns: List[DetectedPatternResponse]


class StockSearchResponse(BaseModel):
    ticker: str
    companyName: str
    exchange: str
    isValid: bool


# Alias for frontend routes
SearchResultResponse = StockSearchResponse


class ModeEnum(str, Enum):
    CANDLESTICK = "candlestick"
    CHART = "chart"
    HARMONIC = "harmonic"


class PopularStockItem(BaseModel):
    ticker: str
    companyName: str
    exchange: str
    lastPrice: float = 0.0
    dailyChange: float = 0.0


class StockDirectoryItem(BaseModel):
    ticker: str
    name: str
    exchange: str
    assetClass: Optional[str] = None


class PatternSummary(BaseModel):
    name: str
    confidence: float
    contextScore: Optional[float] = None
    contextBias: Optional[str] = None
    signal: Optional[Dict[str, Any]] = None
    pre_trend: Optional[Dict[str, Any]] = None
    post_trend: Optional[Dict[str, Any]] = None
    detected_at: Optional[datetime] = None


class TechnicalContextScoreResponse(BaseModel):
    ticker: str
    technicalContextScore: float
    shortScore: float
    mediumScore: float
    longScore: float
    shortTechnicalAnalysis: Optional[dict] = None
    mediumTechnicalAnalysis: Optional[dict] = None
    longTechnicalAnalysis: Optional[dict] = None


class StockAnalysisResponse(BaseModel):
    ticker: str
    companyName: str
    exchange: str
    pattern_type: ModeEnum
    patterns: List[PatternSummary] = Field(default_factory=list)
    patternName: List[str] = Field(default_factory=list)
    confidenceScore: List[float] = Field(default_factory=list)
    trend: str = "neutral"
    interpretation: str = ""
    shortScore: float = 0.0
    mediumScore: float = 0.0
    longScore: float = 0.0


class PatternSummaryItem(BaseModel):
    pattern_name: str
    summary: str


class FundamentalsKeyStats(BaseModel):
    symbol: Optional[str] = None
    longName: Optional[str] = None
    sector: Optional[str] = None
    industry: Optional[str] = None
    marketCap: Optional[float] = None
    enterpriseValue: Optional[float] = None
    trailingPE: Optional[float] = None
    forwardPE: Optional[float] = None
    pegRatio: Optional[float] = None
    priceToBook: Optional[float] = None
    priceToSales: Optional[float] = None
    trailingEps: Optional[float] = None
    forwardEps: Optional[float] = None
    beta: Optional[float] = None
    profitMargins: Optional[float] = None
    grossMargins: Optional[float] = None
    operatingMargins: Optional[float] = None
    ebitdaMargins: Optional[float] = None
    returnOnEquity: Optional[float] = None
    returnOnAssets: Optional[float] = None
    debtToEquity: Optional[float] = None
    currentRatio: Optional[float] = None
    quickRatio: Optional[float] = None
    totalCash: Optional[float] = None
    totalDebt: Optional[float] = None
    totalRevenue: Optional[float] = None
    revenueGrowth: Optional[float] = None
    earningsGrowth: Optional[float] = None
    dividendYield: Optional[float] = None
    payoutRatio: Optional[float] = None
    fiftyTwoWeekHigh: Optional[float] = None
    fiftyTwoWeekLow: Optional[float] = None
    currentPrice: Optional[float] = None


class FundamentalsPriceTargets(BaseModel):
    targetMean: Optional[float] = None
    targetMedian: Optional[float] = None
    targetHigh: Optional[float] = None
    targetLow: Optional[float] = None
    numAnalysts: Optional[int] = None
    recommendationKey: Optional[str] = None
    recommendationMean: Optional[float] = None


class FundamentalsResponse(BaseModel):
    symbol: str
    key_stats: FundamentalsKeyStats
    price_targets: FundamentalsPriceTargets
    income_annual: Optional[Dict[str, Any]] = None
    income_quarterly: Optional[Dict[str, Any]] = None
    balance_annual: Optional[Dict[str, Any]] = None
    balance_quarterly: Optional[Dict[str, Any]] = None
    cashflow_annual: Optional[Dict[str, Any]] = None
    cashflow_quarterly: Optional[Dict[str, Any]] = None
    earnings_history: Optional[Dict[str, Any]] = None
    earnings_estimate: Optional[Dict[str, Any]] = None
    revenue_estimate: Optional[Dict[str, Any]] = None
    eps_trend: Optional[Dict[str, Any]] = None
    eps_revisions: Optional[Dict[str, Any]] = None
    growth_estimates: Optional[Dict[str, Any]] = None
    earnings_dates: Optional[Dict[str, Any]] = None
    next_earnings_date: Optional[str] = None
    recommendations: Optional[Dict[str, Any]] = None
    recommendations_summary: Optional[Dict[str, Any]] = None
    upgrades_downgrades: Optional[Dict[str, Any]] = None


class CalendarNextEarnings(BaseModel):
    earningsTimestamp: Optional[str] = None
    earningsTimestampStart: Optional[str] = None
    earningsTimestampEnd: Optional[str] = None
    earningsCallTimestamp: Optional[str] = None


class CalendarDividendInfo(BaseModel):
    dividendRate: Optional[float] = None
    dividendYield: Optional[float] = None
    trailingAnnualDividendRate: Optional[float] = None
    trailingAnnualDividendYield: Optional[float] = None
    fiveYearAvgDividendYield: Optional[float] = None
    payoutRatio: Optional[float] = None
    exDividendDate: Optional[str] = None
    lastDividendDate: Optional[str] = None
    lastDividendValue: Optional[float] = None
    lastSplitDate: Optional[str] = None
    lastSplitFactor: Optional[float] = None


class NewsProvider(BaseModel):
    displayName: Optional[str] = None
    url: Optional[str] = None
    sourceId: Optional[str] = None


class NewsUrl(BaseModel):
    url: Optional[str] = None
    site: Optional[str] = None
    region: Optional[str] = None
    lang: Optional[str] = None


class NewsResolution(BaseModel):
    url: Optional[str] = None
    width: Optional[int] = None
    height: Optional[int] = None
    tag: Optional[str] = None


class NewsThumbnail(BaseModel):
    originalUrl: Optional[str] = None
    originalWidth: Optional[int] = None
    originalHeight: Optional[int] = None
    caption: Optional[str] = None
    resolutions: Optional[List[NewsResolution]] = None


class NewsMetadata(BaseModel):
    editorsPick: Optional[bool] = None


class NewsFinance(BaseModel):
    premiumFinance: Optional[Dict[str, Any]] = None


class NewsContent(BaseModel):
    id: Optional[str] = None
    contentType: Optional[str] = None
    title: Optional[str] = None
    description: Optional[str] = None
    summary: Optional[str] = None
    pubDate: Optional[str] = None
    displayTime: Optional[str] = None
    isHosted: Optional[bool] = None
    bypassModal: Optional[bool] = None
    previewUrl: Optional[str] = None
    thumbnail: Optional[NewsThumbnail] = None
    provider: Optional[NewsProvider] = None
    canonicalUrl: Optional[NewsUrl] = None
    clickThroughUrl: Optional[NewsUrl] = None
    metadata: Optional[NewsMetadata] = None
    finance: Optional[NewsFinance] = None
    storyline: Optional[str] = None


class NewsSentiment(BaseModel):
    label: str  # "bullish", "bearish", "neutral"
    score: float  # -1.0 (most bearish) to 1.0 (most bullish)
    confidence: str  # "high", "medium", "low"


class NewsOverallSentiment(BaseModel):
    label: str  # "bullish", "bearish", "neutral"
    score: float
    bullish_count: int = 0
    bearish_count: int = 0
    neutral_count: int = 0


class NewsArticle(BaseModel):
    id: Optional[str] = None
    content: Optional[NewsContent] = None
    sentiment: Optional[NewsSentiment] = None


class NewsResponse(BaseModel):
    symbol: str
    name: Optional[str] = None
    articles: List[NewsArticle] = Field(default_factory=list)
    total_count: int = 0
    overall_sentiment: Optional[NewsOverallSentiment] = None


class CalendarEventsResponse(BaseModel):
    symbol: str
    name: Optional[str] = None
    calendar: Optional[Dict[str, Any]] = None
    earnings_dates: Optional[Dict[str, Any]] = None
    next_earnings: CalendarNextEarnings
    dividends: Optional[Dict[str, Any]] = None
    splits: Optional[Dict[str, Any]] = None
    capital_gains: Optional[Dict[str, Any]] = None
    actions: Optional[Dict[str, Any]] = None
    dividend_info: CalendarDividendInfo


class SocialSentimentTicker(BaseModel):
    ticker: Optional[str] = None
    name: Optional[str] = None
    mentions: Optional[int] = None
    mentions_24h_ago: Optional[int] = None
    upvotes: Optional[int] = None
    rank: Optional[int] = None
    rank_24h_ago: Optional[int] = None
    sentiment: Optional[str] = None
    sentiment_score: Optional[float] = None


class SocialSentimentResponse(BaseModel):
    symbol: Optional[str] = None
    filter_type: Optional[str] = None
    page: int = 1
    data: List[SocialSentimentTicker] = Field(default_factory=list)
    total_count: int = 0
    summary: Optional[Dict[str, Any]] = None


class SocialSentimentDetailsResponse(BaseModel):
    ticker: Optional[str] = None
    name: Optional[str] = None
    mentions: Optional[int] = None
    mentions_24h_ago: Optional[int] = None
    upvotes: Optional[int] = None
    rank: Optional[int] = None
    rank_24h_ago: Optional[int] = None
    sentiment: Optional[str] = None
    sentiment_score: Optional[float] = None
    subreddits: Optional[List[str]] = Field(default_factory=list)
    last_updated: Optional[str] = None


class StockSummaryResponse(BaseModel):
    ticker: str
    category: ModeEnum
    summaries: List[PatternSummaryItem]


# StockTwits Schemas
class StockTwitsMessage(BaseModel):
    username: Optional[str] = None
    created_at: Optional[str] = None
    sentiment: Optional[str] = None
    likes: int = 0
    body: Optional[str] = None


class StockTwitsResponse(BaseModel):
    symbol: str
    total_count: int = 0
    messages: List[StockTwitsMessage] = Field(default_factory=list)
