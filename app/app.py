from fastapi import FastAPI
from app.api.routers import webhook_router

app = FastAPI()

app.include_router(webhook_router.router)
