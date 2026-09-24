from os import getenv
from typing import Optional

from pydantic import BaseModel


def _get_bool_env(name: str, default: bool) -> bool:
    value = getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _get_int_env(name: str, default: int) -> int:
    value = getenv(name)
    if value is None:
        return default
    try:
        return int(value)
    except ValueError:
        return default


def _get_float_env(name: str, default: float) -> float:
    value = getenv(name)
    if value is None:
        return default
    try:
        return float(value)
    except ValueError:
        return default


def _get_csv_env(name: str, default: list[str]) -> list[str]:
    value = getenv(name)
    if not value:
        return default
    return [item.strip() for item in value.split(",") if item.strip()]


def _get_kafka_offset_reset_env(name: str, default: str) -> str:
    value = getenv(name)
    if not value:
        return default

    normalized = value.strip().lower()
    if normalized in {"earliest", "latest", "none"}:
        return normalized
    return default


class Settings(BaseModel):
    app_name: str = "Safeguard AI Backend"
    api_prefix: str = "/api/v1"
    timeframe: str = "1H"
    max_patterns_for_context: int = 5
    log_level: str = getenv("LOG_LEVEL", "DEBUG")
    # Gemini / LangChain configuration
    google_api_key: Optional[str] = getenv("GOOGLE_API_KEY","change api key")
    gemini_model: str = getenv("GEMINI_MODEL", "gemini-2.5-flash")
    gemini_temperature: float = _get_float_env("GEMINI_TEMPERATURE", 0.2)

    # Scheduler configuration
    scheduler_enabled: bool = _get_bool_env("SCHEDULER_ENABLED", False)
    scheduler_interval_minutes: int = _get_int_env("SCHEDULER_INTERVAL_MINUTES", 5)
    scheduler_use_sample_data: bool = _get_bool_env("SCHEDULER_USE_SAMPLE_DATA", True)
    scheduler_sample_count: int = _get_int_env("SCHEDULER_SAMPLE_COUNT", 50)
    scheduler_instruments: list[str] = _get_csv_env("SCHEDULER_INSTRUMENTS", ["AAPL", "MSFT"])
    # API configuration
    source_api_url: Optional[str] = getenv("SOURCE_API_URL")
    source_api_timeout_seconds: int = _get_int_env("SOURCE_API_TIMEOUT_SECONDS", 10)
    # Redis cache configuration
    redis_enabled: bool = _get_bool_env("REDIS_ENABLED", True)
    redis_url: str = getenv("REDIS_URL", "redis://localhost:6379/0")
    redis_report_key_prefix: str = getenv("REDIS_REPORT_KEY_PREFIX", "dev:analysis:reports:24hr")
    redis_report_window_seconds: int = _get_int_env("REDIS_REPORT_WINDOW_SECONDS", 86400)
    # Pattern engine configuration
    cs50_engine_enabled: bool = _get_bool_env("CS50_ENGINE_ENABLED", True)
    cs50_engine_path: Optional[str] = getenv("CS50_ENGINE_PATH")
    # Database configuration
    database_url: str = getenv(
        "DATABASE_URL",
        "postgresql://postgres:password@localhost:5432/safeguard-ai"
    )
    # Kafka configuration
    kafka_enabled: bool = _get_bool_env("KAFKA_ENABLED", False)
    kafka_bootstrap_servers: str = getenv("KAFKA_BOOTSTRAP_SERVERS", "localhost:9092")
    kafka_auto_offset_reset: str = _get_kafka_offset_reset_env("KAFKA_AUTO_OFFSET_RESET", "latest")
    kafka_topic_1h: str = getenv("KAFKA_TOPIC_1H", "financial-1h")
    kafka_topic_1m: str = getenv("KAFKA_TOPIC_1M", "financial-1m")
    kafka_topic_1y: str = getenv("KAFKA_TOPIC_1Y", "financial-1y")
    kafka_topic_candlestick: str = getenv("KAFKA_TOPIC_CANDLESTICK", "candlestick")
    kafka_topic_chart: str = getenv("KAFKA_TOPIC_CHART", "chart")
    kafka_topic_harmonic: str = getenv("KAFKA_TOPIC_HARMONIC", "harmonic")
    kafka_topic_run_external_stock_analysis: str = getenv("KAFKA_TOPIC_RUN_EXTERNAL_STOCK_ANALYSIS", "run-external-stock-analysis")
    kafka_group_id_1h: str = getenv("KAFKA_GROUP_ID_1H", "safeguard-consumer-1h")
    kafka_group_id_1m: str = getenv("KAFKA_GROUP_ID_1M", "safeguard-consumer-1m")
    kafka_group_id_1y: str = getenv("KAFKA_GROUP_ID_1Y", "safeguard-consumer-1y")
    kafka_group_id_candlestick: str = getenv(
        "KAFKA_GROUP_ID_CANDLESTICK",
        "safeguard-pattern-consumer-candlestick",
    )
    kafka_group_id_chart: str = getenv("KAFKA_GROUP_ID_CHART", "safeguard-pattern-consumer-chart")
    kafka_group_id_harmonic: str = getenv(
        "KAFKA_GROUP_ID_HARMONIC",
        "safeguard-pattern-consumer-harmonic",
    )
    # Pattern detection lookback periods (in days)
    pattern_lookback_candlestick_days: int = _get_int_env("PATTERN_LOOKBACK_CANDLESTICK_DAYS", 1)
    pattern_lookback_chart_days: int = _get_int_env("PATTERN_LOOKBACK_CHART_DAYS", 60)
    pattern_lookback_harmonic_days: int = _get_int_env("PATTERN_LOOKBACK_HARMONIC_DAYS", 365)


settings = Settings()
