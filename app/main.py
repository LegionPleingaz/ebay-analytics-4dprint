from fastapi import FastAPI

from app.api.health import router as health_router
from app.api.oauth_routes import router as oauth_router
from app.config import get_settings
from app.logging_config import configure_logging

settings = get_settings()
configure_logging(settings.log_level)

app = FastAPI(title="ebay-analytics (4DPrint)")

app.include_router(health_router)
app.include_router(oauth_router)
