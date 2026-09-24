import logging
from contextlib import asynccontextmanager

from dotenv import load_dotenv

load_dotenv()

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse

from app.api.routes import router as api_router
from app.api.frontend_routes import router as frontend_router
from app.api.stock_external_routes import router as external_router
from app.core.config import settings


def _configure_logging() -> None:
    level_name = settings.log_level.upper()
    level = getattr(logging, level_name, logging.INFO)
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
        force=True,
    )
    logging.getLogger("uvicorn.error").setLevel(level)
    logging.getLogger("uvicorn.access").setLevel(level)


_configure_logging()

from app.services.ingestion_worker import periodic_ingestion_worker
from app.services.database_service import init_db
from app.services.kafka_financial_consumer import financial_price_consumer
from app.services.kafka_pattern_consumer import pattern_consumer



@asynccontextmanager
async def lifespan(_: FastAPI):
    # Startup
    try:
        init_db()
    except Exception as exc:
        print(f"Warning: Failed to initialize database: {exc}")
    
    if settings.kafka_enabled:
        financial_price_consumer.start()
        pattern_consumer.start()
    
    await periodic_ingestion_worker.start()
    
    yield
    
    # Shutdown
    if settings.kafka_enabled:
        financial_price_consumer.stop()
        pattern_consumer.stop()
    
    await periodic_ingestion_worker.stop()

app = FastAPI(
    title=settings.app_name,
    version="0.1.0",
    description="Basic backend for Safeguard AI technical context engine",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(api_router, prefix=settings.api_prefix)
app.include_router(frontend_router, prefix="/api")
app.include_router(external_router, prefix="/api")


@app.get("/", include_in_schema=False)
def root() -> RedirectResponse:
    return RedirectResponse(url="/docs")
