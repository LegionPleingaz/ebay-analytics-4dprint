import asyncio
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api.health import router as health_router
from app.api.oauth_routes import router as oauth_router
from app.api.report import router as report_router
from app.config import get_settings
from app.logging_config import configure_logging
from app.monitoring.watchdog import watchdog_loop

settings = get_settings()
configure_logging(settings.log_level)



@asynccontextmanager
async def lifespan(_: FastAPI):
    task = asyncio.create_task(watchdog_loop())
    yield
    task.cancel()


app = FastAPI(title="ebay-analytics (4DPrint)", lifespan=lifespan)

app.include_router(health_router)
app.include_router(oauth_router)
app.include_router(report_router)
