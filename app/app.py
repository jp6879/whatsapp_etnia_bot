from fastapi import FastAPI
from app.api.routers import webhook_router
from app.api.routers import test_router

app = FastAPI()

app.include_router(webhook_router.router)
app.include_router(test_router.router)
