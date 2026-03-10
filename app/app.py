import logging
from fastapi import FastAPI
from app.api.routers import webhook_router
from app.api.routers import test_router

# ── Dev logging: show DEBUG output from our services in the terminal ──────────
logging.basicConfig(
    level=logging.DEBUG,
    format="%(levelname)-8s [%(name)s] %(message)s",
)
# Silence noisy third-party loggers
for _noisy in ("httpcore", "httpx", "openai", "watchfiles", "asyncio"):
    logging.getLogger(_noisy).setLevel(logging.WARNING)

app = FastAPI()

app.include_router(webhook_router.router)
app.include_router(test_router.router)
