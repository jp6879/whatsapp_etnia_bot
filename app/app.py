import logging
from fastapi import FastAPI
from app.api.routers import webhook_router
from app.api.routers import test_router
from app.config import wpp_settings

# ── Logging: level is controlled via LOG_LEVEL in .env ───────────────────────
# Development default: DEBUG — set LOG_LEVEL=WARNING in production .env
_log_level = getattr(logging, wpp_settings.LOG_LEVEL.upper(), logging.DEBUG)
logging.basicConfig(
    level=_log_level,
    format="%(levelname)-8s [%(name)s] %(message)s",
)
# Silence noisy third-party loggers regardless of our LOG_LEVEL
for _noisy in ("httpcore", "httpx", "openai", "watchfiles", "asyncio"):
    logging.getLogger(_noisy).setLevel(logging.WARNING)

app = FastAPI()

app.include_router(webhook_router.router)
app.include_router(test_router.router)
