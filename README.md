# Safeguard AI Backend

FastAPI backend for technical pattern detection and market context classification.

The service can run in two modes:
- **On-demand API mode**: analyze candles when `/analyze` is called.
- **Low-latency scheduled mode**: fetch/analyze/store every 5 minutes so API consumers can read precomputed results quickly.

---

## Tech Stack, Frameworks, and Tools

### Language
- **Python 3.11**

### Backend framework
- **FastAPI**: REST API layer, routing, validation integration
- **Uvicorn**: ASGI server runtime
- **Pydantic v2**: request/response schema validation and serialization

### Caching
- **Redis** (optional, enabled by config)
   - Used for 24-hour instrument report cache
   - Implementation in [app/services/report_cache.py](app/services/report_cache.py)

### Containerization/orchestration
- **Docker**: image build and runtime packaging
- **Docker Compose**: multi-service local stack (API + Redis + PostgreSQL) in [docker-compose.yml](docker-compose.yml)
- **uv**: Fast Python package manager for dependency management

### Data/storage
- **PostgreSQL** (added for persistent storage)
- **In-memory Python store** (dictionary-based) in [app/services/store.py](app/services/store.py)
   - Fast for MVP, but non-persistent

### Streaming/Event Processing
- **Apache Kafka** (added for real-time financial data streaming)
  - Consumes financial price updates across 3 topics: `financial-1h`, `financial-1m`, `financial-1y`
  - Consumer manager in [app/services/kafka_financial_consumer.py](app/services/kafka_financial_consumer.py)
  - Per-topic consumers in [app/services/kafka_financial_1h_consumer.py](app/services/kafka_financial_1h_consumer.py), [app/services/kafka_financial_1m_consumer.py](app/services/kafka_financial_1m_consumer.py), and [app/services/kafka_financial_1y_consumer.py](app/services/kafka_financial_1y_consumer.py)

### Database/ORM
- **SQLAlchemy 2.0** (object-relational mapping)
  - Models defined in [app/models/financial_data.py](app/models/financial_data.py)
  - Connection pooling and session management
  - Database service in [app/services/database_service.py](app/services/database_service.py)
- **psycopg2-binary** (PostgreSQL driver)
- **asyncpg** (async PostgreSQL support)

### External integration
- **Source market data API** (optional)
   - Configurable via `SOURCE_API_URL`
   - Polled by scheduler in [app/services/ingestion_worker.py](app/services/ingestion_worker.py)

### Core techniques used
- Layered architecture (API layer + service layer + model layer)
- Background scheduling (`asyncio` task loop)
- Shared analysis pipeline for both API and scheduler
- Schema-first contracts with Pydantic models
- Cache-first report retrieval with Redis sorted sets
- Environment-driven configuration for runtime behavior

---

## What this backend does

1. Accepts financial candle data.
2. Detects enabled CS50 candlestick/chart/harmonic patterns.
3. Infers pre/post trend context.
4. Produces a technical context score + interpretation.
5. Stores latest analysis for retrieval.
6. Caches instrument reports in Redis for fast retrieval.

This is an MVP backend intended for easy local development and iterative extension.

---

## Backend Architecture (Layered)

1. **Presentation/API layer**  
   FastAPI routes receive requests and return validated response models.

2. **Application/service layer**  
   Analysis orchestration, scheduler control, and Redis cache logic.

3. **Domain/model layer**  
   Typed schemas (`AnalyzeRequest`, `AnalysisResult`, `Pattern`, enums).

4. **Infrastructure layer**  
   Runtime concerns (Docker, Redis, env-based config, ASGI lifecycle).

---

## Complete Backend Code Map (Teammate Handoff)

This section explains what each backend file does and how files connect.

### Entry and configuration

- [app/main.py](app/main.py)
   - Creates FastAPI app
   - Registers CORS and API router
   - Starts/stops scheduler using lifespan

- [app/core/config.py](app/core/config.py)
   - Reads all runtime env vars (scheduler, source API, Redis, CS50 adapter)
   - Exposes `settings` object used by all services

### API layer

- [app/api/routes.py](app/api/routes.py)
   - Owns all HTTP endpoints
   - Delegates analysis to service layer
   - Implements cache-first retrieval for instrument queries:
      1. Redis
      2. Store fallback
      3. `404 Stock '<ticker>' is not available`

### Domain models / contracts

- [app/models/schemas.py](app/models/schemas.py)
   - Request/response models (`AnalyzeRequest`, `AnalysisResult`, etc.)
   - Enums (`PatternType`, `TechnicalContext`, `TrendDirection`)
   - Central schema contract for frontend/backend integration

### Service layer

- [app/services/analysis_engine.py](app/services/analysis_engine.py)
   - Main orchestration (`run_analysis`)
   - Chooses candles (request candles or generated sample)
   - Calls:
      - pattern detection
      - trend inference
      - context scoring
      - interpretation generator
   - Saves result to in-memory store
   - Writes result to Redis report cache

- [app/services/pattern_engine.py](app/services/pattern_engine.py)
   - Adapter-only pattern detection gate
   - Enforces CS50 adapter availability checks
   - Provides trend helper (`infer_pre_and_post_trend`)

- [app/services/pattern_engine_adapter.py](app/services/pattern_engine_adapter.py)
   - Dynamically loads pattern classes from CS50 folders:
      - candlestick patterns
      - chart patterns
      - harmonic patterns
   - Converts backend candle schema to CS50 dataframe format
   - Executes enabled pattern classes
   - Maps outputs to backend `Pattern` schema
   - Exposes adapter status (`get_pattern_engine_status`)

- [app/services/context_engine.py](app/services/context_engine.py)
   - Converts patterns into technical context (`positive/neutral/negative`)
   - Applies weight and direction scoring

- [app/services/report_generator.py](app/services/report_generator.py)
   - Builds plain-language interpretation text for API response

- [app/services/report_cache.py](app/services/report_cache.py)
   - Redis integration for 24-hour report cache
   - Writes sorted sets per instrument
   - Reads latest cached report by instrument
   - Key format:
      - `dev:analysis:reports:24hr:<ticker>`

- [app/services/ingestion_worker.py](app/services/ingestion_worker.py)
   - Optional scheduler worker
   - Periodically fetches candles and runs analysis
   - Updates store/cache through `run_analysis`

- [app/services/sample_data.py](app/services/sample_data.py)
   - Generates synthetic candles for local testing

- [app/services/store.py](app/services/store.py)
   - In-memory fallback store for latest analysis lookups
   - Used when cache is unavailable or for non-persistent local mode

- [app/services/kafka_financial_consumer.py](app/services/kafka_financial_consumer.py)
   - Orchestrates all timeframe Kafka consumers (1h/1m/1y)
   - Aggregates consumer status for API visibility

- [app/services/kafka_financial_1h_consumer.py](app/services/kafka_financial_1h_consumer.py), [app/services/kafka_financial_1m_consumer.py](app/services/kafka_financial_1m_consumer.py), [app/services/kafka_financial_1y_consumer.py](app/services/kafka_financial_1y_consumer.py)
   - One dedicated consumer per topic/timeframe
   - Persists messages into `financial_1h`, `financial_1m`, and `financial_1y` tables

- [app/services/database_service.py](app/services/database_service.py)
   - Manages database connections and sessions
   - Provides CRUD operations for financial data models

### Package marker files

- [app/__init__.py](app/__init__.py), [app/api/__init__.py](app/api/__init__.py), [app/core/__init__.py](app/core/__init__.py), [app/models/__init__.py](app/models/__init__.py), [app/services/__init__.py](app/services/__init__.py)
   - Python package initialization files

---

## End-to-End Process Links (Plain-English)

### A) User asks for fresh analysis (POST /analyze)

1. Route accepts request in [app/api/routes.py](app/api/routes.py)
2. Route calls `run_analysis` in [app/services/analysis_engine.py](app/services/analysis_engine.py)
3. Analysis engine gets patterns from [app/services/pattern_engine.py](app/services/pattern_engine.py)
4. Pattern engine calls [app/services/pattern_engine_adapter.py](app/services/pattern_engine_adapter.py)
5. Adapter loads and executes CS50 patterns, returns normalized patterns
6. Analysis engine computes context using [app/services/context_engine.py](app/services/context_engine.py)
7. Analysis engine builds interpretation via [app/services/report_generator.py](app/services/report_generator.py)
8. Analysis engine stores result in [app/services/store.py](app/services/store.py)
9. Analysis engine caches result in Redis through [app/services/report_cache.py](app/services/report_cache.py)
10. Final response is returned to client

### B) User asks for existing instrument result (GET /context/instrument/{ticker} or /patterns/{ticker})

1. Route checks Redis first via [app/services/report_cache.py](app/services/report_cache.py)
2. If cache hit → return immediately
3. If cache miss → check in-memory fallback store [app/services/store.py](app/services/store.py)
4. If still missing → return `404` with stock-not-available message

### C) Scheduler mode

1. App startup in [app/main.py](app/main.py) starts [app/services/ingestion_worker.py](app/services/ingestion_worker.py)
2. Worker fetches candles (source API or sample)
3. Worker calls `run_analysis`
4. Same store/cache updates happen
5. App shutdown stops worker cleanly



## API Endpoints

- `POST /api/v1/analyze`  
   Analyze one instrument payload.

- `POST /api/v1/batch`  
   Analyze multiple instruments in a single request.

- `GET /api/v1/context/{analysis_id}`  
   Fetch one previous analysis result by id.

- `GET /api/v1/context/instrument/{instrument}`
   Fetch latest analysis by instrument with cache-first lookup.

- `GET /api/v1/patterns/{instrument}`  
   Fetch latest detected patterns for an instrument (Redis cache first, DB/store fallback).

- `GET /api/v1/sample-candles`  
   Generate sample candles for quick testing.

- `GET /api/v1/ingestion/status`  
   View scheduler state, last run/success timestamps, and latest error.

- `GET /api/v1/engine/status`
   View analysis engine wiring status (including CS50 adapter compatibility/path checks and loaded pattern catalog).

- `POST /api/v1/ingestion/run-now`  
   Trigger one ingestion cycle immediately.

- `GET /api/v1/health`  
   Health probe endpoint.

---

## Pattern + Context Coverage

- **Pattern source**: dynamic CS50 pattern discovery (candlestick + chart + harmonic)
- **Detection mode**: adapter-only (no built-in fallback detectors)
- **Trend inference**: uptrend / downtrend / sideways (pre + post)
- **Context output**: positive / neutral / negative + confidence

### Current CS50 pattern catalog (non-dummy)

- **Candlestick**
   - Doji
   - Hammer
   - Bullish Engulfing
   - Bearish Engulfing
   - Morning Star
   - Evening Star
   - Shooting Star

- **Chart**
   - Double Top
   - Double Bottom
   - Head And Shoulders
   - Ascending Triangle
   - Descending Triangle
   - Symmetrical Triangle
   - Flag

- **Harmonic**
   - Gartley
   - Butterfly
   - Bat
   - Crab

---

## Why scheduled ingestion helps with lag

When scheduler mode is enabled, heavy analysis work runs in the background every $5$ minutes instead of during user request time:

1. Pull candles (sample data or source API)
2. Run analysis
3. Save latest results in memory
4. Cache latest instrument report in Redis (24h)

This reduces request-time computation and improves responsiveness for consumers that read recently computed context.

---

## Configuration

### Scheduler

- `SCHEDULER_ENABLED=false`
- `SCHEDULER_INTERVAL_MINUTES=5`
- `SCHEDULER_INSTRUMENTS=AAPL,MSFT,BTCUSD`
- `SCHEDULER_USE_SAMPLE_DATA=true`
- `SCHEDULER_SAMPLE_COUNT=50`

If using real upstream market data:
- `SCHEDULER_USE_SAMPLE_DATA=false`
- `SOURCE_API_URL=https://your-source.example/candles`
- `SOURCE_API_TIMEOUT_SECONDS=10`

### Redis cache (24-hour reports)

- `REDIS_ENABLED=true`
- `REDIS_URL=redis://localhost:6379/0`
- `REDIS_REPORT_KEY_PREFIX=dev:analysis:reports:24hr`
- `REDIS_REPORT_WINDOW_SECONDS=86400`

Backend stores analysis reports in Redis sorted sets for up to 24 hours.
Key format:
- `dev:analysis:reports:24hr:<stock-ticker>`

Lookup flow for instrument-based fetch APIs:
1. Check Redis sorted set
2. If cache miss, check backend DB store
3. If not found, return: `Stock '<ticker>' is not available`

### CS50 pattern engine integration (optional)

- `CS50_ENGINE_ENABLED=true`
- `CS50_ENGINE_PATH=/absolute/path/to/CS50-analysis-main`

When enabled, backend attempts to load and execute patterns from `CS50-analysis-main`.
If dependencies/path/runtime are unavailable, backend returns an explicit error instead of using fallback pattern heuristics.

---

## Local Quickstart (venv)

1. Create environment and install dependencies
    - `python -m venv .venv`
    - `source .venv/bin/activate`
    - `uv sync`

2. Start API
    - `uvicorn app.main:app --reload`

3. Open docs
    - `http://127.0.0.1:8000/docs`

---

## Docker Compose Quickstart

`docker-compose.yml` is configured with:
- API service
- Redis
- PostgreSQL
- Scheduler enabled by default

Run:
- `docker compose up --build`

Then open:
- `http://127.0.0.1:8000/docs`

---

## Example request: `/api/v1/analyze`

```json
{
   "instrument": "AAPL",
   "timeframe": "1H",
   "use_sample_data": false,
   "sample_count": 50,
   "candles": [
      {
         "timestamp": "2026-03-06T09:00:00Z",
         "open": 182.1,
         "high": 182.9,
         "low": 181.8,
         "close": 182.4,
         "volume": 1023000
      },
      {
         "timestamp": "2026-03-06T10:00:00Z",
         "open": 182.4,
         "high": 182.7,
         "low": 181.9,
         "close": 182.0,
         "volume": 993000
      }
   ]
}
```

Notes:
- Minimum candles required: `20`
- For fast local testing, set `use_sample_data=true` and omit `candles`
