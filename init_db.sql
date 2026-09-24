CREATE EXTENSION IF NOT EXISTS timescaledb;
CREATE EXTENSION IF NOT EXISTS pgcrypto;

CREATE TABLE IF NOT EXISTS public.assets (
    id UUID NOT NULL DEFAULT gen_random_uuid(),
    symbol TEXT NOT NULL UNIQUE,
    name TEXT NULL,
    exchange TEXT NULL,
    asset_class TEXT NULL,
    search_count INTEGER NOT NULL DEFAULT 0,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (id)
);

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_schema = 'public' AND table_name = 'assets' AND column_name = 'search_count'
    ) THEN
        ALTER TABLE public.assets ADD COLUMN search_count INTEGER NOT NULL DEFAULT 0;
    END IF;
END;
$$;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_schema = 'public' AND table_name = 'assets' AND column_name = 'is_external'
    ) THEN
        ALTER TABLE public.assets ADD COLUMN is_external BOOLEAN NOT NULL DEFAULT FALSE;
    END IF;
END;
$$;

CREATE TABLE IF NOT EXISTS public.financial_1h (
    id UUID NOT NULL DEFAULT gen_random_uuid(),
    asset_id UUID NOT NULL REFERENCES public.assets (id),
    ts TIMESTAMPTZ NOT NULL,
    open DOUBLE PRECISION NOT NULL,
    high DOUBLE PRECISION NOT NULL,
    low DOUBLE PRECISION NOT NULL,
    close DOUBLE PRECISION NOT NULL,
    volume BIGINT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (id, ts),
    UNIQUE (asset_id, ts)
);

CREATE INDEX IF NOT EXISTS idx_financial_1h_asset_id_ts ON public.financial_1h (asset_id, ts);

SELECT create_hypertable('public.financial_1h', 'ts', if_not_exists => TRUE, migrate_data => TRUE);

CREATE TABLE IF NOT EXISTS public.financial_1m (
    id UUID NOT NULL DEFAULT gen_random_uuid(),
    asset_id UUID NOT NULL REFERENCES public.assets (id),
    ts TIMESTAMPTZ NOT NULL,
    open DOUBLE PRECISION NOT NULL,
    high DOUBLE PRECISION NOT NULL,
    low DOUBLE PRECISION NOT NULL,
    close DOUBLE PRECISION NOT NULL,
    volume BIGINT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (id, ts),
    UNIQUE (asset_id, ts)
);

CREATE INDEX IF NOT EXISTS idx_financial_1m_asset_id_ts ON public.financial_1m (asset_id, ts);

SELECT create_hypertable('public.financial_1m', 'ts', if_not_exists => TRUE, migrate_data => TRUE);

CREATE TABLE IF NOT EXISTS public.financial_1y (
    id UUID NOT NULL DEFAULT gen_random_uuid(),
    asset_id UUID NOT NULL REFERENCES public.assets (id),
    ts TIMESTAMPTZ NOT NULL,
    open DOUBLE PRECISION NOT NULL,
    high DOUBLE PRECISION NOT NULL,
    low DOUBLE PRECISION NOT NULL,
    close DOUBLE PRECISION NOT NULL,
    volume BIGINT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (id, ts),
    UNIQUE (asset_id, ts)
);

CREATE INDEX IF NOT EXISTS idx_financial_1y_asset_id_ts ON public.financial_1y (asset_id, ts);

SELECT create_hypertable('public.financial_1y', 'ts', if_not_exists => TRUE, migrate_data => TRUE);

-- Keep only one day of historical data in all financial hypertables.
SELECT remove_retention_policy('public.financial_1h', if_exists => TRUE);
SELECT add_retention_policy('public.financial_1h', drop_after => INTERVAL '1 day', schedule_interval => INTERVAL '1 hour');

SELECT remove_retention_policy('public.financial_1m', if_exists => TRUE);
SELECT add_retention_policy('public.financial_1m', drop_after => INTERVAL '1 day', schedule_interval => INTERVAL '1 hour');

SELECT remove_retention_policy('public.financial_1y', if_exists => TRUE);
SELECT add_retention_policy('public.financial_1y', drop_after => INTERVAL '1 day', schedule_interval => INTERVAL '1 hour');

CREATE TABLE IF NOT EXISTS public.detected_patterns (
    id UUID NOT NULL DEFAULT gen_random_uuid(),
    analysis_id TEXT NOT NULL,
    instrument TEXT NOT NULL,
    timeframe TEXT NOT NULL,
    detected_at TIMESTAMPTZ NOT NULL,
    pattern TEXT NOT NULL,
    category TEXT NOT NULL,
    pattern_type TEXT NULL,
    window_start INTEGER NOT NULL,
    window_end INTEGER NOT NULL,
    confidence DOUBLE PRECISION NOT NULL,
    confirmed BOOLEAN NOT NULL DEFAULT TRUE,
    structure_detected BOOLEAN NOT NULL DEFAULT TRUE,
    signal JSON NOT NULL DEFAULT '{}'::json,
    context_score JSON NULL,
    pre_trend JSON NOT NULL DEFAULT '{}'::json,
    post_trend JSON NOT NULL DEFAULT '{}'::json,
    PRIMARY KEY (id)
);

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM information_schema.columns
        WHERE table_schema = 'public'
          AND table_name = 'detected_patterns'
          AND column_name = 'context_score'
    ) THEN
        ALTER TABLE public.detected_patterns
            ADD COLUMN context_score JSON NULL;
    END IF;
END;
$$;

CREATE INDEX IF NOT EXISTS idx_detected_patterns_instrument_detected_at
    ON public.detected_patterns (instrument, detected_at);
CREATE INDEX IF NOT EXISTS idx_detected_patterns_analysis_id
    ON public.detected_patterns (analysis_id);
CREATE INDEX IF NOT EXISTS idx_detected_patterns_category
    ON public.detected_patterns (category);

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM pg_constraint
        WHERE conname = 'uq_detected_patterns_dedupe_key'
          AND conrelid = 'public.detected_patterns'::regclass
    ) THEN
        ALTER TABLE public.detected_patterns
            ADD CONSTRAINT uq_detected_patterns_dedupe_key
            UNIQUE (instrument, category, timeframe, pattern, window_start, window_end);
    END IF;
END;
$$;

