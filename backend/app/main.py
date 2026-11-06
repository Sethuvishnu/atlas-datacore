from contextlib import asynccontextmanager

from fastapi import FastAPI

from app import __version__
from app.api.routes import health
from app.config.logging import configure_logging, get_logger
from app.config.settings import get_settings


@asynccontextmanager
async def lifespan(app: FastAPI):
    configure_logging()
    s = get_settings()
    get_logger().info("datacore_started", environment=s.environment, version=__version__)
    yield


def create_app() -> FastAPI:
    app = FastAPI(title="ATLAS DataCore", version=__version__, lifespan=lifespan)
    app.include_router(health.router, prefix="/api/v1")
    return app


app = create_app()
