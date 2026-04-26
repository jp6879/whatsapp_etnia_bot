import logging
from fastapi import FastAPI
from contextlib import asynccontextmanager
from app.api.routers import webhook_router
from app.utils.whatsapp import init_http_client, close_http_client

# ── Dev logging: show DEBUG output from our services in the terminal ──────────
logging.basicConfig(
    level=logging.DEBUG,
    format="%(levelname)-8s [%(name)s] %(message)s",
)
# Silence noisy third-party loggers
for _noisy in ("httpcore", "httpx", "openai", "watchfiles", "asyncio"):
    logging.getLogger(_noisy).setLevel(logging.WARNING)


@asynccontextmanager
async def client_lifespan(app: FastAPI):
    init_http_client()
    yield
    await close_http_client()


app = FastAPI(lifespan=client_lifespan)

app.include_router(webhook_router.router)
